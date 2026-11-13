"""resv_note_first.py <port dir>: lifted lwarx/ldarx register the line reservation BEFORE the load.

The lift emitted  { ea; rD = vm_readN(ea); reserve = ...; ppu_resv_line_note(ea); }  -- the load,
then the registration. An SPU PUTLLC (or other writer) that commits between the two clears nothing
(the PPU holds no reservation yet), the PPU then reserves a line it has already read stale, and its
store-conditional succeeds on a decision made from old data. Hardware cannot do that: the
reservation and the load are one instruction. inFAMOUS 1's load-screen stall (BC-250, 2026-11-02):
the EDGE zlib LFQueue at 0x406C4780 had 22 pushes, 21 pops and one registered, never-woken pop
waiter -- libsre's push read "no waiter", the SPU task registered in that window, the push's stdcx
still succeeded, and the task slept forever while the PPU waited for its result.
Now: { ea; ppu_resv_line_note(ea); rD = vm_readN(ea); reserve = ...; } (GETLLAR reserves first too).
Rewrites the generated game PPU sources and the lifted firmware (lle/*) in place; idempotent.
"""
import re, sys
from pathlib import Path

port = Path(sys.argv[1])
pat = re.compile(r"\{ uint64_t ea = ([^;]+); ctx->gpr\[(\d+)\] = vm_read(32|64)\(ea\); "
                 r"ctx->reserve_addr = \(uint32_t\)ea; ctx->reserve_value = ctx->gpr\[\2\]; "
                 r"ppu_resv_line_note\(ea\); \}")
rep = (r"{ uint64_t ea = \1; ppu_resv_line_note(ea); ctx->gpr[\2] = vm_read\3(ea); "
       r"ctx->reserve_addr = (uint32_t)ea; ctx->reserve_value = ctx->gpr[\2]; }")
files = sorted(port.glob("recompiled/*.cpp")) + sorted(port.glob("lle/*/*.cpp"))
total = left = 0
for f in files:
    s = f.read_text()
    s2, n = pat.subn(rep, s)
    if n:
        f.write_text(s2)
        total += n
    left += s2.count("ppu_resv_line_note(ea); }")
print(f"resv_note_first: {total} lwarx/ldarx sites reordered, {left} left in the old order")
