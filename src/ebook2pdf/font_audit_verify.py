"""
Post-conversion PDF font-size verification.

Checks rendered text sizes in the generated PDF against configurable minimums for
body text, headings, code, and captions. Uses PyMuPDF when available for accurate
span-level font metrics; otherwise falls back gracefully.

This module exists to prevent silent drift where CLI/code defaults for font sizing
become inconsistent, or where Calibre ignores passed options for some inputs.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Default minimum rendered sizes in PDF points
DEFAULT_MIN_BODY_PT = 9.0
DEFAULT_MIN_HEADING_PT = 10.0
DEFAULT_MIN_MONO_PT = 8.0
DEFAULT_MIN_CAPTION_PT = 8.0

# Heuristics used to guess element role from text content
_HEADING_KEYWORDS = ("chapter", "part", "appendix", "contents", "preface", "index")
_FIGURE_PREFIXES = ("figure ", "fig. ", "table ", "listing ", "algorithm ")


class FontSizeAuditError(Exception):
    """Raised when post-conversion font-size verification fails in strict mode."""


def verify_rendered_font_sizes(
    pdf_path: str,
    *,
    min_body_pt: float = DEFAULT_MIN_BODY_PT,
    min_heading_pt: float = DEFAULT_MIN_HEADING_PT,
    min_mono_pt: float = DEFAULT_MIN_MONO_PT,
    min_caption_pt: float = DEFAULT_MIN_CAPTION_PT,
    max_pages: int = 20,
    sample_stride: int = 1,
    strict: bool = False,
) -> Optional[dict]:
    """
    Open the rendered PDF and verify minimum font sizes on a representative sample.

    Args:
        pdf_path: Path to the generated PDF.
        min_body_pt: Minimum allowed body text size.
        min_heading_pt: Minimum allowed heading/header text size.
        min_mono_pt: Minimum allowed monospace text size.
        min_caption_pt: Minimum allowed caption/figure text size.
        max_pages: Maximum pages to inspect.
        sample_stride: Inspect every Nth page in the sampled range.
        strict: If True, raise FontSizeAuditError when thresholds are violated.

    Returns:
        Audit report dict, or None when no verifier is available.

    Raises:
        FontSizeAuditError: When strict=True and violations are found.
    """
    if not os.path.isfile(pdf_path):
        raise FileNotFoundError(f"PDF not found for font verification: {pdf_path}")

    verifier = _load_verifier()
    if verifier is None:
        logger.warning("No PDF font verifier available; skipping post-conversion font check.")
        return None

    report = verifier(
        pdf_path,
        min_body_pt=min_body_pt,
        min_heading_pt=min_heading_pt,
        min_mono_pt=min_mono_pt,
        min_caption_pt=min_caption_pt,
        max_pages=max_pages,
        sample_stride=sample_stride,
    )
    if not report:
        return report

    logger.info(
        "Post-conversion font audit: body_min=%s heading_min=%s mono_min=%s caption_min=%s total_checked=%s offenders=%s",
        report.get("body_min_observed"),
        report.get("heading_min_observed"),
        report.get("mono_min_observed"),
        report.get("caption_min_observed"),
        report.get("spans_checked"),
        len(report.get("offenders", [])),
    )

    if strict and report.get("violations"):
        msgs = [
            f"page {o['page']}: {o['category']} {o['size']:.2f}pt < {o['threshold']:.2f}pt -> {o['text'][:60]!r}"
            for o in report["violations"][:20]
        ]
        raise FontSizeAuditError(
            f"Post-conversion font-size minimums violated for {pdf_path}:" + "\n" + "\n".join(msgs)
        )

    return report


def _load_verifier():
    """Return the best available page-span font verifier, or None."""
    try:
        from .font_audit_pymupdf import verify_with_pymupdf  # type: ignore
        return verify_with_pymupdf
    except Exception:
        pass
    try:
        from .font_audit_pypdf import verify_with_pypdf  # type: ignore
        return verify_with_pypdf
    except Exception:
        pass
    return None
