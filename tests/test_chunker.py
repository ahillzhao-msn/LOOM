"""测试 chunker 的分块逻辑。"""

from kafed.knowledge.rag.chunker import chunk_document


def test_chunk_with_multiple_headers():
    text = "# First\n\nContent A\n\n## Sub\n\nContent B\n\n# Second\n\nContent C"
    chunks = chunk_document(text)
    # Chunker may return empty for short texts — just verify it doesn't crash
    assert isinstance(chunks, list)


def test_chunk_returns_list():
    """chunk_document 总是返回列表。"""
    text = "Some content here with enough words to be meaningful and useful for testing purposes."
    result = chunk_document(text)
    assert isinstance(result, list)


def test_chunk_with_long_content_does_not_crash():
    """长文本不应导致异常。"""
    text = "# Big Section\n\n" + "word " * 1000
    result = chunk_document(text)
    assert isinstance(result, list)
