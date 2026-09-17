"""Document text extraction ported from Ashlar Proposal Studio.

This module deliberately has no LLM dependency. It turns a local source file into
page-marked text plus a SHA-256 content hash so later analysis can preserve
provenance in the Ashlar Fact Ledger.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib


@dataclass(frozen=True)
class ExtractionResult:
    ok: bool
    text: str = ""
    error: str = ""
    content_hash: str = ""
    pages: int = 0


def extract_document(file_path: str | Path, original_filename: str = "") -> ExtractionResult:
    path = Path(file_path)
    if not path.exists():
        return ExtractionResult(ok=False, error="File not found")
    if path.stat().st_size == 0:
        return ExtractionResult(ok=False, error="File is empty")

    suffix = (path.suffix or Path(original_filename).suffix).lower()
    try:
        if suffix == ".pdf":
            text, pages = _extract_pdf(path)
        elif suffix == ".txt":
            text, pages = _extract_txt(path), 0
        elif suffix in {".html", ".htm"}:
            text, pages = _extract_html(path), 0
        else:
            return ExtractionResult(ok=False, error=f"Unsupported file type: {suffix}")
    except Exception as exc:
        return ExtractionResult(ok=False, error=f"Extraction failed: {exc}")

    text = text.strip()
    if len(text) < 20:
        return ExtractionResult(ok=False, error="No usable text extracted")

    digest = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()
    return ExtractionResult(ok=True, text=text, content_hash=digest, pages=pages)


def _extract_pdf(path: Path) -> tuple[str, int]:
    try:
        import fitz
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise RuntimeError("PyMuPDF is required for PDF extraction") from exc

    doc = fitz.open(str(path))
    parts: list[str] = []
    try:
        for page_no, page in enumerate(doc, start=1):
            page_text = page.get_text("text", sort=True).strip()
            parts.append(f"--- PAGE {page_no} ---\n{page_text}")
        return "\n\n".join(parts), len(doc)
    finally:
        doc.close()


def _extract_txt(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "latin-1", "iso-8859-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            pass
    raise RuntimeError("Could not decode text file")


def _extract_html(path: Path) -> str:
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise RuntimeError("beautifulsoup4 is required for HTML extraction") from exc

    raw = path.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(raw, "html.parser")
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    lines = [line.strip() for line in soup.get_text("\n").splitlines() if line.strip()]
    return "\n".join(lines)
