"""Quick PDF inspection helper — prints the first and a middle page of a transcript PDF.

Usage:
    python scripts/inspect_pdf.py path/to/transcript.pdf
"""

import sys

import pdfplumber


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)

    path = sys.argv[1]
    with pdfplumber.open(path) as pdf:
        print(f"Total pages: {len(pdf.pages)}")
        first_page = pdf.pages[0].extract_text() or ""
        print("--- PAGE 1 ---")
        print(first_page[:500])
        print("--------------")

        mid_index = len(pdf.pages) // 2
        mid_page = pdf.pages[mid_index].extract_text() or ""
        print(f"--- PAGE {mid_index + 1} ---")
        print(mid_page[:500])
        print("--------------")


if __name__ == "__main__":
    main()
