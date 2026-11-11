#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D-181: build the MD20 Lite source tree.

What it does
------------
From a clean source tree it makes a second tree in which the code of the complete-edition features is physically absent:

* every file listed by `md20.edition.pro_modules()` is replaced by a stub that defines the same public names, so the
  rest of MD20 still imports; a function or a class constructor of a stub raises `md20.edition.UpgradeRequired` when it
  is CALLED, never when the module is imported; exception classes stay real exception classes;
* `md20/_edition.json` (from `md20.edition.marker_document`) is written, which is what makes the package Lite;
* the source tree is never changed, and the marker never appears in it.

A stub holds none of the original implementation: no function bodies, no docstrings beyond one line, no comments.
A module-level constant keeps its literal value only if another module of MD20 refers to it (it is part of the interface
that module relies on); every other constant becomes `None`.

Verification (`verify_lite`) runs in a subprocess with the Lite tree first on `sys.path`: it imports every `md20.*`
module, checks that the edition there is Lite and that the stubs leak nothing.  `run_smoke_tests` runs a few fast pure
test files inside the Lite tree.

The scripts needs only the standard library.  It never imports the engine, so it runs in any environment.
"""
from __future__ import annotations

import argparse
import ast
import builtins
import hashlib
import importlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

PACKAGE = "md20"
MARKER_REL = "md20/_edition.json"

# never copied into the Lite tree
SKIP_NAMES = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".venv", "venv",
              ".claude", ".DS_Store", ".coverage"}
SKIP_TOP = {"build", "dist"}                   # only at the top level: md20/build is a package
SKIP_SUFFIXES = (".pyc", ".pyo")

# A stub is a handful of lines per name.  Anything larger than this per file is treated as a leak.
STUB_MAX_BYTES = 24_000

# Test files run inside the Lite tree by the integration test and by CI.  They are pure (no engine) and aim at the
# basic route (editions, workflow gates, docking logic, molecular dynamics logic, quick PMF, report), not at the
# complete-edition features.  Three tests of test_edition.py assume the complete edition and differ in a Lite tree on
# purpose (the marker is there), so they are deselected below.
LITE_SMOKE_TESTS: tuple[str, ...] = (
    "tests/test_edition.py",                  # the edition logic itself works in the Lite tree
    "tests/test_docking_pure.py", "tests/test_workflow_gates.py", "tests/test_build_gates.py", "tests/test_engine_fake.py",
    "tests/test_resume.py", "tests/test_workflow_rerun.py", "tests/test_reassess.py",      # md20 binding reassess: the CLI of a Lite tree
    "tests/test_sampling.py", "tests/test_smd_informed_windows.py", "tests/test_adaptive_windows.py", "tests/test_funnel.py",
    "tests/test_pmf_diagnostics.py", "tests/test_pmf_plateau.py", "tests/test_assessment.py", "tests/test_binding_targets.py",
    "tests/test_multi_binding.py", "tests/test_screen_workflow.py",
    "tests/test_extended_analysis.py", "tests/test_toolbox.py", "tests/test_stream.py", "tests/test_longrun.py",
    "tests/test_replica_analysis.py", "tests/test_report_v2.py", "tests/test_license.py", "tests/test_i18n_coverage.py",
    "tests/test_static_names.py",
)
# These three assume that `edition.current()` is the complete edition, which is false in a Lite tree on purpose.
LITE_SMOKE_DESELECT: tuple[str, ...] = (
    "tests/test_edition.py::test_source_tree_is_the_complete_edition",
    "tests/test_edition.py::test_summary_and_comparison",
    "tests/test_edition.py::test_state_record_keeps_each_limit_once",
    # These four drive the workflow beyond the Lite limits on purpose (a second pull, a library selection that goes on to
    # more ligands, long-run planning).  In a Lite tree the workflow refuses them, which is the behaviour Lite wants;
    # tests/test_edition_workflow.py covers that refusal.
    "tests/test_binding_targets.py::test_finished_target_kept_and_one_more_run",
    "tests/test_screen_workflow.py::test_workflow_screen_blocks_on_selection_then_merges",
    "tests/test_longrun.py::test_workflow_blocks_over_one_microsecond_then_applies_plan",
    "tests/test_longrun.py::test_workflow_leaves_runs_up_to_100_ns_untouched",
)


class BuildError(RuntimeError):
    """The Lite tree cannot be built (or verified) as asked."""


# ---------------------------------------------------------------------------------------------- reading the source edition
def _load_edition(root: Path):
    """`md20.edition` of the tree at `root`, loaded under an alias so that the md20 already imported by this process
    (maybe another tree) never decides what is removed.  `edition.py` is the only place that knows."""
    root = Path(root).resolve()
    pkg_dir = root / PACKAGE
    if not (pkg_dir / "edition.py").is_file():
        raise BuildError(f"{pkg_dir / 'edition.py'} 不存在，這不是 MD20 源碼樹")
    alias = "_md20_lite_src_" + hashlib.sha1(str(root).encode("utf-8")).hexdigest()[:10]
    if alias + ".edition" in sys.modules:
        return sys.modules[alias + ".edition"]
    spec = importlib.util.spec_from_file_location(alias, pkg_dir / "__init__.py", submodule_search_locations=[str(pkg_dir)])
    pkg = importlib.util.module_from_spec(spec)
    sys.modules[alias] = pkg
    try:
        spec.loader.exec_module(pkg)
        return importlib.import_module(alias + ".edition")
    except BaseException:
        for k in [k for k in sys.modules if k == alias or k.startswith(alias + ".")]:
            del sys.modules[k]
        raise


def _module_name(rel: str) -> str:
    """'md20/build/fold.py' -> 'md20.build.fold'; 'md20/build/__init__.py' -> 'md20.build'."""
    parts = rel[:-3].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


# ---------------------------------------------------------------------------------------------- the plan
def _plan(root: Path, feature_of: dict[str, str]) -> dict:
    root = Path(root)
    problems: list[str] = []
    for rel in sorted(feature_of):
        if rel.endswith("__init__.py"):
            problems.append(f"{rel}: 套件的 __init__.py 不可移除")
        elif not rel.endswith(".py") or rel.startswith("/") or ".." in rel.split("/") or not rel.startswith(PACKAGE + "/"):
            problems.append(f"{rel}: 不是 md20/ 底下的 .py 相對路徑")
        elif not (root / rel).is_file():
            problems.append(f"{rel}: 檔案不存在（edition.PRO_FEATURES 的清單過期）")
    if problems:
        raise BuildError("移除清單有問題：\n  " + "\n  ".join(problems))
    return {"remove": sorted(feature_of), "feature_of": dict(sorted(feature_of.items()))}


def plan_lite(root) -> dict:
    """Files a Lite tree does not ship, from `md20.edition.pro_modules()`.

    Returns {"remove": [relative paths, sorted], "feature_of": {path: PRO_FEATURES id}}.  Raises `BuildError` when a listed
    file does not exist or is a package `__init__.py` (a package is never removed)."""
    ed = _load_edition(Path(root))
    feature_of: dict[str, str] = {}
    for f in ed.PRO_FEATURES:
        for m in f.modules:
            if feature_of.setdefault(m, f.id) != f.id:
                raise BuildError(f"{m} 同時屬於 {feature_of[m]} 與 {f.id}")
    if set(feature_of) != set(ed.pro_modules()):
        raise BuildError("PRO_FEATURES 與 pro_modules() 不一致")
    return _plan(Path(root), feature_of)


# ---------------------------------------------------------------------------------------------- who refers to a pro module
def _iter_py(root: Path):
    base = root / PACKAGE
    for p in sorted(base.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        yield p.relative_to(root).as_posix(), p


class _Refs(ast.NodeVisitor):
    """Names a file takes from a set of target modules: `from m import a`, `from pkg import m` then `m.a`, `import m as x`."""

    def __init__(self, module: str, is_init: bool, targets: set[str]):
        self.pkg = module if is_init else module.rpartition(".")[0]
        self.targets = targets
        self.depth = 0                              # inside a function body
        self.names: dict[str, dict[str, set]] = {}  # target -> {"import": set, "lazy": set, "attr": set, "star": set}
        self.alias: dict[str, str] = {}             # local name -> target module (for `alias.attr`)

    def _slot(self, target: str) -> dict:
        return self.names.setdefault(target, {"import": set(), "lazy": set(), "attr": set(), "star": set()})

    def _resolve(self, level: int, module: str | None) -> str:
        if level == 0:
            return module or ""
        parts = self.pkg.split(".") if self.pkg else []
        parts = parts[:len(parts) - (level - 1)] if level > 1 else parts
        return ".".join(parts + ([module] if module else []))

    def visit_ImportFrom(self, node: ast.ImportFrom):
        base = self._resolve(node.level, node.module)
        for a in node.names:
            if a.name == "*":
                if base in self.targets:
                    self._slot(base)["star"].add("*")
                continue
            full = f"{base}.{a.name}" if base else a.name
            if full in self.targets:                 # `from pkg import module`
                self.alias[a.asname or a.name] = full
                self._slot(full)
            elif base in self.targets:               # `from module import name`
                self._slot(base)["lazy" if self.depth else "import"].add(a.name)

    def visit_Import(self, node: ast.Import):
        for a in node.names:
            if a.name in self.targets and a.asname:
                self.alias[a.asname] = a.name
                self._slot(a.name)

    def visit_Attribute(self, node: ast.Attribute):
        if isinstance(node.value, ast.Name) and self.alias.get(node.value.id):
            self._slot(self.alias[node.value.id])["attr"].add(node.attr)
        self.generic_visit(node)

    def _fn(self, node):
        self.depth += 1
        self.generic_visit(node)
        self.depth -= 1

    visit_FunctionDef = visit_AsyncFunctionDef = visit_Lambda = _fn


def scan_references(root, targets) -> dict[str, dict]:
    """For every module in `targets` (relative paths), the names other modules of the tree refer to.  Returns
    {rel: {"names": sorted names referred to anywhere, "import_time": sorted names imported at module level,
    "star": [files with `from m import *`], "importers": {name: [files]}}}.  The target modules themselves are not scanned."""
    root = Path(root)
    tmods = {_module_name(r): r for r in targets}
    out = {r: {"names": set(), "import_time": set(), "star": [], "importers": {}} for r in targets}
    for rel, p in _iter_py(root):
        if rel in out:
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"), filename=rel)
        except (SyntaxError, UnicodeDecodeError):
            continue
        v = _Refs(_module_name(rel), rel.endswith("__init__.py"), set(tmods))
        v.visit(tree)
        for t, slots in v.names.items():
            o = out[tmods[t]]
            for kind in ("import", "lazy", "attr"):
                for n in slots[kind]:
                    o["names"].add(n)
                    o["importers"].setdefault(n, []).append(rel)
            o["import_time"] |= slots["import"]
            if slots["star"]:
                o["star"].append(rel)
    return {r: {"names": sorted(o["names"]), "import_time": sorted(o["import_time"]), "star": sorted(o["star"]),
                "importers": {k: sorted(set(v)) for k, v in sorted(o["importers"].items())}} for r, o in out.items()}


# ---------------------------------------------------------------------------------------------- stub generation
_BUILTIN_EXC = {n for n, v in vars(builtins).items() if isinstance(v, type) and issubclass(v, BaseException)}
_BINOPS = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b,
           ast.Div: lambda a, b: a / b, ast.FloorDiv: lambda a, b: a // b, ast.Mod: lambda a, b: a % b,
           ast.Pow: lambda a, b: a ** b}


def _const_value(node: ast.AST, env: dict | None = None):
    """The value of a simple literal (numbers, strings, booleans, None, and tuples, lists, dicts or sets of them, and
    arithmetic on numbers such as 1024 ** 3).  A name stands for a constant defined earlier in the same module when it is
    in `env`.  Raises ValueError for anything else."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name) and env is not None and node.id in env:
        return env[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _const_value(node.operand, env)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        a, b = _const_value(node.left, env), _const_value(node.right, env)
        if all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (a, b)):
            try:
                r = _BINOPS[type(node.op)](a, b)
            except Exception as exc:  # noqa: BLE001
                raise ValueError(str(exc)) from exc
            if isinstance(r, (int, float)) and abs(r) < 1e18:
                return r
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        items = [_const_value(e, env) for e in node.elts]
        return tuple(items) if isinstance(node, ast.Tuple) else (items if isinstance(node, ast.List) else set(items))
    if isinstance(node, ast.Dict) and all(k is not None for k in node.keys):
        return {_const_value(k, env): _const_value(v, env) for k, v in zip(node.keys, node.values)}
    raise ValueError("not a simple literal")


def _literal_text(node: ast.AST, env: dict | None = None, max_len: int = 1200) -> str | None:
    """Source text of a simple literal, or None when it is not one or is long (a long table is implementation)."""
    try:
        v = _const_value(node, env)
    except ValueError:
        return None
    text = repr(v)
    return text if len(text) <= max_len else None


def _target_names(t: ast.AST) -> list[str]:
    if isinstance(t, ast.Name):
        return [t.id]
    if isinstance(t, (ast.Tuple, ast.List)):
        return [n for e in t.elts for n in _target_names(e)]
    return []


def _bound_names(tree: ast.Module) -> dict[str, str]:
    """Top-level names of a module and what they are: 'function', 'async', 'class', 'const', 'import'.
    Names bound inside `if` and `try` blocks at the top level count too."""
    out: dict[str, str] = {}

    def walk(body):
        for n in body:
            if isinstance(n, ast.FunctionDef):
                out[n.name] = "function"
            elif isinstance(n, ast.AsyncFunctionDef):
                out[n.name] = "async"
            elif isinstance(n, ast.ClassDef):
                out[n.name] = "class"
            elif isinstance(n, ast.Assign):
                for t in n.targets:
                    for name in _target_names(t):
                        out.setdefault(name, "const")
            elif isinstance(n, ast.AnnAssign) and n.value is not None:
                for name in _target_names(n.target):
                    out.setdefault(name, "const")
            elif isinstance(n, (ast.Import, ast.ImportFrom)):
                for a in n.names:
                    if a.name != "*":
                        out.setdefault((a.asname or a.name).split(".")[0], "import")
            elif isinstance(n, ast.If):
                walk(n.body)
                walk(n.orelse)
            elif isinstance(n, ast.Try):
                walk(n.body)
                for h in n.handlers:
                    walk(h.body)
                walk(n.orelse)
                walk(n.finalbody)
    walk(tree.body)
    return out


def _all_list(tree: ast.Module) -> list[str] | None:
    for n in tree.body:
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__" for t in n.targets):
            try:
                v = _const_value(n.value)
            except ValueError:
                return None
            if isinstance(v, (list, tuple)) and all(isinstance(x, str) for x in v):
                return list(v)
    return None


def _exception_classes(tree: ast.Module) -> dict[str, list[str]]:
    """Classes of the module that are exceptions -> their (kept) base names.  A base is kept when it is a builtin
    exception or an exception class of the same module; any other base whose name ends in Error, Exception or Warning
    (an imported one) becomes Exception."""
    classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
    exc: dict[str, list[str]] = {}
    changed = True
    while changed:
        changed = False
        for name, node in classes.items():
            if name in exc:
                continue
            bases = []
            for b in node.bases:
                bn = b.id if isinstance(b, ast.Name) else (b.attr if isinstance(b, ast.Attribute) else "")
                if isinstance(b, ast.Name) and (b.id in _BUILTIN_EXC or b.id in exc):
                    bases.append(b.id)
                elif bn.endswith(("Error", "Exception", "Warning")):
                    bases.append("Exception")
            if bases:
                exc[name] = list(dict.fromkeys(bases))
                changed = True
    return exc


def public_names(original_source: str) -> list[str]:
    """Public top-level names of a module (the `__all__` list when there is one), in source order."""
    tree = ast.parse(original_source)
    bound = _bound_names(tree)
    listed = _all_list(tree)
    if listed is not None:
        return list(dict.fromkeys(listed))
    return [n for n in bound if not n.startswith("_") and bound[n] != "import"]


def stub_source(original_source: str, module_rel: str, feature_id: str, keep_constants=(), extra_names=()) -> str:
    """The Lite stub of one module.

    Defines every public top-level name of `original_source` (and each name in `extra_names` that the original binds,
    for private names or re-exports another module needs).  Functions and class constructors raise
    `md20.edition.UpgradeRequired(feature_id, ...)` when called, never at import.  Exception classes stay exception
    classes.  A simple literal constant keeps its value only when its name is in `keep_constants`; all others are None.
    Nothing of the original implementation is copied."""
    tree = ast.parse(original_source)
    bound = _bound_names(tree)
    exc = _exception_classes(tree)
    listed = _all_list(tree)
    keep = set(keep_constants or ())
    mod = _module_name(module_rel)
    names = list(dict.fromkeys(public_names(original_source) + [n for n in extra_names if n in bound]))
    values: dict[str, ast.AST] = {}
    env: dict = {}                                    # constants that are simple literals, in definition order
    for n in tree.body:
        pairs = []
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    pairs.append((t.id, n.value))
                elif isinstance(t, ast.Tuple) and isinstance(n.value, ast.Tuple) and len(t.elts) == len(n.value.elts):
                    pairs += [(a.id, b) for a, b in zip(t.elts, n.value.elts) if isinstance(a, ast.Name)]
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.value is not None:
            pairs = [(n.target.id, n.value)]
        for name, val in pairs:
            values.setdefault(name, val)
            try:
                env.setdefault(name, _const_value(val, env))
            except ValueError:
                pass

    out = [f'"""MD20 Lite stub of {mod}. The code is part of the complete edition."""',
           "from md20.edition import UpgradeRequired", "", f"_FEATURE = {feature_id!r}"]
    if listed is not None:
        out.append(f"__all__ = {sorted(set(names))!r}")
    # exception classes first, in an order where a base comes before the class using it
    ordered = [n for n in names if n in exc]
    placed: set[str] = set()
    while ordered:
        rest = []
        for n in ordered:
            if all(b not in exc or b in placed for b in exc[n]):
                out += ["", "", f"class {n}({', '.join(exc[n])}):", f'    """MD20 Lite stub."""']
                placed.add(n)
            else:
                rest.append(n)
        if len(rest) == len(ordered):                  # cyclic or odd: place the rest as they are
            for n in rest:
                out += ["", "", f"class {n}(Exception):", f'    """MD20 Lite stub."""']
            break
        ordered = rest
    call = f"raise UpgradeRequired(_FEATURE, {{what!r}})"
    for n in names:
        kind = bound.get(n)
        if n in exc:
            continue
        what = f"{mod}.{n}"
        if kind == "class":
            out += ["", "", f"class {n}:", '    """MD20 Lite stub."""', "    def __init__(self, *args, **kwargs):",
                    "        " + call.format(what=what)]
        elif kind in ("function", "async", "import"):
            out += ["", "", f"{'async ' if kind == 'async' else ''}def {n}(*args, **kwargs):", "    " + call.format(what=what)]
        elif kind == "const":
            lit = _literal_text(values[n], env) if n in keep and n in values and n in env else None
            out += ([] if out[-1].startswith(("_FEATURE", "__all__")) or " = " in out[-1] and not out[-1].startswith(" ") else [""]) \
                + [f"{n} = {lit if lit is not None else 'None'}"]
    text = "\n".join(out) + "\n"
    compile(text, module_rel, "exec")                 # a stub that does not compile is a bug here, not in the build
    return text


# ---------------------------------------------------------------------------------------------- checks on a stub
def stub_problems(stub_text: str, original_source: str | None = None) -> list[str]:
    """Reasons this text is not a clean stub (empty when it is): only imports, simple assignments, one-line docstrings,
    functions whose body is a single raise, classes holding a docstring or one `__init__` with a single raise."""
    problems: list[str] = []
    if len(stub_text.encode("utf-8")) > STUB_MAX_BYTES:
        problems.append(f"stub 超過 {STUB_MAX_BYTES} bytes")
    try:
        tree = ast.parse(stub_text)
    except SyntaxError as exc:
        return [f"stub 語法錯誤：{exc}"]

    def is_raise_only(fn) -> bool:
        return len(fn.body) == 1 and isinstance(fn.body[0], ast.Raise)

    def one_line_doc(n) -> bool:
        return isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str) \
            and "\n" not in n.value.value
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not is_raise_only(n):
                problems.append(f"函式 {n.name} 的內容不只一個 raise")
            if n.decorator_list:
                problems.append(f"函式 {n.name} 有裝飾器")
        elif isinstance(n, ast.ClassDef):
            for m in n.body:
                if one_line_doc(m):
                    continue
                if isinstance(m, ast.FunctionDef) and m.name == "__init__" and is_raise_only(m):
                    continue
                problems.append(f"類別 {n.name} 內有多餘的內容（{type(m).__name__}）")
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            if not (isinstance(n, ast.ImportFrom) and n.module == "md20.edition"):
                problems.append("stub 只可 import md20.edition")
        elif isinstance(n, ast.Assign):
            try:
                _const_value(n.value)
            except ValueError:
                problems.append(f"指派 {ast.unparse(n)[:60]} 不是簡單常數")
        elif one_line_doc(n):
            continue
        else:
            problems.append(f"stub 內有不該有的敘述（{type(n).__name__}）")
    if original_source is not None:                   # no line of the implementation may survive
        stub_lines = {l.strip() for l in stub_text.splitlines()}
        for line in original_source.splitlines():
            s = line.strip()
            if len(s) >= 30 and not s.startswith(("#", "class ", "def ", "async def ")) and s in stub_lines:
                problems.append(f"原始碼的一行出現在 stub：{s[:50]}")
                break
    return problems


# ---------------------------------------------------------------------------------------------- build
def _skip(rel_parts: tuple, name: str, is_dir: bool) -> bool:
    if name in SKIP_NAMES or name.endswith(".egg-info") or name.endswith(SKIP_SUFFIXES):
        return True
    return not rel_parts and is_dir and name in SKIP_TOP


def copy_tree(src: Path, dst: Path) -> list[str]:
    """Copy the source tree without VCS metadata, caches and build output.  Returns the copied relative paths."""
    copied: list[str] = []
    for dirpath, dirnames, filenames in os.walk(src):
        rel_parts = Path(dirpath).relative_to(src).parts
        dirnames[:] = sorted(d for d in dirnames if not _skip(rel_parts, d, True))
        (dst / Path(*rel_parts)).mkdir(parents=True, exist_ok=True)
        for f in sorted(filenames):
            if _skip(rel_parts, f, False):
                continue
            s = Path(dirpath) / f
            d = dst / Path(*rel_parts) / f
            shutil.copy2(s, d)
            copied.append("/".join(rel_parts + (f,)))
    return copied


def _is_inside(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _check_places(src: Path, out: Path) -> None:
    if _is_inside(out, src) or _is_inside(src, out):
        raise BuildError(f"輸出資料夾 {out} 與源碼樹 {src} 重疊；Lite 樹必須建在源碼樹之外")
    if (src / MARKER_REL).exists():
        raise BuildError(f"源碼樹內不可有 {MARKER_REL}（那個標記只屬於 Lite 安裝包）；請先移除")
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise BuildError(f"輸出資料夾 {out} 已存在且不是空的")


def build_lite(src, out, version: str = "") -> dict:
    """Build the Lite tree at `out` from the source tree at `src` and return the manifest.

    Refuses to write into (or around) the source tree, and refuses a source tree that already carries the marker."""
    src, out = Path(src).resolve(), Path(out).resolve()
    plan = plan_lite(src)
    _check_places(src, out)
    ed = _load_edition(src)
    refs = scan_references(src, plan["remove"])
    originals = {rel: (src / rel).read_text(encoding="utf-8") for rel in plan["remove"]}
    stubs: dict[str, str] = {}
    for rel in plan["remove"]:
        r = refs[rel]
        if r["star"]:
            raise BuildError(f"{rel} 被 `from ... import *` 使用（{', '.join(r['star'])}）；無法確定要匯出哪些名稱")
        stubs[rel] = stub_source(originals[rel], rel, plan["feature_of"][rel], keep_constants=r["names"], extra_names=r["names"])
    copied = copy_tree(src, out)
    manifest_stubs = []
    placeholders: dict[str, list[str]] = {}
    for rel in plan["remove"]:
        data = stubs[rel].encode("utf-8")
        (out / rel).write_bytes(data)
        tree = ast.parse(stubs[rel])
        bound = _bound_names(tree)
        kept = [n for n, k in bound.items() if k == "const" and _is_kept_literal(tree, n)]
        # constants another module refers to that stay a placeholder: a person should look at each of them
        placeholders[rel] = sorted(n for n in refs[rel]["names"] if bound.get(n) == "const" and n not in kept)
        manifest_stubs.append({"path": rel, "feature": plan["feature_of"][rel], "sha256": hashlib.sha256(data).hexdigest(),
                               "bytes": len(data), "original_bytes": len(originals[rel].encode("utf-8")),
                               "names": sorted(n for n in _bound_names(tree) if n != "UpgradeRequired" and not n.startswith("_")),
                               "kept_constants": sorted(kept)})
    marker = out / MARKER_REL
    marker.write_text(json.dumps(ed.marker_document(version), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"version": str(version), "edition": "lite", "marker": MARKER_REL, "files_copied": len(copied),
            "removed": list(plan["remove"]), "stubs": manifest_stubs, "placeholders_read": {k: v for k, v in placeholders.items() if v},
            "references": {rel: {"names": refs[rel]["names"], "import_time": refs[rel]["import_time"]} for rel in plan["remove"]}}


def _is_kept_literal(tree: ast.Module, name: str) -> bool:
    for n in tree.body:
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in n.targets):
            return not (isinstance(n.value, ast.Constant) and n.value.value is None)
    return False


# ---------------------------------------------------------------------------------------------- verification
_IMPORT_ALL = r'''
import importlib, json, pkgutil, sys, traceback
from pathlib import Path
root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
res = {"md20_file": None, "edition": None, "current": None, "imported": [], "failed": {}}
try:
    import md20
    res["md20_file"] = str(Path(md20.__file__).resolve())
    from md20 import edition
    res["edition"] = edition.build_edition()
    res["current"] = edition.current(features=None)
except BaseException as exc:
    res["failed"]["md20"] = "".join(traceback.format_exception_only(type(exc), exc)).strip()
else:
    def onerror(name):
        res["failed"][name] = "".join(traceback.format_exception_only(*sys.exc_info()[:2])).strip()
    names = ["md20"] + [m.name for m in pkgutil.walk_packages(md20.__path__, "md20.", onerror=onerror)]
    for name in names:
        if name == "md20.__main__":
            continue
        try:
            importlib.import_module(name)
            res["imported"].append(name)
        except BaseException as exc:
            res["failed"][name] = "".join(traceback.format_exception_only(type(exc), exc)).strip()
print("@@MD20@@" + json.dumps(res))
'''


def _run_import_all(root: Path, timeout: int = 600) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    cp = subprocess.run([sys.executable, "-I", "-B", "-c", _IMPORT_ALL, str(root)], capture_output=True, text=True,
                        timeout=timeout, env=env, cwd=str(root.parent))
    for line in reversed(cp.stdout.splitlines()):
        if line.startswith("@@MD20@@"):
            return json.loads(line[len("@@MD20@@"):])
    raise BuildError(f"匯入檢查沒有回報（exit {cp.returncode}）：{cp.stderr[-800:]}")


def check_stub_names(lite_root, plan: dict | None = None) -> list[str]:
    """Static check, so lazy imports are covered too: every name another module takes from a stub exists in the stub."""
    lite_root = Path(lite_root)
    plan = plan or plan_lite(lite_root)
    refs = scan_references(lite_root, plan["remove"])
    problems = []
    for rel in plan["remove"]:
        bound = set(_bound_names(ast.parse((lite_root / rel).read_text(encoding="utf-8"))))
        for name, files in refs[rel]["importers"].items():
            if name not in bound:
                problems.append(f"{rel} 的 stub 沒有 {name}（{', '.join(files[:3])} 會用到）")
    return problems


def verify_lite(lite_root, src_root=None, manifest: dict | None = None) -> dict:
    """Verify a Lite tree.  Returns {"ok", "problems", "imported", "failed", "baseline_failed"}.

    In a SUBPROCESS with the Lite tree first on `sys.path`: import every `md20.*` module; the edition must be Lite.  A module
    that fails to import counts as a problem unless it also fails in the source tree `src_root` (for example a module that
    needs a package this computer lacks).  Then: every stub is clean (`stub_problems`), the stubs hold every name other
    modules take from them, and the marker exists."""
    lite_root = Path(lite_root).resolve()
    problems: list[str] = []
    marker = lite_root / MARKER_REL
    if not marker.is_file():
        problems.append(f"{MARKER_REL} 不存在")
    res = _run_import_all(lite_root)
    if res["md20_file"] is None or not Path(res["md20_file"]).is_relative_to(lite_root):
        problems.append(f"import 到的 md20 不在 Lite 樹內：{res['md20_file']}")
    if res["edition"] != "lite" or res["current"] != "lite":
        problems.append(f"Lite 樹內 edition 不是 lite：build_edition={res['edition']}，current={res['current']}")
    baseline_failed: dict = {}
    if src_root is not None:
        baseline_failed = _run_import_all(Path(src_root).resolve())["failed"]
    for name, err in sorted(res["failed"].items()):
        if name not in baseline_failed:
            problems.append(f"import 失敗 {name}：{err}")
    try:
        plan = plan_lite(lite_root)
    except BuildError as exc:
        plan = None
        problems.append(f"移除清單在 Lite 樹內對不上：{exc}")
    if plan is not None:
        for rel in plan["remove"]:
            text = (lite_root / rel).read_text(encoding="utf-8")
            orig = None
            if src_root is not None and (Path(src_root) / rel).is_file():
                orig = (Path(src_root) / rel).read_text(encoding="utf-8")
                if orig == text:
                    problems.append(f"{rel} 仍是原始碼（沒有被 stub 取代）")
            problems += [f"{rel}: {p}" for p in stub_problems(text, orig)]
        problems += check_stub_names(lite_root, plan)
        if manifest is not None:
            for s in manifest["stubs"]:
                got = hashlib.sha256((lite_root / s["path"]).read_bytes()).hexdigest()
                if got != s["sha256"]:
                    problems.append(f"{s['path']} 的 sha256 與 manifest 不符")
    return {"ok": not problems, "problems": problems, "imported": len(res["imported"]), "failed": res["failed"],
            "baseline_failed": baseline_failed}


def run_smoke_tests(lite_root, tests=None, deselect=None, timeout: int = 1500) -> tuple[int, str]:
    """Run test files inside the Lite tree (Lite first on `sys.path`, md20 checked to come from it).  Returns
    (pytest exit code, output tail)."""
    lite_root = Path(lite_root).resolve()
    tests = list(LITE_SMOKE_TESTS if tests is None else tests)
    deselect = list(LITE_SMOKE_DESELECT if deselect is None else deselect)
    code = ("import sys, pathlib\n"
            "root = pathlib.Path(sys.argv[1])\n"
            "sys.path.insert(0, str(root))\n"
            "import md20\n"
            "assert pathlib.Path(md20.__file__).resolve().is_relative_to(root), md20.__file__\n"
            "import pytest\n"
            "sys.exit(pytest.main(sys.argv[2:]))\n")
    args = ["-o", "addopts=", "-q", "-p", "no:cacheprovider"] + [f"--deselect={d}" for d in deselect] + tests
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    cp = subprocess.run([sys.executable, "-B", "-c", code, str(lite_root)] + args, capture_output=True, text=True,
                        timeout=timeout, env=env, cwd=str(lite_root))
    return cp.returncode, (cp.stdout + cp.stderr)[-4000:]


# ---------------------------------------------------------------------------------------------- command line
def _default_version(src: Path) -> str:
    try:
        m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', (src / "md20" / "__init__.py").read_text(encoding="utf-8"))
        return m.group(1) if m else ""
    except OSError:
        return ""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="D-181 建立 MD20 Lite 源碼樹：移除完整版模組、換成 stub、寫入版本標記")
    ap.add_argument("--src", default=".", help="乾淨的源碼樹（repo 根目錄）")
    ap.add_argument("--out", help="Lite 樹的輸出資料夾（必須在源碼樹之外，不存在或為空）")
    ap.add_argument("--version", default=None, help="寫進標記的版本字串（預設取 md20.__version__）")
    ap.add_argument("--plan-only", action="store_true", help="只印移除清單")
    ap.add_argument("--verify", action="store_true", help="建好後在子行程驗證（import 全部模組、stub 不外洩）")
    ap.add_argument("--smoke-tests", action="store_true", help="驗證後在 Lite 樹內跑挑選的測試檔")
    ap.add_argument("--manifest", help="把 manifest 寫成 JSON 檔（路徑須在 Lite 樹之外）")
    args = ap.parse_args(argv)
    src = Path(args.src).resolve()
    try:
        plan = plan_lite(src)
        if args.plan_only:
            for rel in plan["remove"]:
                print(f"{rel}\t{plan['feature_of'][rel]}")
            return 0
        if not args.out:
            ap.error("--out 必填（除非 --plan-only）")
        version = args.version if args.version is not None else _default_version(src)
        manifest = build_lite(src, args.out, version)
    except BuildError as exc:
        print(f"建置失敗：{exc}", file=sys.stderr)
        return 2
    print(f"Lite 樹已建在 {Path(args.out).resolve()}（版本 {version or '-'}）：移除 {len(manifest['removed'])} 個模組")
    for s in manifest["stubs"]:
        print(f"  stub {s['path']}  {s['bytes']} bytes（原 {s['original_bytes']}）  {s['feature']}")
    if args.manifest:
        mp = Path(args.manifest).resolve()
        if _is_inside(mp, Path(args.out).resolve()):
            print("--manifest 不可寫在 Lite 樹內", file=sys.stderr)
            return 2
        mp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rc = 0
    if args.verify or args.smoke_tests:
        v = verify_lite(args.out, src_root=src, manifest=manifest)
        print(f"驗證：import {v['imported']} 個模組；原樹本身 import 失敗 {len(v['baseline_failed'])} 個（不計）")
        for p in v["problems"]:
            print("  問題：", p)
        rc = 0 if v["ok"] else 1
    if args.smoke_tests and rc == 0:
        code, tail = run_smoke_tests(args.out)
        print(tail)
        rc = 0 if code == 0 else 1
    return rc


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
