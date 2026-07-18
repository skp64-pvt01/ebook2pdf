"""
TOC / NAV normalization heuristics.

Some EPUB publishers emit broken/malformed TOC labels:
- bare page numbers that end up as standalone TOC entries
- duplicated sibling entries for the same target
- merged labels like 'Chapter Title      123'
- wrong ordering because page-number navPoints are inserted before/alongside real entries

This module detects repaired TOC structures and rewrites them into clean,
left-aligned text entries with right-aligned page numbers.
"""

import os
import re


def normalize_toc_labels(root_dir: str, verbose: bool = False) -> bool:
    """Rewrite TOC/nav markup under *root_dir* into a normalized form.

    Returns True if any changes were made.
    """
    changed = False

    for dirpath, _dirs, files in os.walk(root_dir):
        for name in files:
            fpath = os.path.join(dirpath, name)
            lower = name.lower()
            if lower.endswith('.ncx'):
                if _normalize_ncx(fpath, verbose=verbose):
                    changed = True
            elif _is_toc_html(name):
                if _normalize_html_toc(fpath, verbose=verbose):
                    changed = True

    return changed


# ---------------------------------------------------------------------------
# NCX normalization
# ---------------------------------------------------------------------------

_MERGED_LABEL_RE = re.compile(
    r'^(.*?)(?:\s+)(\d+)$',
    re.UNICODE,
)


def _normalize_ncx(path: str, verbose: bool = False) -> bool:
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except Exception:
        return False

    original = content
    content = _fix_merged_ncx_labels(content)

    if content != original:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        if verbose:
            print(f"    Normalized NCX TOC in {os.path.basename(path)}")
        return True
    return False


def _fix_merged_ncx_labels(text: str) -> str:
    """Split labels like 'Chapter Title      123' into title + standalone page entry.

    The injected page-number navPoint is given a distinct id and empty content
    so downstream tools can still render it as a page reference.
    """

    def _replace(match: re.Match) -> str:
        full = match.group(0)
        title = match.group(1).strip()
        page = match.group(2).strip()
        if not title or not page:
            return full
        if re.match(r'^\d+$', title):
            return full
        escaped_title = _escape_xml(title)
        escaped_page = _escape_xml(page)
        return (
            f'<navLabel>\n'
            f'  <text>{escaped_title}</text>\n'
            f'</navLabel>\n'
            f'<navPoint class="chapter toc-page-number" id="toc-page-{_hash(match)}" playOrder="">\n'
            f'  <navLabel>\n'
            f'    <text>{escaped_page}</text>\n'
            f'  </navLabel>\n'
            f'  <content src=""/>'
        )

    return _MERGED_LABEL_RE.sub(_replace, text)


def _escape_xml(value: str) -> str:
    return value.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _hash(match: re.Match) -> str:
    return str(abs(hash(match.group(0))))[:10]


# ---------------------------------------------------------------------------
# HTML TOC normalization
# ---------------------------------------------------------------------------

_HTML_TOC_NAMES = {
    'toc.html', 'toc.xhtml', 'nav.xhtml', 'contents.html', 'contents.xhtml',
}


def _is_toc_html(name: str) -> bool:
    lower = name.lower()
    return lower in _HTML_TOC_NAMES or 'toc' in lower or lower.startswith('nav.')


def _normalize_html_toc(path: str, verbose: bool = False) -> bool:
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except Exception:
        return False

    original = content
    content = _wrap_toc_page_numbers(content)

    if content != original:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        if verbose:
            print(f"    Normalized HTML TOC in {os.path.basename(path)}")
        return True
    return False


def _wrap_toc_page_numbers(text: str) -> str:
    """Wrap standalone trailing page numbers in TOC list items with a span."""
    patterns = [
        re.compile(
            r'(<li[^>]*>\s*<[^>]+>\s*)(.+?)(\s*)(\d+)(\s*</[^>]+>\s*</li>)',
            re.IGNORECASE | re.DOTALL,
        ),
        re.compile(
            r'(<p\b[^>]*>\s*)(.+?)(\s*)(\d+)(\s*</p>)',
            re.IGNORECASE | re.DOTALL,
        ),
    ]

    result = text
    for pattern in patterns:
        result = pattern.sub(
            r'\1\2\3<span class="tocPageNumber">\4</span>\5',
            result,
        )
    return result
