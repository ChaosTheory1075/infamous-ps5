# spurs fix pairs: SPURS_MAXCONT_FIX takes several <from>:<to> pairs ("5:8,1:2"), one per SPURS kernel group size,
# so inFAMOUS 1's audio SPURS (told 2 SPUs instead of 1 by PS3_IF1_SPURS2_SPUS) also gets its workloads' contention
# and per-SPU priority filled: console trace 2026-11-06: audio SPUs 67-76% / 1-13% (the 2nd one barely used).
import sys
p = __import__("os").path.expanduser("~") + "/if2/ps3recomp-fork/runtime/syscalls/lv2_register.c"
s = open(p).read()
if "spurs fix pairs" in s: print("already"); sys.exit(0)
old = '''    { static int fx_from = -1, fx_to = 0;
      if (fx_from < 0) { const char* e = getenv("SPURS_MAXCONT_FIX"); unsigned a = 0, b = 0;
                         fx_from = e && sscanf(e, "%u:%u", &a, &b) == 2 && a && b > a && b <= 8 ? (int)a : 0; fx_to = (int)b; }
      if (fx_from > 0 && !strcmp(g->name, "CellSpursKernelGroup") && num == (uint32_t)fx_to) {
          g->fix_from = (uint32_t)fx_from; g->fix_to = (uint32_t)fx_to;
          fprintf(stderr, "[SPU] group 0x%X: SPURS_MAXCONT_FIX %u -> %u armed\\n", g->id, g->fix_from, g->fix_to);
      } }'''
new = '''    { static int npair = -1; static unsigned pf[4], pt[4];   /* spurs fix pairs: "<from>:<to>[,<from>:<to>...]" */
      if (npair < 0) { npair = 0; const char* e = getenv("SPURS_MAXCONT_FIX");
          while (e && *e && npair < 4) { unsigned a = 0, b = 0; int used = 0;
              if (sscanf(e, "%u:%u%n", &a, &b, &used) != 2) break;
              if (a && b > a && b <= 8) { pf[npair] = a; pt[npair] = b; npair++; }
              e += used; if (*e == ',') e++; else break; } }
      for (int k = 0; k < npair; k++)
          if (!strcmp(g->name, "CellSpursKernelGroup") && num == pt[k]) {
              g->fix_from = pf[k]; g->fix_to = pt[k];
              fprintf(stderr, "[SPU] group 0x%X: SPURS_MAXCONT_FIX %u -> %u armed\\n", g->id, g->fix_from, g->fix_to);
              break;
          } }'''
assert s.count(old) == 1, "fix block not found"
open(p, "w").write(s.replace(old, new)); print("patched")
