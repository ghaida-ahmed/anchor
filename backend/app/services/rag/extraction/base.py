"""Extraction interface shared by every supported document format."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from app.core.exceptions import AnchorError


class ExtractionError(AnchorError):
    """The document could not be turned into text.

    Carries a message safe to store on the document row and show to the student —
    never a stack trace or a filesystem path.
    """


@dataclass(frozen=True)
class ExtractedPage:
    """One page of extracted text.

    `page_number` is 1-based and is what a citation shows. Formats without real
    pages report page 1, so a citation still reads sensibly.
    """

    page_number: int
    text: str


class DocumentExtractor(ABC):
    @abstractmethod
    def extract(self, path: Path) -> list[ExtractedPage]:
        """Return the document's pages in order, skipping any that hold no text.

        Raises `ExtractionError` when the document yields nothing usable.
        """
