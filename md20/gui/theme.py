"""MD20 GUI design system (D-146): tokens, type and component styles, applied on every page from one place.

The interface's job: say where a calculation is, what needs the student's decision, and how to continue safely.
The one expressive element is the gate card: three states told apart by shape and colour (● passed,
◐ corrected automatically, ◆ needs your decision) with a status rule on the card's left edge.  Everything else is
quiet: light header with a thin teal rule, one content width, hairlines instead of shadows, radii by hierarchy.
Fonts are the laptop's own UI faces per language (the GUI runs offline, no web fonts); figures are tabular."""
from __future__ import annotations

PALETTE = {
    "paper": "#F3F6F6", "surface": "#FFFFFF", "ink": "#13232A", "ink_muted": "#53646B",
    "line": "#D3DDDF", "line_strong": "#B7C6C9", "primary": "#0D6870", "primary_soft": "#E2F0F0",
    "pass": "#2E7A4C", "autofix": "#2B6CA3", "needs": "#9A5A00", "error": "#B42318", "running": "#5646C0",
}

QUASAR_COLORS = {"primary": PALETTE["primary"], "secondary": PALETTE["ink_muted"], "accent": PALETTE["running"],
                 "positive": PALETTE["pass"], "negative": PALETTE["error"], "warning": PALETTE["needs"],
                 "info": PALETTE["autofix"], "dark": PALETTE["ink"]}

_LATIN = '"Segoe UI Variable Text", "Segoe UI", -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial'
FONT_STACKS = {
    "zh": _LATIN + ', "Microsoft JhengHei UI", "Microsoft JhengHei", "PingFang TC", "Noto Sans TC", sans-serif',
    "en": _LATIN + ', "Noto Sans", sans-serif',
    "ja": _LATIN + ', "Yu Gothic UI", "Meiryo UI", "Hiragino Sans", "Noto Sans JP", sans-serif',
    "ko": _LATIN + ', "Malgun Gothic", "Apple SD Gothic Neo", "Noto Sans KR", sans-serif',
}
MONO = '"Cascadia Mono", Consolas, "SF Mono", ui-monospace, Menlo, monospace'

GATE_STATE = {"PASS": ("pass", "●"), "AUTO_FIXED": ("autofix", "◐"), "NEEDS_HUMAN": ("needs", "◆"),
              "ERROR": ("error", "▲"), "PAUSED": ("needs", "‖"), "RUNNING": ("running", "●")}
ADVISORY = ("advisory", "○")


def gate_state(status, advisory: bool = False) -> tuple[str, str]:
    """(css modifier, glyph) for a gate status; the glyph carries the state for colour-blind readers and print."""
    if advisory:
        return ADVISORY
    return GATE_STATE.get(str(status or "").upper(), ADVISORY)


_COMPONENTS = """
html, body { background: var(--md20-paper); color: var(--md20-ink); }
body, .q-field__native, .q-btn, .q-item, .q-table, .q-tab { font-family: var(--md20-font); }
body { font-size: 14.5px; line-height: 1.55; -webkit-font-smoothing: antialiased; font-variant-numeric: tabular-nums; }
.font-mono, .md20-mono { font-family: var(--md20-mono) !important; font-size: .92em; }
.text-xs { font-size: 12.5px !important; line-height: 1.5; }
.text-sm { font-size: 13.5px !important; line-height: 1.55; }
.text-lg { font-size: 18px !important; }
.text-xl { font-size: 22.5px !important; font-weight: 650 !important; }
.text-2xl, .text-3xl { font-size: 28px !important; font-weight: 700 !important; line-height: 1.25; }
.md20-section { font-size: 16px; font-weight: 650; margin-top: .25rem; }
.md20-muted { color: var(--md20-ink-muted); font-size: 13.5px; max-width: 72ch; }
.md20-why { color: var(--md20-ink-muted); font-size: 12.5px; line-height: 1.5; max-width: 72ch; }
.md20-changed { color: var(--md20-needs); font-size: 12.5px; }
.md20-param-label { font-size: 13.5px; font-weight: 600; }
.text-gray-500, .text-grey { color: var(--md20-ink-muted) !important; }

.md20-header { background: var(--md20-surface) !important; color: var(--md20-ink) !important;
  border-top: 3px solid var(--md20-primary); border-bottom: 1px solid var(--md20-line); box-shadow: none !important;
  min-height: 56px; padding: 0 20px; }
.md20-title { font-weight: 750; color: var(--md20-ink); }
.md20-header a { color: var(--md20-ink) !important; text-decoration: none; padding: 6px 10px;
  border-radius: var(--md20-r-control); font-weight: 500; }
.md20-header a:hover { background: var(--md20-primary-soft); color: var(--md20-primary) !important; }
.md20-header .q-field { border: 1px solid var(--md20-line); border-radius: var(--md20-r-control); padding: 0 8px; }
.md20-header .q-field__native, .md20-header .q-select__dropdown-icon { color: var(--md20-ink) !important; }

.q-card, .md20-card { background: var(--md20-surface); border: 1px solid var(--md20-line);
  border-radius: var(--md20-r-section) !important; box-shadow: none !important; }
.max-w-5xl, .max-w-6xl { max-width: var(--md20-width) !important; }
.md20-mode { cursor: pointer; transition: border-color .15s ease; }
.md20-mode:hover { border-color: var(--md20-primary); }
.q-expansion-item { border: 1px solid var(--md20-line); border-radius: var(--md20-r-section); background: var(--md20-surface); }

.q-btn { border-radius: var(--md20-r-control) !important; font-weight: 600; text-transform: none !important;
  box-shadow: none !important; min-height: 36px; }
.q-btn--outline:before { border-color: var(--md20-line-strong) !important; }
.q-btn--outline.text-primary:before { border-color: var(--md20-primary) !important; }
.q-field--focused .q-field__control:after { border-color: var(--md20-primary) !important; }
.q-tabs { border-bottom: 1px solid var(--md20-line); }
.q-tab { text-transform: none !important; font-weight: 600; color: var(--md20-ink-muted); }
.q-tab--active { color: var(--md20-primary); }
.q-uploader { border: 1px dashed var(--md20-line-strong); border-radius: var(--md20-r-section); box-shadow: none; }
.q-uploader__header { background: var(--md20-primary-soft) !important; color: var(--md20-primary) !important; }

.q-table__container { border: 1px solid var(--md20-line); border-radius: var(--md20-r-section); box-shadow: none !important; }
.q-table th { font-weight: 600; color: var(--md20-ink-muted); font-size: 12.5px; background: #F7FAFA; }
.q-table tbody td { border-color: var(--md20-line); }
.q-table tbody tr:hover td { background: var(--md20-primary-soft); }
.q-badge { border-radius: 999px; padding: 2px 9px; font-weight: 600; font-size: 12px; text-transform: none; }

.md20-gate { border-left: 4px solid var(--md20-gate-c) !important; }
.md20-gate--pass { --md20-gate-c: var(--md20-pass); }
.md20-gate--autofix { --md20-gate-c: var(--md20-autofix); }
.md20-gate--needs { --md20-gate-c: var(--md20-needs); background: #FFFBF3; }
.md20-gate--error { --md20-gate-c: var(--md20-error); }
.md20-gate--running { --md20-gate-c: var(--md20-running); }
.md20-gate--advisory { --md20-gate-c: var(--md20-line-strong); }
.md20-glyph { color: var(--md20-gate-c); font-size: 15px; line-height: 1; width: 1.1em; display: inline-block; }

.md20-notice { border-left: 4px solid var(--md20-needs) !important; }
.md20-notice--info { border-left-color: var(--md20-primary) !important; }
.md20-running { background: #F1EFFC; border-bottom: 1px solid #D9D4F5; color: var(--md20-ink); }
.md20-pulse { width: 9px; height: 9px; border-radius: 50%; background: var(--md20-running); display: inline-block;
  animation: md20-breathe 1.8s ease-in-out infinite; }
@keyframes md20-breathe { 0%, 100% { opacity: 1; } 50% { opacity: .35; } }

:focus-visible { outline: 2px solid var(--md20-primary) !important; outline-offset: 2px; }
@media (prefers-reduced-motion: reduce) { .md20-pulse { animation: none; } * { transition: none !important; } }
@media (max-width: 640px) { .md20-header { padding: 0 10px; } body { font-size: 14px; } }
"""


def css(lang: str = "en") -> str:
    p = PALETTE
    root = (":root { "
            f"--md20-paper:{p['paper']}; --md20-surface:{p['surface']}; --md20-ink:{p['ink']}; "
            f"--md20-ink-muted:{p['ink_muted']}; --md20-line:{p['line']}; --md20-line-strong:{p['line_strong']}; "
            f"--md20-primary:{p['primary']}; --md20-primary-soft:{p['primary_soft']}; --md20-pass:{p['pass']}; "
            f"--md20-autofix:{p['autofix']}; --md20-needs:{p['needs']}; --md20-error:{p['error']}; "
            f"--md20-running:{p['running']}; --md20-r-section:10px; --md20-r-control:6px; --md20-width:1120px; "
            f"--md20-font:{FONT_STACKS.get(lang, FONT_STACKS['en'])}; --md20-mono:{MONO}; }}")
    return "<style>\n" + root + _COMPONENTS + "</style>"
