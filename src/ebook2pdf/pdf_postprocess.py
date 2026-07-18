"""
PDF post-processing for ToC page-number rewriting.

After Calibre conversion, some ToCs miss accurate page numbers or have
left-aligned page references. This module uses pypdf to:

- open the generated PDF
- walk the bookmark/outline tree
- map each outline destination to its actual page index
- rewrite the ToC text so the page number is appended flush-right
"""

from __future__ import annotations

import re
from typing import Any

from pypdf import PdfReader, PdfWriter


_TOC_NUMBER_RE = re.compile(r"^(.*?)\s*[\u2013\u2014\-]\s*(\d+)\s*$")
_LEADING_NUMBER_RE = re.compile(r"^(\d+)\s+(.*)$")


def rewrite_toc_page_numbers(input_pdf: str, output_pdf: str | None = None) -> str:
    """Rewrite ToC entries in *input_pdf* to include right-aligned page numbers.

    Returns the output PDF path.
    """
    if output_pdf is None:
        output_pdf = input_pdf

    reader = PdfReader(input_pdf)
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)

    changed = False
    for item in writer.outline or []:
        try:
            page_number = _resolve_page_number(reader, item)
        except Exception:
            page_number = None
        title = _sanitize_title(getattr(item, "title", "") or "")
        if not title:
            continue
        new_title = _build_toc_line(title, page_number)
        if new_title != title:
            try:
                item.title = new_title
                changed = True
            except Exception:
                pass

    if changed and output_pdf:
        with open(output_pdf, "wb") as fh:
            writer.write(fh)

    return output_pdf


def _resolve_page_number(reader: PdfReader, item: Any) -> int | None:
    dest = getattr(item, "dest", None)
    if dest is None and hasattr(item, "node"):
        node = item.node or {}
        dest = node.get("/Dest")
    if dest is None:
        return None
    try:
        return int(reader.get_destination_page_number(dest)) + 1
    except Exception:
        return None


def _sanitize_title(title: str) -> str:
    title = re.sub(r"\s+", " ", title).strip()
    return title


def _build_toc_line(title: str, page_number: int | None) -> str:
    if page_number is None:
        return title

    m = _TOC_NUMBER_RE.match(title)
    if m:
        existing_title, existing_page = m.group(1).strip(), m.group(2)
        if existing_page == str(page_number):
            return title
        return f"{existing_title} ..... {page_number}"

    m2 = _LEADING_NUMBER_RE.match(title)
    if m2:
        base = m2.group(2).strip()
        return f"{base} ..... {page_number}"

    return f"{title} ..... {page_number}"
