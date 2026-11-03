"""Interface and report languages (D-74): English (default), Traditional Chinese, Japanese, Korean.

Text is written next to the code that uses it, as tuples in a fixed order:
    (zh, en)            — older two-language text; Japanese and Korean fall back to English
    (zh, en, ja, ko)    — four languages (required for new text; tests/test_i18n_coverage.py checks it)
Dicts {"zh": …, "en": …, "ja": …, "ko": …} are accepted too.  Plain strings pass through unchanged.
"""
from __future__ import annotations

LANGS = ("en", "zh", "ja", "ko")
LANG_NAMES = {"en": "English", "zh": "繁體中文", "ja": "日本語", "ko": "한국어"}
HTML_LANG = {"en": "en", "zh": "zh-Hant", "ja": "ja", "ko": "ko"}
QUASAR_LANG = {"en": "en-US", "zh": "zh-TW", "ja": "ja", "ko": "ko-KR"}
_INDEX = {"zh": 0, "en": 1, "ja": 2, "ko": 3}


def norm(lang: str | None) -> str:
    return lang if lang in LANG_NAMES else "en"


def pick(x, lang: str = "en") -> str:
    """Resolve a language tuple or dict for `lang`; missing languages fall back to English, then Chinese."""
    lang = norm(lang)
    if isinstance(x, tuple) and len(x) in (2, 4) and all(isinstance(v, str) for v in x):
        i = _INDEX[lang]
        if i < len(x) and x[i]:
            return x[i]
        return x[1] or x[0]
    if isinstance(x, dict) and ("zh" in x or "en" in x):
        return x.get(lang) or x.get("en") or x.get("zh") or ""
    return "" if x is None else str(x)


def cjk(lang: str) -> bool:
    """Full-width punctuation (：，。（）) for Chinese and Japanese; Korean and English use ASCII punctuation."""
    return norm(lang) in ("zh", "ja")


def colon(lang: str) -> str:
    return "：" if cjk(lang) else ": "


def paren(text: str, lang: str) -> str:
    return f"（{text}）" if cjk(lang) else f" ({text})"


def stop(lang: str) -> str:
    return "。" if cjk(lang) else ". "
