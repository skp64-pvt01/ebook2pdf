"""
Book type detection heuristics.

Analyses extracted EPUB content to identify publisher/book type,
then returns appropriate CSS selectors for targeting content.
"""

import os
import re
from pathlib import Path


def detect_book_type(extract_dir: str) -> dict:
    """
    Analyse an extracted EPUB directory and return detection info.
    
    Returns a dict with keys:
      - publisher: str  (e.g. 'manning', 'wiley', 'rheinwerk', 'calibre', 'generic')
      - css_selectors: dict of common area selectors
      - has_math_images: bool
      - toc_class: str or None
    """
    info = {
        "publisher": "generic",
        "css_selectors": {},
        "has_math_images": False,
        "toc_class": None,
    }

    # Walk the extracted tree looking for clues
    xhtml_files = []
    css_files = []
    for root, _dirs, files in os.walk(extract_dir):
        for f in files:
            path = os.path.join(root, f)
            if f.endswith((".xhtml", ".html")):
                xhtml_files.append(path)
            elif f.endswith(".css"):
                css_files.append(path)

    if not xhtml_files:
        return info

    # Sample first few content files
    content_sample = ""
    for f in xhtml_files[:5]:
        try:
            with open(f, "r", encoding="utf-8", errors="ignore") as fh:
                content_sample += fh.read(5000)
        except Exception:
            pass

    css_sample = ""
    for f in css_files[:5]:
        try:
            with open(f, "r", encoding="utf-8", errors="ignore") as fh:
                css_sample += fh.read(3000)
        except Exception:
            pass

    # --- Publisher detection ---
    if 'id="sbo-rt-content"' in content_sample or '#sbo-rt-content' in css_sample:
        info["publisher"] = "manning"
        info["css_selectors"] = {
            "content_wrapper": "#sbo-rt-content",
            "paragraph": "#sbo-rt-content p, #sbo-rt-content .readable-text p",
            "figure": ".browsable-container.figure-container",
            "figure_caption": ".figure-container-h5",
            "table": ".browsable-container table",
            "heading1": ".readable-text-h1",
            "heading2": ".readable-text-h2",
            "heading3": ".readable-text-h3",
        }
        info["toc_class"] = "nav[epub|type='toc']"

    elif 'class="ls"' in content_sample or 'body.ls_serif' in css_sample:
        info["publisher"] = "wiley"
        info["css_selectors"] = {
            "content_wrapper": "body",
            "paragraph": "body p, p.ls, .ls p",
            "figure": "figure.ls, figure",
            "figure_caption": "figcaption, span.figureLabel",
            "table": "table.bor2, table.tab_bor, table",
            "heading1": "h1.ls",
            "heading2": "h2.ls",
            "heading3": "h3.ls",
        }
        info["toc_class"] = "nav.tocList, nav[epub|type='toc']"

        # Detect math images
        if any("dequ" in f for f in xhtml_files) or "dequ" in content_sample:
            info["has_math_images"] = True

    elif 'p.standard' in css_sample or 'table.standardtable' in css_sample:
        info["publisher"] = "rheinwerk"
        info["css_selectors"] = {
            "content_wrapper": "body",
            "paragraph": "p.standard",
            "figure": "div.imagebox",
            "figure_caption": "p.caption",
            "table": "table.standardtable",
            "heading1": "h1.t1, h1.content1",
            "heading2": "h2.t2, h2.content2",
            "heading3": "h3.t3, h3.content3",
        }
        info["toc_class"] = ".content1, .content2, .content3"

    elif '.block_' in css_sample or 'class="block_' in content_sample:
        info["publisher"] = "calibre"
        info["css_selectors"] = {
            "content_wrapper": "body",
            "paragraph": ".block_12, .block_26, .block_25, .block_27",
            "figure": "img",
            "figure_caption": None,
            "table": "table",
            "heading1": ".block_23, .block_",
            "heading2": ".block_25",
            "heading3": None,
        }

    elif '.class_s' in css_sample or '.class_s' in content_sample:
        info["publisher"] = "google-docs"
        info["css_selectors"] = {
            "content_wrapper": "body",
            "paragraph": ".class_s3Z-0, .class_s14-0, .class_s12-0, p",
            "figure": "img",
            "figure_caption": None,
            "table": "table",
            "heading1": ".heading_s51, .heading_s55",
            "heading2": ".heading_s59",
            "heading3": None,
        }

    # Final check for math images in any book
    if not info["has_math_images"]:
        for f in xhtml_files[:20]:
            try:
                with open(f, "r", encoding="utf-8", errors="ignore") as fh:
                    c = fh.read(2000)
                    if 'src="images/' in c and 'equation' in c.lower():
                        info["has_math_images"] = True
                        break
                    if 'alt="equation' in c.lower() or 'img[src*="dequ"' in c:
                        info["has_math_images"] = True
                        break
            except Exception:
                pass

    return info


def publisher_label(publisher: str) -> str:
    """Return a human-readable label for a detected publisher."""
    labels = {
        "manning": "Manning Publications",
        "wiley": "Wiley",
        "rheinwerk": "Rheinwerk Publishing",
        "calibre": "Calibre-generated",
        "google-docs": "Google Docs export",
        "generic": "Generic / Unknown",
    }
    return labels.get(publisher, publisher)
