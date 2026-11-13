#!/usr/bin/env python3
"""SPU register caching for lifted SPU code (spu_lifter.py output), in place.

The lifter writes every SPU register access as ctx->gpr[N]. The registers are memory then, and
since local store goes through a uint8_t pointer (-fno-strict-aliasing as well), every LS store
may alias them: the compiler stores each result to ctx->gpr and reloads every operand. This pass
gives each lifted function locals G<N> for the registers it uses:

  - loaded from ctx->gpr at entry;
  - written back (the registers the function assigns) before any statement that calls something
    with ctx itself (the runtime, another lifted function, SPU_DIRECT / SPU_RET, channel I/O),
    before a return, and at the end of the body;
  - reloaded after a call that returns here, except a register the statement itself assigns
    (its value comes from the call: `G3 = spu_rdch(ctx, 29)` keeps the new G3).

spu_ls_read128 / spu_ls_write128 take ctx only for ctx->ls; they are not barriers.
A file is marked once done ("spu regcache" in its first line) and left alone after.

  spu_regcache.py <spu dir> [...]    every */spu_recomp.c below each dir
"""
import re, sys, os, glob

MARK = "/* spu regcache: SPU registers in locals (tools/spu_regcache.py) */\n"
FUNC_RE = re.compile(r'^void ([A-Za-z_][A-Za-z0-9_]*)\(spu_context\* ctx\) \{\n(.*?)^\}\n', re.S | re.M)
GPR_RE = re.compile(r'ctx->gpr\[(\d+)\]')
ASSIGN_RE = re.compile(r'ctx->gpr\[(\d+)\](?:\._[a-z0-9]+\[\d+\])?\s*=(?!=)')
CALL_RE = re.compile(r'\b([A-Za-z_][A-Za-z0-9_]*)\(ctx\s*[,)]')
LABEL_RE = re.compile(r'^(\s*(?:loc_[0-9A-Fa-f]+:\s*)+)')
NOT_BARRIER = {"spu_ls_read128", "spu_ls_write128"}
EXITS = {"SPU_DIRECT", "SPU_RET", "SPU_RET_REG"}


def fragments(body):
    """Split a body into statements (ending ';') and the brace tokens, comments kept in place."""
    out, cur, depth, i, n = [], [], 0, 0, len(body)
    while i < n:
        c = body[i]
        if body.startswith("/*", i):
            j = body.find("*/", i + 2)
            j = n if j < 0 else j + 2
            cur.append(body[i:j]); i = j; continue
        if c == '"' or c == "'":
            j = i + 1
            while j < n and body[j] != c:
                j += 2 if body[j] == '\\' else 1
            cur.append(body[i:j + 1]); i = j + 1; continue
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
        if depth == 0 and c in "{}":
            if cur: out.append(("text", "".join(cur))); cur = []
            out.append(("brace", c)); i += 1; continue
        cur.append(c)
        if depth == 0 and c == ';':
            out.append(("stmt", "".join(cur))); cur = []
        i += 1
    if cur:
        out.append(("text", "".join(cur)))
    return out


def transform_body(body):
    used = sorted({int(m) for m in GPR_RE.findall(body)})
    if not used:
        return None
    written = sorted({int(m) for m in ASSIGN_RE.findall(body)})
    flush = "".join("ctx->gpr[%d] = G%d; " % (r, r) for r in written)
    out = ["    u128 " + ", ".join("G%d = ctx->gpr[%d]" % (r, r) for r in used) + ";\n"]
    for kind, t in fragments(body):
        if kind == "brace":
            out.append(t); continue
        if kind == "text":
            # an `if (...)` head before a block: reads registers, must not call anything with ctx
            if [m for m in CALL_RE.findall(t) if m not in NOT_BARRIER] or re.search(r'\breturn\b', t):
                return None
            out.append(GPR_RE.sub(r'G\1', t)); continue
        calls = [m for m in CALL_RE.findall(t) if m not in NOT_BARRIER]
        is_return = re.search(r'\breturn\b', t) is not None
        if not calls and not is_return:
            out.append(GPR_RE.sub(r'G\1', t)); continue
        lab = LABEL_RE.match(t)
        prefix, core = (lab.group(1), t[lab.end():]) if lab else ("", t)
        # leading whitespace stays outside the block
        ws = re.match(r'^\s*', core).group(0)
        core = core[len(ws):]
        dests = {int(m) for m in ASSIGN_RE.findall(core)}
        exits = is_return or any(c in EXITS for c in calls)
        reload = "" if exits else "".join("G%d = ctx->gpr[%d]; " % (r, r) for r in used if r not in dests)
        out.append(prefix + ws + "{ " + flush + GPR_RE.sub(r'G\1', core) + " " + reload + "}")
    out.append("    " + flush + "\n")
    return "".join(out)


def transform_file(path):
    src = open(path).read()
    if src.startswith(MARK) or "spu regcache" in src[:200]:
        return 0
    count = [0]
    def fn(m):
        nb = transform_body(m.group(2))
        if nb is None:
            return m.group(0)
        count[0] += 1
        return "void %s(spu_context* ctx) {\n%s}\n" % (m.group(1), nb)
    out = FUNC_RE.sub(fn, src)
    if not os.path.exists(path + ".orig"):
        open(path + ".orig", "w").write(src)
    open(path, "w").write(MARK + out)
    return count[0]


if __name__ == "__main__":
    total = files = 0
    for d in sys.argv[1:]:
        for p in sorted(glob.glob(os.path.join(d, "*", "spu_recomp.c"))):
            n = transform_file(p)
            total += n; files += 1 if n else 0
    print("spu regcache: %d functions in %d files" % (total, files))
