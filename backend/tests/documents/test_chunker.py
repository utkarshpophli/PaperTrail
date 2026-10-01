"""Chunker tests: page-aware chunking never crosses a page boundary."""

from app.documents.chunker import chunk_document
from app.documents.schemas import ParsedDocument, ParsedPage


def _document(page_texts: list[str]) -> ParsedDocument:
    return ParsedDocument(
        pages=[ParsedPage(number=i + 1, text=text, figures=[]) for i, text in enumerate(page_texts)],
        metadata={},
    )


def test_chunks_never_cross_a_page_boundary() -> None:
    page_one_text = "alpha beta gamma. " * 100  # long enough to need multiple chunks
    page_two_text = "delta epsilon zeta. " * 100
    document = _document([page_one_text, page_two_text])

    chunks = chunk_document(document, chunk_size=200)

    assert any(chunk.page == 1 for chunk in chunks)
    assert any(chunk.page == 2 for chunk in chunks)
    for chunk in chunks:
        # a page-1 chunk must never contain page-2 vocabulary and vice versa
        if chunk.page == 1:
            assert "delta" not in chunk.text and "epsilon" not in chunk.text
        else:
            assert "alpha" not in chunk.text and "beta" not in chunk.text


def test_chunk_size_is_respected() -> None:
    document = _document(["word " * 500])

    chunks = chunk_document(document, chunk_size=200)

    assert len(chunks) > 1
    assert all(len(chunk.text) <= 200 for chunk in chunks)


def test_chunk_offsets_map_back_into_the_source_page_text() -> None:
    text = "The quick brown fox jumps over the lazy dog. " * 20
    document = _document([text])

    chunks = chunk_document(document, chunk_size=100)

    for chunk in chunks:
        assert text[chunk.start_char : chunk.end_char].strip() == chunk.text


def test_empty_page_produces_no_chunks() -> None:
    document = _document([""])

    chunks = chunk_document(document)

    assert chunks == []


def test_unparsed_page_with_empty_text_produces_no_chunks_but_page_is_not_referenced_falsely() -> None:
    document = _document(["real content here", ""])

    chunks = chunk_document(document)

    assert all(chunk.page == 1 for chunk in chunks)
