from __future__ import annotations

import re

_FW = "\uff5c"
_BAR = "[" + _FW + "|]"
_DSML_OPEN = "<" + _BAR + "{0,2}DSML" + _BAR + "{0,2}[^>]*>"
_DSML_CLOSE = "</" + _BAR + "{0,2}DSML" + _BAR + "{0,2}[^>]*>"

_DSML_BLOCK_RE = re.compile(
    _DSML_OPEN + r".*?" + _DSML_CLOSE, re.IGNORECASE | re.DOTALL
)
_DSML_TAG_RE = re.compile(
    r"</?" + _BAR + "{0,2}DSML" + _BAR + "{0,2}[^>]*>", re.IGNORECASE
)
_TOOL_MARKER_RE = re.compile(r"<\|.*?\|>", re.DOTALL)
_DSML_LINE_RE = re.compile(r"(?im)^.*\bDSML\b.*$")
_BLANK_LINES_RE = re.compile(r"\n{3,}")

_MARKERS = ("dsml", "tool_calls", "function_call", "<|")


def has_tool_markup(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    if any(marker in lowered for marker in _MARKERS):
        return True
    return bool(_TOOL_MARKER_RE.search(text))


def strip_tool_markup(text: str) -> str:
    if not text:
        return ""

    cleaned = _DSML_BLOCK_RE.sub(" ", text)
    cleaned = _DSML_TAG_RE.sub(" ", cleaned)
    cleaned = _TOOL_MARKER_RE.sub(" ", cleaned)
    cleaned = _DSML_LINE_RE.sub(" ", cleaned)
    cleaned = _BLANK_LINES_RE.sub("\n\n", cleaned)
    return cleaned.strip()
