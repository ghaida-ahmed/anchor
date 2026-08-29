"""Whitespace normalisation shared by the extractors.

The aim is to remove artefacts of PDF layout — soft line wraps, runs of spaces
used for column alignment — without destroying structure that carries meaning.
Paragraph and list breaks survive; single wrapped lines are joined.
"""

import re

# Three or more newlines collapse to a paragraph break.
_EXCESS_BLANK_LINES = re.compile(r"\n{3,}")
# Runs of spaces or tabs, common where a PDF aligns columns with whitespace.
_HORIZONTAL_RUNS = re.compile(r"[ \t ]{2,}")
# A word broken across a line by a hyphen, as PDFs do when justifying text.
_HYPHEN_LINE_BREAK = re.compile(r"(\w)-\n(\w)")
# Control characters that survive some PDF text layers.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def normalise_text(raw: str) -> str:
    """Tidy extracted text while preserving paragraph and list structure."""
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL_CHARS.sub("", text)
    text = _HYPHEN_LINE_BREAK.sub(r"\1\2", text)
    text = _HORIZONTAL_RUNS.sub(" ", text)
    text = _EXCESS_BLANK_LINES.sub("\n\n", text)

    # Strip trailing spaces per line, then drop leading/trailing blank lines.
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return text.strip()
