"""
Patch mode: user-assisted overrides for problematic tables, code blocks, and figures.

Reads an auxiliary YAML file describing replacement blocks, locates them in an
intermediate EPUB via fuzzy search, injects the replacements, and copies any
referenced image assets into a reserved EPUB namespace.

YAML schema
-----------
patch_file: optional human label / path hint
files:
  - filename: <base name of the ebook file, with or without extension>
    assets_dir: <optional image directory, relative to patch YAML or absolute>
    blocks:
      - type: table | code-block | figure
        prologue: |
          <text immediately before the target block>
        epilogue: |
          <text immediately after the target block>
        replacement: |
          <Markdown content>

Image Markdown references in `replacement` may use bare filenames or paths.
They are resolved against `assets_dir` and copied into the EPUB under
`OEBPS/Images/__patches__/`, then rewritten to `src="__patches__/<filename>"`
in the injected XHTML.
"""

from __future__ import annotations

import copy
import os
import re
import shutil
import unicodedata
import zipfile
from pathlib import Path
from typing import Any

import rapidfuzz.fuzz as fuzz
import yaml


# ---------------------------------------------------------------------------
# Schema / validation
# ---------------------------------------------------------------------------

ALLOWED_BLOCK_TYPES = {"table", "code-block", "figure"}
DEFAULT_ASSETS_DIR = "assets"
EPUB_ASSET_PREFIX = "__patches__"


class PatchError(Exception):
    """Raised when patch processing fails."""


def _normalize_filename(name: str) -> str:
    """Normalize an ebook filename/identifier for loose matching."""
    base = os.path.splitext(name)[0]
    base = unicodedata.normalize("NFKD", base).lower()
    base = re.sub(r"[^a-z0-9]+", "", base)
    return base


def _load_yaml(path: str) -> dict[str, Any]:
    """Load and shallow-validate a patch YAML file."""
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise PatchError("Patch YAML must be a mapping at the top level.")
    if "files" not in data or not isinstance(data.get("files"), list):
        raise PatchError("Patch YAML must contain a 'files' list.")

    for file_entry in data.get("files", []):
        if not isinstance(file_entry, dict):
            raise PatchError("Each entry in 'files' must be a mapping.")
        filename = file_entry.get("filename")
        if not filename or not isinstance(filename, str):
            raise PatchError("Each file entry must have a string 'filename'.")

        blocks = file_entry.get("blocks")
        if not isinstance(blocks, list) or not blocks:
            raise PatchError(f"File '{filename}' must have a non-empty 'blocks' list.")

        for block in blocks:
            if not isinstance(block, dict):
                raise PatchError(f"File '{filename}': each block must be a mapping.")
            block_type = block.get("type")
            if block_type not in ALLOWED_BLOCK_TYPES:
                raise PatchError(
                    f"File '{filename}': block type must be one of {sorted(ALLOWED_BLOCK_TYPES)}, got '{block_type}'."
                )
            for key in ("prologue", "epilogue", "replacement"):
                if key not in block or not isinstance(block[key], str):
                    raise PatchError(
                        f"File '{filename}': block of type '{block_type}' missing string '{key}'."
                    )

    return data


def _resolve_assets_dir(patch_file: str, file_entry: dict[str, Any]) -> Path:
    """Determine the assets directory for a file entry."""
    if file_entry.get("assets_dir"):
        return Path(file_entry["assets_dir"])
    data_dir = Path(patch_file).parent
    if (data_dir / DEFAULT_ASSETS_DIR).is_dir():
        return data_dir / DEFAULT_ASSETS_DIR
    return data_dir


# ---------------------------------------------------------------------------
# Markdown rendering helpers
# ---------------------------------------------------------------------------

def _collect_image_refs(text: str) -> list[str]:
    """Return image references found in Markdown or HTML img tags."""
    refs: list[str] = []
    for m in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", text):
        refs.append(m.group(1))
    for m in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', text):
        refs.append(m.group(1))
    return refs


def _render_replacement(replacement: str, patch_assets_dir: Path, epub_asset_prefix: str = EPUB_ASSET_PREFIX) -> str:
    """
    Convert Markdown replacement into XHTML suitable for EPUB injection.

    Image references are resolved against `patch_assets_dir` and rewritten to
    EPUB-internal paths under `epub_asset_prefix/`.
    """
    try:
        import markdown

        html = markdown.markdown(
            replacement,
            extensions=["fenced_code", "tables", "codehilite"],
            extension_configs={
                "codehilite": {
                    "linenums": False,
                    "css_class": "ebook2pdf-code-block",
                }
            },
        )
    except Exception:
        html = (
            "<pre>"
            + replacement.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            + "</pre>"
        )

    for ref in _collect_image_refs(replacement):
        src = Path(ref)
        if src.is_absolute() or src.parent != Path("."):
            candidate = src
        else:
            candidate = patch_assets_dir / src.name
        if candidate.exists():
            epub_dest_rel = f"{epub_asset_prefix}/{candidate.name}"
            html = re.sub(re.escape(ref), epub_dest_rel, html)

    return f'<div class="ebook2pdf-patch-block">{html}</div>'


# ---------------------------------------------------------------------------
# EPUB inspection helpers
# ---------------------------------------------------------------------------

def _iter_xhtml_files(extract_dir: str) -> list[dict[str, Any]]:
    """Collect extracted EPUB XHTML/HTML files with raw and normalized text."""
    results: list[dict[str, Any]] = []
    for root, _dirs, files in os.walk(extract_dir):
        for fname in files:
            if not fname.lower().endswith((".html", ".xhtml", ".htm")):
                continue
            fpath = os.path.join(root, fname)
            try:
                raw = Path(fpath).read_text(encoding="utf-8", errors="ignore")
                text = re.sub(r"<[^>]+>", " ", raw)
                text = re.sub(r"\s+", " ", text).strip()
                normalized = unicodedata.normalize("NFKD", text).lower()
                results.append(
                    {
                        "path": fpath,
                        "raw": raw,
                        "normalized": normalized,
                        "original_text": text,
                    }
                )
            except Exception:
                continue
    return results


# ---------------------------------------------------------------------------
# Region matching helpers
# ---------------------------------------------------------------------------

def _match_by_context(file_entries: list[dict[str, Any]], prologue: str, epilogue: str, threshold: int = 75) -> dict[str, Any] | None:
    """Pick the best-matching file for a block using surrounding context."""
    prologue_norm = unicodedata.normalize("NFKD", prologue).lower()
    epilogue_norm = unicodedata.normalize("NFKD", epilogue).lower()
    if not prologue_norm and not epilogue_norm:
        return None

    scored: list[tuple[float, dict[str, Any]]] = []
    for entry in file_entries:
        text = entry["normalized"]
        score = 0.0
        if prologue_norm:
            score = max(score, fuzz.partial_ratio(prologue_norm, text))
        if epilogue_norm:
            score = max(score, fuzz.partial_ratio(epilogue_norm, text))
        if score > 0:
            scored.append((score, entry))

    if not scored:
        return None

    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best_entry = scored[0]
    return best_entry if best_score >= threshold else None


def _inject_into_raw(raw: str, replacement_html: str, prologue: str, epilogue: str) -> str | None:
    """Replace the region bracketed by prologue/epilogue with replacement HTML."""
    pattern = re.compile(
        rf"({re.escape(prologue)})([\s\S]*?)({re.escape(epilogue)})",
        re.IGNORECASE,
    )
    m = pattern.search(raw)
    if not m:
        return None
    return m.group(1) + "\n" + replacement_html + "\n" + m.group(3)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_patch_variants(patch_files: list[str]) -> list[str]:
    """Return variant in/out paths implied by the patch order."""
    return list(patch_files)


def validate_patch_spec(patch_spec: list[str]) -> None:
    """Validate patch spec without applying; raise PatchError on bad input."""
    if not isinstance(patch_spec, list):
        raise PatchError("Patch spec must be a list of patch YAML paths.")
    for p in patch_spec:
        if not p or not isinstance(p, str):
            raise PatchError(f"Invalid patch path: {p!r}")


def merge_patch_data(patch_data_list: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Merge multiple patch YAML payloads into one.

    Only the top-level `files` list is merged. Duplicate `filename` + block
    `type` combinations are deduplicated; later entries win.
    """
    merged: dict[str, Any] = {"files": []}
    seen: set[tuple[str, str]] = set()
    for data in patch_data_list:
        for file_entry in data.get("files", []):
            for block in file_entry.get("blocks", []):
                key = (str(file_entry.get("filename", "")), str(block.get("type", "")))
                if key in seen:
                    continue
                seen.add(key)
                merged["files"].append(copy.deepcopy(file_entry))
                break
    return merged


def apply_patch(
    extract_dir: str,
    patch_spec_or_path: list[str] | str,
    *,
    verbose: bool = False,
) -> dict[str, Any]:
    """
    Apply patch YAML(s) to an extracted EPUB directory.

    `patch_spec_or_path` may be a single YAML path or a list of YAML paths.
    Multiple patch files are merged in order; duplicates are deduplicated.

    Returns a summary dict:
      { applied, skipped, failed, assets_copied, files_seen }
    """
    if isinstance(patch_spec_or_path, str):
        patch_spec = [patch_spec_or_path]
    else:
        patch_spec = list(patch_spec_or_path)

    validate_patch_spec(patch_spec)
    if not patch_spec:
        return {"applied": 0, "skipped": 0, "failed": 0, "assets_copied": [], "files_seen": 0}

    merged_data: dict[str, Any] | None = None
    patch_files: list[str] = []
    for path in patch_spec:
        abs_path = os.path.abspath(path)
        patch_files.append(abs_path)
        data = _load_yaml(abs_path)
        if merged_data is None:
            merged_data = data
        else:
            merged_data = merge_patch_data([merged_data, data])

    if merged_data is None:
        return {"applied": 0, "skipped": 0, "failed": 0, "assets_copied": [], "files_seen": 0}

    file_entries = _iter_xhtml_files(extract_dir)
    if not file_entries:
        raise PatchError("No XHTML/HTML files found in extracted EPUB.")

    summary = {"applied": 0, "skipped": 0, "failed": 0, "assets_copied": [], "files_seen": 0}

    for file_entry in merged_data.get("files", []):
        filename = file_entry["filename"]
        base_name = _normalize_filename(filename)

        matched_entries = [
            entry
            for entry in file_entries
            if _normalize_filename(os.path.basename(entry["path"])) == base_name
        ]
        if not matched_entries:
            if verbose:
                print(f"  [patch] Skipping '{filename}': no matching file in EPUB.")
            summary["skipped"] += 1
            continue

        patch_assets_dir = _resolve_assets_dir(patch_files[0], file_entry)
        if not patch_assets_dir.exists():
            patch_assets_dir = Path(patch_files[0]).parent

        blocks = file_entry.get("blocks", [])
        for block in blocks:
            block_type = block["type"]
            prologue = block["prologue"]
            epilogue = block["epilogue"]
            replacement_md = block["replacement"]

            summary["files_seen"] += 1

            match = _match_by_context(matched_entries, prologue, epilogue)
            if match is None:
                if verbose:
                    print(f"  [patch] Block in '{filename}' ({block_type}): no matching context found.")
                summary["skipped"] += 1
                continue

            target_path = match["path"]
            try:
                target_raw = Path(target_path).read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                if verbose:
                    print(f"  [patch] Cannot read '{target_path}': {e}")
                summary["failed"] += 1
                continue

            replacement_html = _render_replacement(replacement_md, patch_assets_dir)
            updated = _inject_into_raw(target_raw, replacement_html, prologue, epilogue)
            if updated is None:
                if verbose:
                    print(f"  [patch] Block in '{filename}' ({block_type}): context not found in '{target_path}'.")
                summary["skipped"] += 1
                continue

            tmp_path = target_path + ".ebook2pdf-patch-tmp"
            try:
                Path(tmp_path).write_text(updated, encoding="utf-8")
                os.replace(tmp_path, target_path)
            except Exception as e:
                if verbose:
                    print(f"  [patch] Failed to write '{target_path}': {e}")
                summary["failed"] += 1
                continue

            summary["applied"] += 1
            if verbose:
                print(f"  [patch] Applied {block_type} patch in '{target_path}'.")

    assets_copied = _copy_patch_assets(extract_dir, merged_data, patch_files[0])
    summary["assets_copied"] = assets_copied
    return summary


def _copy_patch_assets(extract_dir: str, patch_data: dict[str, Any], patch_file: str) -> list[str]:
    """Copy referenced image files into EPUB Images/__patches__/."""
    assets_dir = Path(patch_file).parent
    epub_images_dir = Path(extract_dir) / "OEBPS" / "Images" / EPUB_ASSET_PREFIX
    epub_images_dir.mkdir(parents=True, exist_ok=True)

    seen: set[str] = set()
    copied: list[str] = []
    for file_entry in patch_data.get("files", []):
        for block in file_entry.get("blocks", []):
            for ref in _collect_image_refs(block.get("replacement", "")):
                src = Path(ref)
                if src.is_absolute() or src.parent != Path("."):
                    candidate = src
                else:
                    candidate = assets_dir / src.name
                if candidate.exists() and candidate.name not in seen:
                    seen.add(candidate.name)
                    dest = epub_images_dir / candidate.name
                    try:
                        shutil.copy2(candidate, dest)
                        copied.append(str(dest.relative_to(extract_dir)))
                    except Exception:
                        continue
    return copied
