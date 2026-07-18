"""
Code Block Detection & Recovery Heuristics.

Scans EPUB HTML content for code blocks that lack proper formatting,
then wraps them in <div class="epub2pdf-code-block"> with light grey
background, border, and monospace font for better PDF rendering.

Detection Strategies
--------------------
1. Existing <pre> blocks — already proper, but add wrapper class if missing
2. Standalone <code> elements not inside <pre> — wrap as block-level
3. Monospace font-family on <div>/<p>/<td> — font-based heuristic
4. Code-like class names — class containing code/listing/terminal/command/output/sample
5. Shell-command lines — lines starting with $, >, #, % (CLI prompts)
6. Indented text blocks — 4+ spaces/1+ tab indentation suggesting code samples
7. Inline <code> inside paragraphs — detect and leave inline (no wrapping)
"""

import os
import re


# Patterns for class names that suggest code content
CODE_CLASS_PATTERNS = re.compile(
    r'\b(code|listing|terminal|command|output|sample|example|snippet'
    r'|program|source|bash|sh|shell|python|ruby|perl|script|console'
    r'|mono|courier|codep|cmdline|cli|prompt|logfile|trace|stacktrace'
    r'|codeblock|code-area|code_area|listing-container)\b',
    re.IGNORECASE
)

# Monospace font-family patterns
MONO_FONT_PATTERN = re.compile(
    r'font-family\s*:[^;}]*'
    r'(monospace|"Courier New"|Courier|"Lucida Console"|Consolas'
    r'|Menlo|Monaco|"Liberation Mono"|"DejaVu Sans Mono"'
    r'|"Source Code Pro"|"Fira Code"|"JetBrains Mono"'
    r'|"SF Mono"|"Cascadia Code"|"Ubuntu Mono")',
    re.IGNORECASE
)

# Shell prompt patterns — lines starting with common prompts
SHELL_PROMPT_RE = re.compile(r'^\s*[\$#>%]\s', re.MULTILINE)

# Elements where block-level code detection is relevant
BLOCK_ELEMENTS = {'div', 'p', 'pre', 'td', 'li'}


def scan_for_code_content(html_content: str) -> list[dict]:
    """
    Scan HTML content for potential code blocks that need formatting.

    Returns a list of dicts with:
      - 'type': str — heuristic type (pre_block, mono_font, code_class,
                      shell_command, indented_block, inline_code)
      - 'context': str — brief context of what was found
      - 'confidence': float — 0.0 to 1.0
      - 'detail': str — description of what was found
    """
    findings = []

    # Strategy 1: Existing <pre> blocks
    _scan_pre_blocks(html_content, findings)

    # Strategy 2: Elements with monospace font-family
    _scan_mono_font(html_content, findings)

    # Strategy 3: Code-like class names on block elements
    _scan_code_classes(html_content, findings)

    # Strategy 4: Shell command / prompt lines
    _scan_shell_commands(html_content, findings)

    # Strategy 5: Indented text blocks (code samples)
    _scan_indented_blocks(html_content, findings)

    return findings


def _scan_pre_blocks(html: str, findings: list) -> None:
    """Existing <pre> blocks — count them and note any that lack wrapper."""
    pre_matches = list(re.finditer(r'<pre[^>]*>', html, re.IGNORECASE))
    wrapped = 0
    unwrapped = 0
    for m in pre_matches:
        tag = m.group(0)
        if 'class="epub2pdf-code-block"' in tag or "epub2pdf-code-block" in tag:
            wrapped += 1
        else:
            unwrapped += 1

    total = wrapped + unwrapped
    if total == 0:
        return

    findings.append({
        'type': 'pre_block',
        'context': f'{total} <pre> blocks ({wrapped} wrapped, {unwrapped} unwrapped)',
        'confidence': 0.9 if unwrapped > 0 else 0.3,
        'detail': f'{total} <pre> elements found, {unwrapped} need wrapping',
    })


def _scan_mono_font(html: str, findings: list) -> None:
    """Detect non-<pre> block elements with monospace font-family."""
    for match in re.finditer(
        r'<(div|p|pre|td|li|span|code)\s[^>]*style=(["\'])(.*?)\2',
        html, re.IGNORECASE
    ):
        tag = match.group(1)
        style = match.group(3)
        if MONO_FONT_PATTERN.search(style):
            # Only flag block-level elements (not inline spans or inline code)
            if tag in BLOCK_ELEMENTS:
                findings.append({
                    'type': 'mono_font',
                    'context': f'<{tag}> with monospace font',
                    'confidence': 0.7,
                    'detail': f'<{tag}> with monospace font-family: {style[:60]}',
                })


def _scan_code_classes(html: str, findings: list) -> None:
    """Detect block elements with code-like class names."""
    for match in re.finditer(
        r'<(div|p|pre|td|li|section)\s[^>]*class=(["\'])(.*?)\2',
        html, re.IGNORECASE
    ):
        tag = match.group(1)
        classes = match.group(3)
        if CODE_CLASS_PATTERNS.search(classes):
            # Determine confidence based on specificity
            has_direct_code = bool(re.search(
                r'\b(code|listing|codeblock|code-area|code_area)\b', classes, re.IGNORECASE
            ))
            confidence = 0.85 if has_direct_code else 0.65
            findings.append({
                'type': 'code_class',
                'context': f'<{tag}> with code-related class',
                'confidence': confidence,
                'detail': f'<{tag}> class="{classes[:60]}"',
            })


def _scan_shell_commands(html: str, findings: list) -> None:
    """Detect lines that look like shell command prompts."""
    # Remove HTML tags to get text content
    text = re.sub(r'<[^>]+>', ' ', html)
    prompt_lines = SHELL_PROMPT_RE.findall(text)
    if len(prompt_lines) >= 3:
        findings.append({
            'type': 'shell_command',
            'context': f'{len(prompt_lines)} shell prompt lines',
            'confidence': min(0.9, 0.5 + len(prompt_lines) * 0.05),
            'detail': f'{len(prompt_lines)} lines with shell prompts ($, #, >, %)',
        })


def _scan_indented_blocks(html: str, findings: list) -> None:
    """Detect indented text blocks suggesting code samples."""
    text = re.sub(r'<[^>]+>', '\n', html)
    lines = text.split('\n')
    indented_lines = 0
    indented_blocks = 0
    in_block = False

    for line in lines:
        # Lines indented by 4+ spaces or 1+ tab
        if re.match(r'^ {4,}', line) or re.match(r'^\t+', line):
            stripped = line.strip()
            if stripped and not stripped.startswith(('<', '/*', '*', '--')):
                indented_lines += 1
                if not in_block:
                    indented_blocks += 1
                    in_block = True
        else:
            in_block = False

    if indented_lines >= 5 and indented_blocks >= 1:
        findings.append({
            'type': 'indented_block',
            'context': f'{indented_lines} indented lines in {indented_blocks} blocks',
            'confidence': min(0.8, 0.3 + indented_lines * 0.02),
            'detail': f'{indented_lines} lines with code-like indentation across {indented_blocks} blocks',
        })


# ---------------------------------------------------------------------------
# Code Block Recovery
# ---------------------------------------------------------------------------

# CSS added to each wrapped code block
CODE_BLOCK_STYLE = (
    'background-color: #f4f4f4;'
    ' border: 1px solid #d0d0d0;'
    ' border-radius: 3px;'
    ' padding: 8pt 10pt;'
    ' margin: 0.5em 0;'
    ' font-family: monospace, "Courier New", Courier;'
    ' font-size: 0.85em;'
    ' white-space: pre;'
    ' overflow-x: auto;'
    ' line-height: 1.3;'
    ' page-break-inside: avoid;'
)

# For inline <code> that's already inside a block with code-block class
INLINE_CODE_STYLE = (
    'background-color: #f4f4f4;'
    ' border: 1px solid #e0e0e0;'
    ' border-radius: 2px;'
    ' padding: 1pt 3pt;'
    ' font-family: monospace, "Courier New", Courier;'
    ' font-size: 0.85em;'
)


def recover_code_blocks_in_file(html_path: str, verbose: bool = False) -> bool:
    """
    Scan a single HTML/XHTML file and wrap detected code blocks.

    Returns True if any changes were made.
    """
    try:
        with open(html_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except Exception:
        return False

    original = content

    # Recovery 1: Wrap existing <pre> blocks that lack the code-block wrapper
    content = _wrap_pre_blocks(content, verbose)

    # Recovery 2: Wrap standalone <code> blocks (not inside <pre>)
    content = _wrap_standalone_code(content, verbose)

    # Recovery 3: Wrap <div>/<p> with monospace font-family
    content = _wrap_mono_font_elements(content, verbose)

    # Recovery 4: Wrap elements with code-like class names
    content = _wrap_code_class_elements(content, verbose)

    # Recovery 5: Wrap shell-command prompt blocks
    content = _wrap_shell_blocks(content, verbose)

    # Recovery 6: Wrap indented text/code blocks
    content = _wrap_indented_blocks(content, verbose)

    # Recovery 7: Style inline <code> tags (in-code-block inline gets container bg)
    content = _style_inline_code(content, verbose)

    if content != original:
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(content)
        if verbose:
            print(f"    Wrapped code blocks in {os.path.basename(html_path)}")
        return True

    return False


def _wrap_pre_blocks(html: str, verbose: bool = False) -> str:
    """Wrap existing <pre> blocks with the code-block div if not already wrapped."""
    def _wrap_pre(match):
        pre_tag = match.group(0)
        # Check if already inside epub2pdf-code-block
        before = html[max(0, match.start() - 200):match.start()]
        if 'epub2pdf-code-block' in before:
            return pre_tag  # Already wrapped

        # Check if pre already has a class
        if 'class=' in pre_tag[:60]:
            # Add epub2pdf-code-block class
            new_tag = re.sub(
                r'class=(["\'])(.*?)\1',
                r'class=\1epub2pdf-code-block \2\1',
                pre_tag
            )
        else:
            new_tag = pre_tag.replace('<pre', '<pre class="epub2pdf-code-block"')

        return new_tag

    html = re.sub(r'<pre[^>]*>', _wrap_pre, html, flags=re.IGNORECASE)

    # Now wrap the <pre> in a styled div if it doesn't have inline style
    def _wrap_pre_container(match):
        pre_block = match.group(0)
        if 'style=' in pre_block[:100] or 'epub2pdf-code-block-wrapper' in pre_block:
            return pre_block
        # Add the style to the pre tag
        if 'style=' in pre_block[:60]:
            new_block = re.sub(
                r'(<pre[^>]*style=(["\'])(.*?)\2)',
                lambda m: m.group(0).rstrip('>') + f' style="{CODE_BLOCK_STYLE}"' + '>'
                           if 'style=' not in m.group(0)[:m.group(0).find('>')]
                           else re.sub(
                               r'(style=(["\'])(.*?)\2)',
                               lambda sm: f'style={sm.group(2)}{CODE_BLOCK_STYLE}{sm.group(2)}',
                               m.group(0)
                           ),
                pre_block
            )
            return new_block
        else:
            return pre_block.replace('<pre', f'<pre style="{CODE_BLOCK_STYLE}"')

    html = re.sub(r'<pre[^>]*>.*?</pre>', _wrap_pre_container, html, flags=re.IGNORECASE | re.DOTALL)

    return html


def _wrap_standalone_code(html: str, verbose: bool = False) -> str:
    """
    Wrap standalone <code> elements not already inside <pre>.
    Multi-line or block-level <code> gets wrapped; inline stays.
    """
    # Find <code> blocks that aren't inside <pre>
    def _check_code(match):
        code_tag = match.group(0)
        inner = match.group(1)

        # Skip if inside <pre>
        before = html[max(0, match.start() - 200):match.start()]
        if re.search(r'<pre[^>]*>', before) and '</pre>' not in before:
            return code_tag  # Already inside <pre>

        # Only wrap if multi-line or contains significant content
        lines = inner.strip().split('\n')
        has_newlines = len(lines) > 1
        is_block = has_newlines or len(inner.strip()) > 100

        if not is_block:
            return code_tag  # Leave inline code alone

        # Wrap in styled div
        return (
            f'<div class="epub2pdf-code-block" style="{CODE_BLOCK_STYLE}">\n'
            f'{inner}\n'
            f'</div>'
        )

    html = re.sub(
        r'<code[^>]*>((?:(?!</code>).)*)</code>',
        _check_code,
        html,
        flags=re.IGNORECASE | re.DOTALL
    )

    return html


def _wrap_mono_font_elements(html: str, verbose: bool = False) -> str:
    """Wrap <div>/<p> elements using monospace font-family."""
    def _wrap_mono(match):
        full_tag = match.group(0)
        tag = match.group(1)
        style = match.group(3)

        # Skip if already wrapped
        if 'epub2pdf-code-block' in full_tag:
            return full_tag

        # Only wrap block-level elements
        if tag not in BLOCK_ELEMENTS:
            return full_tag

        # CRITICAL: Only wrap if style matches monospace font-family!
        if not MONO_FONT_PATTERN.search(style):
            return full_tag

        new_style = f'{CODE_BLOCK_STYLE} {style}'
        new_tag = re.sub(
            r'(style=(["\'])(.*?)\2)',
            lambda m: f'style={m.group(2)}{new_style}{m.group(2)}',
            full_tag
        )
        return new_tag

    html = re.sub(
        r'<(div|p|pre|td|li)\s[^>]*style=(["\'])(.*?)\2[^>]*>',
        _wrap_mono,
        html,
        flags=re.IGNORECASE | re.DOTALL
    )

    return html


def _wrap_code_class_elements(html: str, verbose: bool = False) -> str:
    """Wrap block elements with code-related class names."""
    def _wrap_class(match):
        full_tag = match.group(0)
        tag = match.group(1)
        classes = match.group(3)

        # Skip if already wrapped
        if 'epub2pdf-code-block' in full_tag:
            return full_tag

        # Skip if already inside a code-block wrapper
        before = html[max(0, match.start() - 300):match.start()]
        if 'epub2pdf-code-block' in before:
            return full_tag

        # CRITICAL: Only wrap if class matches code block class patterns!
        if not CODE_CLASS_PATTERNS.search(classes):
            return full_tag

        # Add inline style
        if 'style=' in full_tag[:60]:
            new_tag = re.sub(
                r'(style=(["\'])(.*?)\2)',
                lambda m: f'style={m.group(2)}{CODE_BLOCK_STYLE} {m.group(3)}{m.group(2)}',
                full_tag
            )
        else:
            new_tag = full_tag.replace('>', f' style="{CODE_BLOCK_STYLE}">', 1)
        return new_tag

    html = re.sub(
        r'<(div|p|pre|td|li|section)\s[^>]*class=(["\'])(.*?)\2[^>]*>',
        _wrap_class,
        html,
        flags=re.IGNORECASE | re.DOTALL
    )

    return html


def _style_inline_code(html: str, verbose: bool = False) -> str:
    """Add light background to inline <code> tags not inside <pre> or code-block div."""
    def _style_code(match):
        code_tag = match.group(0)
        inner = match.group(1)

        # Skip if inside <pre>
        before = html[max(0, match.start() - 300):match.start()]
        if re.search(r'<pre[^>]*>', before) and '</pre>' not in before:
            return code_tag
        if 'epub2pdf-code-block' in before:
            return code_tag

        # Skip if already styled
        if 'background-color' in code_tag or 'style=' in code_tag[:60]:
            return code_tag

        # Add inline style
        return code_tag.replace('<code', f'<code style="{INLINE_CODE_STYLE}"')

    html = re.sub(
        r'<code[^>]*>((?:(?!</code>).)*)</code>',
        _style_code,
        html,
        flags=re.IGNORECASE | re.DOTALL
    )

    return html


# ---------------------------------------------------------------------------
# Shell-prompt & indented-code block wrappers
# ---------------------------------------------------------------------------

def _wrap_shell_blocks(html: str, verbose: bool = False) -> str:
    """Wrap block elements whose inner text contains 3+ shell-prompt lines."""
    def _wrap(match: re.Match) -> str:
        tag = match.group(1)
        attrs = match.group(2) or ''
        inner_start = match.start(3)
        inner_end = match.end(3)

        if 'epub2pdf-code-block' in html[max(0, inner_start - 200):inner_start]:
            return match.group(0)

        text = _strip_tags(html[inner_start:inner_end])
        prompt_lines = SHELL_PROMPT_RE.findall(text)
        if len(prompt_lines) < 3:
            return match.group(0)

        extra = ''
        if 'class=' not in attrs:
            extra += ' class="epub2pdf-code-block"'
        if 'style=' not in attrs:
            extra += f' style="{CODE_BLOCK_STYLE}"'

        start_tag = match.group(0).split('>', 1)[0] + extra + '>'
        return f"{start_tag}{match.group(3)}</{tag}>"

    return re.sub(
        r'<(p|div|li|td|pre|section)\b([^>]*)>(.*?)</\1>',
        _wrap,
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )


def _wrap_indented_blocks(html: str, verbose: bool = False) -> str:
    """Wrap block elements whose inner text contains 5+ code-like indented lines."""
    def _wrap(match: re.Match) -> str:
        tag = match.group(1)
        attrs = match.group(2) or ''
        inner_start = match.start(3)
        inner_end = match.end(3)

        if 'epub2pdf-code-block' in html[max(0, inner_start - 200):inner_start]:
            return match.group(0)

        text = _strip_tags(html[inner_start:inner_end])
        lines = text.split('\n')
        indented = 0
        for ln in lines:
            s = ln.strip()
            if not s:
                continue
            if s.startswith(('<', '/*', '*', '--')):
                continue
            if re.match(r'^ {4,}', ln) or re.match(r'^\t+', ln):
                indented += 1

        if indented < 5:
            return match.group(0)

        extra = ''
        if 'class=' not in attrs:
            extra += ' class="epub2pdf-code-block"'
        if 'style=' not in attrs:
            extra += f' style="{CODE_BLOCK_STYLE}"'

        start_tag = match.group(0).split('>', 1)[0] + extra + '>'
        return f"{start_tag}{match.group(3)}</{tag}>"

    return re.sub(
        r'<(p|div|li|td|pre|section)\b([^>]*)>(.*?)</\1>',
        _wrap,
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )


def _strip_tags(text: str) -> str:
    return re.sub(r'<[^>]+>', '\n', text)


# ---------------------------------------------------------------------------
# Batch recovery
# ---------------------------------------------------------------------------

def recover_code_blocks_in_epub(extract_dir: str, verbose: bool = False) -> int:
    """
    Scan all HTML/XHTML files in an extracted EPUB and wrap code blocks.

    Returns the number of files that were modified.
    """
    modified = 0
    scanned = 0

    for root, _dirs, files in os.walk(extract_dir):
        for fname in files:
            if not fname.endswith(('.html', '.xhtml', '.htm')):
                continue
            fpath = os.path.join(root, fname)
            scanned += 1

            try:
                if recover_code_blocks_in_file(fpath, verbose=verbose):
                    modified += 1
            except Exception as e:
                if verbose:
                    print(f"    [WARN] Error scanning {fname} for code: {e}")

    if verbose and scanned > 0:
        print(f"    Scanned {scanned} files for code blocks, wrapped in {modified}")

    return modified


# ---------------------------------------------------------------------------
# CSS injection for code blocks
# ---------------------------------------------------------------------------

CODE_RECOVERY_CSS = """
/* ebook2pdf: Recovered code block formatting */
div.epub2pdf-code-block {
    background-color: #f4f4f4 !important;
    border: 1px solid #d0d0d0 !important;
    border-radius: 3px !important;
    padding: 8pt 10pt !important;
    margin: 0.5em 0 !important;
    font-family: monospace, "Courier New", Courier !important;
    font-size: 0.85em !important;
    white-space: pre !important;
    overflow-x: auto !important;
    line-height: 1.3 !important;
    page-break-inside: avoid !important;
}
pre.epub2pdf-code-block {
    background-color: #f4f4f4 !important;
    border: 1px solid #d0d0d0 !important;
    border-radius: 3px !important;
    padding: 8pt 10pt !important;
    margin: 0.5em 0 !important;
    font-family: monospace, "Courier New", Courier !important;
    font-size: 0.85em !important;
    white-space: pre-wrap !important;
    overflow-x: auto !important;
    line-height: 1.3 !important;
    page-break-inside: avoid !important;
}
code {
    background-color: #f4f4f4 !important;
    border: 1px solid #e0e0e0 !important;
    border-radius: 2px !important;
    padding: 1pt 3pt !important;
    font-family: monospace, "Courier New", Courier !important;
    font-size: 0.85em !important;
}
"""
