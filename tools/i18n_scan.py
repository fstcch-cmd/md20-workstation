"""List interface/report text that is not yet in all four languages (zh, en, ja, ko).

Counts, per file: 2-element (zh, en) tuples, `_(zh, en)` calls with two arguments, {"zh", "en"} dicts without ja/ko,
and `... if lang == "zh" else ...` choices.  Used by tests/test_i18n_coverage.py and by hand:
    python tools/i18n_scan.py [files...]
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

CJK = re.compile(r"[㐀-鿿＀-￯]")
ROOT = Path(__file__).resolve().parents[1]


def _text(node) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        a, b = _text(node.left), _text(node.right)
        return (a or "") + (b or "") if (a is not None or b is not None) else None
    return None


KANA = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
HANGUL = re.compile(r"[\uac00-\ud7af]")


def _lang_ok(node, pat) -> bool:
    """A Japanese or Korean element: text in that script, or a symbol-only string (units, "—", numbers)."""
    if node is None:
        return False
    t = _text(node)
    if t is None:
        return True            # computed value (variable, call): trust it
    return bool(pat.search(t)) or not re.search(r"[A-Za-z\u3400-\u9fff]", t)


def _is_pair(a, b) -> bool:
    za, eb = _text(a), _text(b)
    return bool(za is not None and eb is not None and CJK.search(za) and re.search(r"[A-Za-z]", eb) and not CJK.search(eb))


def scan_file(path: Path) -> list[tuple[int, str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Tuple) and len(node.elts) >= 2 and _is_pair(*node.elts[:2]):
            if len(node.elts) != 4 or not (_lang_ok(node.elts[2], KANA) and _lang_ok(node.elts[3], HANGUL)):
                out.append((node.lineno, f"tuple{len(node.elts)}", _text(node.elts[1])[:70]))
        elif isinstance(node, ast.Call):
            kw = {k.arg: k.value for k in node.keywords}
            for i in range(len(node.args) - 1):
                if _is_pair(node.args[i], node.args[i + 1]):
                    ja = node.args[i + 2] if len(node.args) > i + 2 else kw.get("ja")
                    ko = node.args[i + 3] if len(node.args) > i + 3 else kw.get("ko")
                    if not (_lang_ok(ja, KANA) and _lang_ok(ko, HANGUL)):
                        name = getattr(node.func, "id", None) or getattr(node.func, "attr", "?")
                        out.append((node.lineno, f"call:{name}", _text(node.args[i + 1])[:70]))
                    break
        elif isinstance(node, ast.Dict):
            keys = {k.value for k in node.keys if isinstance(k, ast.Constant)}
            if {"zh", "en"} <= keys and not {"ja", "ko"} <= keys:
                out.append((node.lineno, "dict", ""))
        elif isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], ast.Eq):
            vals = [node.left, *node.comparators]
            if any(isinstance(v, ast.Constant) and v.value == "zh" for v in vals) and \
               any((isinstance(v, ast.Name) and v.id in {"lang", "L"}) or
                   (isinstance(v, ast.Attribute) and v.attr == "lang") or
                   (isinstance(v, ast.Call) and getattr(v.func, "id", None) == "lang") for v in vals):
                out.append((node.lineno, "lang==zh", ""))
    return sorted(out)


def files() -> list[Path]:
    return sorted(p for p in (ROOT / "md20").rglob("*.py") if "__pycache__" not in p.parts)


if __name__ == "__main__":
    targets = [Path(a) for a in sys.argv[1:]] or files()
    total = 0
    for f in targets:
        r = scan_file(f)
        if r:
            kinds = {}
            for _, k, _t in r:
                kinds[k] = kinds.get(k, 0) + 1
            print(f"{len(r):5d}  {f.relative_to(ROOT) if f.is_absolute() else f}  {kinds}")
            total += len(r)
    print(f"total {total}")
