#!/usr/bin/env python3
# spu reglocal: SPU registers as C locals in the lifted functions (the SPU codegen rewrite, step 1).
#
# The lifter writes every guest register as ctx->gpr[N]. LS lives in the same struct (ctx->ls points
# at ctx->ls_store), so clang must assume each LS store may change any register: every result is
# stored to ctx and often loaded straight back (objdump of jobmod_d466 spu_func_00006CC8: store
# 0x480(%rdi) then load 0x480(%rdi) inside the loop). Here each function copies the registers it
# uses into locals (u128 r_N) on entry; locals are never address-taken, so they live in host
# registers. They go back to ctx->gpr (the registers this function writes) right before anything
# that leaves the function or runs other guest code -- SPU_DIRECT / SPU_RET / SPU_RET_REG, return,
# calls of the form f(ctx) (lifted calls, spu_indirect_branch, spu_stop, spu_halt), channel ops --
# and are reloaded (all used registers) after anything that returns here having run other code.
# Same instructions, same order, same results: only where the values are kept changes.
# A function with a statement shape this pass does not know is left as it was (and counted).
#   spu_reglocal.py <spu_recomp.c> ...        in place, original kept as spu_recomp.c.pre-rl (idempotent)
#   spu_reglocal.py --undo <spu_recomp.c> ...
import re, sys, os

FN_START = re.compile(r'^void ([A-Za-z0-9_]+)\(spu_context\* ctx\) \{$')
GPR = re.compile(r'ctx->gpr\[(\d+)\]')
WRITE = re.compile(r'\br_(\d+) = (?!=)')
# statements that run other guest code or leave: spill before
CALLSTMT = re.compile(r'\b([A-Za-z_][A-Za-z0-9_]*)\(ctx\);')
EXIT_TOK = re.compile(r'SPU_DIRECT\(|SPU_RET\(|SPU_RET_REG\(|\breturn\b')
CHAN = re.compile(r'spu_(rdch|wrch|rchcnt)\(')
PURE_CTX_CALLS = set()   # every f(ctx) is treated as a barrier

def spill_code(regs):
    return "".join(f"ctx->gpr[{n}] = r_{n}; " for n in regs).rstrip() or "/* no spill */"

def transform_fn(name, body):
    """body: list of lines (without the 'void ...{' and the closing '}'). Returns new lines or None."""
    text = "\n".join(body)
    used = sorted({int(n) for n in GPR.findall(text)})
    if not used:
        return None, "no regs"
    if '&ctx->gpr' in text or 'ctx->gpr[' in GPR.sub('', text):
        return None, "odd gpr use"
    lines = [GPR.sub(lambda m: "r_" + m.group(1), l) for l in body]
    written = sorted({int(n) for l in lines for n in WRITE.findall(l)})
    # per-line spill set: the registers that can have been written before that line -- the writes
    # textually before it, plus every write inside a loop (label .. backward goto) that contains it
    label_at = {}
    for k, l in enumerate(lines):
        m = re.match(r'^(loc_[0-9A-F]+):$', l.strip())
        if m: label_at[m.group(1)] = k
    loops = []
    for k, l in enumerate(lines):
        for t in re.findall(r'goto (loc_[0-9A-F]+);', l):
            if t in label_at and label_at[t] <= k: loops.append((label_at[t], k))
    wr_line = [set(int(n) for n in WRITE.findall(l)) for l in lines]
    def spill_set(i):
        w = set()
        for k in range(i): w |= wr_line[k]
        w |= wr_line[i]   # an assignment earlier on the same line (e.g. the link register before a call)
        for a, b in loops:
            if a <= i <= b:
                for k in range(a, b + 1): w |= wr_line[k]
        return sorted(w)
    spill_defs = {}
    out = []
    for li, l in enumerate(lines):
        s = l.strip()
        if not s or s.endswith(':') and not ' ' in s:   # label
            out.append(l); continue
        has_chan = CHAN.search(l) is not None
        calls = [m for m in CALLSTMT.finditer(l)]
        has_exit = EXIT_TOK.search(l) is not None
        if has_chan:
            ind = l[:len(l) - len(l.lstrip())]
            m = re.match(r'^r_(\d+) = (spu_(?:rdch|rchcnt)\(ctx, [^;]*\));$', s)
            if m:
                sp = spill_set(li); out.append(f"{ind}{{ {spill_code(sp)} __typeof__({m.group(2)}) _ch = {m.group(2)}; SPU_RL_(); r_{m.group(1)} = _ch; }}")
                continue
            m = re.match(r'^(spu_wrch\(ctx, [^;]*\));$', s)
            if m:
                sp = spill_set(li); out.append(f"{ind}{{ {spill_code(sp)} {m.group(1)}; SPU_RL_(); }}")
                continue
            return None, "channel shape: " + s[:80]
        if not calls and not has_exit:
            out.append(l); continue
        if 'goto' in l:
            return None, "goto with call/exit: " + s[:80]
        # spill right before the first barrier token in the line
        first = min([m.start() for m in calls] + [m.start() for m in EXIT_TOK.finditer(l)])
        nl = l[:first] + spill_code(spill_set(li)) + " " + l[first:]
        # a call that returns here: reload at the end of the line, unless the line always leaves
        if calls and not re.search(r'\breturn;\s*\}?\s*$', s) and not re.search(r'SPU_(DIRECT|RET|RET_REG)\([^;]*\);\s*\}?\s*$', s):
            nl = nl + " SPU_RL_();"
        out.append(nl)
    decl = ["    /* spu reglocal (tools/spu_reglocal.py) */"]
    decl += ["    u128 " + ", ".join(f"r_{n} = ctx->gpr[{n}]" for n in used[i:i + 6]) + ";"
             for i in range(0, len(used), 6)]
    rl = " ".join(f"r_{n} = ctx->gpr[{n}];" for n in used)
    pre = [f"#define SPU_RL_() do {{ {rl} }} while (0)"]
    return (pre, decl + out), None

def process(path):
    src = open(path).read()
    if "spu reglocal (tools/spu_reglocal.py)" in src:
        return "already"
    lines = src.split("\n")
    res, i, done, skipped, why = [], 0, 0, 0, {}
    while i < len(lines):
        m = FN_START.match(lines[i])
        if not m:
            res.append(lines[i]); i += 1; continue
        j = i + 1
        while j < len(lines) and lines[j] != "}":
            j += 1
        body = lines[i + 1:j]
        r, err = transform_fn(m.group(1), body)
        if r is None:
            res.extend(lines[i:j + 1]); skipped += 1
            k = (err or "").split(":")[0]; why[k] = why.get(k, 0) + 1
        else:
            pre, nb = r
            res.extend(pre); res.append(lines[i]); res.extend(nb); res.append("}")
            res.append("#undef SPU_RL_")
            done += 1
        i = j + 1
    if not os.path.exists(path + ".pre-rl"):
        open(path + ".pre-rl", "w").write(src)
    open(path, "w").write("\n".join(res))
    return f"{done} functions, {skipped} left as they were {why}"

if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--undo":
        for p in args[1:]:
            if os.path.exists(p + ".pre-rl"):
                os.replace(p + ".pre-rl", p); print(p, "restored")
        sys.exit(0)
    for p in args:
        print(p, process(p))
