# Handoff & Session State — ebook2pdf

This document provides the current project context, architecture, CLI surface,
and known limitations for a downstream agent or future session.

## Project Metadata
- **Project Name:** ebook2pdf
- **Project Location:** `/home/sysadmin/tmp/ebook2pdf/`
- **Language/Runtime:** Python 3.10+ (host currently uses python3.14)
- **Status:** Functional, packaged as `.deb`, installed system-wide
- **Debian Package:** `/home/sysadmin/tmp/ebook2pdf_1.0.0-1_all.deb`
- **Installed Binary:** `/usr/bin/ebook2pdf`
- **Upstream Remote:** `https://github.com/skp64-pvt01/ebook2pdf.git`

## Current Architecture

```
ebook2pdf/
├── src/
│   └── ebook2pdf/
│       ├── __init__.py          # Version (1.0.0)
│       ├── __main__.py          # python -m ebook2pdf support
│       ├── cli.py               # Argparse CLI with all flags
│       ├── converter.py         # Single-format EPUB pipeline + patch hooks
│       ├── universal_converter.py  # Any Calibre input -> EPUB -> PDF pipeline
│       ├── patcher.py           # YAML-driven user-assisted block replacements
│       ├── detector.py          # Publisher-specific class / ID mapping
│       ├── table_heuristics.py  # Table recovery strategies
│       ├── code_heuristics.py   # Code block detection / wrapping
│       ├── audit.py             # Font/margin audit + auto-fixes + source profiling
│       ├── pdf_postprocess.py   # PDF ToC page-number rewriting via pypdf
│       ├── font_audit_verify.py # Public post-conversion font verification API
│       ├── font_audit_pymupdf.py# PyMuPDF-backed span-level font audit
│       ├── figure_heuristics.py # Caption normalization
│       ├── toc_heuristics.py    # ToC label normalization
│       └── data/
│           ├── comprehensive_fixes.css     # Injected CSS bundle
│           └── pdf-audit-reference.md      # Audit reference docs
├── debian/                      # Debian packaging artifacts
├── setup.py                     # Setuptools package metadata
├── pyproject.toml               # Build configuration hints
├── dev.sh                       # Lifecycle helper script
├── README.md                    # User guide / CLI docs
└── plan-patch-mode.md           # Patch-mode implementation plan
```

## Pipeline Modes

### Direct EPUB mode (`converter.py`)
`epub -> extract -> heuristics -> audit -> CSS -> auto-scale -> repack -> pdf`

### Universal mode (`universal_converter.py`)
`any_format -> ebook-convert -> intermediate EPUB -> extract -> user patches ->
heuristics -> audit -> CSS -> auto-scale -> repack -> pdf`

## CLI Surface

Key flags added since initial scaffolding:
- `--format INPUT_FORMAT` / `--output-format OUTPUT_FORMAT`
- `--force-universal`
- `--raw`
- `--no-conversion-overrides`
- `--patch-file PATH` (repeatable)
- `--no-auto-font-scale`
- `--auto-font-scale-threshold N`
- `--rewrite-toc-page-numbers`
- `--font-size` / `--body-font-size` / `--mono-font-size`

Defaults: base 14pt, body 13pt, mono 11pt.
Auto-scale triggers when source font is at least 2pt below target unless disabled.

## Patch Mode (User-Assisted Overrides)

Optional YAML-driven assistance layer for tables, code blocks, and figures.

### YAML Schema
- Top-level `files:` list
- Per-file:
  - `filename` - source ebook basename
  - `assets_dir` - optional image folder relative to YAML or absolute
  - `blocks:` list of override regions
    - `type`: `table` | `code-block` | `figure`
    - `prologue`: text before bad block
    - `epilogue`: text after bad block
    - `replacement`: Markdown content

### Image Asset Convention
- Place images next to the patch YAML under `./assets/` by default
- In Markdown `replacement`, reference images by filename or path
- Pipeline resolves them against `assets_dir`
- Copies into EPUB under `OEBPS/Images/__patches__/`
- Rewrites rendered XHTML to `src="__patches__/<filename>"`

### CLI Usage
- `--patch-file path/to/one.yaml` may be specified multiple times
- Patch files are merged; duplicate entries are deduplicated
- Multiple `blocks` are supported per-file
- Multiple `files` are supported per YAML
- Ignored when `--raw` or `--no-conversion-overrides` is set

## Key Implementation Notes
- Runtime CSS class names like `epub2pdf-code-block` were intentionally kept;
  they are output/behavior markers, not project identity.
- `rapidfuzz` is used for fuzzy region matching; `thefuzz` is not required.
- `markdown` with `fenced_code`, `tables`, and `codehilite` renders replacements.
- EPUB injection uses atomic writes via tmp + `os.replace`.
- Unknown/missing prompt-response from earlier remote operations was resolved by
  explicit `gh auth switch` and `gh repo rename` with `-R owner/repo -y`.

## Known Limitations / Open Items
- `dev.sh test` still exits non-zero under some conditions; pre-existing failure
  not directly related to the new patch pipeline.
- Fuzzy block matching can fail if Calibre rewrites surrounding context between
  editions. Increasing `threshold` in `patcher.py` or tightening `prologue` /
  `epilogue` text can help.
- Multi-file split blocks are not yet handled; matching stays within single
  XHTML files.
- `--no-conversion-overrides` disables patches because it is meant as an escape
  hatch; document this clearly in user-facing docs.
- `plan-patch-mode.md` contains the longer-term roadmap for patcher tests,
  dry-run reporting, and troubleshooting docs.

## Verified State
- Project renamed from `epub2pdf` to `ebook2pdf` in source, package metadata,
  `.deb` artifacts, `dev.sh`, git history, and GitHub remote.
- Upstream repo renamed to `skp64-pvt01/ebook2pdf`.
- Sample batch conversion of 10 EPUBs in `/home/sysadmin/tmp/ebook2pdf/samples`
  completed successfully into `samples/out-app/`.
- Patch layer scaffold is present in `patcher.py`; sample YAML exists at
  `/home/sysadmin/tmp/ebook2pdf/samples/sample-patch.yaml`.
