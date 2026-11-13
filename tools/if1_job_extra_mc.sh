#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Relift inFAMOUS 1's SPU job images 0002 / 0003 / 0004 (LS 0x4000, the jobs of the one-SPU SPURS group
# 0x1001 = spu 2005) with the PCs that ran on the interpreter as extra function entries. [ibstat] nofn
# pcs on spu 2005 (console run 2026-11-03 21:22 + BC-250 run rp1, work/nofn2005.txt): 37 PCs = 16.8M
# interpreted entries, most of them return points after brsl/bisl (reached through spu_indirect_branch
# when the host call chain was unwound) and function-pointer targets the auto-function scan missed
# (0x43A0: a full prologue). A relift without extras reproduces the current sources byte for byte.
# PS3_SPU_IF1_JOB_EXTRA=0 = the extra entries are lifted but not registered (old dispatch).
#   if1_job_extra.sh          relift + install (old sources kept as spu_recomp.c.pre-extra)
#   if1_job_extra.sh --undo   restore the old sources
cd $HOME/if1/infamous2-lle || exit 1
IMGS="spu_0002_at_0068FE00 spu_0003_at_006A3800 spu_0004_at_006BF480"
if [ "$1" = --undo ]; then
  for i in $IMGS; do [ -f spu/$i/spu_recomp.c.pre-extra ] && cp spu/$i/spu_recomp.c.pre-extra spu/$i/spu_recomp.c && cp spu/$i/spu_recomp.h.pre-extra spu/$i/spu_recomp.h; done
  echo restored; exit 0
fi
PCS=$(awk '$1>=5000 {printf "0x%s,", $2}' ~/inFamous/work/nofn2005.txt | sed 's/,$//')
for i in $IMGS; do
  T=$(mktemp -d)
  $HOME/if2/.venv/bin/python $HOME/if2/ps3recomp-fork/tools/spu_lifter.py spu/images/$i.elf \
    --auto-functions spu/images/$i.elf --symbol-prefix ${i}_ -o $T --extra-funcs $PCS --merge-chunks | tail -1
  sed -i 's|#include "../../runtime/spu/spu_helpers.h"|#include "spu_helpers.h"|' $T/spu_recomp.c
  sed -i 's|#include "../../runtime/spu/spu_context.h"|#include "spu_context.h"|' $T/spu_recomp.h
  # the env switch: entries the old lift did not have are registered only when it is on
  O=spu/$i/spu_recomp.c; [ -f $O.pre-extra ] && O=$O.pre-extra
  python3 - "$T/spu_recomp.c" "$O" "$i" <<'EOF'
import re, sys
new, old, img = sys.argv[1], sys.argv[2], sys.argv[3]
src = open(new).read()
had = set(re.findall(r'^void %s_spu_func_([0-9A-F]+)\(' % img, open(old).read(), re.M))
now = re.findall(r'^void %s_spu_func_([0-9A-F]+)\(' % img, src, re.M)
extra = sorted(int(a, 16) for a in now if a not in had)
reg = '''void %s_spu_recomp_register(void) {
    for (const spu_func_entry* e = spu_function_table; e->func; ++e)
        spu_register_function(e->addr, e->func);
}''' % img
assert reg in src, "register function shape changed"
lst = ", ".join("0x%X" % a for a in extra) or "0"
src = src.replace(reg, '''/* if1 job extra (tools/if1_job_extra.sh): entries added by the relift; PS3_SPU_IF1_JOB_EXTRA=0 leaves
 * them unregistered (the old dispatch: those PCs run on the interpreter). */
static const uint32_t s_job_extra[] = { %s };
void %s_spu_recomp_register(void) {
    const char* ev = getenv("PS3_SPU_IF1_JOB_EXTRA");
    const int on = !(ev && ev[0] == '0');
    for (const spu_func_entry* e = spu_function_table; e->func; ++e) {
        int skip = 0;
        for (unsigned k = 0; !on && k < sizeof s_job_extra / sizeof s_job_extra[0]; k++)
            if (s_job_extra[k] == e->addr) skip = 1;
        if (!skip) spu_register_function(e->addr, e->func);
    }
}''' % (lst, img))
if "#include <stdlib.h>" not in src:
    src = src.replace('#include "spu_helpers.h"', '#include "spu_helpers.h"\n#include <stdlib.h>', 1)
open(new, "w").write(src)
print(img, "extra entries:", len(extra))
EOF
  [ -f spu/$i/spu_recomp.c.pre-extra ] || { cp spu/$i/spu_recomp.c spu/$i/spu_recomp.c.pre-extra; cp spu/$i/spu_recomp.h spu/$i/spu_recomp.h.pre-extra; }
  cp $T/spu_recomp.c spu/$i/spu_recomp.c; cp $T/spu_recomp.h spu/$i/spu_recomp.h
  rm -rf $T
done
