# ebook2pdf

EPUB to PDF converter with comprehensive formatting fixes.

Converts ebooks to high-quality PDFs with automatic content recovery, CSS injection,
font-size enforcement, user-assisted patch injection, and a universal Calibre-backed
input pipeline. Includes a typed patch workflow so you can override content, add code
blocks, substitute figures, or inject tables without forking the source.

Features
- Universal input: accepts EPUB, PDF, MOBI, AZW3, FB2, DOCX, TXT, and other
  Calibre-supported formats
- Recoverable pipeline: converts any supported format to an intermediate EPUB,
  applies fixes, then produces the final PDF
- Typographic controls: header 14pt, body 13pt, code 11pt; auto-scale with
  `--auto-font-scale-threshold`
- Patch mode: YAML-driven content patches via `--patch-file`
- Python API + CLI

Requirements
- Python 3.10+
- Calibre (`ebook-convert`)
- PyMuPDF optional for font auditing

Install

```bash
# From PyPI
pip install ebook2pdf

# From .deb release asset
wget https://github.com/skp64-pvt01/ebook2pdf/releases/download/v1.0.0/ebook2pdf_1.0.0-1_all.deb
sudo dpkg -i ebook2pdf_1.0.0-1_all.deb
```

Quick Start

```bash
# Convert an EPUB
ebook2pdf book.epub -o book.pdf

# Convert all files in samples/
ebook2pdf ./samples --recursive --output-dir ./out

# Use patch mode
ebook2pdf book.epub -o book.pdf --patch-file patch.yaml
```

Patch Mode

```yaml
entries:
  - input: book.epub
    blocks:
      - mode: insert_after
        anchor: "Introduction"
        html: "<div>Injected content</div>"
```

Use `--patch-file patch.yaml` to apply patches during conversion.

Configuration

```bash
ebook2pdf --help
```

Release Workflow

This project uses annotated semver tags to trigger releases.

```bash
./dev.sh release-bump patch
./dev.sh release-tag
git push origin v1.0.1
```

GitHub Actions will build the Debian package, then create a GitHub Release with the `.deb` asset.

For full pipeline and architecture details, see `./doc/DESIGN.md`.

Sample Files

Place your own test ebooks in the `samples/` directory. This directory is ignored by git.

```bash
ebook2pdf ./samples --recursive --output-dir ./pdf-output
```

If you don't have sample files, you can generate a minimal test EPUB or point the tool at any Calibre-supported ebook on your system.

Development

```bash
git clone https://github.com/skp64-pvt01/ebook2pdf.git
cd ebook2pdf
python -m venv .venv
source .venv/bin/activate
pip install -e ".[font-audit]"
```

License

MIT
