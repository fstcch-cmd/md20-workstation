# -*- coding: utf-8 -*-
"""D-181: tools/build_lite.py builds a Lite tree in which the complete-edition modules are absent (replaced by stubs).

Pure tests (no engine, no network).  The integration test at the end builds a whole Lite tree into a temporary folder,
imports every module of it in a subprocess and runs a few fast test files inside it."""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

from md20 import edition as E

ROOT = Path(__file__).resolve().parents[1]

# Load the tool by file path, as test_build_protected.py does (tools/ is not a package).
_spec = importlib.util.spec_from_file_location("build_lite", ROOT / "tools" / "build_lite.py")
bl = importlib.util.module_from_spec(_spec)
sys.modules["build_lite"] = bl
_spec.loader.exec_module(bl)


def _tree_digest(root: Path, sub: tuple = ("md20", "tools", "tests")) -> str:
    h = hashlib.sha256()
    for s in sub:
        for p in sorted((root / s).rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts:
                h.update(p.relative_to(root).as_posix().encode())
                h.update(p.read_bytes())
    return h.hexdigest()


def _exec_stub(text: str, name: str = "stub_under_test") -> dict:
    ns: dict = {"__name__": name}
    exec(compile(text, name, "exec"), ns)
    return ns


# a small module with every kind of top-level name the real modules have
SYNTHETIC = '''"""A long docstring that explains the secret method in detail.

SECRET_ALGORITHM: multiply by 41 and add 7.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

LIMIT_NS = 12.5
NAMES = ("a", "b")
PAIR = (LIMIT_NS, 2)
GB = 1024 ** 3
LO, HI = 50.0, 70.0
TABLE = {"x": 1, "y": [1, 2]}
UNUSED_LITERAL = 99
COMPUTED = math.sqrt(2.0)
_PRIVATE_NUMBER = 5


class WidgetError(RuntimeError):
    """Raised by the widget."""


class SubWidgetError(WidgetError):
    pass


class Other(ValueError):
    pass


@dataclass
class Plan:
    """A plan."""
    n: int = 3
    items: list = field(default_factory=list)

    def run(self):
        return self.n * 41 + 7                      # SECRET_ALGORITHM


class Plain:
    X = 1

    def __init__(self, a):
        self.a = a

    def go(self):
        secret = 0
        for i in range(10):
            secret += i * 41 + 7
        return secret


def public_function(x, y=LIMIT_NS, *, flag=False):
    """Does the secret computation."""
    total = 0
    for i in range(int(x)):
        total += i * 41 + 7
    return total


async def public_async(x):
    return x * 41 + 7


def _private_helper(x):
    return x + 1


def _needed_private(x):
    return x + 2
'''


# ------------------------------------------------------------------------------------------- the plan
def test_plan_lists_every_pro_module_and_nothing_else():
    plan = bl.plan_lite(ROOT)
    assert plan["remove"] == list(E.pro_modules())
    assert plan["remove"], "the registry lists no module: a Lite package would remove nothing"
    for rel in plan["remove"]:
        assert (ROOT / rel).is_file()
        assert not rel.endswith("__init__.py")
    want = {m: f.id for f in E.PRO_FEATURES for m in f.modules}
    assert plan["feature_of"] == dict(sorted(want.items()))


def test_plan_refuses_a_missing_file_a_package_init_and_a_path_outside_the_package(tmp_path):
    (tmp_path / "md20").mkdir()
    (tmp_path / "md20" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "md20" / "__init__.py").write_text("", encoding="utf-8")
    assert bl._plan(tmp_path, {"md20/a.py": "f"})["remove"] == ["md20/a.py"]
    for bad in ("md20/missing.py", "md20/__init__.py", "../md20/a.py", "tools/build_lite.py", "md20/a.txt"):
        with pytest.raises(bl.BuildError):
            bl._plan(tmp_path, {bad: "f"})


# ------------------------------------------------------------------------------------------- stub generation
def test_stub_defines_every_public_name_and_nothing_is_called_at_import():
    stub = bl.stub_source(SYNTHETIC, "md20/build/widget.py", "fold", keep_constants={"LIMIT_NS", "NAMES"})
    ns = _exec_stub(stub)                                           # importing a stub never raises
    public = ["LIMIT_NS", "NAMES", "PAIR", "GB", "LO", "HI", "TABLE", "UNUSED_LITERAL", "COMPUTED", "WidgetError",
              "SubWidgetError", "Other", "Plan", "Plain", "public_function", "public_async"]
    for n in public:
        assert n in ns, n
    for n in ("_private_helper", "_PRIVATE_NUMBER", "math", "dataclass", "field", "_needed_private"):
        assert n not in ns, n
    assert bl.stub_problems(stub, SYNTHETIC) == []


def test_calling_a_stub_function_or_constructing_a_stub_class_raises_upgrade_required():
    ns = _exec_stub(bl.stub_source(SYNTHETIC, "md20/build/widget.py", "fold"))
    for call in (lambda: ns["public_function"](3), lambda: ns["public_function"](3, y=1, flag=True), lambda: ns["Plan"](),
                 lambda: ns["Plan"](n=1), lambda: ns["Plain"](1)):
        with pytest.raises(E.UpgradeRequired) as ei:
            call()
        assert ei.value.feature == "fold"
        assert ei.value.texts[1].startswith("Folding a peptide from its sequence is part of the MD20 complete edition.")
        assert "md20.build.widget." in ei.value.what
    import asyncio
    with pytest.raises(E.UpgradeRequired) as ei:
        asyncio.run(ns["public_async"](1))
    assert ei.value.feature == "fold"


def test_exception_classes_stay_real_exception_classes():
    ns = _exec_stub(bl.stub_source(SYNTHETIC, "md20/build/widget.py", "fold"))
    W, S, O = ns["WidgetError"], ns["SubWidgetError"], ns["Other"]
    assert issubclass(W, RuntimeError) and issubclass(S, W) and issubclass(O, ValueError)
    with pytest.raises(W):
        raise S("x")                                                # `except F.WidgetError` in a caller still works
    assert str(O("text")) == "text"


def test_constants_keep_a_simple_literal_only_when_another_module_refers_to_them():
    kept = bl.stub_source(SYNTHETIC, "md20/build/widget.py", "fold",
                          keep_constants={"LIMIT_NS", "NAMES", "PAIR", "GB", "LO", "TABLE", "COMPUTED"})
    ns = _exec_stub(kept)
    assert ns["LIMIT_NS"] == 12.5 and ns["NAMES"] == ("a", "b")
    assert ns["PAIR"] == (12.5, 2)                                  # a name of an earlier literal constant is resolved
    assert ns["GB"] == 1024 ** 3
    assert ns["LO"] == 50.0 and ns.get("HI") is None                # tuple unpacking; HI was not asked for
    assert ns["TABLE"] == {"x": 1, "y": [1, 2]}
    assert ns["COMPUTED"] is None                                   # not a literal: a placeholder even when asked for
    assert ns["UNUSED_LITERAL"] is None                             # not referred to: a placeholder
    none = _exec_stub(bl.stub_source(SYNTHETIC, "md20/build/widget.py", "fold"))
    assert all(none[n] is None for n in ("LIMIT_NS", "NAMES", "PAIR", "GB", "LO", "HI", "TABLE", "UNUSED_LITERAL"))


def test_a_private_or_imported_name_another_module_takes_is_defined_as_a_callable():
    stub = bl.stub_source(SYNTHETIC, "md20/build/widget.py", "fold", extra_names=("_needed_private", "math", "no_such_name"))
    ns = _exec_stub(stub)
    assert "no_such_name" not in ns                                 # a name the original does not bind is not invented
    for n in ("_needed_private", "math"):
        with pytest.raises(E.UpgradeRequired):
            ns[n](1)
    assert bl.stub_problems(stub, SYNTHETIC) == []


def test_nothing_of_the_implementation_survives_in_a_stub():
    stub = bl.stub_source(SYNTHETIC, "md20/build/widget.py", "fold", keep_constants={"LIMIT_NS"})
    for leaked in ("SECRET_ALGORITHM", "41", "range(", "for ", "return", "def _private_helper", "self.n", "math.sqrt",
                   "explains the secret", "Does the secret", "Raised by the widget"):
        assert leaked not in stub, leaked
    tree = ast.parse(stub)
    for node in ast.walk(tree):
        assert not isinstance(node, (ast.For, ast.While, ast.If, ast.Return, ast.Try, ast.With, ast.Lambda)), type(node)
    fns = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    assert fns and all(len(f.body) == 1 and isinstance(f.body[0], ast.Raise) for f in fns)
    assert len(stub) < len(SYNTHETIC)


def test_stub_problems_catches_a_leak():
    good = bl.stub_source(SYNTHETIC, "md20/build/widget.py", "fold")
    assert bl.stub_problems(good) == []
    assert bl.stub_problems("def f():\n    x = 1\n    raise RuntimeError()\n")                     # more than one statement
    assert bl.stub_problems("import os\n")                                                         # an import beyond edition
    assert bl.stub_problems("X = [i for i in range(3)]\n")                                         # not a simple constant
    assert bl.stub_problems("class A:\n    def go(self):\n        raise RuntimeError()\n")        # a method with logic
    assert bl.stub_problems("def f():\n    raise RuntimeError()\n" + "# x\n" * 10 + "Y = '" + "a" * 30_000 + "'\n")  # size
    original = "def f(x):\n    return compute_the_secret_value(x) * 41 + 7\n"
    assert bl.stub_problems("def g(*args, **kwargs):\n    raise Z\nW = 1\n", original) == []
    assert bl.stub_problems("def f(x):\n    return compute_the_secret_value(x) * 41 + 7\n", original)  # an implementation line


# ------------------------------------------------------------------------------------------- the real modules
@pytest.mark.parametrize("rel", list(E.pro_modules()))
def test_every_real_pro_module_gets_a_clean_stub_that_defines_all_its_public_names(rel):
    plan = bl.plan_lite(ROOT)
    original = (ROOT / rel).read_text(encoding="utf-8")
    refs = bl.scan_references(ROOT, plan["remove"])[rel]
    stub = bl.stub_source(original, rel, plan["feature_of"][rel], keep_constants=refs["names"], extra_names=refs["names"])
    assert bl.stub_problems(stub, original) == []
    ns = _exec_stub(stub)
    for n in bl.public_names(original) + refs["names"]:
        assert n in ns, f"{rel}: {n}"
    tree = ast.parse(original)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_") and \
                any(getattr(b, "id", "").endswith(("Error", "Exception")) or getattr(b, "id", "") in ("RuntimeError", "ValueError")
                    for b in node.bases):
            assert issubclass(ns[node.name], Exception), f"{rel}: {node.name} must stay an exception class"
    fn = next((n.name for n in tree.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")), None)
    if fn:
        with pytest.raises(E.UpgradeRequired) as ei:
            ns[fn]()
        assert ei.value.feature == plan["feature_of"][rel]
    assert len(stub) < len(original) / 4, f"{rel}: the stub is not much smaller than the module"


def test_exception_classes_of_the_fold_module_keep_their_bases():
    plan = bl.plan_lite(ROOT)
    rel = "md20/build/fold.py"
    original = (ROOT / rel).read_text(encoding="utf-8")
    ns = _exec_stub(bl.stub_source(original, rel, plan["feature_of"][rel]))
    from md20.build import fold as real
    assert issubclass(ns["FoldError"], real.FoldError.__mro__[1])
    assert issubclass(ns["FoldUnavailable"], ns["FoldError"]) == issubclass(real.FoldUnavailable, real.FoldError)


def test_the_references_scan_sees_lazy_and_module_attribute_uses():
    refs = bl.scan_references(ROOT, ["md20/build/fold.py", "md20/build/martini.py"])
    # workflow.py reads fold through `from .build import fold as F` inside methods
    assert "md20/workflow.py" in refs["md20/build/fold.py"]["importers"]["clean"]
    # cli.py takes names of martini inside functions
    assert "availability" in refs["md20/build/martini.py"]["names"]
    assert "md20/build/fold.py" not in sum(refs["md20/build/fold.py"]["importers"].values(), [])   # the module itself is not scanned


# ------------------------------------------------------------------------------------------- building
@pytest.fixture(scope="module")
def built(tmp_path_factory):
    before = _tree_digest(ROOT)
    out = tmp_path_factory.mktemp("lite") / "lite_tree"
    manifest = bl.build_lite(ROOT, out, "9.9.9-test")
    return {"out": out, "manifest": manifest, "before": before}


def test_building_leaves_the_source_tree_untouched(built):
    assert _tree_digest(ROOT) == built["before"]
    assert not (ROOT / bl.MARKER_REL).exists(), "the Lite marker must never appear in the source tree"
    assert E.build_edition() == E.FULL


def test_the_marker_is_written_and_makes_the_tree_lite(built):
    marker = built["out"] / bl.MARKER_REL
    assert json.loads(marker.read_text(encoding="utf-8")) == E.marker_document("9.9.9-test")
    assert E.build_edition(marker) == E.LITE
    assert built["manifest"]["version"] == "9.9.9-test" and built["manifest"]["marker"] == bl.MARKER_REL


def test_every_pro_module_is_replaced_by_its_stub_and_the_rest_is_copied_unchanged(built):
    out, m = built["out"], built["manifest"]
    assert m["removed"] == list(E.pro_modules())
    assert [s["path"] for s in m["stubs"]] == m["removed"]
    for s in m["stubs"]:
        data = (out / s["path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == s["sha256"]
        assert data != (ROOT / s["path"]).read_bytes()
        assert b"Lite stub" in data and s["bytes"] == len(data) < s["original_bytes"]
        assert bl.stub_problems(data.decode("utf-8"), (ROOT / s["path"]).read_text(encoding="utf-8")) == []
    stubbed = set(m["removed"]) | {bl.MARKER_REL}
    for p in ("md20/edition.py", "md20/workflow.py", "md20/sampling/binding.py", "md20/__init__.py", "pyproject.toml",
              "tests/test_edition.py", "tools/build_lite.py"):
        assert (out / p).read_bytes() == (ROOT / p).read_bytes(), p
    same = [p for p in (ROOT / "md20").rglob("*.py") if "__pycache__" not in p.parts
            and p.relative_to(ROOT).as_posix() not in stubbed]
    assert same and all((out / p.relative_to(ROOT)).read_bytes() == p.read_bytes() for p in same)


def test_no_git_metadata_or_caches_are_copied(built):
    out = built["out"]
    assert not (out / ".git").exists()
    assert not list(out.rglob("__pycache__")) and not list(out.rglob("*.pyc"))
    assert (out / "md20" / "build" / "__init__.py").is_file()       # md20/build is a package: only a top-level build/ is skipped


def test_the_manifest_tells_which_constants_stay_placeholders(built):
    ph = built["manifest"]["placeholders_read"]
    # every constant another module refers to is either kept as a literal or listed here for a person to look at
    assert all(isinstance(v, list) and v for v in ph.values())
    assert set(ph) <= set(built["manifest"]["removed"])


def test_building_into_or_around_the_source_tree_is_refused(tmp_path):
    for out in (ROOT, ROOT / "lite_out", ROOT / "md20" / "x", ROOT.parent):
        with pytest.raises(bl.BuildError):
            bl.build_lite(ROOT, out, "1")
    assert not (ROOT / "lite_out").exists()
    assert not (ROOT / bl.MARKER_REL).exists()


def test_building_into_a_folder_that_has_files_is_refused(tmp_path):
    (tmp_path / "keep.txt").write_text("x", encoding="utf-8")
    with pytest.raises(bl.BuildError):
        bl.build_lite(ROOT, tmp_path, "1")
    assert (tmp_path / "keep.txt").read_text(encoding="utf-8") == "x" and len(list(tmp_path.iterdir())) == 1


def test_a_source_tree_that_already_has_the_marker_is_refused(tmp_path):
    src = tmp_path / "src"
    shutil.copytree(ROOT / "md20", src / "md20", ignore=shutil.ignore_patterns("__pycache__"))
    (src / bl.MARKER_REL).write_text(json.dumps(E.marker_document("x")), encoding="utf-8")
    with pytest.raises(bl.BuildError, match="_edition.json"):
        bl.build_lite(src, tmp_path / "out", "1")
    assert not (tmp_path / "out").exists()


def test_a_registry_that_names_a_missing_file_stops_the_build(tmp_path):
    src = tmp_path / "src"
    shutil.copytree(ROOT / "md20", src / "md20", ignore=shutil.ignore_patterns("__pycache__"))
    (src / "md20" / "build" / "fold.py").unlink()
    with pytest.raises(bl.BuildError, match="fold.py"):
        bl.build_lite(src, tmp_path / "out", "1")
    assert not (tmp_path / "out").exists()


def test_the_source_edition_is_read_from_the_given_tree_not_from_the_imported_md20(tmp_path):
    src = tmp_path / "src"
    shutil.copytree(ROOT / "md20", src / "md20", ignore=shutil.ignore_patterns("__pycache__"))
    text = (src / "md20" / "edition.py").read_text(encoding="utf-8")
    assert 'modules=("md20/build/fold.py",)' in text
    (src / "md20" / "edition.py").write_text(text.replace('modules=("md20/build/fold.py",)', "modules=()"), encoding="utf-8")
    plan = bl.plan_lite(src)
    assert "md20/build/fold.py" not in plan["remove"] and "md20/build/fold.py" in E.pro_modules()


def test_no_environment_variable_or_flag_reads_the_edition_in_the_tool():
    src = (ROOT / "tools/build_lite.py").read_text(encoding="utf-8")
    for banned in ("getenv", "os.environ[", "os.environ.get", "MD20_EDITION", "exec(", "eval("):
        assert banned not in src, f"build_lite should not use {banned}"
    assert "MD20_" not in src.replace("MD20 Lite", "")


def test_command_line_plan_only_prints_the_removed_modules(capsys):
    assert bl.main(["--src", str(ROOT), "--plan-only"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert [l.split("\t")[0] for l in lines] == list(E.pro_modules())


def test_command_line_refuses_to_build_in_place(capsys):
    assert bl.main(["--src", str(ROOT), "--out", str(ROOT)]) == 2
    assert not (ROOT / bl.MARKER_REL).exists()


# ------------------------------------------------------------------------------------------- the Lite tree works
def test_every_module_of_the_lite_tree_imports_in_a_subprocess(built):
    v = bl.verify_lite(built["out"], src_root=ROOT, manifest=built["manifest"])
    assert v["ok"], v["problems"]
    assert v["imported"] > 100
    assert set(v["failed"]) <= set(v["baseline_failed"])            # only what the source tree cannot import here either


def test_the_verification_notices_a_tree_that_is_not_lite_or_leaks(built, tmp_path):
    out = tmp_path / "copy"
    shutil.copytree(built["out"], out)
    (out / bl.MARKER_REL).unlink()
    v = bl.verify_lite(out, src_root=ROOT)
    assert not v["ok"] and any("edition" in p or "_edition.json" in p for p in v["problems"])
    (out / bl.MARKER_REL).write_text(json.dumps(E.marker_document("1")), encoding="utf-8")
    assert bl.verify_lite(out, src_root=ROOT)["ok"]
    shutil.copy2(ROOT / "md20/build/fold.py", out / "md20/build/fold.py")                          # the original comes back
    v = bl.verify_lite(out, src_root=ROOT)
    assert not v["ok"] and any("fold.py" in p for p in v["problems"])


def test_the_verification_notices_a_name_a_stub_lacks(built, tmp_path):
    out = tmp_path / "copy"
    shutil.copytree(built["out"], out)
    p = out / "md20/build/martini.py"
    p.write_text(p.read_text(encoding="utf-8").replace("def availability(", "def availability_renamed("), encoding="utf-8")
    assert any("availability" in x for x in bl.check_stub_names(out))


def test_the_lite_tree_reports_itself_as_lite_and_the_stubs_raise_there(built):
    import subprocess
    code = ("import sys; sys.path.insert(0, sys.argv[1])\n"
            "from md20 import edition as E\n"
            "assert E.build_edition() == 'lite' and E.current(features=None) == 'lite'\n"
            "from md20.build import fold as F\n"
            "assert issubclass(F.FoldError, Exception)\n"
            "try:\n    F.clean('AAA', 'p')\nexcept E.UpgradeRequired as e:\n    assert e.feature == 'fold'\nelse:\n    raise SystemExit('no raise')\n"
            "print('ok')\n")
    cp = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(built["out"])], capture_output=True, text=True, timeout=120)
    assert cp.returncode == 0 and cp.stdout.strip() == "ok", cp.stderr[-600:]


def test_the_chosen_smoke_tests_exist_and_do_not_aim_at_removed_features():
    assert bl.LITE_SMOKE_TESTS, "name some fast pure test files to run inside the Lite tree"
    for t in bl.LITE_SMOKE_TESTS:
        assert (ROOT / t).is_file(), t
        assert not any(w in t for w in ("fold", "membrane", "martini", "cg_", "autonomy")), t
    for d in bl.LITE_SMOKE_DESELECT:
        assert (ROOT / d.split("::")[0]).is_file()


def test_pure_tests_run_inside_the_lite_tree(built):
    code, tail = bl.run_smoke_tests(built["out"])
    assert code == 0, tail
    assert "passed" in tail
