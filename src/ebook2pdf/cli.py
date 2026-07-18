"""
Command-line interface for ebook2pdf.
"""

from __future__ import annotations

import argparse
import os
import sys
import textwrap
import warnings
from typing import Dict, Optional

from . import __version__
from .converter import check_dependencies, convert_batch, convert_single, ConversionError
from .universal_converter import universal_convert, universal_convert_batch


# Keep a single source of truth for CLI font defaults so other modules can verify
# converter.py and cli.py do not accidentally diverge.
CLI_FONT_DEFAULTS: Dict[str, int] = {
    "base_font_size": 14,
    "body_font_size": 13,
    "mono_font_size": 11,
}


def check_matching_defaults() -> None:
    """Assert that converter.convert_single() font defaults match CLI defaults.

    Call this at import-time or in tests to prevent silent default drift between
    the CLI parser and the conversion engine.
    """
    import inspect

    from .converter import convert_single

    param_defaults = {
        name: param.default
        for name, param in inspect.signature(convert_single).parameters.items()
        if name in CLI_FONT_DEFAULTS
    }
    mismatches = {
        k: (param_defaults[k], CLI_FONT_DEFAULTS[k])
        for k in CLI_FONT_DEFAULTS
        if param_defaults.get(k) != CLI_FONT_DEFAULTS[k]
    }
    if mismatches:
        warnings.warn(
            "Font default mismatch between CLI and converter: " + repr(mismatches),
            stacklevel=2,
        )


def build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser."""
    parser = argparse.ArgumentParser(
        prog="ebook2pdf",
        description="Convert ebooks to PDF with comprehensive formatting fixes. "
                    "Supports any format Calibre can read, including PDF input.",
        epilog=textwrap.dedent("""\
            Examples:
              ebook2pdf book.epub
              ebook2pdf book.epub -o output.pdf --verbose
              ebook2pdf book.pdf -o repaired.pdf --raw
              ebook2pdf /path/to/ebooks/ --recursive
              ebook2pdf /path/to/ebooks/ --output-dir /path/to/pdfs/
              ebook2pdf /path/to/ebooks/ --font-size 10 --margin 24
              ebook2pdf book.epub --raw
              ebook2pdf book.mobi --format mobi
        """),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Positional
    parser.add_argument(
        "input",
        nargs="?",
        default=None,
        help="Ebook file or directory containing ebook files",
    )

    # Output options
    parser.add_argument(
        "-o", "--output",
        dest="output",
        help="Output PDF path (for single file) or output directory (for batch)",
    )

    # Format options
    parser.add_argument(
        "--format",
        dest="input_format",
        default=None,
        help="Input format override (e.g. pdf, mobi, epub). Default: auto-detect by extension",
    )
    parser.add_argument(
        "--output-format",
        dest="output_format",
        default="pdf",
        help="Output format. Currently only PDF is supported (default: pdf)",
    )

    # Font options
    parser.add_argument(
        "--font-size", "--base-font-size",
        dest="base_font_size",
        type=int,
        default=CLI_FONT_DEFAULTS["base_font_size"],
        help="Base font size in pt (default: %(default)s)",
    )
    parser.add_argument(
        "--body-font-size",
        dest="body_font_size",
        type=int,
        default=CLI_FONT_DEFAULTS["body_font_size"],
        help="Body text font size in pt (default: %(default)s)",
    )
    parser.add_argument(
        "--mono-font-size",
        dest="mono_font_size",
        type=int,
        default=CLI_FONT_DEFAULTS["mono_font_size"],
        help="Monospace/code font size in pt (default: %(default)s)",
    )

    # Margin options
    parser.add_argument(
        "--margin",
        type=int,
        default=None,
        help="Uniform page margin in pts (overrides individual margin settings)",
    )
    parser.add_argument(
        "--margin-top", type=int, default=36,
        help="Top margin in pts (default: 36)",
    )
    parser.add_argument(
        "--margin-bottom", type=int, default=36,
        help="Bottom margin in pts (default: 36)",
    )
    parser.add_argument(
        "--margin-left", type=int, default=36,
        help="Left margin in pts (default: 36)",
    )
    parser.add_argument(
        "--margin-right", type=int, default=36,
        help="Right margin in pts (default: 36)",
    )

    # Batch options
    parser.add_argument(
        "-r", "--recursive",
        action="store_true",
        help="Search directories recursively for ebook files",
    )
    parser.add_argument(
        "--output-dir",
        dest="output_dir",
        help="Output directory for batch conversions",
    )

    # Toggle options
    parser.add_argument(
        "--no-page-numbers",
        dest="page_numbers",
        action="store_false",
        default=True,
        help="Disable page number footer in PDF",
    )
    parser.add_argument(
        "--rewrite-toc-page-numbers",
        dest="rewrite_toc_page_numbers",
        action="store_true",
        default=False,
        help="After conversion, rewrite PDF ToC entries to actual page numbers",
    )
    parser.add_argument(
        "--no-auto-font-scale",
        dest="auto_font_scale",
        action="store_false",
        default=True,
        help="Disable automatic font-size upscaling for small-source fonts",
    )
    parser.add_argument(
        "--auto-font-scale-threshold",
        dest="auto_font_scale_threshold",
        type=int,
        default=2,
        help="Minimum pt gap between source and requested font to trigger scaling (default: 2)",
    )
    parser.add_argument(
        "--raw",
        dest="raw",
        action="store_true",
        default=False,
        help="Passthrough mode: disable all injected overrides and use source ebook conversion settings",
    )
    parser.add_argument(
        "--force-universal",
        dest="force_universal",
        action="store_true",
        default=False,
        help="Force the universal multi-format pipeline even for EPUB inputs",
    )
    parser.add_argument(
        "--no-toc",
        dest="add_toc",
        action="store_false",
        default=True,
        help="Disable auto-generated Table of Contents page",
    )

    # Other
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show detailed progress information",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Show version information and exit",
    )

    return parser


def _detect_format(input_path: str, explicit_format: Optional[str]) -> str:
    if explicit_format:
        return explicit_format.lower().lstrip(".")
    ext = os.path.splitext(input_path)[1].lower()
    if ext:
        return ext.lstrip(".")
    return ""


def run_cli(argv: list[str] | None = None) -> int:
    """Run the CLI. Returns exit code."""
    check_matching_defaults()
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        print(f"ebook2pdf v{__version__}")
        return 0

    # Check dependencies early
    try:
        check_dependencies()
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if not args.input:
        parser.print_usage()
        print("ebook2pdf: error: the following arguments are required: input")
        return 2

    input_path = args.input
    input_format = _detect_format(input_path, args.input_format)

    if args.margin is not None:
        mt = mb = ml = mr = args.margin
    else:
        mt = args.margin_top
        mb = args.margin_bottom
        ml = args.margin_left
        mr = args.margin_right

    font_kwargs = {
        "base_font_size": args.base_font_size,
        "body_font_size": args.body_font_size,
        "mono_font_size": args.mono_font_size,
    }

    common_kwargs = {
        "margin_top": mt,
        "margin_bottom": mb,
        "margin_left": ml,
        "margin_right": mr,
        "page_numbers": args.page_numbers,
        "add_toc": args.add_toc,
        "rewrite_toc_page_numbers": args.rewrite_toc_page_numbers,
        "auto_font_scale": args.auto_font_scale,
        "auto_font_scale_threshold": args.auto_font_scale_threshold,
        "raw": args.raw,
        "verbose": args.verbose,
    }

    is_batch = os.path.isdir(input_path)

    if is_batch:
        output_dir = args.output_dir or args.output or None
        results = universal_convert_batch(
            input_path,
            output_dir=output_dir,
            recursive=args.recursive,
            verbose=args.verbose,
            **font_kwargs,
            **common_kwargs,
        )
        err_count = sum(1 for r in results if r["status"] == "error")
        return 1 if err_count else 0

    # Single file mode
    output_path = args.output
    if args.output_dir:
        out_name = os.path.splitext(os.path.basename(input_path))[0] + ".pdf"
        output_path = os.path.join(args.output_dir, out_name)

    try:
        if args.force_universal or (input_format and input_format != "epub"):
            result = universal_convert(
                input_path,
                output_path=output_path,
                **font_kwargs,
                **common_kwargs,
            )
        else:
            result = convert_single(
                input_path,
                output_path=output_path,
                **font_kwargs,
                **common_kwargs,
            )
        if not args.verbose:
            print(result)
        return 0
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except ConversionError as e:
        print(f"Conversion failed: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1
