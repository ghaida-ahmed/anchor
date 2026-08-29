"""Splitting extracted pages into retrievable chunks.

Sizing, and why:

* **512 tokens per chunk.** Large enough to hold a complete idea — a definition
  plus the sentences that elaborate it — so a retrieved chunk answers rather than
  teases. Small enough that a top-5 retrieval is ~2,560 tokens, leaving ample room
  for the question and instructions inside the model's context.
* **64 tokens of overlap (12.5%).** A definition that lands on a chunk boundary
  would otherwise be split from the term it defines. Overlap costs storage and a
  little duplication in results; losing the answer costs the feature.
* **Chunks never span a page.** This is the important one. A chunk covering pages
  16–17 could not be cited honestly, and citations are the product. The cost is
  that slide decks produce some short chunks; `top_k` absorbs that.

Token counts come from `tiktoken`'s `cl100k_base`. For OpenAI that is the model's
own tokenizer. For Gemini it is an approximation — Gemini tokenises differently —
but it is a far better one than counting characters, and the margin does not matter
here: chunks are sized at 512 tokens against an input limit in the thousands, so a
±15% counting error cannot truncate anything. The value of a real tokenizer is
consistent, reproducible chunk boundaries, which this gives either way.
"""

from dataclasses import dataclass
from functools import lru_cache

import tiktoken

from app.core.config import settings
from app.services.rag.extraction import ExtractedPage

# Below this a chunk carries too little meaning to retrieve well; a trailing
# fragment this small is folded back into the previous chunk instead.
MIN_CHUNK_TOKENS = 32


@dataclass(frozen=True)
class TextChunk:
    """A chunk plus everything a citation needs to point back at its source."""

    chunk_index: int
    page_number: int
    content: str
    token_count: int


@lru_cache(maxsize=4)
def _encoding_for(model: str) -> tiktoken.Encoding:
    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        # Unknown model, or a non-OpenAI one such as Gemini: cl100k_base is a
        # stable, reasonable approximation for sizing purposes.
        return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str, model: str | None = None) -> int:
    return len(_encoding_for(model or settings.embedding_model).encode(text))


def _split_page(
    text: str,
    encoding: tiktoken.Encoding,
    chunk_tokens: int,
    overlap_tokens: int,
) -> list[tuple[str, int]]:
    """Split one page's text into (content, token_count) windows."""
    tokens = encoding.encode(text)
    if not tokens:
        return []

    if len(tokens) <= chunk_tokens:
        return [(text, len(tokens))]

    stride = chunk_tokens - overlap_tokens
    windows: list[tuple[str, int]] = []
    start = 0

    while start < len(tokens):
        window = tokens[start : start + chunk_tokens]
        windows.append((encoding.decode(window).strip(), len(window)))

        if start + chunk_tokens >= len(tokens):
            break
        start += stride

    # A tiny trailing fragment retrieves poorly on its own; merge it backwards.
    if len(windows) > 1 and windows[-1][1] < MIN_CHUNK_TOKENS:
        tail_content, tail_tokens = windows.pop()
        head_content, head_tokens = windows[-1]
        windows[-1] = (
            f"{head_content}\n{tail_content}".strip(),
            head_tokens + tail_tokens,
        )

    return windows


def chunk_pages(pages: list[ExtractedPage]) -> list[TextChunk]:
    """Turn extracted pages into ordered chunks.

    `chunk_index` is a single sequence across the whole document, so ordering is
    deterministic and a chunk can be located without a composite key.
    """
    encoding = _encoding_for(settings.embedding_model)
    chunk_tokens = settings.CHUNK_TOKENS
    overlap_tokens = settings.CHUNK_OVERLAP_TOKENS

    chunks: list[TextChunk] = []
    index = 0

    for page in pages:
        for content, token_count in _split_page(
            page.text, encoding, chunk_tokens, overlap_tokens
        ):
            if not content:
                continue
            chunks.append(
                TextChunk(
                    chunk_index=index,
                    page_number=page.page_number,
                    content=content,
                    token_count=token_count,
                )
            )
            index += 1

    return chunks
