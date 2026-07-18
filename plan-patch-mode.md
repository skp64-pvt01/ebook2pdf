# Plan: User-Assisted Patch Mode for Problematic Tables, Code Blocks, and Figures

## Goal
Add an optional YAML-driven assistance layer so users can explicitly override
regions in an ebook that `ebook2pdf` heuristics don’t cover well:
tables, code blocks, figures. The pipeline should:
1. Accept an auxiliary YAML input describing override regions.
2. Locate matching regions in the intermediate EPUB with fuzzy search.
3. Replace those regions with richer Markdown content rendered to XHTML.
4. Continue through the existing conversion pipeline.

## Inputs
- Source ebook format: any Calibre-readable format.
- Optional override YAML file with one or more blocks:
  - `filename`: original source filename base.
  - `type`: `table` | `code-block` | `figure`.
  - `prologue`: text immediately before the bad block.
  - `epilogue`: text immediately after the bad block.
  - `replacement`: Markdown content to replace the block with.

## Pipeline Extension
```
<input ebook> -> ebook-convert -> <intermediate EPUB> -> apply YAML patch ->
<fixed EPUB> -> existing fixes -> ebook-convert -> <output PDF>
```

## Proposed CLI Flags
- `--patch-yaml PATH` / `--patch-file PATH`: optional YAML override file.
- `--patch-mode`: `prefer` | `replace` to choose how conflicts are handled.

## Implementation Outline

### 1. YAML loader/validator
- Parse the YAML structure.
- Validate allowed fields and types.
- Produce structured patch descriptors.

### 2. EPUB region matcher
- Iterate extracted intermediate EPUB XHTML files.
- Flatten each file to text while preserving original markup.
- For each patch descriptor:
  - Build context windows from `prologue`, target candidate, `epilogue`.
  - Use `rapidfuzz` to score candidate matches across the EPUB text.
  - Select best match above a configurable confidence threshold.
  - Record source file path and byte offsets or block boundaries.

### 3. Replacement renderer
- Convert Markdown replacement into EPUB-safe XHTML.
- Use `markdown` / `mistune` with extensions:
  - `codehilite` / `fenced_code` for syntax-highlighted code blocks.
  - `tables` for Markdown tables -> HTML tables.
  - For figures, allow embedded image references resolved against the EPUB
    `OEBPS/Images/` folder, or ask user to place local images in a known
    patch assets directory.
- Sanitize resulting HTML to prevent malformed EPUB.

### 4. EPUB injector
- Replace matched region boundaries in the source XHTML.
- Update manifest/spine only if files added/removed (asset images).
- Repackage the EPUB.

### 5. Verification
- Optional dry-run mode producing patch stats and match confidence report.
- Add unit tests for:
  - YAML parsing.
  - fuzzy region matching on known bad EPUBs.
  - round-trip inject and tabular preservation.

## Feasibility
- Feasible.
- `rapidfuzz` is already installed.
- `pygments`, `markdown`, `mistune` are available.
- The main complexity is robust region localization in multi-file EPUBs.

## Difficulties / Risks
- EPUB extraction may minify/rebuild content between editions,
  changing adjacency context used for fuzzy matching.
- Multi-file splits: a table may start in `chapter1.html` and end in
  `chapter1-cont.html`. Matching across file boundaries increases complexity.
- Calibre conversion may later alter or ignore injected content if
  CSS/stylesheet precedence conflicts.
- Image assets in YAML need a user-friendly placement convention.
- A mismatch can corrupt the EPUB; must implement safe atomic writes
  and backup originals.

## Proposed Files
- `src/ebook2pdf/patcher.py`
- `tests/test_patcher.py`
- Reference docs:
  - `references/patch-yaml-format.md`
  - `references/patch-troubleshooting.md`

## Implementation Order
1. `patcher.py` scaffolding: YAML loader + EPUB inspection utilities.
2. Region matcher using `rapidfuzz` with configurable threshold.
3. Replacement renderer supporting code-block and table Markdown.
4. EPUB injector with backup + atomic rewrite.
5. CLI integration and tests.
6. Documentation and troubleshooting notes.
