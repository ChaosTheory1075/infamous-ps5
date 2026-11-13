#!/usr/bin/env python3
"""spu fastlift: a faster form of one lifted SPU module (spu/<module>/spu_recomp.c), added beside the
original code, chosen at run time (SPU_FASTLIFT=0 = the original functions).

The lifter emits one C function per basic-block chunk, the 128 SPU registers live in ctx->gpr, and
every branch between chunks is a checked tail call (SPU_DIRECT). The local-store accesses go
through a uint8_t pointer, which may alias anything, so the compiler reloads and re-stores the
registers around every LS store. This tool regroups the chunks into functions (a run of chunks
from one call target to the next) and in each group:
  - the registers it uses are locals (loaded from ctx->gpr at entry; the ones it writes are stored
    back before every exit, call and channel op, and all are reloaded after a call or channel op);
  - a branch to a chunk of the same group is a goto, with SPU_DIRECT's checks kept (g_spu_direct,
    the stack-reset hint, and on a backward branch a pending interrupt); if they fail it leaves
    through SPU_DIRECT as before;
  - every chunk address gets a wrapper that sets ctx->pc and tail-calls its group, whose entry
    switch jumps to that chunk. The wrappers are what the module registers (and calls, for brsl).
Relocatable modules (ctx->code_base) are left alone.

usage: spu_fastlift.py <module dir> [--max-lines N]    (keeps the original as spu_recomp.c.orig;
       re-running regenerates from it; --undo puts it back)
"""
import argparse
import os
import re
import sys

ap = argparse.ArgumentParser()
ap.add_argument("module")
ap.add_argument("--max-lines", type=int, default=2500)
ap.add_argument("--undo", action="store_true")
args = ap.parse_args()

src = os.path.join(args.module, "spu_recomp.c")
orig = src + ".orig"
if args.undo:
    if os.path.exists(orig):
        os.replace(orig, src)
        print("restored", src)
    sys.exit(0)
text = open(orig if os.path.exists(orig) else src).read()
if "spu fastlift" in text:
    sys.exit(f"{src}: already transformed and no .orig to start from")
if "ctx->code_base" in text:
    print(f"{src}: relocatable module, left alone")
    sys.exit(0)

FUNC_RE = re.compile(r"^void (\w+?_spu_func_([0-9A-F]{8}))\(spu_context\* ctx\) \{$")
lines = text.split("\n")
funcs = []          # (name, addr, body lines)
i = 0
while i < len(lines):
    m = FUNC_RE.match(lines[i])
    if m:
        j = i + 1
        while lines[j] != "}":
            j += 1
        funcs.append((m.group(1), int(m.group(2), 16), lines[i + 1:j]))
        i = j
    i += 1
if not funcs:
    sys.exit(f"{src}: no lifted functions found")
prefix = funcs[0][0][: funcs[0][0].index("spu_func_")]
by_name = {f[0]: f for f in funcs}
reg_m = re.search(r"\nvoid (\w+)_spu_recomp_register\(void\) \{\n(.*?)\n\}\n", text, re.S)
if not reg_m:
    sys.exit(f"{src}: no registration function")

GPR = re.compile(r"ctx->gpr\[(\d+)\]")
GPR_W = re.compile(r"ctx->gpr\[(\d+)\](?:\._[a-z0-9]+\[\d+\])?\s*=(?!=)")
CALL = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
DIRECT = re.compile(r"SPU_DIRECT\(ctx, (0x[0-9A-Fa-f]+), (\w+)\);")
LOCFN = re.compile(r"\b(" + re.escape(prefix) + r"spu_func_[0-9A-F]{8})\(ctx\);")
GOTO = re.compile(r"^if \((.*)\) goto (loc_[0-9A-F]+);$")
LABEL = re.compile(r"^(loc_[0-9A-F]+):$")
KEYWORDS = {"if", "while", "for", "switch", "sizeof", "return"}

# Pure helpers: every spu_* a register is assigned from, except the channel reads.
pure = {m.group(1) for m in re.finditer(r"ctx->gpr\[\d+\] = (spu_[a-z0-9_]+)\(", text)}
pure -= {"spu_rdch", "spu_rchcnt"}
pure |= {"spu_ls_write128", "spu_arch_fence", "spu_link"}

def is_pure(s):
    """Touches only registers and local store: no call out, no ctx state, no control transfer."""
    if "return" in s or "goto" in s or "SPU_" in s:
        return False
    rest = s.replace("spu_ls_read128(ctx,", "").replace("spu_ls_write128(ctx,", "")
    rest = GPR.sub("", rest)
    if re.search(r"\bctx\b", rest):
        return False
    return all(n in pure or n in KEYWORDS for n in CALL.findall(s))

def loc(s):
    """ctx->gpr[n] -> the local rn, a GNU vector (spul_v): lanes as vector elements, SPUL_U/SPUL_V
    (bitcasts) where a u128 is passed or returned. A u128 local is split by SROA into two i64
    halves (its first member is _u64[2]), which costs a GPR<->XMM move per lane access."""
    s = re.sub(r"ctx->gpr\[(\d+)\]\._u32\[(\d+)\]", r"r\1[\2]", s)
    s = re.sub(r"ctx->gpr\[(\d+)\]\._u16\[(\d+)\]", r"((spul_h)r\1)[\2]", s)
    val = lambda t: GPR.sub(lambda m: f"SPUL_U(r{m.group(1)})", t)
    s = re.sub(r"ctx->gpr\[(\d+)\] = (?!=)([^;]*);", lambda m: f"r{m.group(1)} = SPUL_V({val(m.group(2))});", s)
    return val(s)

# Groups: consecutive chunks (by address) from one call target to the next, capped in size.
call_targets = {m.group(1) for m in LOCFN.finditer(text)}
funcs.sort(key=lambda f: f[1])
groups, cur, n = [], [], 0
for f in funcs:
    if cur and (f[0] in call_targets or n + len(f[2]) > args.max_lines):
        groups.append(cur); cur, n = [], 0
    cur.append(f); n += len(f[2])
if cur:
    groups.append(cur)
gname = {}
for k, g in enumerate(groups):
    for f in g:
        gname[f[0]] = f"{prefix}spuL_group_{g[0][1]:08X}"
wrap = lambda name: name.replace("_spu_func_", "_spuL_func_")

def bits(regs):
    m = 0
    for r in regs:
        m |= 1 << int(r)
    return m

def regs_of(m):
    return [r for r in range(128) if m >> r & 1]

def reads_of(t):
    """registers a statement reads (an assignment's target only where its right side names it)"""
    return bits(GPR.findall(re.sub(r"ctx->gpr\[\d+\] = (?!=)", "", t)))

out = []
for k, g in enumerate(groups):
    G = gname[g[0][0]]
    names = {f[0] for f in g}
    # ---- pass 1: the group as items; @FL@/@RL@ are filled in from the dataflow below ----
    items = []      # dict(kind, text, reads, defs, pre, targets, fall)
    def item(kind, text, reads=0, defs=0, pre=0, targets=(), fall=True):
        items.append(dict(kind=kind, text=text, reads=reads, defs=defs, pre=pre, targets=list(targets), fall=fall))
    for ci, (name, addr, body) in enumerate(g):
        item("label", f"E_{addr:08X}")
        relabel = lambda s, ci=ci: re.sub(r"\bloc_([0-9A-F]+)\b", lambda m: f"c{ci}_loc_{m.group(1)}", s)
        for raw in body:
            s = raw.strip()
            if not s:
                continue
            if LABEL.match(s):
                item("label", relabel(s)[:-1]); continue
            if s.startswith("/*") and (s.endswith("*/;") or s.endswith("*/")):
                continue
            if s.startswith("uint8_t* const _lsb = ctx->ls;"):   # spu lsb: one per group, at its top
                continue
            um = re.match(r"^goto (loc_[0-9A-F]+);$", s)
            if um:   # an unconditional jump inside the function
                lab = relabel(um.group(1))
                item("goto", f"goto {lab};", targets=[lab], fall=False); continue
            gm = GOTO.match(s)
            if gm and is_pure(gm.group(1)):
                lab = relabel(gm.group(2))
                item("goto", f"if ({loc(gm.group(1))}) goto {lab};", reads=reads_of(gm.group(1)), targets=[lab]); continue
            if is_pure(s):
                item("pure", loc(s), reads=reads_of(s), defs=bits(GPR_W.findall(s))); continue
            if DIRECT.search(s) and "return" not in s and "host_depth" not in s:
                tg = []
                def direct(m):
                    pc, fn = m.group(1), m.group(2)
                    if fn in names:
                        tgt = int(pc, 16)
                        guard = f"g_spu_direct > 0 && !g_spu_stack_reset_hint[{(tgt >> 2) & 1023}u]"
                        if tgt <= addr:   # backward: a pending interrupt is taken through SPU_DIRECT
                            guard += " && !(ctx->int_enable && !ctx->irq_saved && (spu_ev_get(ctx) & ctx->event_mask))"
                        if tgt & 0x3FFFF:
                            tg.append(f"E_{tgt:08X}")
                            return f"if (__builtin_expect({guard}, 1)) goto E_{tgt:08X}; @FL@ SPU_DIRECT(ctx, {pc}, {G});"
                        return f"@FL@ SPU_DIRECT(ctx, {pc}, {G});"
                    return f"@FL@ SPU_DIRECT(ctx, {pc}, {gname.get(fn, fn)});"
                t = DIRECT.sub(direct, loc(s))
                item("direct", t, reads=reads_of(s), pre=bits(GPR_W.findall(s)), targets=tg, fall=s.startswith("if ("))
                continue
            if "ctx->host_depth++;" in s:   # brsl/bisl: a host call
                t = LOCFN.sub(lambda m: (wrap(m.group(1)) if m.group(1) in by_name else m.group(1)) + "(ctx);", loc(s))
                t = t.replace("ctx->host_depth++;", "@FL@ ctx->host_depth++;", 1)
                item("call", t + " @RL@", reads=reads_of(s), pre=bits(GPR_W.findall(s))); continue
            t = loc(s)
            cm = re.match(r"^if \((.*?)\) \{ (.*) \}$", t)
            if cm and ("return" in cm.group(2) or "SPU_RET" in cm.group(2)):
                item("condexit", f"if ({cm.group(1)}) {{ @FL@ {cm.group(2)} }}", reads=reads_of(s)); continue
            if (re.search(r"(^|; )return;$", t) and not re.search(r"\) return;$", t)) or t.startswith("SPU_RET"):
                item("exit", f"@FL@ {t}", reads=reads_of(s), fall=False); continue
            # anything else (channel ops, resuming stops, ...): a full barrier. The statement itself
            # keeps ctx->gpr: what it assigns (r = spu_rdch(..)) must survive the reload after it.
            item("barrier", f"ctx->pc = 0x{addr:X}u; @FL@ {s} @RL@")
        item("exit", "@FL@ return;   /* the chunk's end: the original function returned here */", fall=False)
    n_it = len(items)
    lab_ix = {it["text"]: i for i, it in enumerate(items) if it["kind"] == "label"}
    succ = []
    for i, it in enumerate(items):
        sx = [lab_ix[t] for t in it["targets"]]
        if it["fall"] and i + 1 < n_it:
            sx.append(i + 1)
        succ.append(sx)
    preds = [[] for _ in range(n_it)]
    for i, sx in enumerate(succ):
        for j in sx:
            preds[j].append(i)
    # ---- forward: registers whose local may differ from ctx->gpr (written since the last store) ----
    d_in, d_out = [0] * n_it, [0] * n_it
    def d_transfer(i, x):
        it = items[i]; kd = it["kind"]
        if kd == "pure": return x | it["defs"]
        if kd == "direct": return x | it["pre"]
        if kd in ("call", "barrier"): return 0
        return x
    work = list(range(n_it))
    while work:
        i = work.pop()
        x = 0
        for p in preds[i]:
            x |= d_out[p]
        d_in[i] = x
        y = d_transfer(i, x)
        if y != d_out[i]:
            d_out[i] = y
            work.extend(succ[i])
    flm = [0] * n_it   # what each item stores before leaving
    for i, it in enumerate(items):
        if it["kind"] in ("direct", "call"):
            flm[i] = d_in[i] | it["pre"]
        elif it["kind"] in ("condexit", "exit", "barrier"):
            flm[i] = d_in[i]
    # ---- backward: registers read before being written again (what must be loaded) ----
    l_in, l_out = [0] * n_it, [0] * n_it
    def l_transfer(i, x):
        it = items[i]; kd = it["kind"]
        if kd == "pure": return it["reads"] | (x & ~it["defs"])
        if kd in ("call", "exit"): return it["reads"] | flm[i]
        if kd == "barrier": return flm[i]
        return it["reads"] | flm[i] | x          # label, goto, direct, condexit
    work = list(range(n_it))
    while work:
        i = work.pop()
        x = 0
        for j in succ[i]:
            x |= l_in[j]
        l_out[i] = x
        y = l_transfer(i, x)
        if y != l_in[i]:
            l_in[i] = y
            work.extend(preds[i])
    st = lambda m: " ".join(f"ctx->gpr[{r}] = SPUL_U(r{r});" for r in regs_of(m))
    ld = lambda m: " ".join(f"r{r} = SPUL_V(ctx->gpr[{r}]);" for r in regs_of(m))
    used = 0
    for it in items:
        used |= it["reads"] | it["defs"] | it["pre"]
    for i in range(n_it):
        used |= flm[i] | l_in[i]
    out.append(f"void {G}(spu_context* ctx) {{")
    out.append("    uint8_t* const _lsb = ctx->ls; (void)_lsb;   /* spu lsb */")
    if used:
        out.append("    spul_v " + ", ".join(f"r{r}" for r in regs_of(used)) + ";")
    out.append("    switch (ctx->pc & SPU_LS_MASK) {")
    for f in g:
        out.append(f"    case 0x{f[1]:X}u: {ld(l_in[lab_ix[f'E_{f[1]:08X}']])} goto E_{f[1]:08X};")
    out.append(f"    default: spu_fastlift_bad_entry(ctx, \"{G}\"); SPU_TAILCALL({g[0][0]}(ctx));")
    out.append("    }")
    for i, it in enumerate(items):
        if it["kind"] == "label":
            out.append(it["text"] + ":"); continue
        t = it["text"].replace("@FL@", st(flm[i]))
        t = t.replace("@RL@", ld(l_out[i]))
        out.append("    " + t)
    out.append("}")
    out.append("")

decl = [f"void {gname[g[0][0]]}(spu_context* ctx);" for g in groups]
decl += [f"void {wrap(f[0])}(spu_context* ctx);" for f in funcs]
wrappers = [f"void {wrap(f[0])}(spu_context* ctx) {{ ctx->pc = 0x{f[1]:X}u; SPU_TAILCALL({gname[f[0]]}(ctx)); }}"
            for f in funcs]
table = re.search(r"static const spu_func_entry spu_function_table\[\] = \{\n(.*?)\n\};", text, re.S)
if not table:
    sys.exit(f"{src}: no function table")
rows = []
for row in table.group(1).split("\n"):
    m = re.match(r"\s*\{ (0x[0-9A-F]+u), (\w+), (\"\w+\") \},", row)
    if m:
        fn = m.group(2)
        rows.append(f"    {{ {m.group(1)}, {wrap(fn) if fn in by_name else fn}, {m.group(3)} }},")
rows.append("    { 0, NULL, NULL }")
mod = reg_m.group(1)
new_reg = f'''
void {mod}_spu_recomp_register(void) {{
    const char* e = getenv("SPU_FASTLIFT");
    const int on = !(e && e[0] == '0');
    static int said;
    if (!said) {{ said = 1; fprintf(stderr, "[spu] fastlift %s: %s\\n", "{mod}", on ? "on" : "off (SPU_FASTLIFT=0)"); }}
    for (const spu_func_entry* t = on ? spu_function_table_L : spu_function_table, *e2 = t; e2->func; ++e2)
        spu_register_function(e2->addr, e2->func);
}}
'''
body = text[: reg_m.start()] + "\n" + text[reg_m.end():]
extra = ["", "/* ---- spu fastlift (tools/spu_fastlift.py): registers in locals, chunks grouped, gotos ---- */",
         "#include <stdio.h>", "#include <stdlib.h>", "#include <string.h>",
         "typedef uint32_t spul_v __attribute__((vector_size(16)));",
         "typedef uint16_t spul_h __attribute__((vector_size(16)));",
         "static inline __attribute__((always_inline)) spul_v SPUL_V(u128 x) { spul_v v; memcpy(&v, &x, 16); return v; }",
         "static inline __attribute__((always_inline)) u128 SPUL_U(spul_v v) { u128 x; memcpy(&x, &v, 16); return x; }",
         "static __attribute__((noinline, cold)) void spu_fastlift_bad_entry(spu_context* ctx, const char* g) {",
         "    static int n; if (n++ < 8) fprintf(stderr, \"[spu] fastlift: %s entered at pc 0x%05X, not a chunk: original code\\n\", g, ctx->pc & SPU_LS_MASK);",
         "}"] + decl + [""] + out + wrappers + [
         "", "static const spu_func_entry spu_function_table_L[] = {"] + rows + ["};", new_reg]
if not os.path.exists(orig):
    os.replace(src, orig)
open(src, "w").write(body + "\n".join(extra))
print(f"{src}: {len(funcs)} chunks in {len(groups)} groups (largest {max(sum(len(f[2]) for f in g) for g in groups)} lines)")
