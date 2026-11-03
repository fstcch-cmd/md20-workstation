"""D-74: every piece of interface and report text exists in Chinese, English, Japanese and Korean."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import i18n_scan  # noqa: E402

from md20.i18n import pick, LANG_NAMES  # noqa: E402

# Text that is deliberately not translated (developer logs, command-line output, DecisionLog reasons kept in Chinese).
EXEMPT = {"md20/cli.py", "md20/util/decisions.py"}


def test_pick_four_languages_and_fallback():
    t = ("中", "en", "日本", "한국")
    assert [pick(t, l) for l in ("zh", "en", "ja", "ko")] == ["中", "en", "日本", "한국"]
    assert pick(("中", "en"), "ja") == "en" and pick(("中", "en"), "ko") == "en"
    assert pick({"zh": "中", "en": "en"}, "ko") == "en"
    assert pick(t, "xx") == "en"
    assert set(LANG_NAMES) == {"en", "zh", "ja", "ko"}


def test_no_text_left_in_two_languages():
    root = Path(i18n_scan.ROOT)
    bad = []
    for f in i18n_scan.files():
        rel = f.relative_to(root).as_posix()
        if rel in EXEMPT:
            continue
        bad += [f"{rel}:{ln} {kind} {txt}" for ln, kind, txt in i18n_scan.scan_file(f)]
    assert not bad, f"{len(bad)} texts lack Japanese or Korean:\n" + "\n".join(bad[:60])
