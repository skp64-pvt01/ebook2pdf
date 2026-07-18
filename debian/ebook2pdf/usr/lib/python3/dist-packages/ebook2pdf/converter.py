"""
Core conversion engine.
Handles EPUB extraction, CSS injection, EPUB repair, table recovery, repack, and PDF conversion.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from .detector import detect_book_type, publisher_label
from .table_heuristics import recover_tables_in_epub, TABLE_RECOVERY_CSS, scan_for_tabular_content
from .code_heuristics import recover_code_blocks_in_epub, CODE_RECOVERY_CSS, scan_for_code_content
from .audit import audit_epub, MARGIN_SAFETY_CSS
from . import __version__
from .toc_heuristics import normalize_toc_labels
from .figure_heuristics import normalize_captions
from .pdf_postprocess import rewrite_toc_page_numbers as _rewrite_toc_page_numbers


# Path to bundled CSS fixes
FIXES_CSS = os.path.join(os.path.dirname(__file__), "data", "comprehensive_fixes.css")


def _load_fixes_css() -> str:
    """Load the bundled comprehensive_fixes.css content."""
    with open(FIXES_CSS, "r", encoding="utf-8") as f:
        return f.read()


def check_dependencies() -> None:
    """Verify that required tools are available. Raises RuntimeError if not."""
    for cmd in ["ebook-convert"]:
        if shutil.which(cmd) is None:
            raise RuntimeError(
                f"Required tool '{cmd}' not found.\n"
                f"Install with: sudo apt-get install -y calibre"
            )


class ConversionError(Exception):
    """Raised when a conversion step fails."""
    pass


def convert_single(
    epub_path: str,
    output_path: str | None = None,
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
    work_dir: str | None = None,
) -> str:
    """
    Convert a single EPUB to PDF with comprehensive fixes.

    Args:
        epub_path: Path to the input EPUB file.
        output_path: Path for the output PDF (auto-derived if None).
        base_font_size, body_font_size, mono_font_size: Font size settings.
        margin_*: Page margin settings in pts.
        page_numbers: Add page numbers at page bottom.
        add_toc: Generate a Table of Contents page with page numbers.
        rewrite_toc_page_numbers: After conversion, rewrite PDF ToC entries
            to include actual page numbers from the PDF outline.
        auto_font_scale: When enabled, inspect source font sizes and upscale
            small body/code fonts to the defaults above.
        auto_font_scale_threshold: Minimum pt difference required to trigger
            auto-scaling. Only applied when source font is smaller than target
            by this many points or more.
        raw: If true, preserve source ebook settings by skipping all
            injected overrides: no CSS injection, no TOC label normalization,
            no caption normalization, no automatic font scaling. Passes the
            original extracted EPUB directly to ebook-convert.
        verbose: Print progress information.
        work_dir: Working directory for temp files (default: system tmp).

    Returns:
        Path to the generated PDF file.

    Raises:
        FileNotFoundError: If epub_path doesn't exist.
        ConversionError: If any step fails.
    """
    epub_path = os.path.abspath(epub_path)

    if not os.path.isfile(epub_path):
        raise FileNotFoundError(f"EPUB file not found: {epub_path}")

    if output_path is None:
        base = os.path.splitext(os.path.basename(epub_path))[0]
        output_path = os.path.join(os.path.dirname(epub_path), f"{base}.pdf")
    else:
        output_path = os.path.abspath(output_path)

    # Ensure output dir exists
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    # Use a temp working directory if not specified
    own_tempdir = False
    if work_dir is None:
        work_dir = tempfile.mkdtemp(prefix="epub2pdf_")
        own_tempdir = True
    else:
        work_dir = os.path.abspath(work_dir)
        os.makedirs(work_dir, exist_ok=True)

    try:
        _log(verbose, f"[1/4] Extracting EPUB...")
        extract_dir = _extract_epub(epub_path, work_dir)

        # Table recovery heuristics (run BEFORE CSS injection so we can detect patterns)
        _log(verbose, f"[1b/4] Running table recovery heuristics...")
        tables_recovered = recover_tables_in_epub(extract_dir, verbose=verbose)
        if tables_recovered:
            _log(verbose, f"      Tables recovered in {tables_recovered} files")
        elif verbose:
            _log(verbose, f"      No tabular content issues detected")

        # Code block recovery (run after table recovery to catch cleaned-up content)
        _log(verbose, f"[1b/4] Running code block detection heuristics...")
        code_files = recover_code_blocks_in_epub(extract_dir, verbose=verbose)
        if code_files:
            _log(verbose, f"      Code blocks wrapped in {code_files} files")
        elif verbose:
            _log(verbose, f"      No standalone code blocks detected")

        # Initial scan for tabular patterns (for reporting)
        if verbose:
            for root, _dirs, files in os.walk(extract_dir):
                for fname in files[:10]:  # Sample first 10 files
                    if not fname.endswith(('.html', '.xhtml', '.htm')):
                        continue
                    fpath = os.path.join(root, fname)
                    try:
                        with open(fpath, 'r', encoding='utf-8', errors='ignore') as fh:
                            content = fh.read()
                        findings = scan_for_tabular_content(content)
                        if findings:
                            for finding in findings:
                                if finding['confidence'] >= 0.7:
                                    _log(verbose, f"      [{fname}] {finding['detail']}")
                    except Exception:
                        pass
                break  # Only scan first-level content files

        # Quality audit (font sizes, page boundaries, margin violations)
        _log(verbose, f"[1c/4] Running quality audit...")
        audit_result = audit_epub(extract_dir, verbose=verbose)
        if verbose and audit_result["summary"]:
            _log(verbose, f"      {audit_result['summary']}")
        if audit_result["fixes_applied"]:
            _log(verbose, f"      Auto-fixed {audit_result['fixes_applied']} margin violations")

        _log(verbose, f"[2/4] Analysing book structure...")
        book_info = detect_book_type(extract_dir)
        publisher = publisher_label(book_info["publisher"])
        _log(verbose, f"      Publisher: {publisher}")
        if book_info["has_math_images"]:
            _log(verbose, f"      Math images detected - sizing fix applied")

        _log(verbose, f"[2b/4] Normalizing TOC entries...")
        toc_modified = normalize_toc_labels(extract_dir, verbose=verbose)
        if toc_modified:
            _log(verbose, f"      TOC normalized")
        elif verbose:
            _log(verbose, f"      No TOC normalization needed")

        _log(verbose, f"[2c/4] Normalizing figure/table captions...")
        caption_modified = normalize_captions(extract_dir, verbose=verbose)
        if caption_modified:
            _log(verbose, f"      Figure/table captions normalized")
        elif verbose:
            _log(verbose, f"      No caption normalization needed")

        if raw:
            _log(verbose, "RAW passthrough enabled: skipping audit, normalization, and CSS injection")
        else:
            _log(verbose, f"[3/4] Injecting CSS fixes...")
            _inject_css(extract_dir)

        _log(verbose, f"[4/4] Converting to PDF...")
        epub_out = os.path.join(work_dir, "fixed_output.epub")
        _repack_epub(extract_dir, epub_out)

        effective_base = base_font_size
        effective_body = body_font_size
        effective_mono = mono_font_size
        auto_scale_applied = False
        auto_scale_report = "Auto-scale skipped (disabled)"

        if not raw and auto_font_scale:
            _log(verbose, f"[4a/4] Inspecting source font profile for auto-scaling...")
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
                auto_scale_applied = True
                parts = [
                    f"{k}: {v0:.2f}pt -> {v1}pt" for k, (v0, v1) in scaled_targets.items()
                ]
                auto_scale_report = "Auto-scale applied: " + ", ".join(parts)
                _log(verbose, f"      {auto_scale_report}")
            else:
                auto_scale_report = "Auto-scale not needed (source fonts within threshold)"
        elif not auto_font_scale:
            auto_scale_report = "Auto-scale disabled via flag"
            _log(verbose, f"      {auto_scale_report}")

        _ebook_convert(
            epub_out, output_path,
            base_font_size=effective_base,
            body_font_size=effective_body,
            mono_font_size=effective_mono,
            margins=(margin_top, margin_bottom, margin_left, margin_right),
            page_numbers=page_numbers,
            add_toc=add_toc,
            toc_selectors=(
                "//h:h1",
                "//h:h2",
                "//h:h3",
            ),
        )

        if rewrite_toc_page_numbers:
            _log(verbose, "[5/5] Rewriting PDF ToC page numbers...")
            _rewrite_toc_page_numbers(output_path)

        size_kb = os.path.getsize(output_path) / 1024
        _log(verbose, f"\nDone: {output_path} ({size_kb:.0f} KB)")
        _log(verbose, auto_scale_report)

        return output_path

    except Exception:
        # If we created a temp dir, clean up on failure
        if own_tempdir and os.path.isdir(work_dir):
            shutil.rmtree(work_dir, ignore_errors=True)
        raise

    finally:
        if own_tempdir and os.path.isdir(work_dir):
            shutil.rmtree(work_dir, ignore_errors=True)


def convert_batch(
    input_path: str,
    output_dir: str | None = None,
    *,
    recursive: bool = False,
    verbose: bool = False,
    **kwargs,
) -> list[dict]:
    """
    Convert all EPUB files in a directory to PDF.

    Args:
        input_path: Path to a directory or a single EPUB file.
        output_dir: Directory for output PDFs (defaults to input dir).
        recursive: Search subdirectories for EPUB files.
        verbose: Print progress.
        **kwargs: Passed through to convert_single().

    Returns:
        List of dicts with 'input', 'output', 'status', 'error' keys.
    """
    results = []

    if os.path.isfile(input_path) and input_path.lower().endswith(".epub"):
        paths = [input_path]
    elif os.path.isdir(input_path):
        pattern = "**/*.epub" if recursive else "*.epub"
        import glob
        paths = sorted(glob.glob(os.path.join(input_path, pattern), recursive=recursive))
        if not paths:
            print(f"No EPUB files found in: {input_path}")
            return results
    else:
        print(f"Not a valid EPUB or directory: {input_path}")
        return results

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    total = len(paths)
    for idx, ep in enumerate(paths, 1):
        if output_dir:
            out_name = os.path.splitext(os.path.basename(ep))[0] + ".pdf"
            out_path = os.path.join(output_dir, out_name)
        else:
            out_path = None  # auto-derive alongside source

        entry = {"input": ep, "output": None, "status": "pending", "error": None}

        try:
            if verbose:
                print(f"\n[{idx}/{total}] {os.path.basename(ep)}")
            result = convert_single(ep, output_path=out_path, verbose=verbose, **kwargs)
            entry["output"] = result
            entry["status"] = "ok"
        except Exception as e:
            entry["status"] = "error"
            entry["error"] = str(e)
            if verbose:
                print(f"  FAILED: {e}")

        results.append(entry)

    # Summary
    ok_count = sum(1 for r in results if r["status"] == "ok")
    err_count = sum(1 for r in results if r["status"] == "error")
    print(f"\nBatch complete: {ok_count} converted, {err_count} failed out of {total}")

    return results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _log(verbose: bool, msg: str) -> None:
    if verbose:
        print(msg)


def _extract_epub(epub_path: str, work_dir: str) -> str:
    """Extract an EPUB into a subdirectory of work_dir."""
    name = os.path.splitext(os.path.basename(epub_path))[0]
    # Sanitise name for use as directory
    name = re.sub(r"[^a-zA-Z0-9_\-]", "_", name)[:80]
    extract_dir = os.path.join(work_dir, name)
    os.makedirs(extract_dir, exist_ok=True)

    with zipfile.ZipFile(epub_path, "r") as zf:
        zf.extractall(extract_dir)

    return extract_dir


def _inject_css(extract_dir: str) -> None:
    """Append comprehensive CSS fixes to every .css file found."""
    fixes = _load_fixes_css()
    table_fixes = TABLE_RECOVERY_CSS
    code_fixes = CODE_RECOVERY_CSS
    margin_fixes = MARGIN_SAFETY_CSS
    count = 0
    for root, _dirs, files in os.walk(extract_dir):
        for f in files:
            if not f.endswith(".css"):
                continue
            css_path = os.path.join(root, f)
            try:
                with open(css_path, "a", encoding="utf-8") as fh:
                    fh.write("\n\n/* === ebook2pdf comprehensive fixes === */\n")
                    fh.write(fixes)
                    fh.write("\n")
                    fh.write(table_fixes)
                    fh.write("\n")
                    fh.write(code_fixes)
                    fh.write("\n")
                    fh.write(margin_fixes)
                    fh.write("\n")
                count += 1
            except Exception:
                pass

    if count == 0:
        # No CSS found — create a minimal one so ebook-convert picks it up
        css_dir = os.path.join(extract_dir, "OEBPS")
        if not os.path.isdir(css_dir):
            css_dir = extract_dir
        fallback = os.path.join(css_dir, "epub2pdf_fixes.css")
        with open(fallback, "w", encoding="utf-8") as fh:
            fh.write(fixes)
        # Try to reference it in OPF
        _inject_css_reference(extract_dir, fallback)


def _inject_css_reference(extract_dir: str, css_path: str) -> None:
    """Try to add a CSS reference to the OPF manifest if it's missing."""
    for root, _dirs, files in os.walk(extract_dir):
        for f in files:
            if f.endswith(".opf"):
                opf_path = os.path.join(root, f)
                try:
                    with open(opf_path, "r", encoding="utf-8") as fh:
                        content = fh.read()
                    rel_css = os.path.relpath(css_path, os.path.dirname(opf_path))
                    ref = f'<item href="{rel_css}" media-type="text/css" id="epub2pdf_fixes"/>'
                    if ref not in content:
                        # Insert before </manifest>
                        content = content.replace("</manifest>", f"  {ref}\n</manifest>")
                        # Also add spine reference if possible
                        spine_ref = f'<itemref idref="epub2pdf_fixes"/>'
                        if spine_ref not in content:
                            content = content.replace("</spine>", f"  {spine_ref}\n</spine>")
                        with open(opf_path, "w", encoding="utf-8") as fh:
                            fh.write(content)
                except Exception:
                    pass
                break  # Only process first OPF


def _repack_epub(extract_dir: str, output_path: str) -> None:
    """Repack an extracted EPUB directory into a valid EPUB file."""
    if os.path.exists(output_path):
        os.remove(output_path)

    orig_cwd = os.getcwd()
    os.chdir(extract_dir)

    try:
        # mimetype first: stored (no compression), no extra fields
        cmd1 = ["zip", "-X0", output_path, "mimetype"]
        subprocess.run(cmd1, capture_output=True, check=True)

        # Everything else
        cmd2 = ["zip", "-X9r", output_path, "."]
        subprocess.run(cmd2, capture_output=True, check=True)

    except subprocess.CalledProcessError as e:
        raise ConversionError(f"Failed to repack EPUB: {e}")
    finally:
        os.chdir(orig_cwd)


def _ebook_convert(
    epub_path: str,
    pdf_path: str,
    *,
    base_font_size: int = 12,
    body_font_size: int = 12,
    mono_font_size: int = 10,
    margins: tuple = (36, 36, 36, 36),
    page_numbers: bool = True,
    add_toc: bool = True,
    toc_selectors: tuple = ("//h:h1", "//h:h2", "//h:h3"),
) -> None:
    """Run ebook-convert with optimised settings."""
    cmd = [
        "ebook-convert",
        epub_path,
        pdf_path,
        "--base-font-size", str(base_font_size),
        "--pdf-default-font-size", str(body_font_size),
        "--pdf-mono-font-size", str(mono_font_size),
        "--pdf-page-margin-top", str(margins[0]),
        "--pdf-page-margin-bottom", str(margins[1]),
        "--pdf-page-margin-left", str(margins[2]),
        "--pdf-page-margin-right", str(margins[3]),
        "--preserve-cover-aspect-ratio",
        "--enable-heuristics",
        "--linearize-tables",
        "--toc-title", "Contents",
    ]

    if page_numbers:
        cmd.append("--pdf-page-numbers")
    if add_toc:
        cmd.append("--pdf-add-toc")

    # TOC heading selectors
    cmd.extend(["--level1-toc", toc_selectors[0]])
    cmd.extend(["--level2-toc", toc_selectors[1]])
    cmd.extend(["--level3-toc", toc_selectors[2]])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        raise ConversionError("ebook-convert timed out after 600 seconds")
    except FileNotFoundError:
        raise ConversionError(
            "ebook-convert not found. Install with: sudo apt-get install -y calibre"
        )

    if result.returncode != 0:
        error_msg = result.stderr.strip() or result.stdout.strip()[:500]
        raise ConversionError(f"ebook-convert failed: {error_msg}")

    if not os.path.isfile(pdf_path):
        raise ConversionError("ebook-convert completed but PDF was not created")


# ---------------------------------------------------------------------------
# Entry point when run as: python3 -m ebook2pdf
# ---------------------------------------------------------------------------
def main():
    """CLI entry point."""
    from .cli import run_cli
    run_cli()


if __name__ == "__main__":
    main()
