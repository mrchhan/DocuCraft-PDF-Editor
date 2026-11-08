"""Font selection helpers for text inserted into PDFs."""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable

import pymupdf

_UNICODE_CANDIDATES = [
    r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\tahoma.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf", "/Library/Fonts/Arial Unicode.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
]

BASE14 = {
    ("sans", False, False): "helv", ("sans", True, False): "hebo",
    ("sans", False, True): "heit", ("sans", True, True): "hebi",
    ("serif", False, False): "tiro", ("serif", True, False): "tibo",
    ("serif", False, True): "tiit", ("serif", True, True): "tibi",
    ("mono", False, False): "cour", ("mono", True, False): "cobo",
    ("mono", False, True): "coit", ("mono", True, True): "cobi",
}


def is_latin1(text: str) -> bool:
    try:
        text.encode("latin-1")
        return True
    except UnicodeEncodeError:
        return False


@lru_cache(maxsize=1)
def unicode_font_file() -> str | None:
    return next((c for c in _UNICODE_CANDIDATES if os.path.exists(c)), None)


# ----------------------------------------------------------------------------------- matching real fonts
_SANS_HINTS = ("inter", "roboto", "opensans", "lato", "montserrat", "poppins", "canva", "helvet", "arial", "calibri", "carlito",
               "segoe", "verdana", "tahoma", "notosans", "sourcesans", "nunito", "raleway", "ubuntu", "dejavusans", "liberationsans",
               "worksans", "dmsans", "manrope", "firasans", "cabin", "oswald", "sans")
_SERIF_HINTS = ("times", "georgia", "garamond", "playfair", "merriweather", "lora", "cambria", "caladea", "palatino", "minion",
                "baskerville", "bookman", "liberationserif", "dejavuserif", "notoserif", "sourceserif", "serif")
_MONO_HINTS = ("courier", "mono", "consolas", "typewriter", "menlo", "inconsolata")
_STYLE_TOKENS = ("extrabold", "semibold", "demibold", "extralight", "bolditalic", "bold", "italic", "oblique", "regular", "medium",
                 "light", "thin", "black", "heavy", "book", "roman")


def parse_font_name(name: str) -> tuple[str, str, bool, bool]:
    """'ABCDEF+Inter_18pt-SemiBold' -> (family 'inter', style 'semibold', bold, italic)."""
    n = re.sub(r"^[A-Z]{6}\+", "", name or "")
    low = n.lower()
    parts = re.split(r"[-,]", low, maxsplit=1)
    fam = parts[0]
    style = parts[1] if len(parts) > 1 else ""
    fam = re.sub(r"\d+pt", "", fam)
    for tok in _STYLE_TOKENS:                                     # 'arialbold' -> family 'arial'
        if fam.endswith(tok) and len(fam) > len(tok) + 2:
            style = style or tok
            fam = fam[: -len(tok)]
    fam = re.sub(r"[^a-z0-9]", "", fam)
    bold = any(k in low for k in ("bold", "black", "heavy"))
    italic = any(k in low for k in ("italic", "oblique"))
    return fam, re.sub(r"[^a-z]", "", style), bold, italic


def classify_font(name: str, flags: int) -> tuple[str, bool, bool]:  
    fam, _style, bold_n, italic_n = parse_font_name(name)
    if any(h in fam for h in _MONO_HINTS):
        kind = "mono"
    elif any(h in fam for h in _SERIF_HINTS) and not fam.endswith("sans"):
        kind = "serif"
    elif any(h in fam for h in _SANS_HINTS):
        kind = "sans"
    else:                                                           # unknown family: trust the flags
        kind = "mono" if flags & 8 else "serif" if flags & 4 else "sans"
    return kind, bold_n or bool(flags & 16), italic_n or bool(flags & 2)


def _font_dirs() -> list[Path]:
    dirs: list[Path] = []
    if getattr(sys, "frozen", False):
        dirs += [Path(getattr(sys, "_MEIPASS", "")) / "assets" / "fonts", Path(sys.executable).parent / "assets" / "fonts"]
    dirs.append(Path(__file__).resolve().parent.parent / "assets" / "fonts")
    if sys.platform.startswith("win"):
        dirs += [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
                 Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts"]
    elif sys.platform == "darwin":
        dirs += [Path("/Library/Fonts"), Path("/System/Library/Fonts"), Path.home() / "Library" / "Fonts"]
    else:
        dirs += [Path("/usr/share/fonts"), Path.home() / ".fonts", Path.home() / ".local" / "share" / "fonts"]
    return [d for d in dirs if d.is_dir()]


@lru_cache(maxsize=1)
def font_index() -> dict[str, list[tuple[Path, str, bool, bool]]]:
    """family -> [(file, style, bold, italic)] for .ttf/.otf files found in bundled and system font folders."""
    idx: dict[str, list[tuple[Path, str, bool, bool]]] = {}
    seen: set[str] = set()
    for base in _font_dirs():
        for root, _dirs, files in os.walk(base):
            for f in files:
                if not f.lower().endswith((".ttf", ".otf")) or "variable" in f.lower() or "[" in f:
                    continue
                path = Path(root) / f
                if str(path) in seen:
                    continue
                seen.add(str(path))
                fam, style, bold, italic = parse_font_name(path.stem)
                if fam:
                    idx.setdefault(fam, []).append((path, style, bold, italic))
    return idx


_ALIASES = {"arial": "liberationsans", "helvetica": "liberationsans", "helveticaneue": "liberationsans", "arialmt": "liberationsans",
            "timesnewroman": "liberationserif", "times": "liberationserif", "timesnewromanps": "liberationserif",
            "couriernew": "liberationmono", "courier": "liberationmono", "calibri": "carlito"}   # metric-compatible open fonts


def find_font_file(font_name: str, bold: bool, italic: bool) -> Path | None:
    """Best installed/bundled file for the same font family, or None. Never returns a different family."""
    fam, style, _b, _i = parse_font_name(font_name)
    cands = font_index().get(fam) or font_index().get(_ALIASES.get(fam, ""))   # exact family first, then open look-alike
    if not cands:
        return None

    def score(c):
        _path, st, b, i = c
        s = 10 * (b == bold) + 10 * (i == italic)
        if style and style in _STYLE_TOKENS and style == st:
            s += 6
        if not bold and st in ("regular", "", "roman", "book"):
            s += 3
        if bold and st == "bold":
            s += 3
        return s
    return max(cands, key=score)[0]


@dataclass
class ResolvedFont:
    kwargs: dict                                  # keyword arguments for Page.insert_text / insert_textbox
    measure: Callable[[str, float], float]        # text width in points
    faithful: bool                                # True = same family as the original text
    label: str
    register: Callable = field(default=lambda page: None)   # (re)adds the font to a page - redaction drops unused fonts


_GLYPH_OK_CACHE: dict = {}


def _has_all(font: "pymupdf.Font", text: str) -> bool:
    return all(c.isspace() or font.has_glyph(ord(c)) for c in text)


def clear_glyph_cache() -> None:
    _GLYPH_OK_CACHE.clear()


def _chars_used_with(page, font_name: str) -> set[str]:
    key = (id(page.parent), page.number, font_name, page.parent.page_count)
    got = _GLYPH_OK_CACHE.get(key)
    if got is None:
        got = set()
        for block in page.get_text("dict").get("blocks", []):
            for line in block.get("lines", []):
                for sp in line["spans"]:
                    if sp["font"] == font_name:
                        got.update(c for c in sp["text"] if not c.isspace())
        _GLYPH_OK_CACHE.clear() if len(_GLYPH_OK_CACHE) > 64 else None
        _GLYPH_OK_CACHE[key] = got
    return got


def resolve_font(doc, page, original_name: str, flags: int, text: str) -> ResolvedFont:
    """Pick the best font for `text` so it looks like text set in `original_name`.

    1. the document's own embedded font, if it contains every glyph needed;
    2. an installed / bundled font of the same family;
    3. a built-in font of the same kind (sans / serif / mono), bold and italic preserved.
    """
    fam, _style, _b, _i = parse_font_name(original_name)
    kind, bold, italic = classify_font(original_name, flags)
    # 1. embedded font
    try:
        for entry in page.get_fonts(full=False):
            xref, basefont = entry[0], entry[3]
            if xref > 0 and basefont.split("+")[-1] == original_name.split("+")[-1]:
                _n, _ext, _t, buf = doc.extract_font(xref)
                if buf and _chars_used_with(page, original_name) >= {c for c in text if not c.isspace()}:
                    # embedded fonts are usually subsets: only characters the page already uses are certain to exist
                    f = pymupdf.Font(fontbuffer=buf)
                    if _has_all(f, text):
                        name = f"dce{xref}"
                        reg = lambda pg, n=name, b=buf: pg.insert_font(fontname=n, fontbuffer=b)
                        reg(page)
                        return ResolvedFont({"fontname": name}, lambda t, sz, f=f: f.text_length(t, fontsize=sz), True,
                                            f"{original_name.split('+')[-1]} (embedded)", reg)
    except Exception:
        pass
    # 2. same family on this computer / bundled
    path = find_font_file(original_name, bold, italic)
    if path is not None:
        try:
            f = pymupdf.Font(fontfile=str(path))
            if _has_all(f, text):
                name = "dcf" + re.sub(r"[^A-Za-z0-9]", "", path.stem)[:20]
                reg = lambda pg, n=name, fp=str(path): pg.insert_font(fontname=n, fontfile=fp)
                reg(page)
                return ResolvedFont({"fontname": name}, lambda t, sz, f=f: f.text_length(t, fontsize=sz), True, path.stem, reg)
        except Exception:
            pass
    # 3. built-in / unicode fallback
    if not is_latin1(text) and unicode_font_file():
        f = pymupdf.Font(fontfile=unicode_font_file())
        reg = lambda pg, fp=unicode_font_file(): pg.insert_font(fontname="dcuni", fontfile=fp)
        reg(page)
        return ResolvedFont({"fontname": "dcuni"}, lambda t, sz, f=f: f.text_length(t, fontsize=sz), False, "Unicode fallback", reg)
    base = BASE14[(kind, bold, italic)]
    return ResolvedFont({"fontname": base}, lambda t, sz, b=base: pymupdf.get_text_length(t, fontname=b, fontsize=sz), False,
                        f"{kind} built-in ({base})")
