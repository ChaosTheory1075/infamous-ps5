"""The inFamous: ReCharged launcher's art and the app's dashboard art, from the user's pictures in
Extras/Launcher, into Extras/app-assets (laid out as the app folder: launcher/, sce_sys/), the way the
other recomps keep theirs. Windows Python with Pillow, numpy and OpenCV:
    python make_assets.py
launcher/  title.png       the header's name at the top right (the inFAMOUS wordmark + ReCharged)
           logo_<g>.png    each game's wordmark for HOME, cut out of the user's art
           bg_<g>.jpg      each game's 1920x1080 picture, the art's own logo and watermark painted out
sce_sys/   icon0.png (512x512), pic0.dds / pic1.dds (3840x2160 BC7: sce_art.py, Saints Row's
           ci/make_sce_art.py).
snd0.at9 (the hover music: "inFamous App Hover Music.mp3", 0:00-1:00), the launcher's music and the
fonts (Oswald, Inter: SIL Open Font License) are made / copied by make_audio.sh in WSL."""
import os

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import sce_art

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
SRC = os.path.join(ROOT, "Extras", "Launcher")
OUT = os.path.join(ROOT, "Extras", "app-assets")
PREVIEW = os.path.join(ROOT, "work", "dbg")
ACCENT = (56, 189, 255)      # the launcher's accent: Cole's lightning
IMPACT = r"C:\Windows\Fonts\impact.ttf"


def load(name):
    return Image.open(os.path.join(SRC, name)).convert("RGB")


# ---- the wordmarks: the logo's white (and FoB's red) letters keyed off the art ----

def key(rgb, white_rows=None, red_rows=None):
    a = rgb.astype(np.float32)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mx, mn = a.max(-1), a.min(-1)
    sat = (mx - mn) / np.maximum(mx, 1)
    rows = np.arange(rgb.shape[0])[:, None]
    wr = white_rows or (0, rgb.shape[0])
    # (not the lightning's blue-white)
    m = (mx > 105) & (sat < 0.30) & (b - r < 18) & (rows >= wr[0]) & (rows < wr[1])
    if red_rows:
        m |= (r > 110) & (r > 2.4 * g) & (r > 2.4 * b) & (rows >= red_rows[0]) & (rows < red_rows[1])
    m = cv2.morphologyEx(m.astype(np.uint8) * 255, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    # the letters' texture (dark windows, specks) filled; the counters of A and O stay open
    n, lab, st, _ = cv2.connectedComponentsWithStats(255 - m, 4)
    for i in range(1, n):
        if st[i, cv2.CC_STAT_AREA] < 40:
            m[lab == i] = 255
    # stray bits (lightning, blood splatter) dropped
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, 8)
    keep = np.zeros_like(m)
    for i in range(1, n):
        if st[i, cv2.CC_STAT_AREA] >= 150:
            keep[lab == i] = 255
    keep = cv2.GaussianBlur(keep, (3, 3), 0)
    img = Image.fromarray(np.dstack([rgb, keep]), "RGBA")
    return img.crop(img.getbbox())


def wordmark(name, box, **kw):
    return key(np.array(load(name).crop(box)), **kw)


def with_shadow(img, blur, strength=230, pad=None):
    pad = blur * 2 if pad is None else pad
    out = Image.new("RGBA", (img.width + pad * 2, img.height + pad * 2), (0, 0, 0, 0))
    a = Image.new("L", out.size, 0)
    a.paste(img.getchannel("A"), (pad, pad))
    a = a.filter(ImageFilter.GaussianBlur(blur)).point(lambda v: min(255, v * strength // 100))
    out.paste(Image.new("RGBA", out.size, (0, 0, 0, 255)), (0, 0), a)
    out.alpha_composite(img, (pad, pad))
    return out


def recharged(height):
    """"ReCharged" in Impact, height = its capitals' height, lit like the lightning: the accent's blue
    brightening to white-blue at the top, a thin dark edge and a soft blue glow."""
    f = ImageFont.truetype(IMPACT, 100)
    cap = f.getbbox("R")[3] - f.getbbox("R")[1]
    f = ImageFont.truetype(IMPACT, round(100 * height / cap))
    l, t, r, b = f.getbbox("ReCharged", anchor="ls")   # (from the baseline: t < 0, b the descender)
    mask = Image.new("L", (r - l + 8, b - t + 8), 0)
    ImageDraw.Draw(mask).text((4 - l, 4 - t), "ReCharged", font=f, fill=255, anchor="ls")
    m = np.array(mask).astype(np.float32)
    grad = np.clip(np.linspace(-0.2, 1.1, m.shape[0]), 0, 1)[:, None, None]
    top, bot = np.array([200, 238, 255], np.float32), np.array(ACCENT, np.float32)
    col = np.broadcast_to(top * (1 - grad) + bot * grad, m.shape + (3,))
    text = Image.fromarray(np.dstack([col, m]).astype(np.uint8), "RGBA")
    pad = max(4, height // 4)
    out = Image.new("RGBA", (text.width + pad * 2, text.height + pad * 2), (0, 0, 0, 0))
    glow = Image.new("L", out.size, 0)
    glow.paste(text.getchannel("A"), (pad, pad))
    edge = glow.filter(ImageFilter.MaxFilter(3))
    glow = glow.filter(ImageFilter.GaussianBlur(max(2, height / 9))).point(lambda v: v * 110 // 100)
    out.paste(Image.new("RGBA", out.size, ACCENT + (255,)), (0, 0), glow)
    out.paste(Image.new("RGBA", out.size, (2, 8, 20, 255)), (0, 0), edge)
    out.alpha_composite(text, (pad, pad))
    out.baseline = pad + 4 - t
    return out


def fit_h(img, h):
    return img.resize((max(1, round(img.width * h / img.height)), h), Image.LANCZOS)


def title_line(word, height):
    """The header's name: the wordmark and ReCharged on one line, height pixels tall."""
    return beside(word, height - 16, 4)


def beside(word, wh, sh):
    """The wordmark wh tall, ReCharged after it: its capitals as tall as the wordmark's, on its baseline."""
    wm = with_shadow(fit_h(word, wh), sh, 260)
    rc = recharged(round(wh * 0.74))
    top = max(0, rc.baseline - (2 * sh + wh))      # (room above when ReCharged's glow is taller)
    out = Image.new("RGBA", (wm.width + rc.width + wh // 7, top + max(wm.height, rc.height + 2 * sh + wh)), (0, 0, 0, 0))
    out.alpha_composite(wm, (0, top))
    base = top + 2 * sh + wh                        # the wordmark's bottom = its baseline
    out.alpha_composite(rc, (wm.width - 2 * sh - rc.height // 8 + wh // 7, base - rc.baseline))
    return out.crop(out.getbbox())


def title_block(word, width):
    """The name for the icon and the dashboard, width pixels wide."""
    probe = beside(word, 100, 3)
    return beside(word, round(100 * width / probe.width), max(3, width // 160))


# ---- the pictures ----

def paint_out(img, boxes, radius=9, dark=1.0, black=()):
    """The art's own logo and watermark painted over from what's around them (darkened by dark: a
    patch of smoke), or with black where they sit on the art's black frame."""
    a = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    mask = np.zeros(a.shape[:2], np.uint8)
    for x0, y0, x1, y1 in boxes:
        mask[y0:y1, x0:x1] = 255
    if boxes:
        a = cv2.inpaint(a, mask, radius, cv2.INPAINT_TELEA)
        # the patch's smears softened into the rest
        soft = cv2.GaussianBlur(a, (0, 0), 14) * dark
        m = cv2.GaussianBlur(mask, (0, 0), 18)[..., None] / 255.0
        a = (a * (1 - m) + soft * m).astype(np.uint8)
    if black:
        bm = np.zeros(a.shape[:2], np.uint8)
        for x0, y0, x1, y1 in black:
            bm[y0:y1, x0:x1] = 255
        m = cv2.GaussianBlur(bm, (0, 0), 10)[..., None] / 255.0
        a = (a * (1 - m)).astype(np.uint8)
    return Image.fromarray(cv2.cvtColor(a, cv2.COLOR_BGR2RGB))


def cover(img, w, h, fx=0.5, fy=0.5):
    s = max(w / img.width, h / img.height)
    img = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
    x = round((img.width - w) * fx)
    y = round((img.height - h) * fy)
    return img.crop((x, y, x + w, y + h))


def main():
    lo, sce = os.path.join(OUT, "launcher"), os.path.join(OUT, "sce_sys")
    for d in (lo, sce, PREVIEW):
        os.makedirs(d, exist_ok=True)

    w1 = wordmark("Infamous1Logo.jpg", (170, 8, 590, 97))      # (the lightning under the letters left out)
    w2 = wordmark("Infamous2Logo.png", (20, 8, 560, 152))
    w3 = wordmark("InfamousFOBLogo.jpg", (330, 726, 975, 965), white_rows=(0, 150), red_rows=(165, 239))
    big = wordmark("InfamousFOBLogo.jpg", (330, 726, 862, 880), white_rows=(0, 150))   # the largest inFAMOUS
    for g, w in (("if1", w1), ("if2", w2), ("fob", w3)):
        with_shadow(w, 6, 200).save(os.path.join(lo, "logo_%s.png" % g))
    title_line(w1, 96).save(os.path.join(lo, "title.png"))

    bg1 = paint_out(load("Infamous1Background.jpg"), [(522, 30, 1245, 225), (0, 0, 140, 70)], 12, dark=0.45)
    bg2 = paint_out(load("Infamous2Background.jpg"), [(150, 880, 510, 1000)])
    bgf = paint_out(load("InfamousFOBBackground.jpg"), [], black=[(622, 384, 970, 545)])
    for g, im in (("if1", bg1), ("if2", bg2), ("fob", bgf)):
        cover(im, 1920, 1080).save(os.path.join(lo, "bg_%s.jpg" % g), quality=92)

    # the dashboard: the three Coles side by side (Empire City, New Marais, Pyre Night), the name over
    # a dark band at the bottom
    W, H = sce_art.W, sce_art.H
    pw = W // 3
    panels = [cover(bg1.crop((10, 0, 610, 960)), pw + 200, H),
              cover(bg2.crop((700, 0, 1620, 1080)), pw + 200, H, 0.55),
              cover(load("InfamousFOBLogo.jpg").crop((150, 0, 840, 700)), pw + 200, H, 0.5, 0.15)]
    bg = Image.new("RGB", (W, H))
    for i, p in enumerate(panels):
        seam = None
        if i:
            ramp = np.clip(np.arange(p.width) / 200.0, 0, 1)
            seam = Image.fromarray((np.broadcast_to(ramp, (p.height, p.width)) * 255).astype(np.uint8))
        bg.paste(p, (i * pw - (100 if i else 0), 0), seam)
    shade = np.clip((np.arange(H) - H * 0.52) / (H * 0.30), 0, 1) ** 1.3 * 225
    shade = Image.fromarray(np.broadcast_to(shade[:, None], (H, W)).astype(np.uint8))
    bg = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), bg, shade).convert("RGBA")
    t = title_block(big, 1500)
    bg.alpha_composite(t, ((W - t.width) // 2, H - t.height - 150))
    bg = bg.convert("RGB")
    bg.resize((1920, 1080), Image.LANCZOS).save(os.path.join(PREVIEW, "pic0-preview.jpg"), quality=88)
    data = sce_art.bc7_mode6(bg)
    for name in ("pic0.dds", "pic1.dds"):
        with open(os.path.join(sce, name), "wb") as f:
            f.write(sce_art.DDS_HEADER + data)

    # the icon: inFamous 2's Cole between his red and blue lightning, the name under him
    icon = cover(bg2.crop((760, 230, 1610, 1080)), 512, 512)
    band = np.clip((np.arange(512) - 250) / 150.0, 0, 1) * 235
    band = Image.fromarray(np.broadcast_to(band[:, None], (512, 512)).astype(np.uint8))
    icon = Image.composite(Image.new("RGB", (512, 512), (0, 0, 0)), icon, band).convert("RGBA")
    t = title_block(big, 440)
    icon.alpha_composite(t, ((512 - t.width) // 2, 512 - t.height - 22))
    icon.convert("RGB").save(os.path.join(sce, "icon0.png"), optimize=True)
    print("launcher/ title.png logo_*.png bg_*.jpg; sce_sys/ icon0.png pic0.dds pic1.dds ->", OUT)


if __name__ == "__main__":
    main()
