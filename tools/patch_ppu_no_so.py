# ppu no SO: XER[SO] is never set in this title's lifted code (no o-form instruction, no mtxer: only CA, bit 29,
# is ever written -- checked 2026-11-07), so every compare's "| ((ctx->xer >> 31) & 1u)" (111,761 sites) and every
# record form's "((ctx->xer >> 31) << 28)" read a constant 0 from memory. Drop them: exact, not an approximation.
#   patch_ppu_no_so.py [~/if1/infamous2-lle]   (idempotent; refuses if any SO write appears)
import sys, pathlib, glob, re
root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else __import__("os").path.expanduser("~") + "/if1/infamous2-lle")
files = sorted(glob.glob(str(root / "recompiled" / "ppu_recomp_0*.cpp"))) + sorted(glob.glob(str(root / "lle" / "*" / "*_recomp_0*.cpp")))
so_write = re.compile(r"ctx->xer\s*=\s*ctx->gpr|ctx->xer\s*\|=|1u\s*<<\s*31\)[^;]*ctx->xer|ctx->xer\s*=\s*[^;]*0x80000000")
for f in files:
    s = pathlib.Path(f).read_text()
    if so_write.search(s): print("SO WRITE FOUND, not patching:", f); sys.exit(1)
tot = 0
for f in files:
    p = pathlib.Path(f); s = p.read_text()
    n1 = s.count(" | ((ctx->xer >> 31) & 1u)"); n2 = s.count("((ctx->xer >> 31) << 28)")
    if not (n1 or n2): continue
    s = s.replace(" | ((ctx->xer >> 31) & 1u)", "").replace("((ctx->xer >> 31) << 28)", "0u")
    p.write_text(s); tot += n1 + n2
print("ppu no SO: removed", tot, "reads in", len(files), "files")
