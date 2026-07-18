"""
Figure / table caption normalization heuristics.

Some EPUB publishers emit caption markup with broken structure:
- figure/table number and caption text split across separate elements or lines,
- spurious newlines/whitespace inside <figcaption> blocks,
- inconsistent wrapping for <span class="figureLabel">.

This module rewrites caption markup into a normalized, single-line,
center-friendly form before PDF conversion.
"""

import os
import re


def normalize_captions(root_dir: str, verbose: bool = False) -> bool:
    """Normalize figure/table caption markup under *root_dir*.

    Returns True if any changes were made.
    """
    changed = False

    for dirpath, _dirs, files in os.walk(root_dir):
        for name in files:
            fpath = os.path.join(dirpath, name)
            if not name.lower().endswith(('.html', '.xhtml', '.htm')):
                continue
            if _normalize_caption_file(fpath, verbose=verbose):
                changed = True

    return changed


def _normalize_caption_file(path: str, verbose: bool = False) -> bool:
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except Exception:
        return False

    original = content
    content = _normalize_figcaption_whitespace(content)
    content = _merge_broken_caption_lines(content)

    if content != original:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        if verbose:
            print(f"    Normalized captions in {os.path.basename(path)}")
        return True
    return False


def _normalize_figcaption_whitespace(text: str) -> str:
    """Collapse whitespace/newlines inside <figcaption> blocks.

    Targets:
    - <figcaption>\\n  <p>...\\n</p>\\n</figcaption>
    - multiline caption paragraphs
    """
    patterns = [
        re.compile(
            r'(<figcaption[^>]*>)(\s*)(<p[^>]*>)(\s*)(.+?)(\s*)(</p>)(\s*)(</figcaption>)',
            re.IGNORECASE | re.DOTALL,
        ),
        re.compile(
            r'(<figcaption[^>]*>)(\s*)(.+?)(\s*)(</figcaption>)',
            re.IGNORECASE | re.DOTALL,
        ),
    ]

    def _clean_caption(match: re.Match) -> str:
        opening = match.group(1)
        p_open = match.group(3) if match.group(3) else ''
        text = match.group(5) if len(match.groups()) >= 7 else match.group(3)
        p_close = match.group(7) if len(match.groups()) >= 9 else ''
        closing = match.group(9) if len(match.groups()) >= 9 else match.group(4)
        cleaned_text = ' '.join(text.split())
        if p_open:
            return f'{opening}\n{p_open} {cleaned_text} {p_close}\n{closing}'
        return f'{opening} {cleaned_text} {closing}'

    result = text
    for pattern in patterns:
        result = pattern.sub(_clean_caption, result)
    return result


def _merge_broken_caption_lines(text: str) -> str:
    """Merge figure/table labels split across lines or adjacent blocks.

    Handles patterns like:
    - <span class="figureLabel">Figure 8.1</span> Topics covered...
      where newlines or stray elements split them.
    """
    # Merge newlines between a figureLabel span and the following text
    # within the same paragraph/figcaption.
    pattern = re.compile(
        r'(<span\b[^>]*\bclass="figureLabel"[^>]*>.*?</span>)(\s*)(?=<[A-Za-z])',
        re.IGNORECASE | re.DOTALL,
    )

    def _trim(match: re.Match) -> str:
        return match.group(1) + ' '

    return pattern.sub(_trim, text)
