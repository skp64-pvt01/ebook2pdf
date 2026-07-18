# ebook2pdf

EPUB to PDF converter with comprehensive formatting fixes.

Converts ebooks to high-quality PDFs with automatic content recovery, CSS injection,
font-size enforcement, user-assisted patch mode, and universal input support.

## Features

- **Single file conversion** — `ebook2pdf book.epub`
- **Batch directory conversion** — `ebook2pdf /path/to/ebooks/ --recursive --output-dir ./pdfs/`
- **Universal input** — accepts any Calibre-supported format via `ebook-convert` (`--force-universal`)
- **Automatic publisher detection** — Manning, Wiley, Rheinwerk, Calibre, Google Docs exports
- **Typography control** — base, body, and mono font targets with threshold-based auto-scaling
- **Content recovery** — table, code block, and figure heuristics
- **Patch mode** — YAML-driven manual overrides for problematic regions
- **Table of contents** — PDF ToC with right-aligned page numbers and optional rewrite to actual page numbers

## Installation

### From .deb

```bash
sudo apt install ./ebook2pdf_1.0.0-1_all.deb
```

### From source

```bash
pip install .
```

## Dependencies

- `calibre` (>= 7.0) — for `ebook-convert`
- `python3` (>= 3.10)

Install calibre with:

```bash
sudo apt-get install -y calibre
```

## Quick Start

```bash
# Basic conversion
ebook2pdf book.epub

# Convert a directory recursively
ebook2pdf /path/to/ebooks/ --recursive --output-dir /path/to/pdfs/

# Preserve source settings
ebook2pdf book.epub --raw

# Universal pipeline for non-EPUB input
ebook2pdf book.mobi --format mobi
ebook2pdf scanned.pdf --force-universal -o repaired.pdf --raw
```

## Usage

```
ebook2pdf [options] <input>

Positional:
  input            Ebook file or directory containing ebook files

Options:
  -o OUTPUT        Output PDF path or batch output directory
  -r, --recursive  Search directories recursively
  -v, --verbose    Show detailed progress
  --version        Show version

Input/output:
  --format INPUT_FORMAT               Input format override
  --output-format OUTPUT_FORMAT       Output format (default: pdf)
  --force-universal                   Force universal pipeline for EPUB too

Font sizing:
  --font-size SIZE                    Base font size in pt (default: 14)
  --body-font-size SIZE               Body font size in pt (default: 13)
  --mono-font-size SIZE               Mono/code font size in pt (default: 11)
  --no-auto-font-scale                Disable auto-scaling for small fonts
  --auto-font-scale-threshold N       Minimum pt gap to trigger scaling (default: 2)

Margins:
  --margin MARGIN                     Uniform margin in pts
  --margin-top SIZE                   Top margin (default: 36)
  --margin-bottom SIZE                Bottom margin (default: 36)
  --margin-left SIZE                  Left margin (default: 36)
  --margin-right SIZE                 Right margin (default: 36)

Behavior:
  --no-page-numbers                   Disable page number footer
  --rewrite-toc-page-numbers          Rewrite ToC entries to actual page numbers
  --no-toc                            Disable auto-generated Table of Contents
  --raw                               Preserve source settings; skip injected fixes
  --no-conversion-overrides           Disable all overrides, including patches
  --patch-file PATH                   Apply YAML patch file (may repeat)

Examples:
  ebook2pdf book.epub
  ebook2pdf book.epub -o output.pdf --verbose
  ebook2pdf book.epub --raw
  ebook2pdf book.epub --patch-file ./fixes/tables.yaml --patch-file ./fixes/code.yaml
  ebook2pdf /path/to/ebooks/ --recursive --output-dir /path/to/pdfs/
  ebook2pdf /path/to/ebooks/ --font-size 12 --body-font-size 11 --mono-font-size 10 --margin 24
  ebook2pdf book.epub --no-auto-font-scale --font-size 14 --body-font-size 13 --mono-font-size 11
  ebook2pdf book.epub --rewrite-toc-page-numbers -o book-indexed.pdf
  ebook2pdf book.mobi --format mobi
  ebook2pdf scanned.pdf --force-universal -o repaired.pdf --raw
```

## Patch Mode

Patch mode lets you manually override problematic tables, code blocks, or figures in specific ebooks.

Example YAML:

```yaml
files:
  - filename: "<ebook basename>"
    assets_dir: "./assets"
    blocks:
      - type: table | code-block | figure
        prologue: |
          <text immediately before the block>
        epilogue: |
          <text immediately after the block>
        replacement: |
          <Markdown replacement content>
```

Usage:

```bash
ebook2pdf book.epub \
  --patch-file ./fixes/tables.yaml \
  --patch-file ./fixes/code.yaml \
  -o book-patched.pdf
```

For the full schema and troubleshooting, see `./doc/USERGUIDE.md`.

## How It Works

1. **Extract / normalize input** — EPUB is unzipped or other formats are converted to EPUB via Calibre
2. **Apply patches** — optional user-assisted YAML replacements
3. **Recover content** — heuristics restore tables, code blocks, and captions
4. **Audit** — font sizes and margins are checked and auto-fixed when possible
5. **Inject CSS** — comprehensive fixes are appended to stylesheets
6. **Auto-scale fonts** — small source fonts are bumped based on configurable thresholds
7. **Convert to PDF** — `ebook-convert` produces the final PDF with settings overrides
8. **Post-process** — optional ToC page-number rewrite using actual rendered pages

## Sample Files

Place your own test ebooks in the `samples/` directory. This directory is ignored by git.

```bash
ebook2pdf ./samples --recursive --output-dir ./pdf-output
```

If you don't have sample files, you can generate a minimal test EPUB or point the tool at any Calibre-supported ebook on your system.

## Development

```bash
./dev.sh setup
source .venv/bin/activate
./dev.sh test
./dev.sh font-audit samples/Generative\\ AI\\ for\\ Communications\\ Systems....epub
```

## Release Workflow

This project uses annotated semver tags to trigger releases.

```bash
./dev.sh release-bump patch
./dev.sh release-tag
./dev.sh push
git push origin v1.0.1
```

GitHub Actions will build `.deb` and Python packages, then create a GitHub Release with assets.

For full pipeline and architecture details, see `./doc/DESIGN.md`.
