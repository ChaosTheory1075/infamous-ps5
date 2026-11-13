#!/usr/bin/env python3
# if1 spurs1 spus: inFAMOUS 1's gameplay SPURS instance (SPU group 0x1000, 5 SPUs, prio 128) runs the
# WWS job batches the main PPU thread waits for (func_0041FC38). Console trace 2026-11-04 21:07 run:
# all 5 SPUs busy at once 45-47% of the time, none 20-27% (bimodal) -> the batches are throughput-
# bound, and the PS5 has idle cores. PS3_IF1_SPURS1_SPUS=<n> (6..8) asks the real (LLE) SPURS for n
# SPUs at initialize time, the same way as tools/if1_spurs2_spus.py (which this extends: it must be
# applied first). Matched by nSpus == 5 and spuPriority == 128. Unset = old (5 SPUs).
#   if1_spurs1_spus.py [~/if1/infamous2-lle]   (idempotent)
import sys, pathlib
root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else __import__("os").path.expanduser("~") + "/if1/infamous2-lle")
f = root / "lle" / "libsre" / "libsre_recomp_000.cpp"
s = f.read_text()
if "if1_spurs1_spus" in s:
    print("if1 spurs1 spus: already applied"); sys.exit(0)
old = '''        ctx->gpr[nreg] = (uint64_t)n;
    }
}'''
assert s.count(old) == 1, "if1_spurs2_fix not found (apply if1_spurs2_spus.py first)"
new = '''        ctx->gpr[nreg] = (uint64_t)n;
    }
    {   /* if1 spurs1 spus (tools/if1_spurs1_spus.py) */
        static int v1 = -1;
        if (v1 < 0) { const char* e = getenv("PS3_IF1_SPURS1_SPUS"); v1 = e ? atoi(e) : 0; if (v1 > 8) v1 = 8; }
        if (v1 >= 6 && (uint32_t)ctx->gpr[nreg] == 5u && (uint32_t)ctx->gpr[preg] == 128u) {
            fprintf(stderr, "[if1 spurs1] %s: nSpus 5 -> %d (spuPriority 128)\\n", fn, v1);
            ctx->gpr[nreg] = (uint64_t)v1;
        }
    }
}'''
s = s.replace(old, new, 1)
f.write_text(s)
print("if1 spurs1 spus: applied to", f)
