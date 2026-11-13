"""sheet.py <run name> [every Nth]: copy a run's minute frames from WSL and make work/if2-frames/<run>/sheet.png"""
import glob
import os
import shutil
import sys

from PIL import Image, ImageFile

ImageFile.LOAD_TRUNCATED_IMAGES = True
run = sys.argv[1]
step = int(sys.argv[2]) if len(sys.argv) > 2 else 1
src = r"\\wsl.localhost\Ubuntu-24.04\root\if2\runs" + "\\" + run
dst = os.path.join(os.path.dirname(__file__), "..", "work", "if2-frames", run)
os.makedirs(dst, exist_ok=True)
for f in glob.glob(os.path.join(src, "frame_*s.ppm")):
    shutil.copy(f, dst)
fs = sorted(glob.glob(os.path.join(dst, "frame_*s.ppm")), key=lambda p: int(p.rsplit("_", 1)[1][:-5]))[::step]
ims = []
for f in fs:
    try:
        ims.append(Image.open(f).convert("RGB").resize((320, 180)))
    except Exception:
        ims.append(Image.new("RGB", (320, 180), (255, 0, 255)))   # unreadable frame: magenta
cols = 5
sheet = Image.new("RGB", (320 * cols, 180 * ((len(ims) + cols - 1) // cols)))
for i, im in enumerate(ims):
    sheet.paste(im, ((i % cols) * 320, (i // cols) * 180))
sheet.save(os.path.join(dst, "sheet.png"))
print(len(ims), "frames:", ", ".join(os.path.basename(f)[6:-5] for f in fs))
