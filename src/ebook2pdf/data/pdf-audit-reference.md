# PDF Quality Audit

The `ebook2pdf` application includes a built-in quality audit module (`audit.py`) that runs at **step 1c** of the pipeline — after table recovery, before CSS injection.

## What It Checks

### 1. Font Size Audit
Scans all CSS files and inline styles for font-size declarations, then analyses the distribution:

| Finding | Threshold | Severity | Auto-fix |
|---------|-----------|----------|----------|
| Body text too small | < 9pt | ⚠️ warn | No (user must increase base-font-size) |
| Body text too large | > 14pt | ℹ️ info | No |
| Code/mono too small | < 7pt | ⚠️ warn | No |
| Heading too large | > 24pt | ⚠️ warn | No |
| Footnote/superscript | < 7pt | ⚠️ warn | No |

Reports specific CSS rule locations (file + context) for manual review.

### 2. Page Boundary / Margin Violation Audit
Scans all HTML/XHTML files for elements that exceed the printable page area (default: 360pt = 5" at 36pt margins on 6×9" page):

| Violation Type | Detection Signal | Auto-fix |
|---------------|------------------|----------|
| **Image overflow** | `width` attribute or inline style > printable width | Adds `max-width: 100%; height: auto` to the `<img>` tag |
| **Table overflow** | 5+ columns in the first row | Adds `table-layout: fixed; max-width: 100%; font-size: 0.8em` |
| **Code/pre overflow** | Longest line > 120 chars | Adds `white-space: pre-wrap; overflow-wrap: break-word` |
| **Fixed-width element** | `<div>/<p>/<span>` with width > printable area | Adds `max-width: 100%; overflow: hidden` |
| **SVG overflow** | `viewBox` width > printable area | Adds `max-width: 100%; height: auto` |

All auto-fixes modify the HTML inline and are complemented by `MARGIN_SAFETY_CSS` injected into every stylesheet.

### 3. CSS Margin Safety (injected into all stylesheets)
```css
table, img, pre, svg { max-width: 100% !important; height: auto !important; }
table { table-layout: auto !important; }
td, th { word-wrap: break-word !important; overflow-wrap: break-word !important; }
pre, code { white-space: pre-wrap !important; overflow-wrap: break-word !important; }
div, section, article, aside, main, header, footer, nav { max-width: 100% !important; }
```

## Audit Output (verbose mode)

```
[1c/4] Running quality audit...
    Font audit: 3 findings
      [WARN] Body text 8.4pt is too small for print (min 9pt recommended)
      [WARN] Heading 25.2pt is very large for print (max 22pt recommended)
      [WARN] Footnote/superscript 7.0pt may be illegible in print
    Margin audit: 124 violations
      [WARN] chapter-10.html: Image width 671pt exceeds printable width 360pt
      [WARN] chapter-10.html: Table with 5 columns may exceed page width
      [INFO] appendix-b.html: Code line with 161 chars may overflow margins
      ... and 121 more
    Auto-fixes applied: 124
      Font audit: 1 warnings, 2 info | Margin audit: 124 violations detected | Auto-fixes: 124 applied
      Auto-fixed 124 margin violations
```

## Real-World Results (tested on 5 books)

| Book | Font Warnings | Margin Violations | Auto-Fixes |
|------|:---:|:---:|:---:|
| AI Agents (Manning) | 1 | 124 | 124 |
| Gen AI (Wiley) | 1 | 1 | 1 |
| Hacking Hardware (Rheinwerk) | 3 | 135 | 135 |
| Mojo (Google Docs) | 3 | 1 | 1 |
| OO (Calibre) | 0 | 0 | 0 |
| **Total** | **8** | **261** | **261** |
