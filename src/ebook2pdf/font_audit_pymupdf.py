"""
PDF font-size verifier using PyMuPDF (fitz).

This is the preferred verifier because PyMuPDF can extract per-text-span font sizes.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, List

logger = logging.getLogger(__name__)


def verify_with_pymupdf(
    pdf_path: str,
    *,
    min_body_pt: float = 9.0,
    min_heading_pt: float = 10.0,
    min_mono_pt: float = 8.0,
    min_caption_pt: float = 8.0,
    max_pages: int = 20,
    sample_stride: int = 1,
) -> Dict[str, Any]:
    """
    Verify rendered font sizes in a PDF using PyMuPDF text blocks/spans.

    Returns a report dict with observed minimums and a list of offenders.
    """
    try:
        import fitz  # type: ignore
    except ImportError:
        raise RuntimeError("PyMuPDF is not installed.")

    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    page_limit = min(total_pages, max_pages)

    body_sizes: List[float] = []
    mono_sizes: List[float] = []
    caption_sizes: List[float] = []
    heading_sizes: List[float] = []

    offenders: List[Dict[str, Any]] = []
    violations: List[Dict[str, Any]] = []

    spans_checked = 0

    for page_idx in range(page_limit):
        if page_idx % sample_stride != 0:
            continue
        page = doc.load_page(page_idx)
        blocks = page.get_text("dict").get("blocks", [])
        for b in blocks:
            if b.get("type") != 0:
                continue
            for line in b.get("lines", []):
                spans = line.get("spans", [])
                if not spans:
                    continue
                line_text = "".join(s.get("text", "") for s in spans).strip()
                if not line_text:
                    continue
                sizes = [s.get("size") for s in spans if s.get("text", "").strip()]
                if not sizes:
                    continue
                line_min = min(sizes)
                line_max = max(sizes)
                fonts = [s.get("font", "") for s in spans if s.get("text", "").strip()]
                is_mono = any(
                    any(k in (f or "").lower() for k in ("mono", "courier", "consolas", "liberation", "jetbrains", "source code", "fira code"))
                    for f in fonts
                )
                is_heading = (
                    line_max >= 12.0
                    or line_text.strip() in _HEADING_KEYWORDS
                    or any(line_text.strip().lower().startswith(k) for k in _HEADING_KEYWORDS)
                )
                is_caption = any(line_text.strip().lower().startswith(k) for k in _FIGURE_PREFIXES)

                category_thresholds = {
                    "body": min_body_pt,
                    "heading": min_heading_pt,
                    "mono": min_mono_pt,
                    "caption": min_caption_pt,
                }
                if is_heading:
                    body_sizes.append(line_min)
                    heading_sizes.append(line_min)
                    threshold = min_heading_pt
                    category = "heading"
                elif is_caption:
                    caption_sizes.append(line_min)
                    body_sizes.append(line_min)
                    threshold = min_caption_pt
                    category = "caption"
                elif is_mono:
                    mono_sizes.append(line_min)
                    threshold = min_mono_pt
                    category = "mono"
                else:
                    body_sizes.append(line_min)
                    threshold = min_body_pt
                    category = "body"

                spans_checked += len(sizes)

                if line_min < threshold:
                    offender = {
                        "page": page_idx + 1,
                        "category": category,
                        "size": round(line_min, 2),
                        "threshold": threshold,
                        "text": line_text,
                    }
                    offenders.append(offender)
                    violations.append(offender)

    doc.close()

    report: Dict[str, Any] = {
        "verifier": "pymupdf",
        "pdf_path": pdf_path,
        "pages_scanned": page_limit,
        "spans_checked": spans_checked,
        "body_min_observed": round(min(body_sizes), 2) if body_sizes else None,
        "heading_min_observed": round(min(heading_sizes), 2) if heading_sizes else None,
        "mono_min_observed": round(min(mono_sizes), 2) if mono_sizes else None,
        "caption_min_observed": round(min(caption_sizes), 2) if caption_sizes else None,
        "offenders": offenders,
        "violations": violations,
    }
    return report


_HEADING_KEYWORDS = ("chapter", "part", "appendix", "contents", "preface", "index")
_FIGURE_PREFIXES = ("figure ", "fig. ", "table ", "listing ", "algorithm ")
