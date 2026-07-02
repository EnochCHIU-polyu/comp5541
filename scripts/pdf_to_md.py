"""CLI: Convert an input PDF to markdown and save under data/."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from phase1_data_pipeline.pdf_to_markdown import convert_pdf_to_markdown, _env_default_data_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert PDF to markdown and save in data folder")
    parser.add_argument("--pdf", required=True, help="Path to input PDF")
    parser.add_argument("--output-dir", default=_env_default_data_dir(), help="Output directory (default: data)")
    parser.add_argument("--name", default=None, help="Output markdown filename (optional)")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing markdown output")
    args = parser.parse_args()

    result = convert_pdf_to_markdown(
        pdf_path=args.pdf,
        output_dir=args.output_dir,
        output_name=args.name,
        overwrite=args.overwrite,
    )

    print("Converted successfully")
    print(f"Method: {result.method}")
    print(f"Output: {result.output_path}")
    print(f"Chars: {result.chars_written}")


if __name__ == "__main__":
    main()
