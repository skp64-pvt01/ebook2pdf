# ebook2pdf

EPUB to PDF converter with comprehensive formatting fixes.

Converts EPUB e-books to high-quality PDFs with automatic book-type detection,
CSS injection, and optimised PDF output.

## Features

- **Single file conversion** — `ebook2pdf book.epub`
- **Batch directory conversion** — `ebook2pdf /path/to/ebooks/`
- **Recursive search** — `ebook2pdf /path/to/ --recursive`
- **Automatic publisher detection** — Manning, Wiley, Rheinwerk, Calibre, Google Docs exports
- **5 key fixes applied automatically:**
  1. **ToC page numbers** — Auto-generated Table of Contents with page references via `--pdf-add-toc`
  2. **Centered figures** — Figures, images, and captions aligned to center
  3. **Math formula sizing** — Equation images constrained to match text size
  4. **Justified body text** — All paragraphs set to `text-align: justify`
  5. **Table formatting** — Borders, cell padding, header styling restored
- **Configurable** — font sizes, margins, page numbers, TOC generation

## Installation

### From .deb (Ubuntu 24.04+)

```bash
sudo apt install ./epub2pdf_1.0.0-1_all.deb
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

## Usage

```
ebook2pdf [options] <input>

Positional:
  input           EPUB file or directory containing EPUB files

Options:
  -o, --output          Output PDF path (single file) or output directory (batch)
  --font-size           Base font size in pt (default: 11)
  --body-font-size      Body text font size in pt (default: 11)
  --mono-font-size      Monospace/code font size in pt (default: 9)
  --margin              Uniform page margin in pts
  --margin-top          Top margin in pts (default: 36)
  --margin-bottom       Bottom margin in pts (default: 36)
  --margin-left         Left margin in pts (default: 36)
  --margin-right        Right margin in pts (default: 36)
  -r, --recursive       Search directories recursively
  --output-dir          Output directory for batch conversions
  --no-page-numbers     Disable page number footer
  --no-toc              Disable auto-generated Table of Contents
  -v, --verbose         Show detailed progress
  --version             Show version

Examples:
  ebook2pdf book.epub
  ebook2pdf book.epub -o output.pdf --verbose
  ebook2pdf ~/ebooks/ --recursive --output-dir ~/pdfs/
  ebook2pdf ~/ebooks/ --font-size 10 --margin 24
```

## How It Works

1. **Extract** — The EPUB is unzipped to a temporary directory
2. **Analyse** — Content files are scanned to determine the publisher/format
3. **Inject CSS** — Comprehensive CSS fixes are appended to every stylesheet
4. **Repack** — The modified EPUB is re-zipped with correct EPUB packaging
5. **Convert** — `ebook-convert` generates the PDF with optimised settings including heading-based TOC generation

## Building the .deb package

```bash
# Install build dependencies
sudo apt-get install -y devscripts debhelper dh-python python3-all python3-setuptools

# Build
cd ebook2pdf/
chmod +x debian/rules
dpkg-buildpackage -us -uc -b

# The .deb will be in the parent directory
```
