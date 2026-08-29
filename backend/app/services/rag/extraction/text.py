"""Plain text and Markdown extraction."""

from pathlib import Path

from app.services.rag.extraction.base import (
    DocumentExtractor,
    ExtractedPage,
    ExtractionError,
)
from app.services.rag.normalise import normalise_text


class PlainTextExtractor(DocumentExtractor):
    """Reads the whole file as a single page.

    Text and Markdown files have no page structure, so everything is page 1 and a
    citation reads "notes.md · page 1". Markdown is deliberately not stripped of its
    syntax: headings and list markers are useful structure for both retrieval and
    for a reader checking the source.
    """

    def extract(self, path: Path) -> list[ExtractedPage]:
        try:
            # Course notes are occasionally saved as Latin-1; replacing undecodable
            # bytes keeps a mostly-readable document rather than failing outright.
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError as error:
            raise ExtractionError("The file could not be read.") from error

        text = normalise_text(raw)
        if not text:
            raise ExtractionError("The file contains no readable text.")

        return [ExtractedPage(page_number=1, text=text)]
