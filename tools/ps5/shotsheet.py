"""Contact sheet of a console run's screenshots: shotsheet.py <shots dir> -> <dir>/sheet.png
Ordered by file time (the numbers wrap at 200); each tile labelled with its index."""
import sys, os, glob
from PIL import Image, ImageDraw
d = sys.argv[1]
files = sorted(glob.glob(os.path.join(d, "shot.*.ppm")), key=os.path.getmtime)
if not files:
    sys.exit("no shots")
tw, th, cols = 320, 180, 6
rows = (len(files) + cols - 1) // cols
sheet = Image.new("RGB", (tw * cols, th * rows))
for i, f in enumerate(files):
    try:
        im = Image.open(f).convert("RGB").resize((tw, th))
    except Exception:
        continue
    ImageDraw.Draw(im).text((4, 4), "%d" % i, fill=(255, 255, 0))
    sheet.paste(im, ((i % cols) * tw, (i // cols) * th))
sheet.save(os.path.join(d, "sheet.png"))
print("%d shots -> %s" % (len(files), os.path.join(d, "sheet.png")))
