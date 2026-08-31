"""Terminal display width calculation for unicode and ANSI-colored text."""

import re
import unicodedata

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;:]*[A-Za-z]")


def _is_wide(char: str) -> bool:
    """Return True for characters rendered as two terminal columns."""
    if unicodedata.east_asian_width(char) in {"F", "W"}:
        return True
    cp = ord(char)
    return unicodedata.category(char) == "So" and (
        0x2600 <= cp <= 0x27BF or 0x1F300 <= cp <= 0x1F9FF or 0x1FA00 <= cp <= 0x1FAFF
    )


def display_width(text: str) -> int:
    """Calculate the display width of a string in terminal columns.

    ANSI escape codes are ignored. Wide characters (East Asian F/W and
    emoji) count as two columns, combining marks and format characters
    (e.g. emoji variation selectors) as zero.
    """
    plain = ANSI_ESCAPE_RE.sub("", text)
    width = 0
    for char in plain:
        if unicodedata.category(char) in {"Mn", "Mc", "Me", "Cf"}:
            continue
        width += 2 if _is_wide(char) else 1
    return width


def pad_display(text: str, width: int) -> str:
    """Pad text with trailing spaces to the given display width (no truncation)."""
    return text + " " * max(width - display_width(text), 0)
