"""Turning retrieved chunks into prompt context, and mapping the model's answer
back to real database rows.

This is where Phase 4's grounding guarantee is enforced. The rule is the same one
the tutor follows, applied to generated study material:

    The model is shown numbered excerpts and must cite an excerpt NUMBER.
    The application maps that number back to the DocumentChunk it supplied.

So provenance is never parsed out of generated text. The model cannot invent a
document name or a page number, because it is never asked for one — the worst it
can do is cite an excerpt index, and an index we did not supply is rejected.
"""

from dataclasses import dataclass

from app.core.exceptions import AnchorError
from app.services.rag.retrieval import RetrievedChunk, page_number_for


class InsufficientMaterialError(AnchorError):
    """The course does not contain enough material to generate what was asked.

    Raised instead of falling back to the model's general knowledge. A quiz about
    material the student never uploaded would be worse than no quiz.
    """


@dataclass(frozen=True)
class GroundingContext:
    """Numbered excerpts, plus the mapping back to their source rows."""

    text: str
    chunks: list[RetrievedChunk]

    def resolve(self, excerpt_number: int) -> RetrievedChunk | None:
        """Map a model-supplied excerpt number to the chunk it refers to.

        Returns None for anything out of range, which the caller treats as an
        invalid question rather than a missing citation.
        """
        index = excerpt_number - 1
        if 0 <= index < len(self.chunks):
            return self.chunks[index]
        return None


def build_grounding_context(
    chunks: list[RetrievedChunk], *, max_chars: int = 12_000
) -> GroundingContext:
    """Render chunks as numbered excerpts for a prompt.

    Excerpt numbers are 1-based because models handle 1-based references more
    reliably than 0-based ones.
    """
    blocks: list[str] = []
    used: list[RetrievedChunk] = []
    total = 0

    for chunk in chunks:
        block = f"[Excerpt {len(used) + 1}]\n{chunk.content}"
        if total + len(block) > max_chars and used:
            break
        blocks.append(block)
        used.append(chunk)
        total += len(block)

    return GroundingContext(text="\n\n".join(blocks), chunks=used)


# Re-exported from the RAG layer, where it lives beside `RetrievedChunk`.
# It was defined here first, but `services/rag` must not import from
# `services/learning` — the dependency runs the other way, and importing it back
# created a cycle. Kept in this namespace so existing callers are unaffected.
__all__ = [
    "GroundingContext",
    "InsufficientMaterialError",
    "build_grounding_context",
    "page_number_for",
]
