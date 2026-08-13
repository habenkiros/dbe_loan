#!/usr/bin/env python3
"""Build DECSI_Loan_Hub_User_Manuals.pdf from the combined HTML (WeasyPrint)."""

from __future__ import annotations

import runpy
from pathlib import Path

MANUAL_DIR = Path(__file__).resolve().parent
SRC = MANUAL_DIR / 'DECSI_Loan_Hub_User_Manuals.html'
OUT = MANUAL_DIR / 'DECSI_Loan_Hub_User_Manuals.pdf'


def main() -> None:
    runpy.run_path(str(MANUAL_DIR / 'build_html.py'), run_name='__main__')
    if not SRC.exists():
        raise SystemExit(f'Missing HTML: {SRC}')
    from weasyprint import HTML

    HTML(filename=str(SRC), base_url=str(MANUAL_DIR)).write_pdf(OUT)
    print(f'Wrote {OUT} ({OUT.stat().st_size} bytes)')


if __name__ == '__main__':
    main()
