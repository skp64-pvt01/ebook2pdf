# ebook2pdf Design Document

This document describes the architecture, data flow, module boundaries,
pipeline modes, and extension points in `ebook2pdf`. It is intended for
maintainers and advanced users who want to understand or extend the tool.

## 1. High-Level Architecture

```mermaid
%% ebook2pdf High-Level Architecture
graph TB
    User --> CLI[CLI / argparse]
    CLI --> Input{Input exists?}
    Input -->|No| Error[Exit 2: missing input]
    Input -->|Yes| Deps{Check deps}
    Deps -->|Missing| DepError[Exit 1: missing calibre]
    Deps -->|OK| Mode{EPUB or other?}

    Mode -->|EPUB| Direct[Direct EPUB pipeline]
    Mode -->|Other| Universal[Universal converter pipeline]

    Direct --> EpubOut[PDF output]
    Universal --> EpubOut

    subgraph "Extras"
        Patch[--patch-file YAML]
        Raw[--raw / --no-conversion-overrides]
        FontScale[Auto font scale]
        TocRewrite[Rewrite ToC page numbers]
    end

    Patch -.->|injected step| Direct
    Patch -.->|injected step| Universal
    Raw -.->|disables| Direct
    Raw -.->|disables| Universal
    FontScale -.->|applied before PDF| Direct
    FontScale -.->|applied before PDF| Universal
    TocRewrite -.->|post-processes| EpubOut
```

## 2. Module Dependency Map

```mermaid
%% Module dependencies
flowchart LR
    cli --> converter
    cli --> universal_converter
    cli --> patcher

    universal_converter --> converter
    universal_converter --> patcher
    universal_converter --> detector
    universal_converter --> audit
    universal_converter --> table_heuristics
    universal_converter --> code_heuristics
    universal_converter --> toc_heuristics
    universal_converter --> figure_heuristics
    universal_converter --> pdf_postprocess

    converter --> detector
    converter --> audit
    converter --> table_heuristics
    converter --> code_heuristics
    converter --> toc_heuristics
    converter --> figure_heuristics
    converter --> pdf_postprocess

    patcher --> yaml
    patcher --> rapidfuzz
    patcher --> markdown
```

## 3. Pipeline Modes

### 3.1 Direct EPUB Pipeline

```mermaid
%% Direct EPUB pipeline
flowchart LR
    input_epub[Input EPUB] --> extract[Extract ZIP]
    extract --> table_recovery[Table recovery heuristics]
    table_recovery --> code_recovery[Code block recovery]
    code_recovery --> audit[Font/margin audit]
    audit --> detector[Publisher detection]
    detector --> toc_norm[ToC normalization]
    toc_norm --> caption_norm[Caption normalization]
    caption_norm --> css[Inject comprehensive CSS]
    css --> raw_check{Raw / --no-conversion-overrides?}
    raw_check -->|Yes| repack[Repack EPUB]
    raw_check -->|No| patch_check{Patch files?}
    patch_check -->|Yes| patch[Apply YAML patches]
    patch_check -->|No| repack
    patch --> repack
    repack --> auto_scale[Auto font scale]
    auto_scale --> ebook_convert[ebook-convert → PDF]
    ebook_convert --> toc_rewrite{Rewrite ToC?}
    toc_rewrite -->|Yes| pypdf[Rewrite page numbers]
    toc_rewrite -->|No| done[Done]
    pypdf --> done
```

### 3.2 Universal Converter Pipeline

```mermaid
%% Universal converter pipeline
flowchart LR
    input_any[Any Calibre-supported input] --> format_check{Already EPUB?}
    format_check -->|Yes| extract[Extract ZIP]
    format_check -->|No| pre_convert[ebook-convert → Intermediate EPUB]
    pre_convert --> extract
    extract --> raw_check{Raw / --no-conversion-overrides?}
    raw_check -->|Yes| repack[Repack EPUB]
    raw_check -->|No| patch_check{Patch files?}
    patch_check -->|Yes| patch[Apply YAML patches]
    patch_check -->|No| fixes[Run heuristics + audit + CSS]
    patch --> fixes
    fixes --> repack
    repack --> auto_scale[Auto font scale]
    auto_scale --> ebook_convert[ebook-convert → PDF]
    ebook_convert --> toc_rewrite{Rewrite ToC?}
    toc_rewrite -->|Yes| pypdf[Rewrite page numbers]
    toc_rewrite -->|No| done[Done]
    pypdf --> done
```

## 4. Patch Mode Data Flow

```mermaid
flowchart TB
    yaml_file[patch.yaml] --> loader[_load_yaml]
    loader --> validator{Valid?}
    validator -->|No| patch_error[PatchError]
    validator -->|Yes| merger[merge_patch_data]
    merger --> matcher[_iter_xhtml_files]

    matcher --> context_match[_match_by_context]
    context_match --> threshold_check{Score ≥ threshold?}
    threshold_check -->|No| skip[skipped]
    threshold_check -->|Yes| extractor[Extract raw XHTML]

    extractor --> renderer[_render_replacement]
    renderer --> md_to_html[Markdown → HTML]
    md_to_html --> img_rewrite[Rewrite image refs to __patches__/]
    img_rewrite --> injector[_inject_into_raw]
    injector --> atomic_write[Atomic write tmp + os.replace]
    atomic_write --> applied[applied]

    assets_dir[assets/] --> copier[_copy_patch_assets]
    copier --> epub_images[OEBPS/Images/__patches__/]
```

## 5. Key Class/Module Responsibilities

### 5.1 `cli.py`
- Defines `CLI_FONT_DEFAULTS` as source-of-truth defaults
- Builds argparse parser with all flags
- Maps user inputs to converter/patcher kwargs
- Early dependency check via `check_dependencies()`
- Dispatches single-file vs batch mode

### 5.2 `converter.py`
- `convert_single()`: Direct EPUB → PDF pipeline
- `_extract_epub()`: ZIP extraction into work_dir
- `_inject_css()`: Appends comprehensive CSS bundle to all `.css` files
- `_inject_css_reference()`: Adds manifest/spine references when no CSS exists
- `_repack_epub()`: Rebuilds EPUB with mimetype-first zip ordering
- `_ebook_convert()`: Invokes Calibre `ebook-convert` with tuned options
- Auto-font-scaling logic at end of pipeline

### 5.3 `universal_converter.py`
- `universal_convert()`: Any format → EPUB → PDF
- `universal_convert_batch()`: Directory conversion using universal path
- `normalize_to_epub()`: Pre-converts non-EPUB inputs via Calibre
- `SUPPORTED_INPUT_FORMATS`: Calibre-readable formats
- Orchestrates recovery, audit, CSS, patches, PDF conversion

### 5.4 `patcher.py`
- `_load_yaml()`: Load and shallow-validate YAML structure
- `_resolve_assets_dir()`: Determine patch assets directory
- `_render_replacement()`: Markdown → XHTML via `markdown` lib
- `_iter_xhtml_htmlfiles()`: Flatten EPUB XHTML files for matching
- `_match_by_context()`: Fuzzy context matching via `rapidfuzz`
- `_inject_into_raw()`: Regex-based block replacement in raw XHTML
- `_copy_patch_assets()`: Copy images into EPUB `__patches__` namespace
- `apply_patch()`: Public API; merges multiple YAMLs, applies patches

### 5.5 `audit.py`
- Pre-flight font and margin checks
- `source_font_profile`: Extracts representative body/code/heading sizes
- Auto-fixes for margin violations

### 5.6 `pdf_postprocess.py`
- Post-conversion ToC page-number rewriting via `pypdf`

## 6. File Layout

```
/home/sysadmin/tmp/ebook2pdf/
├── src/ebook2pdf/
│   ├── __init__.py             # Version
│   ├── __main__.py             # python -m ebook2pdf
│   ├── cli.py                  # CLI parser and dispatcher
│   ├── converter.py            # EPUB -> PDF pipeline
│   ├── universal_converter.py  # Any format -> EPUB -> PDF pipeline
│   ├── patcher.py              # YAML-driven user patches
│   ├── detector.py             # Publisher detection heuristics
│   ├── table_heuristics.py     # Table recovery
│   ├── code_heuristics.py      # Code block detection
│   ├── audit.py                # Font/margin audit + source profiling
│   ├── pdf_postprocess.py      # PDF ToC page-number rewrite
│   ├── font_audit_verify.py    # Post-conversion font verification API
│   ├── font_audit_pymupdf.py   # PyMuPDF span-level font audit
│   ├── figure_heuristics.py    # Caption normalization
│   ├── toc_heuristics.py       # ToC label normalization
│   └── data/
│       ├── comprehensive_fixes.css     # Injected CSS bundle
│       └── pdf-audit-reference.md      # Audit reference docs
├── debian/                     # .deb packaging
├── setup.py                    # Python package config
├── dev.sh                      # Lifecycle helper script
├── README.md                   # User-facing documentation
├── AGENTS.md                   # Session handoff / state
├── plan-patch-mode.md          # Patch-mode implementation plan
├── samples/                    # Sample EPUBs + output PDFs
│   ├── sample-patch.yaml       # Example patch YAML
│   ├── patch-assets/           # Example image assets
│   └── out-app/                # Generated PDFs
└── doc/
    ├── DESIGN.md               # This file
    └── USERGUIDE.md            # End-user guide
```

## 7. Configuration Model

```mermaid
flowchart LR
    User[User input] --> CLI[CLI flags]
    CLI --> FontDefaults[CLI_FONT_DEFAULTS]
    FontDefaults --> KW[Common kwargs dict]
    KW --> Converter[converter / universal_converter]
    Converter --> Effective[Effective values]
    Effective --> Scale{Auto-scale enabled?}
    Scale -->|Yes| Profile[Source font profile from audit.py]
    Profile --> Threshold{Gap ≥ threshold?}
    Threshold -->|Yes| Bump[Bump target = source + threshold]
    Threshold -->|No| Keep[Keep CLI target]
    Scale -->|No| Keep
    Bump --> Calibre[ebook-convert args]
    Keep --> Calibre
```

## 8. Extension Points

- New input formats: Add to `SUPPORTED_INPUT_FORMATS` in `universal_converter.py`.
- New patch block types: Extend `ALLOWED_BLOCK_TYPES` in `patcher.py` and add renderer branch.
- New heuristic modules: Wire into `universal_converter.py` and `converter.py` pipeline steps.
- New post-processing: Add a step after `_ebook_convert()` in both converters.
- New CLI flags: Add to `cli.py`, include in `common_kwargs`, and forward in converter signatures.

## 9. Testing Strategy

- Unit tests for `patcher.py`: YAML loading, validation, context matching, asset copying.
- Unit tests for `audit.py`: Source font profile extraction, threshold logic.
- Integration tests via `dev.sh test` and `dev.sh font-audit` on sample EPUBs.
- Regression tests: Verify `check_matching_defaults()` warns on drift.
- Snapshot tests: Golden `.deb` artifact names, remotes, binary paths.
