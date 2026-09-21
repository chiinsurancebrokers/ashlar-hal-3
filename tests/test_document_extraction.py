from backend.app.documents.extraction import extract_document


def test_txt_extraction_has_hash_and_text(tmp_path):
    path = tmp_path / "quote.txt"
    path.write_text("Cigna Executive quotation\nAnnual limit EUR 2,000,000\nPremium EUR 8,500", encoding="utf-8")
    result = extract_document(path)
    assert result.ok is True
    assert "Annual limit" in result.text
    assert len(result.content_hash) == 64


def test_unsupported_document_type_fails_closed(tmp_path):
    path = tmp_path / "quote.bin"
    path.write_bytes(b"some binary content that is long enough")
    result = extract_document(path)
    assert result.ok is False
    assert "Unsupported file type" in result.error
