"""Compose the portfolio video and share images from frames captured by make_portfolio_media.py.

    python scripts/compose_portfolio.py <frames_dir> [out_dir]

Needs ffmpeg on PATH. Output: docucraft-demo.mp4, docucraft-demo-preview.gif, linkedin-card.png, github-social-preview.png,
feature-overview.png, before-after-replace.png
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONT_B, FONT_R = ROOT / "assets" / "fonts" / "Inter-Bold.otf", ROOT / "assets" / "fonts" / "Inter-Regular.otf"
LOGO = ROOT / "assets" / "images" / "logo.png"
W, H, FPS = 1920, 1080, 30
BG1, BG2, WHITE, MUTED, ACCENT = (11, 18, 32), (23, 37, 84), (255, 255, 255), (148, 163, 184), (96, 165, 250)


def font(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_B if bold else FONT_R), size)


def gradient(w: int, h: int) -> Image.Image:
    base = Image.new("RGB", (w, h), BG1)
    glow = Image.new("RGB", (w, h), BG2)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).ellipse((w * 0.35, -h * 0.6, w * 1.3, h * 0.7), fill=170)
    return Image.composite(glow, base, mask.filter(ImageFilter.GaussianBlur(w // 7)))


def rounded(im: Image.Image, r: int) -> Image.Image:
    im = im.convert("RGBA")
    m = Image.new("L", im.size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, im.width - 1, im.height - 1), r, fill=255)
    im.putalpha(m)
    return im


def shadow_paste(canvas: Image.Image, im: Image.Image, xy: tuple[int, int], blur: int = 28, offset: int = 14) -> None:
    sh = Image.new("RGBA", (im.width + 2 * blur, im.height + 2 * blur), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((blur, blur, blur + im.width, blur + im.height), 16, fill=(0, 0, 0, 150))
    sh = sh.filter(ImageFilter.GaussianBlur(blur // 2))
    canvas.paste(sh, (xy[0] - blur, xy[1] - blur + offset), sh)
    canvas.paste(im, xy, im)


def fit(im: Image.Image, w: int, h: int) -> Image.Image:
    s = min(w / im.width, h / im.height)
    return im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.LANCZOS)


def wrap(draw, text: str, fnt, width: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        t = (cur + " " + word).strip()
        if draw.textlength(t, font=fnt) <= width:
            cur = t
        else:
            lines.append(cur)
            cur = word
    return lines + [cur] if cur else lines


def header(canvas: Image.Image, title: str, sub: str) -> int:
    d = ImageDraw.Draw(canvas)
    d.text((96, 56), title, font=font(True, 58), fill=WHITE)
    d.text((98, 132), sub, font=font(False, 29), fill=MUTED)
    logo = Image.open(LOGO).convert("RGBA").resize((52, 52), Image.LANCZOS)
    canvas.paste(logo, (W - 96 - 52, 60), logo)
    return 200


def scene_shot(frame: Path, title: str, sub: str, crop: tuple | None = None) -> Image.Image:
    c = gradient(W, H)
    top = header(c, title, sub)
    im = Image.open(frame).convert("RGB")
    if crop:
        im = im.crop(crop)
    im = rounded(fit(im, W - 2 * 100, H - top - 50), 14)
    shadow_paste(c, im, ((W - im.width) // 2, top + (H - top - 40 - im.height) // 2))
    return c


def scene_compare(before: Path, after: Path) -> Image.Image:
    c = gradient(W, H)
    header(c, "Replace text — same font, same size", "Words are swapped in place and the rest of the line re-flows. Labelled honestly: not native editing.")
    d = ImageDraw.Draw(c)
    for k, (lab, path) in enumerate((("BEFORE", before), ("AFTER", after))):
        y = 250 + k * 400
        d.text((120, y), lab, font=font(True, 30), fill=ACCENT if k else MUTED)
        im = Image.open(path).convert("RGB")
        im = rounded(im.resize((1680, int(im.height * 1680 / im.width)), Image.LANCZOS), 14)
        shadow_paste(c, im, (120, y + 52), blur=18, offset=8)
    return c


def scene_title(title: str, sub: str, tag: str) -> Image.Image:
    c = gradient(W, H)
    logo = Image.open(LOGO).convert("RGBA").resize((176, 176), Image.LANCZOS)
    c.paste(logo, ((W - 176) // 2, 250), logo)
    d = ImageDraw.Draw(c)
    for text, fnt, y, col in ((title, font(True, 104), 470, WHITE), (sub, font(True, 46), 610, ACCENT), (tag, font(False, 34), 690, MUTED)):
        d.text(((W - d.textlength(text, font=fnt)) / 2, y), text, font=fnt, fill=col)
    return c


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def encode_scene(png: Path, secs: float, dst: Path) -> None:
    tmp = dst.with_name(dst.stem + ".tmp.mp4")                  # renamed only when ffmpeg succeeds
    vf = (f"format=yuv420p,loop=loop=-1:size=1,trim=duration={secs},setpts=PTS-STARTPTS,"
          f"fade=t=in:st=0:d=0.4,fade=t=out:st={secs - 0.4}:d=0.4")
    run(["ffmpeg", "-y", "-framerate", str(FPS), "-i", str(png), "-vf", vf, "-r", str(FPS), "-c:v", "libx264", "-crf", "18",
         "-preset", "veryfast", "-pix_fmt", "yuv420p", "-an", str(tmp)])
    tmp.replace(dst)


def main() -> None:
    frames = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "marketing" / "media"
    out.mkdir(parents=True, exist_ok=True)
    f = lambda n: frames / n                                      # noqa: E731
    work = Path(tempfile.mkdtemp(prefix="dc_video_"))

    rep = Image.open(f("09-conversion-report.png")).convert("RGB")
    rep.crop((0, 190, rep.width, 296)).save(work / "report_crop.png")        # the honest "limitations" section

    scenes: list[tuple[Image.Image, float]] = [
        (scene_title("DocuCraft", "Your Documents. Your Control.", "A free, offline PDF reader, editor and converter"), 4.5),
        (scene_shot(f("01-home.png"), "Everything stays on your computer", "No accounts. No uploads. No tracking."), 4.0),
        (scene_shot(f("02-reader-bookmarks.png"), "Read comfortably", "Tabs, thumbnails, bookmarks, zoom, page layouts, full screen and print"), 4.5),
        (scene_shot(f("03-search.png"), "Find anything fast", "Search highlights every match across the whole document"), 4.0),
        (scene_shot(f("04-annotate.png"), "Mark up and comment", "Highlights, notes, shapes, arrows, text boxes and signatures — with undo and redo"), 5.0),
        (scene_compare(f("replace-before.png"), f("replace-after.png")), 6.5),
        (scene_shot(f("05-replace-dialog.png"), "Preview before you apply", "See the result first — nothing changes until you confirm, and you can undo"), 4.5),
        (scene_shot(f("07-redacted.png"), "True redaction", "Content is removed from the file and verified — not just covered by a black box"), 5.0),
        (scene_shot(f("08-convert.png"), "PDF to Word", "Layout or editable mode, page ranges, OCR for scans, batch conversion"), 4.5),
        (scene_shot(work / "report_crop.png", "Honest conversion reports", "You see what was preserved — and what may need a second look"), 4.5),
        (scene_shot(f("10-organize.png"), "Merge, split, compress, convert", "Everyday PDF tools in one place — images to PDF, extract pages, OCR"), 4.0),
        (scene_shot(f("11-security.png"), "Protect and sanitise", "AES-256 passwords, and remove metadata, attachments and scripts"), 3.5),
        (scene_shot(f("12-dark.png"), "Light and dark themes", "Comfortable in any light — with crash recovery and safe saving built in"), 4.0),
        (scene_title("Free · Offline · Open source", "DocuCraft for Windows 10/11", "Find it on GitHub — search “DocuCraft PDF Editor”"), 5.0),
    ]
    parts = []
    for i, (img, secs) in enumerate(scenes):
        png = work / f"s{i:02d}.png"
        img.save(png)
        dst = work / f"s{i:02d}.mp4"
        encode_scene(png, secs, dst)
        parts.append(dst)
        print("scene", i, f"{secs}s")
    lst = work / "list.txt"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts))
    tmp = out / "docucraft-demo.tmp.mp4"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", "-movflags", "+faststart", str(tmp)])
    tmp.replace(out / "docucraft-demo.mp4")
    # small looping preview for the README (re-encode from the finished file)
    run(["ffmpeg", "-y", "-i", str(out / "docucraft-demo.mp4"), "-vf",
         "fps=5,scale=720:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96[p];[b][p]paletteuse=dither=bayer:bayer_scale=4",
         "-loop", "0", str(out / "docucraft-demo-preview.gif")])
    # ---------------------------------------------------------------- still images
    for src, name, size in ((f("02-reader-bookmarks.png"), "linkedin-card.png", (1200, 627)),
                            (f("02-reader-bookmarks.png"), "github-social-preview.png", (1280, 640))):
        c = gradient(*size)
        d = ImageDraw.Draw(c)
        logo = Image.open(LOGO).convert("RGBA").resize((72, 72), Image.LANCZOS)
        c.paste(logo, (60, 56), logo)
        d.text((150, 62), "DocuCraft", font=font(True, 54), fill=WHITE)
        d.text((60, 170), "Your Documents.", font=font(True, 48), fill=WHITE)
        d.text((60, 228), "Your Control.", font=font(True, 48), fill=ACCENT)
        y = 316
        for line in ("Read · annotate · redact", "Replace text in the same font", "PDF → Word, merge, split, OCR", "Free, offline, open source"):
            d.text((60, y), "•  " + line, font=font(False, 27), fill=(203, 213, 225))
            y += 46
        im = rounded(fit(Image.open(src).convert("RGB"), int(size[0] * 0.47), int(size[1] * 0.78)), 14)
        shadow_paste(c, im, (size[0] - im.width - 44, (size[1] - im.height) // 2), blur=22)
        c.convert("RGB").save(out / name)
    # feature overview grid
    cells = [("01-home.png", "Private by design", None), ("04-annotate.png", "Annotate & sign", None), ("REPLACE", "Replace text, same font", None),
             ("07-redacted.png", "True redaction", None), ("08-convert.png", "PDF to Word", None), ("10-organize.png", "Merge · split · compress", None)]
    gw, gh = 1600, 980
    c = gradient(gw, gh)
    d = ImageDraw.Draw(c)
    d.text((80, 40), "DocuCraft — what it does", font=font(True, 52), fill=WHITE)
    d.text((82, 112), "Free, offline PDF reader, editor and converter for Windows", font=font(False, 26), fill=MUTED)
    cw, ch = 450, 253
    for k, (fn, label, crop) in enumerate(cells):
        if fn == "REPLACE":                                       # before / after crops stacked: shows the actual change
            b0, a0 = Image.open(f("replace-before.png")).convert("RGB"), Image.open(f("replace-after.png")).convert("RGB")
            im = Image.new("RGB", (b0.width, b0.height * 2 + 16), (23, 37, 84))
            im.paste(b0, (0, 0))
            im.paste(a0, (0, b0.height + 16))
        else:
            im = Image.open(f(fn)).convert("RGB")
            im = im.crop(crop) if crop else im
        im = rounded(fit(im, cw, ch), 10)
        x, y = 80 + (k % 3) * (cw + 45), 190 + (k // 3) * (ch + 150)
        shadow_paste(c, im, (x, y), blur=14, offset=6)
        d.text((x, y + im.height + 18), label, font=font(True, 28), fill=WHITE)
    c.convert("RGB").save(out / "feature-overview.png")
    # before / after
    b, a = Image.open(f("replace-before.png")).convert("RGB"), Image.open(f("replace-after.png")).convert("RGB")
    c = gradient(1760, 800)
    d = ImageDraw.Draw(c)
    d.text((60, 36), "Replace text — same font, same size", font=font(True, 46), fill=WHITE)
    for k, (lab, im) in enumerate((("BEFORE", b), ("AFTER", a))):
        y = 130 + k * 330
        d.text((60, y), lab, font=font(True, 24), fill=ACCENT if k else MUTED)
        shadow_paste(c, rounded(im.resize((1640, int(im.height * 1640 / im.width)), Image.LANCZOS), 10), (60, y + 40), blur=12, offset=5)
    c.convert("RGB").save(out / "before-after-replace.png")
    shutil.rmtree(work, ignore_errors=True)
    print("done ->", out)


if __name__ == "__main__":
    main()
