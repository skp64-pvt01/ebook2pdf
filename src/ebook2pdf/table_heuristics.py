"""
Table Formatting Recovery Heuristics.

Scans EPUB HTML content for patterns that suggest tabular data that was
rendered as non-table elements, then rebuilds proper <table> markup.

Detection Strategies
--------------------
1. CSS class heuristics — class names containing table/row/col/grid/tbl/cell
2. CSS display heuristics — elements using display:table/table-row/table-cell
3. Separator heuristics — pipe-delimited, tab-separated, or multi-space aligned text
4. Repeated-structure heuristics — repeated sibling elements with similar child patterns
5. List-based table heuristics — structured <ul>/<ol> content that looks tabular
6. Fixed-width alignment heuristics — text with column-aligned content
"""

import os
import re
from html.parser import HTMLParser


# Patterns for class names that suggest table-like content
TABLE_CLASS_PATTERNS = re.compile(
    r'\b(table|tbl|tabel|tabular|grid|row|col|cell|thead|tbody|tfoot|th|tr|td)\b',
    re.IGNORECASE
)

# HTML elements where tabular content detection is relevant
TABULAR_ELEMENTS = {'div', 'p', 'span', 'li', 'section', 'ul', 'ol'}


def scan_for_tabular_content(html_content: str) -> list[dict]:
    """
    Scan a chunk of HTML content for potential lost tabular data.
    
    Returns a list of dicts with:
      - 'type': str — heuristic type (css_class, separator, repeated, list)
      - 'start_tag': str — the opening tag context
      - 'confidence': float — 0.0 to 1.0
      - 'detail': str — description of what was found
    """
    findings = []

    # Strategy 1: CSS class heuristics
    _scan_css_classes(html_content, findings)

    # Strategy 2: Separator-based heuristics (pipe, tab, csv)
    _scan_separators(html_content, findings)

    # Strategy 3: Repeated structure heuristics
    _scan_repeated_structure(html_content, findings)

    # Strategy 4: List-based table detection
    _scan_list_tables(html_content, findings)

    return findings


def _scan_css_classes(html: str, findings: list) -> None:
    """Detect elements with table-like class names used on non-<table> elements."""
    # Match class="..." or class='...'
    for match in re.finditer(
        r'<(div|p|span|section|ul|ol)\s[^>]*class=(["\'])(.*?)\2',
        html, re.IGNORECASE
    ):
        tag, _, classes = match.groups()
        if TABLE_CLASS_PATTERNS.search(classes):
            # Check if this is a structural pattern (row/col combinations)
            has_row = bool(re.search(r'\b(row|grid-row)\b', classes, re.IGNORECASE))
            has_col = bool(re.search(r'\b(col|grid-col|table-cell)\b', classes, re.IGNORECASE))
            has_table = bool(re.search(r'\b(table|tbl|grid)\b', classes, re.IGNORECASE))

            confidence = 0.0
            detail = f"<{tag}> with class='{classes}'"
            if has_table and (has_row or has_col):
                confidence = 0.9
                detail += " — strong table pattern"
            elif has_row and has_col:
                confidence = 0.8
                detail += " — row/col pattern"
            elif has_table:
                confidence = 0.7
                detail += " — table keyword in class"
            elif has_row or has_col:
                confidence = 0.4
                detail += " — possible row/col layout"

            if confidence >= 0.5:
                findings.append({
                    'type': 'css_class',
                    'start_tag': match.group(0),
                    'confidence': confidence,
                    'detail': detail,
                })


def _scan_separators(html: str, findings: list) -> None:
    """Detect pipe-delimited, tab-separated, or CSV-like content."""
    # Remove HTML tags to get text content
    text = re.sub(r'<[^>]+>', ' ', html)
    # Collapse multiple spaces but keep tabs and newlines
    lines = text.split('\n')

    pipe_lines = 0
    tab_lines = 0
    csv_lines = 0
    multi_space_lines = 0
    total_text_lines = 0

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        total_text_lines += 1

        # Pipe-separated: | A | B | C |
        if re.search(r'^\|.*\|.*\|.*\|', stripped):
            pipe_lines += 1
        # Tab-separated: A\tB\tC (multiple tabs)
        elif '\t' in stripped and stripped.count('\t') >= 2:
            tab_lines += 1
        # CSV-like: A,B,C (3+ commas on one line)
        elif stripped.count(',') >= 2 and not stripped.startswith('<'):
            csv_lines += 1
        # Multi-space aligned: multiple consecutive spaces suggesting columns
        elif re.search(r'  {3,}', stripped) and len(stripped) > 40:
            multi_space_lines += 1

    if total_text_lines == 0:
        return

    # Multiple consecutive lines with same pattern = table
    total = pipe_lines + tab_lines + csv_lines + multi_space_lines
    if total >= 3 and total >= total_text_lines * 0.3:
        primary = max(
            ('pipe', pipe_lines),
            ('tab', tab_lines),
            ('csv', csv_lines),
            ('multi-space', multi_space_lines),
            key=lambda x: x[1]
        )
        confidence = min(1.0, total / total_text_lines)
        findings.append({
            'type': 'separator',
            'start_tag': f'{primary[0]} separator ({primary[1]} lines of {total_text_lines})',
            'confidence': confidence,
            'detail': f'{primary[0]}-delimited text across {primary[1]}/{total_text_lines} lines',
        })


def _scan_repeated_structure(html: str, findings: list) -> None:
    """Detect repeated sibling elements with similar internal structure."""
    # Look for repeated <p> or <div> patterns with similar class names
    # where they appear to be table rows

    # Find groups of consecutive similar elements
    p_matches = list(re.finditer(
        r'<(p|div)\s[^>]*class=(["\'])(.*?)\2',
        html, re.IGNORECASE
    ))

    # Group by class name
    from collections import Counter
    class_counts = Counter()
    for m in p_matches:
        class_counts[m.group(3)] += 1

    # If the same class appears 5+ times in a file, it might be table rows
    for cls, count in class_counts.most_common(10):
        if count >= 5:
            # Check if this is NOT already inside a <table>
            if _is_outside_table(html, cls):
                # Check for internal structure suggesting columns
                sample_pos = [m.start() for m in p_matches if m.group(3) == cls]
                if len(sample_pos) >= 3:
                    # Get text content of first few matches
                    texts = _extract_element_texts(html, sample_pos[:3])
                    # Check if texts have consistent separator patterns
                    separator_count = sum(
                        1 for t in texts
                        if '\t' in t or re.search(r'  {3,}', t) or t.count(',') >= 2
                    )
                    confidence = 0.3 + (separator_count / len(texts)) * 0.5
                    if confidence >= 0.5:
                        findings.append({
                            'type': 'repeated',
                            'start_tag': f'class="{cls}" ({count} occurrences)',
                            'confidence': confidence,
                            'detail': f'Repeated class "{cls}" ({count}x) with column-like content',
                        })


def _scan_list_tables(html: str, findings: list) -> None:
    """Detect <ul>/<ol> lists where items contain structured multi-column data."""
    # Find <li> elements with complex internal structure
    li_matches = list(re.finditer(r'<li[^>]*>', html, re.IGNORECASE))
    if len(li_matches) < 3:
        return

    # Sample a few <li> elements to check for internal structure
    sample_texts = []
    for m in li_matches[:5]:
        end = html.find('</li>', m.end())
        if end > 0:
            inner = html[m.end():end]
            # Check for multiple elements inside the <li>
            inner_tags = re.findall(r'<(p|div|span)[>\s]', inner)
            inner_links = re.findall(r'<a[>\s]', inner)
            inner_breaks = inner.count('<br')
            if len(inner_tags) >= 2 or inner_links >= 2:
                sample_texts.append(inner)

    if len(sample_texts) >= 3:
        # Check for consistent structure across list items
        tag_counts = []
        for txt in sample_texts:
            tags = re.findall(r'<(p|div|span|a|strong|em|b|i)[>\s]', txt)
            tag_counts.append(len(tags))

        if len(set(tag_counts)) == 1 and tag_counts[0] >= 2:
            confidence = min(0.8, 0.4 + len(sample_texts) * 0.1)
            findings.append({
                'type': 'list_table',
                'start_tag': f'<ul>/<ol> with {len(li_matches)} items',
                'confidence': confidence,
                'detail': f'Structured list with {len(li_matches)} items, each with {tag_counts[0]} sub-elements',
            })


def _is_outside_table(html: str, class_name: str) -> bool:
    """Check if a class reference is outside any <table> element."""
    # Simple check: look for the class before a </table> or after <table>
    pos = html.find(class_name)
    if pos < 0:
        return True

    # Count <table> and </table> before this position
    opens = html[:pos].count('<table')
    closes = html[:pos].count('</table>')
    return opens <= closes


def _extract_element_texts(html: str, positions: list) -> list[str]:
    """Extract text content around given positions."""
    texts = []
    for pos in positions[:5]:
        # Find the matching closing tag
        start = html.find('>', pos) + 1
        if start <= 0:
            continue
        # Try to find the end at same nesting level
        depth = 1
        end = start
        while depth > 0 and end < len(html):
            end += 1
            next_open = html.find('<', end)
            if next_open < 0:
                break
            next_close = html.find('>', next_open)
            tag = html[next_open:next_close + 1]
            if tag.startswith('</') and not tag.startswith('</ '):
                depth -= 1
            elif not tag.startswith('</') and not tag.startswith('<!') and not tag.startswith('</ '):
                depth += 1
            end = next_close
        texts.append(html[start:end])
    return texts


# ---------------------------------------------------------------------------
# Table Recovery
# ---------------------------------------------------------------------------

def recover_tables_in_file(html_path: str, verbose: bool = False) -> bool:
    """
    Scan a single HTML/XHTML file and recover lost table formatting.
    
    Returns True if any changes were made.
    """
    with open(html_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

    original = content
    changes = 0

    # Recovery 1: Convert CSS class-based table patterns
    content = _recover_css_tables(content, verbose)

    # Recovery 2: Convert separator-based tables (pipe-separated)
    content = _recover_pipe_tables(content, verbose)

    # Recovery 3: Convert repeated block tables
    content = _recover_repeated_tables(content, verbose)

    # Recovery 4: Convert list-based tables
    content = _recover_list_tables(content, verbose)

    if content != original:
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(content)
        if verbose:
            print(f"    Recovered tables in {os.path.basename(html_path)}")
        return True

    return False


def _recover_css_tables(html: str, verbose: bool = False) -> str:
    """
    Recover tables from <div>/<p> elements using display:table CSS classes.
    
    Converts patterns like:
      <div class="table-row">
        <div class="table-cell">A</div>
        <div class="table-cell">B</div>
      </div>
    Into proper <table>/<tr>/<td> markup.
    """

    # Pattern 1: Grid/row container with cell children
    # Look for <div class="table-row">...</div> or similar
    row_patterns = [
        r'<div[^>]*class="[^"]*\brow\b[^"]*"[^>]*>',
        r'<div[^>]*class="[^"]*\bgrid-row\b[^"]*"[^>]*>',
        r'<div[^>]*class="[^"]*\btablerow\b[^"]*"[^>]*>',
        r'<div[^>]*class="[^"]*\btbl-row\b[^"]*"[^>]*>',
    ]

    # This is a complex DOM transformation. For now, we wrap detected
    # row/col patterns in <table> tags and add CSS for proper display.
    # Full DOM parsing would require a proper HTML parser with tree manipulation.

    row_count = 0
    for pattern in row_patterns:
        for match in re.finditer(pattern, html, re.IGNORECASE):
            # Check if this row is already inside a <table>
            # by looking backwards for <table> or </table>
            pos = match.start()
            open_tables = html[:pos].count('<table')
            close_tables = html[:pos].count('</table>')
            if open_tables > close_tables:
                continue  # Already inside a table

            # Find the closing </div> for this row
            depth = 1
            end = match.end()
            while depth > 0 and end < len(html):
                next_div_open = html.find('<div', end)
                next_div_close = html.find('</div>', end)
                if next_div_close < 0:
                    break
                if next_div_open >= 0 and next_div_open < next_div_close:
                    depth += 1
                    end = next_div_open + 5
                else:
                    depth -= 1
                    if depth == 0:
                        end = next_div_close + 6
                    else:
                        end = next_div_close + 6

            if depth == 0 and end > match.end():
                row_content = html[match.start():end]
                # Only wrap if this contains cell-like children
                if re.search(r'class="[^"]*\bcell\b[^"]*"', row_content, re.IGNORECASE):
                    # Wrap entire row group in <table>
                    table_wrapped = f'<table>\n{row_content}\n</table>'
                    html = html[:match.start()] + table_wrapped + html[end:]
                    row_count += 1

    if row_count > 0 and verbose:
        print(f"    Wrapped {row_count} CSS table-row patterns in <table>")

    return html


def _recover_pipe_tables(html: str, verbose: bool = False) -> str:
    """
    Recover tables from pipe-separated text content.
    
    Converts patterns like:
      | Header 1 | Header 2 | Header 3 |
      |----------|----------|----------|
      | Cell A1  | Cell A2  | Cell A3  |
    
    Into <table> markup. Also handles markdown-style pipe tables.
    """
    lines = html.split('\n')
    new_lines = []
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Check for pipe table line: | A | B | C |
        # Must have at least 3 pipe characters for a meaningful table
        if re.search(r'^\|.*\|.*\|', stripped):
            # Collect consecutive pipe table lines
            table_lines = []
            while i < len(lines) and re.search(r'^\|.*\|', lines[i].strip()):
                table_lines.append(lines[i].strip())
                i += 1

            if len(table_lines) >= 2:
                # Skip separator line (---|---|---)
                data_lines = [l for l in table_lines if not re.match(r'^\|[\s\-:]+\|', l)]

                if len(data_lines) >= 2:
                    cells_per_row = []
                    for dl in data_lines:
                        cells = [c.strip() for c in dl.split('|')]
                        cells = [c for c in cells if c]  # Remove empty first/last
                        cells_per_row.append(len(cells))

                    # Check for consistent column count
                    if len(set(cells_per_row)) == 1 and cells_per_row[0] >= 2:
                        # Build table
                        table_buf = ['<table class="epub2pdf-recovered-table">']
                        for idx, dl in enumerate(data_lines):
                            cells = [c.strip() for c in dl.split('|')]
                            cells = [c for c in cells if c]
                            tag = 'th' if idx == 0 else 'td'
                            table_buf.append(f'  <tr>')
                            for cell in cells:
                                table_buf.append(f'    <{tag}>{cell}</{tag}>')
                            table_buf.append(f'  </tr>')
                        table_buf.append('</table>')
                        new_lines.extend(table_buf)
                        continue

            # If not a valid table, add back all collected lines
            new_lines.extend(table_lines)
            continue

        new_lines.append(lines[i])
        i += 1

    return '\n'.join(new_lines)


def _recover_repeated_tables(html: str, verbose: bool = False) -> str:
    """
    Recover tables from repeated <p> or <div> elements with tab/space-separated content.
    
    Detects sequences of sibling elements that each contain tab-delimited or
    multi-space-aligned text suggesting multiple columns.
    """
    # Find blocks of consecutive <p> elements with tab characters
    # Pattern: <p class="xxx">text\tmore\tdata</p> repeated 3+ times

    # This is complex to do with regex. We use a simpler approach:
    # Find adjacent <p>...</p> blocks within a container <div>
    # that have tab-separated content.

    p_blocks = list(re.finditer(
        r'<p[^>]*class=(["\'])(.*?)\1[^>]*>((?:(?!</p>).)*)</p>',
        html, re.IGNORECASE | re.DOTALL
    ))

    if len(p_blocks) < 3:
        return html

    # Group consecutive blocks with same class
    groups = []
    current_group = [p_blocks[0]]

    for block in p_blocks[1:]:
        if block.group(2) == current_group[0].group(2):
            # Same class - check if they're close together
            gap = block.start() - current_group[-1].end()
            if gap < 200:  # Within reasonable distance (no large gap)
                current_group.append(block)
                continue
        # Different class or large gap - save group and start new
        if len(current_group) >= 3:
            groups.append(current_group)
        current_group = [block]

    if len(current_group) >= 3:
        groups.append(current_group)

    # Check each group for tabular content
    for group in groups:
        contents = []
        for block in group:
            inner = block.group(3)
            # Check for tab separation or consistent comma separation
            stripped = re.sub(r'<[^>]+>', '', inner).strip()
            content_parts = None

            if '\t' in stripped:
                parts = [p.strip() for p in stripped.split('\t') if p.strip()]
                if len(parts) >= 2:
                    content_parts = parts
            elif re.search(r'  {3,}', stripped):
                parts = re.split(r'  {2,}', stripped)
                parts = [p.strip() for p in parts if p.strip()]
                if len(parts) >= 2:
                    content_parts = parts

            if content_parts:
                contents.append(content_parts)

        if len(contents) >= 3:
            # Check consistent column count
            col_counts = set(len(c) for c in contents)
            if len(col_counts) == 1 and list(col_counts)[0] >= 2:
                # Build table
                table_buf = ['<table class="epub2pdf-recovered-table">']
                for idx, cells in enumerate(contents):
                    tag = 'th' if idx == 0 else 'td'
                    table_buf.append('  <tr>')
                    for cell in cells:
                        table_buf.append(f'    <{tag}>{cell}</{tag}>')
                    table_buf.append('  </tr>')
                table_buf.append('</table>')

                # Replace the group with the table
                start = group[0].start()
                end = group[-1].end()
                html = html[:start] + '\n'.join(table_buf) + html[end:]

                if verbose:
                    print(f"    Recovered {len(contents)}-row repeated-block table")

    return html


def _recover_list_tables(html: str, verbose: bool = False) -> str:
    """
    Recover tables from structured <ul>/<ol> lists.
    
    Detects <li> elements that contain multiple child elements (like
    <a>, <span>, <strong>) suggesting tabular row structure.
    Converts them to <table> markup.
    """
    # Find <ul> or <ol> blocks
    list_pattern = re.compile(
        r'(<(?:ul|ol)[^>]*>)(.*?)(</(?:ul|ol)>)',
        re.IGNORECASE | re.DOTALL
    )

    def _convert_list(match):
        open_tag = match.group(1)
        inner = match.group(2)
        close_tag = match.group(3)

        # Find all <li> elements
        li_items = list(re.finditer(
            r'<li[^>]*>((?:(?!</li>).)*)</li>',
            inner, re.IGNORECASE | re.DOTALL
        ))

        if len(li_items) < 3:
            return match.group(0)  # Too few items, not a table

        # Check if each <li> has complex internal structure
        rows = []
        col_counts = set()

        for li in li_items:
            li_inner = li.group(1)
            # Count child elements
            child_elements = re.findall(r'<(p|div|span|a|strong|em|b|i)[>\s]', li_inner)
            if len(child_elements) < 2:
                continue  # Simple <li>, not tabular

            # Extract text segments between child tags
            text_parts = re.findall(r'>([^<]+)<', li_inner)
            text_parts = [t.strip() for t in text_parts if t.strip()]

            if len(text_parts) >= 2:
                rows.append(text_parts)
                col_counts.add(len(text_parts))

        if len(rows) >= 3 and len(col_counts) == 1:
            # Build table
            cols = list(col_counts)[0]
            table_buf = ['<table class="epub2pdf-recovered-table">']
            for idx, cells in enumerate(rows):
                tag = 'th' if idx == 0 else 'td'
                table_buf.append('  <tr>')
                for cell in cells[:cols]:
                    table_buf.append(f'    <{tag}>{cell}</{tag}>')
                table_buf.append('  </tr>')
            table_buf.append('</table>')

            return '\n'.join(table_buf)

        return match.group(0)  # Not convertible, return as-is

    return list_pattern.sub(_convert_list, html)


# ---------------------------------------------------------------------------
# Batch recovery
# ---------------------------------------------------------------------------

def recover_tables_in_epub(extract_dir: str, verbose: bool = False) -> int:
    """
    Scan all HTML/XHTML files in an extracted EPUB and recover lost tables.
    
    Returns the number of files that were modified.
    """
    modified = 0
    scanned = 0

    for root, _dirs, files in os.walk(extract_dir):
        for fname in files:
            if not fname.endswith(('.html', '.xhtml', '.htm')):
                continue
            fpath = os.path.join(root, fname)

            try:
                with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                scanned += 1

                if _recover_tables_in_content(content, fpath, fname, verbose):
                    modified += 1

            except Exception as e:
                if verbose:
                    print(f"    [WARN] Error scanning {fname}: {e}")

    if verbose and scanned > 0:
        print(f"    Scanned {scanned} files, recovered tables in {modified}")

    return modified


def _recover_tables_in_content(content: str, fpath: str, fname: str, verbose: bool) -> bool:
    """Apply all table recovery strategies to a file's content."""
    original = content

    # Strategy 1: Pipe-delimited tables
    content = _recover_pipe_tables(content, verbose)

    # Strategy 2: CSS class-based table rows
    content = _recover_css_tables(content, verbose)

    # Strategy 3: Repeated block tables
    content = _recover_repeated_tables(content, verbose)

    # Strategy 4: List-based tables
    content = _recover_list_tables(content, verbose)

    if content != original:
        with open(fpath, 'w', encoding='utf-8') as f:
            f.write(content)
        if verbose:
            print(f"    Recovered tables in {fname}")
        return True

    return False


# ---------------------------------------------------------------------------
# CSS injection for recovered tables
# ---------------------------------------------------------------------------

TABLE_RECOVERY_CSS = """
/* ebook2pdf: Recovered table formatting */
table.epub2pdf-recovered-table {
    max-width: 100% !important;
    border-collapse: collapse !important;
    margin: 0.5em auto !important;
    font-size: 0.9em !important;
}
table.epub2pdf-recovered-table td,
table.epub2pdf-recovered-table th {
    border: 1px solid #333 !important;
    padding: 4pt 6pt !important;
    vertical-align: top !important;
}
table.epub2pdf-recovered-table th {
    background-color: #e0e0e0 !important;
    font-weight: bold !important;
}
table.epub2pdf-recovered-table tr {
    page-break-inside: avoid !important;
}
"""
