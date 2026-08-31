"""Startup banner: a rounded unicode box printed to stderr (not via logging)."""

import sys

from .termwidth import display_width, pad_display


def print_box(text: str) -> None:
    """Print text in a rounded unicode box sized to its longest line.

    The text is split on newlines as-is (not trimmed). Padding accounts
    for ANSI colors and unicode display width (see termwidth.display_width).
    """
    lines = text.split("\n")
    width = max(map(display_width, lines))
    border = "─" * (width + 2)
    out = [f"╭{border}╮"]
    out.extend(f"│ {pad_display(line, width)} │" for line in lines)
    out.append(f"╰{border}╯")
    sys.stderr.write("\n".join(out) + "\n")
