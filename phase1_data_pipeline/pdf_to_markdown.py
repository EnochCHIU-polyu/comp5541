"""
Phase 1 - Data Pipeline: PDF to Markdown conversion utilities.

Primary path:
- Use MarkItDown when available.

Fallback path:
- Use pypdf text extraction and wrap as plain markdown.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import sys


@dataclass
class PdfConversionResult:
    output_path: str
    method: str
    chars_written: int


def _find_local_markitdown_src() -> str | None:
    """Best-effort path to local markitdown workspace in this dev setup."""
    candidates = [
        Path("/home/enoch/Documents/markitdown/packages/markitdown/src"),
        Path(__file__).resolve().parents[3] / "markitdown" / "packages" / "markitdown" / "src",
    ]
    for c in candidates:
        if c.exists() and c.is_dir():
            return str(c)
    return None


def _load_markitdown_class():
    """Return MarkItDown class, adding local workspace path when needed."""
    try:
        from markitdown import MarkItDown  # type: ignore

        return MarkItDown
    except ImportError:
        local_src = _find_local_markitdown_src()
        if local_src and local_src not in sys.path:
            sys.path.insert(0, local_src)
        from markitdown import MarkItDown  # type: ignore

        return MarkItDown


def _convert_with_markitdown(pdf_path: Path) -> str:
    MarkItDown = _load_markitdown_class()
    converter = MarkItDown()
    result = converter.convert(str(pdf_path))

    markdown = getattr(result, "markdown", None)
    if isinstance(markdown, str) and markdown.strip():
        return markdown

    text_content = getattr(result, "text_content", None)
    if isinstance(text_content, str) and text_content.strip():
        return text_content

    raise RuntimeError("MarkItDown returned empty output for PDF conversion")


def _convert_with_pypdf(pdf_path: Path) -> str:
    from pypdf import PdfReader  # type: ignore

    reader = PdfReader(str(pdf_path))
    chunks: list[str] = [f"# {pdf_path.stem}"]

    for idx, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ""
        text = text.strip()
        if not text:
            continue
        chunks.append(f"\n\n## Page {idx}\n\n{text}")

    md = "".join(chunks).strip()
    if not md:
        raise RuntimeError("No text extracted from PDF via pypdf")
    return md


def convert_pdf_to_markdown(
    pdf_path: str,
    output_dir: str = "data",
    output_name: str | None = None,
    overwrite: bool = False,
) -> PdfConversionResult:
    """
    Convert a PDF file to markdown and store it in output_dir.

    Conversion order:
    1. MarkItDown
    2. pypdf fallback
    """
    src = Path(pdf_path).expanduser().resolve()
    if not src.exists() or not src.is_file():
        raise FileNotFoundError(f"PDF not found: {src}")
    if src.suffix.lower() != ".pdf":
        raise ValueError(f"Input must be a .pdf file: {src}")

    out_dir = Path(output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    name = output_name or f"{src.stem}.md"
    if not name.lower().endswith(".md"):
        name = f"{name}.md"
    dst = out_dir / name

    if dst.exists() and not overwrite:
        raise FileExistsError(f"Output already exists: {dst}. Use overwrite=True to replace it.")

    used_method = ""
    try:
        markdown = _convert_with_markitdown(src)
        used_method = "markitdown"
    except Exception:
        markdown = _convert_with_pypdf(src)
        used_method = "pypdf"

    dst.write_text(markdown, encoding="utf-8")
    return PdfConversionResult(
        output_path=str(dst),
        method=used_method,
        chars_written=len(markdown),
    )


def _env_default_data_dir() -> str:
    return os.getenv("PDF_TO_MD_OUTPUT_DIR", "data")
