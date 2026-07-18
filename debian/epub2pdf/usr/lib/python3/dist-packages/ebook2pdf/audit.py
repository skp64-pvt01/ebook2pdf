"""
PDF Quality Audit module.

Audits EPUB content before conversion for:
  1. Font size — warns about text too small (<9pt body, <7pt code) or too large (>14pt body)
  2. Page boundaries — detects tables, images, and elements that exceed page margins
  3. Auto-fixes margin violations by injecting CSS constraints
"""

import os
import re
from collections import defaultdict
from html.parser import HTMLParser

# Page layout defaults (for a standard 6x9 trade paperback at 36pt margins)
PAGE_WIDTH_PT = 432   # 6 inches
PAGE_HEIGHT_PT = 648  # 9 inches
MARGIN_PT = 36
PRINTABLE_WIDTH_PT = PAGE_WIDTH_PT - 2 * MARGIN_PT  # 360pt = 5 inches

# Font size thresholds (in points)
FONT_WARNINGS = {
    "body_too_small": {"threshold": 9, "severity": "warn",
                        "msg": "Body text {size}pt is too small for print (min 9pt recommended)"},
    "body_too_large": {"threshold": 14, "severity": "info",
                        "msg": "Body text {size}pt is larger than typical print (max 14pt)"},
    "code_too_small": {"threshold": 7, "severity": "warn",
                        "msg": "Code/monospace text {size}pt is very small (min 8pt recommended)"},
    "code_too_large": {"threshold": 11, "severity": "info",
                        "msg": "Code/monospace text {size}pt is large for print"},
    "heading_too_large": {"threshold": 24, "severity": "warn",
                           "msg": "Heading {size}pt is very large for print (max 22pt recommended)"},
    "footnote_too_small": {"threshold": 7, "severity": "warn",
                            "msg": "Footnote/superscript {size}pt may be illegible in print"},
}


def audit_epub(extract_dir: str, verbose: bool = False) -> dict:
    """
    Run all audits on an extracted EPUB directory.
    
    Returns a dict with:
      - font_sizes: list of font size findings
      - margin_violations: list of margin violation findings
      - fixes_applied: count of auto-fixes
      - summary: human-readable summary string
    """
    result = {
        "font_sizes": [],
        "margin_violations": [],
        "fixes_applied": 0,
        "summary": "",
        "source_font_profile": {
            "body": None,
            "code": None,
            "heading": None,
        },
    }

    # Gather all HTML and CSS files
    html_files = []
    css_files = []
    for root, _dirs, files in os.walk(extract_dir):
        for f in files:
            path = os.path.join(root, f)
            if f.endswith((".html", ".xhtml", ".htm")):
                html_files.append(path)
            elif f.endswith(".css"):
                css_files.append(path)

    # --- Font Size Audit ---
    _audit_font_sizes(css_files, html_files, result, verbose)

    # --- Page Boundary / Margin Violation Audit ---
    fixes = _audit_margin_violations(html_files, extract_dir, result, verbose)
    result["fixes_applied"] = fixes

    # Build summary
    parts = []
    if result["font_sizes"]:
        fw = sum(1 for f in result["font_sizes"] if f["severity"] == "warn")
        fi = sum(1 for f in result["font_sizes"] if f["severity"] == "info")
        parts.append(f"Font audit: {fw} warnings, {fi} info")
    if result["margin_violations"]:
        mw = sum(1 for m in result["margin_violations"] if m["severity"] == "warn")
        parts.append(f"Margin audit: {mw} violations detected")
    if result["fixes_applied"]:
        parts.append(f"Auto-fixes: {result['fixes_applied']} applied")
    if not parts:
        parts.append("No issues detected")
    result["summary"] = " | ".join(parts)

    if result.get("source_font_profile"):
        profile = result["source_font_profile"]
        profile_parts = []
        for k, v in profile.items():
            if v is None:
                profile_parts.append(f"{k}=n/a")
            else:
                profile_parts.append(f"{k}={v:.2f}pt")
        result["summary"] += " | Source profile: " + ", ".join(profile_parts)

    return result


# =========================================================================
# Font Size Audit
# =========================================================================

FONT_SIZE_RE = re.compile(
    r'font-size\s*:\s*([\d.]+)\s*(pt|px|em|%)',
    re.IGNORECASE
)
FONT_FAMILY_RE = re.compile(
    r'font-family\s*:\s*([^;}]+)',
    re.IGNORECASE
)
PX_TO_PT = 0.75  # 1px ≈ 0.75pt


def _audit_font_sizes(css_files: list, html_files: list, result: dict,
                      verbose: bool) -> None:
    """Scan CSS and inline styles for font size issues."""
    seen_sizes = defaultdict(list)  # size -> [(source, context)]

    # --- Scan CSS files ---
    for css_path in css_files:
        try:
            with open(css_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            continue

        fname = os.path.basename(css_path)
        for match in FONT_SIZE_RE.finditer(content):
            val = float(match.group(1))
            unit = match.group(2).lower()
            size_pt = _to_pt(val, unit)
            if size_pt:
                # Get context (the CSS rule context)
                start = max(0, match.start() - 60)
                end = min(len(content), match.end() + 60)
                ctx = content[start:end].strip()
                seen_sizes[size_pt].append((fname, ctx))

        # Also check font-family for code/mono clues
        for match in FONT_FAMILY_RE.finditer(content):
            family = match.group(1).lower()
            if any(mono in family for mono in ["mono", "courier", "consolas",
                                                 "jetbrains", "fira code",
                                                 "source code", "menlo"]):
                pass  # We note this for context but don't flag without size

    # --- Scan inline styles in HTML ---
    for html_path in html_files:
        try:
            with open(html_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            continue
        fname = os.path.basename(html_path)
        # Inline style attributes: style="font-size: 10pt"
        for match in FONT_SIZE_RE.finditer(content):
            val = float(match.group(1))
            unit = match.group(2).lower()
            size_pt = _to_pt(val, unit)
            if size_pt:
                start = max(0, match.start() - 40)
                end = min(len(content), match.end() + 40)
                ctx = f"[inline] {content[start:end].strip()}"
                seen_sizes[size_pt].append((fname, ctx))

    if not seen_sizes:
        return

    # Analyse the distribution
    all_sizes = sorted(seen_sizes.keys())

    # Body text: most common size in the 8-14pt range
    body_candidates = [s for s in all_sizes if 8 <= s <= 14]
    body_size = max(set(body_candidates), key=body_candidates.count) if body_candidates else None

    # Code blocks: look for distinct smaller sizes
    code_candidates = [s for s in all_sizes if 6 <= s <= 10 and s != body_size]
    code_size = max(set(code_candidates), key=code_candidates.count) if code_candidates else None

    # Headings: sizes > 14pt
    heading_sizes = [s for s in all_sizes if s > 14]

    # Report findings
    entries = []

    # Body text check
    if body_size is not None:
        if body_size < FONT_WARNINGS["body_too_small"]["threshold"]:
            entries.append({
                "type": "body_too_small",
                "size": body_size,
                "severity": "warn",
                "message": FONT_WARNINGS["body_too_small"]["msg"].format(size=body_size),
                "sources": seen_sizes[body_size][:3],
            })
        elif body_size > FONT_WARNINGS["body_too_large"]["threshold"]:
            entries.append({
                "type": "body_too_large",
                "size": body_size,
                "severity": "info",
                "message": FONT_WARNINGS["body_too_large"]["msg"].format(size=body_size),
                "sources": seen_sizes[body_size][:3],
            })

    # Code text check
    if code_size is not None:
        if code_size < FONT_WARNINGS["code_too_small"]["threshold"]:
            entries.append({
                "type": "code_too_small",
                "size": code_size,
                "severity": "warn",
                "message": FONT_WARNINGS["code_too_small"]["msg"].format(size=code_size),
                "sources": seen_sizes[code_size][:3],
            })
        elif code_size > FONT_WARNINGS["code_too_large"]["threshold"]:
            entries.append({
                "type": "code_too_large",
                "size": code_size,
                "severity": "info",
                "message": FONT_WARNINGS["code_too_large"]["msg"].format(size=code_size),
                "sources": seen_sizes[code_size][:3],
            })

    # Heading size check
    for hs in heading_sizes:
        if hs > FONT_WARNINGS["heading_too_large"]["threshold"]:
            entries.append({
                "type": "heading_too_large",
                "size": hs,
                "severity": "warn",
                "message": FONT_WARNINGS["heading_too_large"]["msg"].format(size=hs),
                "sources": seen_sizes[hs][:2],
            })

    # Also report very small text that might be footnotes
    for s in all_sizes:
        if s < 7 and s >= 5:
            entries.append({
                "type": "footnote_too_small",
                "size": s,
                "severity": "warn",
                "message": FONT_WARNINGS["footnote_too_small"]["msg"].format(size=s),
                "sources": seen_sizes[s][:2],
            })

    result["font_sizes"] = entries
    result["source_font_profile"] = {
        "body": body_size,
        "code": code_size,
        "heading": heading_sizes[0] if heading_sizes else None,
    }

    if verbose and entries:
        print(f"    Font audit: {len(entries)} findings")
        for e in entries:
            print(f"      [{e['severity'].upper()}] {e['message']}")


def _to_pt(value: float, unit: str) -> float | None:
    """Convert a font-size value to points. Returns None if unscalable."""
    if unit == "pt":
        return value
    elif unit == "px":
        return value * PX_TO_PT
    elif unit == "em":
        # Assume 1em = 12pt base (typical print default)
        return value * 12
    elif unit == "%":
        # Assume 100% = 12pt base
        return value / 100 * 12
    return None


# =========================================================================
# Page Boundary / Margin Violation Audit
# =========================================================================

# Patterns for fixed widths that might exceed printable area
FIXED_WIDTH_RE = re.compile(
    r'(?:width|max-width|min-width)\s*:\s*(\d+)\s*(pt|px|in|cm|mm|%)?',
    re.IGNORECASE
)
OVERFLOW_RE = re.compile(
    r'overflow\s*:\s*(hidden|auto|scroll|visible)',
    re.IGNORECASE
)

# Elements known to cause margin issues
WIDE_ELEMENT_TAGS = {'table', 'img', 'pre', 'object', 'embed', 'iframe', 'svg'}

IN_TO_PT = 72
CM_TO_PT = 28.35
MM_TO_PT = 2.835


def _audit_margin_violations(html_files: list, extract_dir: str,
                              result: dict, verbose: bool) -> int:
    """
    Scan HTML files and CSS for elements that violate page margins.
    Returns count of auto-fixes applied.
    """
    violations = []
    fixes = 0

    # Track the CSS constraint additions we make per file
    css_fix_map = defaultdict(set)

    for html_path in html_files:
        try:
            with open(html_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            continue

        fname = os.path.basename(html_path)
        file_changed = False

        # --- 1. Check images with explicit dimensions ---
        for match in re.finditer(
            r'<img[^>]*?(?:width|height)\s*=\s*["\'](\d+)["\'][^>]*>',
            content, re.IGNORECASE
        ):
            img_tag = match.group(0)
            width_val = None

            # Try style attribute first
            style_match = re.search(r'style\s*=\s*["\'][^"\']*?width\s*:\s*(\d+)\s*(pt|px|in|cm|mm)', img_tag, re.IGNORECASE)
            if style_match:
                width_val = _dim_to_pt(float(style_match.group(1)), style_match.group(2))
            else:
                # Try width attribute
                wm = re.search(r'width\s*=\s*["\'](\d+)["\']', img_tag, re.IGNORECASE)
                if wm:
                    width_val = int(wm.group(1)) * PX_TO_PT  # Assume px

            if width_val and width_val > PRINTABLE_WIDTH_PT * 0.95:
                violations.append({
                    "type": "image_overflow",
                    "file": fname,
                    "severity": "warn",
                    "detail": f"Image width {width_val:.0f}pt exceeds printable width {PRINTABLE_WIDTH_PT}pt",
                })
                # Fix: add style max-width constraint if missing
                if 'style="' in img_tag:
                    new_tag = re.sub(
                        r'style\s*=\s*["\']',
                        'style="max-width: 100% !important; height: auto; ',
                        img_tag
                    )
                else:
                    new_tag = img_tag.replace('/>', ' style="max-width: 100% !important; height: auto;" />')
                    new_tag = new_tag.replace('>', ' style="max-width: 100% !important; height: auto;" />', 1)

                content = content.replace(img_tag, new_tag, 1)
                file_changed = True
                fixes += 1

        # --- 2. Check tables with many columns ---
        for match in re.finditer(
            r'<table[^>]*>(.*?)</table>',
            content, re.IGNORECASE | re.DOTALL
        ):
            table_html = match.group(0)
            # Count columns in the first row
            cols = len(re.findall(r'<th[>\s]|<td[>\s]', table_html[:table_html.index('</tr>')] if '</tr>' in table_html else table_html))
            if cols >= 5:
                violations.append({
                    "type": "table_overflow",
                    "file": fname,
                    "severity": "warn",
                    "detail": f"Table with {cols} columns may exceed page width",
                })
                # Fix: ensure table-layout is set and max-width constrained
                if 'style=' in table_html[:60]:
                    new_table = re.sub(
                        r'(<table[^>]*style\s*=\s*["\'])([^"\']*)',
                        r'\1\2; table-layout: fixed; max-width: 100%; font-size: 0.8em;',
                        table_html
                    )
                else:
                    new_table = re.sub(
                        r'<table\s',
                        '<table style="table-layout: fixed; max-width: 100%; font-size: 0.8em;" ',
                        table_html, 1
                    )
                content = content.replace(table_html, new_table, 1)
                file_changed = True
                fixes += 1

        # --- 3. Check for pre/code with long lines ---
        for match in re.finditer(
            r'<pre[^>]*>((?:(?!</pre>).)*)</pre>',
            content, re.IGNORECASE | re.DOTALL
        ):
            pre_content = match.group(1)
            # Find the longest line
            lines = pre_content.split('\n')
            max_line = max((l.strip() for l in lines), key=len) if lines else ""
            if len(max_line) > 120:
                violations.append({
                    "type": "code_overflow",
                    "file": fname,
                    "severity": "info",
                    "detail": f"Code line with {len(max_line)} chars may overflow margins",
                })
                # Fix: ensure word-wrap/overflow-wrap
                if 'style=' in match.group(0):
                    new_pre = re.sub(
                        r'(<pre[^>]*style\s*=\s*["\'])([^"\']*)',
                        r'\1\2; white-space: pre-wrap; overflow-wrap: break-word; font-size: 0.8em;',
                        match.group(0)
                    )
                else:
                    new_pre = re.sub(
                        r'<pre\s',
                        '<pre style="white-space: pre-wrap; overflow-wrap: break-word; font-size: 0.8em;" ',
                        match.group(0), 1
                    )
                content = content.replace(match.group(0), new_pre, 1)
                file_changed = True
                fixes += 1

        # --- 4. Check for elements with fixed-width that exceed printable area ---
        for match in re.finditer(
            r'<(div|p|span|section)[^>]*style\s*=\s*["\'][^"\']*?width\s*:\s*(\d+(?:\.\d+)?)\s*(pt|px|in|cm|mm)',
            content, re.IGNORECASE
        ):
            tag = match.group(1)
            val = float(match.group(2))
            unit = match.group(3)
            width_pt = _dim_to_pt(val, unit)
            if width_pt and width_pt > PRINTABLE_WIDTH_PT:
                elem_start = match.start()
                violations.append({
                    "type": "element_overflow",
                    "file": fname,
                    "severity": "warn",
                    "detail": f"<{tag}> with fixed width {width_pt:.0f}pt exceeds printable area {PRINTABLE_WIDTH_PT}pt",
                })
                # Inject max-width constraint into the style
                full_tag_end = content.find('>', match.end())
                full_tag = content[match.start():full_tag_end + 1]
                new_tag = re.sub(
                    r'(style\s*=\s*["\'])([^"\']*)',
                    r'\1\2; max-width: 100%; overflow: hidden;',
                    full_tag
                )
                content = content.replace(full_tag, new_tag, 1)
                file_changed = True
                fixes += 1

        # --- 5. Check for SVG with oversized viewBox ---
        for match in re.finditer(
            r'<svg[^>]*viewBox\s*=\s*["\']\d+\s+\d+\s+(\d+)\s+(\d+)["\']',
            content, re.IGNORECASE
        ):
            vb_w = int(match.group(1))
            if vb_w > PRINTABLE_WIDTH_PT:
                violations.append({
                    "type": "svg_overflow",
                    "file": fname,
                    "severity": "warn",
                    "detail": f"SVG viewBox width {vb_w}pt exceeds printable area",
                })
                if 'style=' in match.group(0):
                    new_svg = re.sub(
                        r'(<svg[^>]*style\s*=\s*["\'])([^"\']*)',
                        r'\1\2; max-width: 100%; height: auto;',
                        match.group(0)
                    )
                else:
                    new_svg = re.sub(
                        r'<svg\s',
                        '<svg style="max-width: 100%; height: auto;" ',
                        match.group(0), 1
                    )
                content = content.replace(match.group(0), new_svg, 1)
                file_changed = True
                fixes += 1

        # Write back if changed
        if file_changed:
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(content)

    result["margin_violations"] = violations

    if verbose:
        if violations:
            print(f"    Margin audit: {len(violations)} violations")
            for v in violations[:10]:  # Show first 10
                print(f"      [{v['severity'].upper()}] {v['file']}: {v['detail']}")
            if len(violations) > 10:
                print(f"      ... and {len(violations) - 10} more")
        if fixes:
            print(f"    Auto-fixes applied: {fixes}")

    return fixes


def _dim_to_pt(value: float, unit: str) -> float:
    """Convert a dimension to points."""
    if unit == "pt":
        return value
    elif unit == "px":
        return value * PX_TO_PT
    elif unit == "in":
        return value * IN_TO_PT
    elif unit == "cm":
        return value * CM_TO_PT
    elif unit == "mm":
        return value * MM_TO_PT
    return value


# =========================================================================
# CSS injection for margin safety
# =========================================================================

MARGIN_SAFETY_CSS = """
/* ebook2pdf: Margin safety constraints */
table, img, pre, svg, object, embed, iframe, video {
    max-width: 100% !important;
    height: auto !important;
}
table {
    table-layout: auto !important;
}
td, th {
    word-wrap: break-word !important;
    overflow-wrap: break-word !important;
}
pre, code {
    white-space: pre-wrap !important;
    overflow-wrap: break-word !important;
}
/* Prevent layout containers from bleeding */
div, section, article, aside, main, header, footer, nav {
    max-width: 100% !important;
    overflow-wrap: break-word !important;
}
/* Shrink oversized elements gracefully */
img[width]:not([width=""]),
table[width]:not([width=""]) {
    max-width: 100% !important;
}
"""
