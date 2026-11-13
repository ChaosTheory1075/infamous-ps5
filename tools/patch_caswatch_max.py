# caswatch max: PPU_CASWATCH_MAX=<n> lifts the 200-line cap of the PPU_CASWATCH log (0 = unlimited).
# FoB's lost task wake-up happens after a few hundred commits on the taskset line (2026-11-02).
PPL = "runtime/ppu/ppu_loader.cpp"
edit(PPL,
     '''          static int n; if (PS3_LOG_FIRST(n, 200))''',
     '''          static int n; static int cap = -2;   /* caswatch max (tools/patch_caswatch_max.py) */
          if (cap == -2) { const char* m = getenv("PPU_CASWATCH_MAX"); cap = m ? atoi(m) : 200; if (cap <= 0) cap = 0x7FFFFFFF; }
          if (PS3_LOG_FIRST(n, cap))''',
     "caswatch max")
