"""
Universal converter for ebook-to-PDF workflows.

Pipeline:
  <input X> -> ebook-convert -> <intermediate EPUB> -> process/clean/fix ->
  ebook-convert -> <output PDF>

This lets ebook2pdf accept any format Calibre supports, including PDF input,
while still applying CSS injection, table/code recovery, audit, and PDF fixes.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from typing import Optional

from .converter import (
    ConversionError,
    _ebook_convert,
    _extract_epub,
    _inject_css,
    _load_fixes_css,
    _log,
    _repack_epub,
    audit_epub,
    recover_code_blocks_in_epub,
    recover_tables_in_epub,
)
from .audit import MARGIN_SAFETY_CSS
from .code_heuristics import CODE_RECOVERY_CSS
from .figure_heuristics import normalize_captions
from .pdf_postprocess import rewrite_toc_page_numbers as _rewrite_toc_page_numbers
from .table_heuristics import TABLE_RECOVERY_CSS
from .toc_heuristics import normalize_toc_labels
from .detector import detect_book_type, publisher_label


# Calibre-supported input formats that can be converted TO epub first.
# PDF is explicitly included so users can rerun a PDF through the fix pipeline.
SUPPORTED_INPUT_FORMATS = {
    ".epub", ".pdf", ".mobi", ".azw", ".azw3", ".kfx",
    ".fb2", ".fb2.zip", ".lit", ".lrf", ".pdb", ".rb",
    ".snb", ".tcr", ".txt", ".text", ".md", ".markdown",
    ".rtf", ".doc", ".docx", ".odt", ".html", ".htm",
    ".xhtml", ".xml", ".chm", ".djvu", ".cbz", ".cbr",
    ".iba", ".ibooks", ".azw4", ".tpz", ".azw8", ".k8",
}


def _is_supported_input(path: str) -> bool:
    ext = os.path.splitext(path)[1].lower()
    if ext in SUPPORTED_INPUT_FORMATS:
        return True
    # Some Calibre inputs come through double extensions like .fb2.zip
    for fmt in SUPPORTED_INPUT_FORMATS:
        if path.lower().endswith(fmt):
            return True
    return False


def normalize_to_epub(
    input_path: str,
    work_dir: str,
    verbose: bool = False,
) -> str:
    """Convert an arbitrary ebook input to an EPUB in work_dir.

    If the input is already EPUB, this is a no-op copy/extract step.

    Returns the path to the extracted EPUB directory.
    """
    input_path = os.path.abspath(input_path)
    ext = os.path.splitext(input_path)[1].lower()

    if ext == ".epub":
        _log(verbose, "Input is already EPUB; skipping pre-conversion")
        return _extract_epub(input_path, work_dir)

    _log(verbose, f"[0/4] Converting {ext or 'unknown'} input to EPUB...")
    intermediate_epub = os.path.join(work_dir, "intermediate.epub")

    cmd = [
        "ebook-convert",
        input_path,
        intermediate_epub,
        "--output-profile=generic_eink",
        "--enable-heuristics",
        "--linearize-tables",
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        raise ConversionError("ebook-convert timed out during pre-conversion to EPUB")
    except FileNotFoundError:
        raise ConversionError(
            "ebook-convert not found. Install with: sudo apt-get install -y calibre"
        )

    if result.returncode != 0:
        error_msg = result.stderr.strip() or result.stdout.strip()[:500]
        raise ConversionError(f"Pre-conversion to EPUB failed: {error_msg}")

    if not os.path.isfile(intermediate_epub):
        raise ConversionError(
            "ebook-convert completed but intermediate EPUB was not created"
        )

    _log(verbose, f"      Pre-converted to EPUB: {intermediate_epub}")
    return _extract_epub(intermediate_epub, work_dir)


def universal_convert(
    input_path: str,
    output_path: Optional[str] = None,
    *,
    base_font_size: int = 14,
    body_font_size: int = 13,
    mono_font_size: int = 11,
    margin_top: int = 36,
    margin_bottom: int = 36,
    margin_left: int = 36,
    margin_right: int = 36,
    page_numbers: bool = True,
    add_toc: bool = True,
    rewrite_toc_page_numbers: bool = False,
    auto_font_scale: bool = True,
    auto_font_scale_threshold: int = 2,
    raw: bool = False,
    verbose: bool = False,
    work_dir: Optional[str] = None,
) -> str:
    """Convert any Calibre-supported ebook format to PDF with full fixes.

    This is the universal entrypoint. Unlike ``convert_single``, it accepts
    any input format that Calibre can read. The pipeline is:

      1. Convert input to EPUB if needed
      2. Run recovery/audit/normalization passes on the EPUB
      3. Inject comprehensive fixes CSS
      4. Auto-scale small fonts based on source profile
      5. Convert the cleaned EPUB to PDF

    Args:
        input_path: Path to any Calibre-supported ebook file.
        output_path: Desired output PDF path.
        base_font_size / body_font_size / mono_font_size: Font targets.
        margin_*: Page margins in points.
        page_numbers / add_toc: PDF pagination features.
        rewrite_toc_page_numbers: Post-process PDF ToC entries.
        auto_font_scale: Enable threshold-based font upscaling.
        auto_font_scale_threshold: Minimum pt gap before bumping a font.
        raw: If True, skip all fixup passes and pass the intermediate EPUB
             straight to ebook-convert.
        verbose: Print progress.
        work_dir: Working directory for temporary files.

    Returns:
        Path to the generated PDF.
    """
    input_path = os.path.abspath(input_path)

    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"Input file not found: {input_path}")

    if not _is_supported_input(input_path):
        raise ConversionError(
            f"Unsupported input format: {os.path.splitext(input_path)[1]}\n"
            f"Supported: {', '.join(sorted(SUPPORTED_INPUT_FORMATS))}"
        )

    if output_path is None:
        base = os.path.splitext(os.path.basename(input_path))[0]
        output_path = os.path.join(os.path.dirname(input_path), f"{base}.pdf")
    else:
        output_path = os.path.abspath(output_path)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    own_tempdir = False
    if work_dir is None:
        work_dir = tempfile.mkdtemp(prefix="epub2pdf_universal_")
        own_tempdir = True
    else:
        work_dir = os.path.abspath(work_dir)
        os.makedirs(work_dir, exist_ok=True)

    try:
        # Step 0: normalize arbitrary input -> EPUB
        extract_dir = normalize_to_epub(input_path, work_dir, verbose=verbose)

        if raw:
            _log(verbose, "RAW passthrough: skipping all EPUB fixup passes")
        else:
            # Step 1: table and code recovery
            _log(verbose, "[1/4] Running recovery heuristics...")
            tables_recovered = recover_tables_in_epub(extract_dir, verbose=verbose)
            if tables_recovered:
                _log(verbose, f"      Tables recovered in {tables_recovered} files")
            elif verbose:
                _log(verbose, "      No tabular recovery needed")

            code_files = recover_code_blocks_in_epub(extract_dir, verbose=verbose)
            if code_files:
                _log(verbose, f"      Code blocks wrapped in {code_files} files")
            elif verbose:
                _log(verbose, "      No code-block recovery needed")

            # Step 1b: audit
            _log(verbose, "[1b/4] Running quality audit...")
            audit_result = audit_epub(extract_dir, verbose=verbose)
            if verbose and audit_result.get("summary"):
                _log(verbose, f"      {audit_result['summary']}")
            if audit_result.get("fixes_applied"):
                _log(
                    verbose,
                    f"      Auto-fixed {audit_result['fixes_applied']} margin violations",
                )

            # Step 1c: structure detection
            _log(verbose, "[1c/4] Analysing book structure...")
            book_info = detect_book_type(extract_dir)
            publisher = publisher_label(book_info["publisher"])
            _log(verbose, f"      Publisher: {publisher}")
            if book_info.get("has_math_images"):
                _log(verbose, "      Math images detected - sizing fix applied")

            # Step 2: normalizations
            _log(verbose, "[2/4] Normalizing content...")
            toc_modified = normalize_toc_labels(extract_dir, verbose=verbose)
            if toc_modified and verbose:
                _log(verbose, "      TOC normalized")

            caption_modified = normalize_captions(extract_dir, verbose=verbose)
            if caption_modified and verbose:
                _log(verbose, "      Figure/table captions normalized")

            _log(verbose, "[3/4] Injecting CSS fixes...")
            _inject_css(extract_dir)

        # Step 4: convert to PDF
        _log(verbose, "[4/4] Converting to PDF...")
        epub_out = os.path.join(work_dir, "fixed_output.epub")
        _repack_epub(extract_dir, epub_out)

        effective_base = base_font_size
        effective_body = body_font_size
        effective_mono = mono_font_size
        auto_scale_report = "Auto-scale skipped (disabled)"

        if not raw and auto_font_scale:
            _log(verbose, "[4a/4] Inspecting source font profile for auto-scaling...")
            try:
                audit_result = audit_epub(extract_dir, verbose=False)
            except Exception:
                audit_result = {}

            profile = audit_result.get("source_font_profile") or {}
            source_body = profile.get("body")
            source_code = profile.get("code")
            threshold = auto_font_scale_threshold

            scaled_targets = {}
            if source_body is not None and (base_font_size - source_body) >= threshold:
                scaled_targets["base"] = (source_body, base_font_size)
                effective_base = max(effective_base, int(source_body + threshold))
            if source_body is not None and (body_font_size - source_body) >= threshold:
                scaled_targets["body"] = (source_body, body_font_size)
                effective_body = max(effective_body, int(source_body + threshold))
            if source_code is not None and (mono_font_size - source_code) >= threshold:
                scaled_targets["mono"] = (source_code, mono_font_size)
                effective_mono = max(effective_mono, int(source_code + threshold))

            if scaled_targets:
                parts = [
                    f"{k}: {v0:.2f}pt -> {v1}pt" for k, (v0, v1) in scaled_targets.items()
                ]
                auto_scale_report = "Auto-scale applied: " + ", ".join(parts)
                if verbose:
                    _log(verbose, f"      {auto_scale_report}")
            else:
                auto_scale_report = "Auto-scale not needed (source fonts within threshold)"
                if verbose:
                    _log(verbose, f"      {auto_scale_report}")
        elif not auto_font_scale:
            auto_scale_report = "Auto-scale disabled via flag"
            if verbose:
                _log(verbose, f"      {auto_scale_report}")

        _ebook_convert(
            epub_out,
            output_path,
            base_font_size=effective_base,
            body_font_size=effective_body,
            mono_font_size=effective_mono,
            margins=(margin_top, margin_bottom, margin_left, margin_right),
            page_numbers=page_numbers,
            add_toc=add_toc,
            toc_selectors=("//h:h1", "//h:h2", "//h:h3"),
        )

        if rewrite_toc_page_numbers:
            _log(verbose, "[5/5] Rewriting PDF ToC page numbers...")
            _rewrite_toc_page_numbers(output_path)

        size_kb = os.path.getsize(output_path) / 1024
        _log(verbose, f"\nDone: {output_path} ({size_kb:.0f} KB)")
        _log(verbose, auto_scale_report)

        return output_path

    except Exception:
        if own_tempdir and os.path.isdir(work_dir):
            shutil.rmtree(work_dir, ignore_errors=True)
        raise

    finally:
        if own_tempdir and os.path.isdir(work_dir):
            shutil.rmtree(work_dir, ignore_errors=True)


def universal_convert_batch(
    input_path: str,
    output_dir: Optional[str] = None,
    *,
    recursive: bool = False,
    verbose: bool = False,
    **kwargs,
) -> list[dict]:
    """Batch-convert any supported ebook files in a directory to PDF.

    Args:
        input_path: Directory or single file path.
        output_dir: Directory for PDFs.
        recursive: Recurse into subdirectories.
        verbose: Print progress.
        **kwargs: Forwarded to ``universal_convert``.

    Returns:
        List of dicts with keys: input, output, status, error.
    """
    results = []

    if os.path.isfile(input_path) and _is_supported_input(input_path):
        paths = [input_path]
    elif os.path.isdir(input_path):
        pattern = "**/*" if recursive else "*"
        import glob

        paths = sorted(
            p
            for p in glob.glob(os.path.join(input_path, pattern), recursive=recursive)
            if _is_supported_input(p)
        )
        if not paths:
            print(f"No supported ebook files found in: {input_path}")
            return results
    else:
        print(f"Not a valid input path: {input_path}")
        return results

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    total = len(paths)
    for idx, path in enumerate(paths, 1):
        if output_dir:
            out_name = os.path.splitext(os.path.basename(path))[0] + ".pdf"
            out_path = os.path.join(output_dir, out_name)
        else:
            out_path = None

        entry = {"input": path, "output": None, "status": "pending", "error": None}
        try:
            if verbose:
                print(f"\n[{idx}/{total}] {os.path.basename(path)}")
            result = universal_convert(
                path, output_path=out_path, verbose=verbose, **kwargs
            )
            entry["output"] = result
            entry["status"] = "ok"
        except Exception as e:
            entry["status"] = "error"
            entry["error"] = str(e)
            if verbose:
                print(f"  FAILED: {e}")

        results.append(entry)

    ok_count = sum(1 for r in results if r["status"] == "ok")
    err_count = sum(1 for r in results if r["status"] == "error")
    print(f"\nBatch complete: {ok_count} converted, {err_count} failed out of {total}")
    return results
