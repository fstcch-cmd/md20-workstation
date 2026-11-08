"""D-146 design tokens and D-147 connection stability (pure; no NiceGUI needed)."""
import re

import pytest

from md20.gui import theme
from md20.util import jsonio


def _lum(h):
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4  # noqa: E731
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _contrast(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


@pytest.mark.parametrize("fg", ["ink", "ink_muted", "primary", "pass", "autofix", "needs", "error", "running"])
def test_text_colours_meet_wcag_aa_on_paper_and_surface(fg):
    for bg in ("paper", "surface"):
        assert _contrast(theme.PALETTE[fg], theme.PALETTE[bg]) >= 4.5, (fg, bg)


def test_white_text_on_filled_buttons_and_chips_is_readable():
    for k in ("primary", "pass", "autofix", "needs", "error", "running"):
        assert _contrast("#FFFFFF", theme.PALETTE[k]) >= 4.5, k


def test_gate_states_differ_by_shape_not_only_colour():
    glyphs = {theme.gate_state(s)[1] for s in ("PASS", "AUTO_FIXED", "NEEDS_HUMAN")}
    assert len(glyphs) == 3
    assert theme.gate_state("NEEDS_HUMAN") == ("needs", "◆")
    assert theme.gate_state("PASS", advisory=True)[0] == "advisory"
    assert theme.gate_state("weird")[0] == "advisory"


@pytest.mark.parametrize("lang,face", [("zh", "Microsoft JhengHei UI"), ("ja", "Yu Gothic UI"), ("ko", "Malgun Gothic")])
def test_cjk_font_stack_per_language_and_no_web_fonts(lang, face):
    c = theme.css(lang)
    assert face in c and "@import" not in c and "fonts.googleapis" not in c and "url(" not in c
    assert "prefers-reduced-motion" in c and ":focus-visible" in c
    assert not re.search(r"text-transform:\s*uppercase", c)


def test_quasar_brand_colours_follow_tokens():
    assert theme.QUASAR_COLORS["primary"] == theme.PALETTE["primary"]
    assert theme.QUASAR_COLORS["warning"] == theme.PALETTE["needs"]


def test_replace_retry_rides_through_a_windows_sharing_violation():
    calls, slept = [], []

    def flaky(src, dst):
        calls.append((src, dst))
        if len(calls) < 4:
            raise PermissionError(5, "Access is denied")
    jsonio.replace_retry("a", "b", _replace=flaky, _sleep=slept.append)
    assert len(calls) == 4 and slept == list(jsonio.REPLACE_DELAYS[:3])


def test_replace_retry_raises_after_the_last_attempt_never_silently():
    def always(src, dst):
        raise PermissionError(5, "Access is denied")
    with pytest.raises(PermissionError):
        jsonio.replace_retry("a", "b", _replace=always, _sleep=lambda d: None)


def test_replace_retry_does_not_swallow_other_errors():
    def missing(src, dst):
        raise FileNotFoundError(src)
    with pytest.raises(FileNotFoundError):
        jsonio.replace_retry("a", "b", _replace=missing, _sleep=lambda d: None)


def test_atomic_write_json_uses_the_retry(tmp_path, monkeypatch):
    n = {"k": 0}
    real = jsonio.os.replace

    def flaky(src, dst):
        n["k"] += 1
        if n["k"] == 1:
            raise PermissionError(32, "being used by another process")
        return real(src, dst)
    monkeypatch.setattr(jsonio.os, "replace", flaky)
    p = jsonio.atomic_write_json({"a": 1}, tmp_path / "s.json")
    assert jsonio.load_json(p)["a"] == 1 and n["k"] == 2


def test_heartbeat_is_tuned_on_the_engineio_server_and_never_blocks_start():
    from md20.gui.connection import HEARTBEAT, tune_heartbeat

    class Eio:
        ping_interval, ping_timeout = 25, 20

    class Sio:
        eio = Eio()
    s = Sio()
    assert tune_heartbeat(s) == HEARTBEAT and s.eio.ping_timeout == 90 and s.eio.ping_interval == 20
    assert tune_heartbeat(object()) == {}                     # no engine.io server exposed → nothing, no error


def test_client_reconnects_when_the_tab_returns():
    from md20.gui.connection import CONNECTION_JS
    for ev in ("visibilitychange", "online", "focus"):
        assert ev in CONNECTION_JS
    assert "connect()" in CONNECTION_JS and "location.reload" not in CONNECTION_JS   # keeps the page; no forced reload
