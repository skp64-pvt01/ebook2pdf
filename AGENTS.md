# Handoff & Session State — ebook2pdf

This document provides all the context, architecture, state, and workflows required for a downstream agent to pick up where we left off, or to restart/resume this session.

## Project Metadata
- **Project Name:** ebook2pdf
- **Project Location:** `/home/sysadmin/tmp/ebook2pdf/`
- **Language/Runtime:** Python 3.10+ (specifically python3.14 on host system)
- **Status:** Complete, packaged, and verified.
- **Debian Package:** `/home/sysadmin/tmp/epub2pdf_1.0.0-1_all.deb` (installed system-wide to `/usr/bin/ebook2pdf`)

## App Architecture
The app wraps the complex EPUB-to-PDF conversion pipeline into a structured Python CLI application.

```
ebook2pdf/
├── src/
│   └── ebook2pdf/
│       ├── __init__.py          # Version (1.0.0)
│       ├── __main__.py          # Python run support (python -m ebook2pdf)
│       ├── cli.py               # Argparse CLI (options: base-font-size, margins, recursive, etc.)
│       ├── converter.py         # Pipeline coordinator (extract, heuristics, inject, repack, calibre call)
│       ├── detector.py          # Heuristics for publisher-specific class & ID mapping (Manning, Wiley, etc.)
│       ├── table_heuristics.py  # 4 strategies for recovering display:table/pipe/list structures to actual HTML tables
│       ├── code_heuristics.py   # 7 strategies to detect & wrap unformatted pre/code block and inline elements
│       ├── audit.py             # Pre-flight checks for font sizes, margin overflows + auto-fixes
│       └── data/
│           └── comprehensive_fixes.css   # Single source of truth CSS injected into all files
├── debian/                      # Debian packaging configuration
│   ├── control, changelog, rules, copyright, postinst, prerm
├── setup.py                     # Setuptools configuration
├── pyproject.toml               # Python build config
├── dev.sh                       # Convenience lifecycle helper (setup, build, deb, test, clean, git support)
└── README.md                    # User guide & CLI documentation
```

## Workflows and Lifecycle Helper (`dev.sh`)
At `/home/sysadmin/tmp/ebook2pdf/dev.sh`, we've added a highly complete development script:
- `./dev.sh setup` — Sets up venv and installs package in editable mode.
- `./dev.sh build` — Builds Python packages (`wheel` and `sdist`).
- `./dev.sh deb` — Compiles/rebuilds the `.deb` file using `dpkg-buildpackage`.
- `./dev.sh install` — Installs or upgrades the `.deb` package system-wide.
- `./dev.sh test` — Runs a conversion on a test book.
- `./dev.sh clean` — Safely deletes all temporary build and packaging files.
- `./dev.sh git-init` — Inits git and sets up the standard `.gitignore` list.
- `./dev.sh git-remote <github|gitlab> <user> [repo]` — Easily links GitHub/GitLab.
- `./dev.sh commit "message"` — Stages and commits.
- `./dev.sh push` — Pushes to origin.
- `./dev.sh full` — Cleans, builds, packages, installs, and runs test suite in one shot.

## Core Feature Specs (Newly Added)
1. **Font Sizing Default Increase:** Base font size default has been raised by `+1pt` (default is now `12pt` base/body, `10pt` mono/code).
2. **List Padding Halving:** Level 2 TOC/List padding reduced from `1.5em` to `0.75em`, Level 3 reduced from `3.0em` to `1.5em`, and `.contentsH2` reduced from `1.5em` to `0.75em` inside the CSS files to avoid excessive indentation.
3. **Code Block Detection & Backgrounds:** Scans files at Step 1b for pre-existing or implicit block/inline code elements (e.g., monospace inline styling, shell prompts `$`, indentation blocks, code-related class names). Wraps block code inside `<div class="epub2pdf-code-block">` with background color `#f4f4f4`, light grey border, 3px border radius, and `page-break-inside: avoid`. Styles inline code treats accordingly.

## Session State & Verification
- **Skill Created:** `epub-to-pdf-pipeline` in Hermes, featuring matching comprehensive CSS references, references/epub2pdf-application.md, table-recovery, and pdf-audit sheets.
- **Shadow Executable Cleaned:** A stale Bash script at `/opt/bin/ebook2pdf` was shadowing our Python CLI. It was safely removed; standard execution now resolves directly to `/usr/bin/ebook2pdf`.
- **Tests Passed:** Verified successfully against multiple books in `/home/sysadmin/tmp/ebook`.
