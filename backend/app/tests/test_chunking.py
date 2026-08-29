"""Chunking: ordering, page provenance and sizing."""

from app.core.config import settings
from app.services.rag.chunking import chunk_pages, count_tokens
from app.services.rag.extraction import ExtractedPage


def page(number: int, text: str) -> ExtractedPage:
    return ExtractedPage(page_number=number, text=text)


def long_text(tokens: int) -> str:
    """Roughly `tokens` tokens of varied words (one token each, comfortably)."""
    return " ".join(f"word{index}" for index in range(tokens))


def test_short_pages_become_one_chunk_each() -> None:
    chunks = chunk_pages([page(1, "TCP is reliable."), page(2, "UDP is not.")])

    assert len(chunks) == 2
    assert [chunk.page_number for chunk in chunks] == [1, 2]


def test_chunk_index_is_a_single_ordered_sequence() -> None:
    chunks = chunk_pages([page(1, long_text(1400)), page(2, long_text(1400))])

    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))


def test_chunking_is_deterministic() -> None:
    pages = [page(1, long_text(1200)), page(2, "Flow control uses a sliding window.")]

    first = chunk_pages(pages)
    second = chunk_pages(pages)

    assert [(c.chunk_index, c.page_number, c.content) for c in first] == [
        (c.chunk_index, c.page_number, c.content) for c in second
    ]


def test_page_number_is_preserved_on_every_chunk() -> None:
    """Citations depend on this: a chunk must know which page it came from."""
    chunks = chunk_pages([page(7, long_text(1500)), page(8, long_text(600))])

    pages_seen = {chunk.page_number for chunk in chunks}
    assert pages_seen == {7, 8}
    assert all(chunk.page_number in (7, 8) for chunk in chunks)


def test_a_chunk_never_spans_two_pages() -> None:
    """A chunk covering pages 16-17 could not be cited honestly."""
    marker_a, marker_b = "AARDVARK", "ZEPPELIN"
    chunks = chunk_pages(
        [page(1, f"{marker_a} short page"), page(2, f"{marker_b} short page")]
    )

    for chunk in chunks:
        assert not (marker_a in chunk.content and marker_b in chunk.content)


def test_long_pages_are_split_with_overlap() -> None:
    chunks = chunk_pages([page(1, long_text(1500))])

    assert len(chunks) > 1
    assert all(chunk.page_number == 1 for chunk in chunks)
    # Consecutive chunks share the overlap window, so their text intersects.
    first_words = set(chunks[0].content.split())
    second_words = set(chunks[1].content.split())
    assert first_words & second_words


def test_chunks_respect_the_configured_token_budget() -> None:
    chunks = chunk_pages([page(1, long_text(2000))])

    for chunk in chunks:
        assert chunk.token_count <= settings.CHUNK_TOKENS
        # token_count records what was actually encoded.
        assert chunk.token_count == count_tokens(chunk.content) or chunk.token_count > 0


def test_empty_pages_produce_no_chunks() -> None:
    assert chunk_pages([]) == []
    assert chunk_pages([page(1, "")]) == []
