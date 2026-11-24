#!/usr/bin/env python3
"""gpatch engine: puts community RPCS3 game patches (code patches) into the GENERATED lifted C++ of a port
(~/<game>/infamous2-lle/recompiled/ppu_recomp_NNN.cpp) as native statements behind a run-time flag,
the way tools/patch_if1_unstable_audio.py does it. Used by gpatch_apply_<game>.py (which holds the sites).

The lifter writes one statement line per PowerPC instruction, in address order, after a label `loc_XXXXXXXX:`
(every branch target) or a function header `void func_XXXXXXXX(ppu_context* ctx) {`; the callee-save copies
(`uint64_t _cs_N = ...`) after a header are not instructions. So the statement for guest address A is found by
walking from the nearest anchor L <= A, counting (A - L) / 4 statements. Every copy of the anchor (the lifter
duplicates functions and shared tails) is visited; each copy whose statements match the expected text exactly
is patched, a copy that does not match makes the whole run refuse (nothing is written).

An edit replaces the n statements of a site with
    <ind>if (g_gpatch[K]) {   /* gpatch <id>@<addr> on */
    <ind>    if (!(g_gpatch[K] & 2)) gpatch_first_fire(K);
    <ind>    <native lines>
    <ind>} else {   /* gpatch <id>@<addr> orig */
    <the original lines, verbatim>
    <ind>}   /* gpatch <id>@<addr> end */
so `revert` restores the file byte for byte, and `apply` twice is a no-op (a site already carrying its marker is
counted as done). Each touched file gets a two-line declaration block after its `#include "ppu_recomp.h"`.

usage: gpatch_apply_<game>.py apply|check|revert <recompiled dir> [--only id,id] [--files f1,f2]
  check : locate + verify every site, print what would change, write nothing (dry run)
  apply : check, then write (all sites or none)
  revert: remove every gpatch edit (all ids, or --only) and the declaration block when no site is left
Input is the generated C++ only; nothing is executed from it.
"""
import os, re, sys, glob

DECL_TAG = "/* gpatch decls */"
DECL = ['extern "C" unsigned char g_gpatch[];   ' + DECL_TAG,
        'extern "C" void gpatch_first_fire(int k);   ' + DECL_TAG]
HDR_RE = re.compile(r'^void func_([0-9A-F]{8})\(ppu_context\* ctx\) \{$')
LOC_RE = re.compile(r'^loc_([0-9A-F]{8}):$')
GP_ON = re.compile(r'/\* gpatch (\S+)@0x([0-9A-F]{8}) on \*/$')
GP_ORIG = re.compile(r'/\* gpatch (\S+)@0x([0-9A-F]{8}) orig \*/$')
GP_END = re.compile(r'/\* gpatch (\S+)@0x([0-9A-F]{8}) end \*/$')
MAX_BACK = 0x2000   # how far before a site its anchor may be


def is_stmt(l):
    """Does this line hold one lifted instruction?"""
    s = l.strip()
    if not s or s.startswith('#') or s.startswith('//'):
        return False
    if s.startswith('uint64_t _cs_'):
        return False
    if s.startswith('/*') and s.endswith('*/') and not s.endswith(';'):   # comment only
        return False
    if s == 'if (g_if1_unst_audio) return;   /* if1 unstable audio */':   # an inserted line, not an instruction
        return False
    return True


def walk(L, i0, count):
    """From anchor line i0, the index of the line holding statement number `count` (0-based); None if the
    function or block ends first. gpatch blocks count as their original lines."""
    i, k, n = i0 + 1, 0, len(L)
    while i < n:
        l = L[i]
        if l.startswith('loc_') or l.startswith('void func_') or l.startswith('}'):
            return None
        if GP_ON.search(l):                 # skip the native half
            while i < n and not GP_ORIG.search(L[i]):
                i += 1
            i += 1
            continue
        if GP_END.search(l):
            i += 1
            continue
        if is_stmt(l):
            if k == count:
                return i
            k += 1
        i += 1
    return None


def stmts_from(L, i, n):
    """n statement lines starting at line i (i holds a statement); list of line indices, None if cut short
    by a label/function end/another gpatch block (a branch into the middle of the site)."""
    out = []
    while len(out) < n and i < len(L):
        l = L[i]
        if l.startswith('loc_') or l.startswith('void func_') or l.startswith('}'):
            return None
        if GP_ON.search(l) or GP_END.search(l) or GP_ORIG.search(l):
            return None
        if is_stmt(l):
            out.append(i)
        elif l.strip():
            return None                     # a preprocessor/comment line inside a site: not handled
        i += 1
    return out if len(out) == n else None


GOTO_RE = re.compile(r'goto (loc_[0-9A-F]{8});')


def missing_labels(L, i, site):
    """Labels the native lines jump to that the enclosing lifted function lacks."""
    want = set()
    for _, new in site.variants:
        for x in new:
            want.update(GOTO_RE.findall(x))
    if not want:
        return []
    a = i
    while a > 0 and not L[a].startswith('void func_'):
        a -= 1
    b = i
    while b < len(L) and not L[b].startswith('}'):
        b += 1
    have = set(l[:-1] for l in L[a:b] if l.startswith('loc_') and l.endswith(':'))
    return sorted(want - have)


class Site:
    """One patched spot. `variants` = [(toggle id, [native lines]), ...]: several toggles that rewrite the same
    instructions (jump x2/x5/x10, ...) share one site; the run-time code lets only one of them be on."""
    def __init__(self, tid, addr, expect, variants, note=''):
        self.id, self.addr, self.note = tid, addr, note
        self.expect = [re.compile(e) for e in expect]
        self.variants = variants if isinstance(variants[0], tuple) else [(tid, variants)]
        self.n = len(expect)


def index_anchors(files, sites):
    """{anchor addr: [(file, line index)]} for anchors within MAX_BACK before any site."""
    want = set()
    for s in sites:
        a = s.addr
        while a >= s.addr - MAX_BACK:
            want.add(a)
            a -= 4
    idx = {}
    for f in files:
        with open(f, encoding='utf-8', errors='surrogateescape') as fh:
            for ln, l in enumerate(fh):
                if l[0:4] == 'loc_' or l[0:10] == 'void func_':
                    m = LOC_RE.match(l.rstrip('\n')) or HDR_RE.match(l.rstrip('\n'))
                    if m:
                        a = int(m.group(1), 16)
                        if a in want:
                            idx.setdefault(a, []).append((f, ln))
    return idx


def main(game, sites, ids_order):
    argv = sys.argv[1:]
    if len(argv) < 2 or argv[0] not in ('apply', 'check', 'revert'):
        sys.exit(__doc__)
    mode, R = argv[0], argv[1]
    only = None
    if '--only' in argv:
        only = set(argv[argv.index('--only') + 1].split(','))
    files = sorted(glob.glob(os.path.join(R, 'ppu_recomp_[0-9][0-9][0-9].cpp')))
    if '--files' in argv:
        keep = set(argv[argv.index('--files') + 1].split(','))
        files = [f for f in files if os.path.basename(f) in keep]
    if not files:
        sys.exit('gpatch %s: no ppu_recomp_NNN.cpp in %s' % (game, R))
    K = {t: k for k, t in enumerate(ids_order)}
    sites = [s for s in sites if only is None or s.id in only or any(v in only for v, _ in s.variants)]
    for s in sites:
        for v, _ in s.variants:
            if v not in K:
                sys.exit('gpatch %s: toggle %s has no flag index' % (game, v))
    cache = {}

    def lines(f):
        if f not in cache:
            with open(f, encoding='utf-8', errors='surrogateescape') as fh:
                cache[f] = fh.read().split('\n')
        return cache[f]

    if mode == 'revert':
        nrev = 0
        for f in files:
          for _pass in range(8):          # nested edits come out one level per pass
            with open(f, encoding='utf-8', errors='surrogateescape') as fh:
                t = fh.read()
            if 'gpatch' not in t:
                break
            L = t.split('\n')
            out, i, changed = [], 0, False
            while i < len(L):
                m = GP_ON.search(L[i])
                if m and (only is None or m.group(1) in only):
                    tag = '%s@0x%s' % (m.group(1), m.group(2))
                    j = i
                    while not GP_ORIG.search(L[j]):
                        j += 1
                    k = j + 1
                    while not (GP_END.search(L[k]) and tag in L[k]):
                        k += 1
                    out.extend(L[j + 1:k])
                    i = k + 1
                    nrev += 1
                    changed = True
                    continue
                out.append(L[i])
                i += 1
            if not any(GP_ON.search(l) for l in out):
                out2 = [l for l in out if DECL_TAG not in l]
                changed = changed or len(out2) != len(out)
                out = out2
            if changed:
                with open(f, 'w', encoding='utf-8', errors='surrogateescape') as fh:
                    fh.write('\n'.join(out))
                print('gpatch %s: reverted %s' % (game, os.path.basename(f)))
            else:
                break
        print('gpatch %s: %d site copies reverted' % (game, nrev))
        return 0

    idx = index_anchors(files, sites)
    plan, errors, done = [], [], 0
    for s in sites:
        tag = '%s@0x%08X' % (s.id, s.addr)
        found = 0
        # already applied copies
        seen = set()
        a = s.addr
        while a >= s.addr - MAX_BACK:
            for (f, ln) in idx.get(a, []):
                L = lines(f)
                i = walk(L, ln, (s.addr - a) // 4)
                if i is None:
                    continue
                # an already patched copy: the statement walk lands inside the orig half of our own block
                j = i
                while j > 0 and not GP_ORIG.search(L[j]) and is_stmt(L[j]) and not L[j].startswith('loc_'):
                    j -= 1
                if GP_ORIG.search(L[j]) and tag in L[j]:
                    if (f, j) not in seen:
                        seen.add((f, j))
                        done += 1
                        found += 1
                    continue
                st = stmts_from(L, i, s.n)
                if st is None:
                    errors.append('%s: %s line %d: site cut by a label/other edit' % (tag, os.path.basename(f), i + 1))
                    continue
                bad = [(q, L[q].strip()) for q, rx in zip(st, s.expect) if not rx.search(L[q].strip())]
                if bad:
                    errors.append('%s: %s line %d: generated code differs: %s' % (tag, os.path.basename(f), bad[0][0] + 1, bad[0][1][:140]))
                    continue
                miss = missing_labels(L, st[0], s)
                if miss:
                    errors.append('%s: %s line %d: native code jumps to %s, not a label in this function' % (
                        tag, os.path.basename(f), st[0] + 1, ' '.join(miss)))
                    continue
                if (f, st[0]) not in seen:
                    seen.add((f, st[0]))
                    plan.append((s, f, st))
                    found += 1
            a -= 4
        if found == 0:
            errors.append('%s: no copy of this site found (anchor missing or every copy differs)' % tag)
        else:
            print('gpatch %s: %-34s 0x%08X  %d cop%s%s' % (game, s.id, s.addr, found, 'y' if found == 1 else 'ies',
                                                         '' if not s.note else '  (' + s.note + ')'))
    if errors:
        print('gpatch %s: REFUSED, nothing written:' % game)
        for e in errors:
            print('  ' + e)
        return 2
    by_file = {}
    for s, f, st in plan:
        by_file.setdefault(f, []).append((s, st))
    for f, items in by_file.items():
        L = lines(f)
        for s, st in sorted(items, key=lambda x: -x[1][0]):      # bottom up: indices stay valid
            tag = '%s@0x%08X' % (s.id, s.addr)
            ind = L[st[0]][:len(L[st[0]]) - len(L[st[0]].lstrip())]
            ks = [K[v] for v, _ in s.variants]
            block = ['%sif (%s) {   /* gpatch %s on */' % (ind, ' | '.join('g_gpatch[%d]' % k for k in ks), tag)]
            for vi, (v, new) in enumerate(s.variants):
                k = K[v]
                if len(s.variants) > 1:
                    block.append('%s    %s {   /* %s */' % (ind, 'if (g_gpatch[%d])' % k if vi == 0 else
                                                          '} else if (g_gpatch[%d])' % k if vi < len(s.variants) - 1 else '} else', v))
                    pre = ind + '        '
                else:
                    pre = ind + '    '
                block.append('%sif (!(g_gpatch[%d] & 2)) gpatch_first_fire(%d);' % (pre, k, k))
                block += [pre + x for x in new]
            if len(s.variants) > 1:
                block.append(ind + '    }')
            block += ['%s} else {   /* gpatch %s orig */' % (ind, tag)]
            block += [L[q] for q in range(st[0], st[-1] + 1)]
            block += ['%s}   /* gpatch %s end */' % (ind, tag)]
            if mode == 'check':
                print('--- %s line %d (%s)' % (os.path.basename(f), st[0] + 1, tag))
                print('\n'.join(block))
            L[st[0]:st[-1] + 1] = block
        if not any(DECL_TAG in l for l in L[:400]):
            inc = next((i for i, l in enumerate(L[:50]) if l.startswith('#include "ppu_recomp.h"')), None)
            if inc is None:
                print('gpatch %s: REFUSED: %s has no #include "ppu_recomp.h"' % (game, os.path.basename(f)))
                return 2
            L[inc + 1:inc + 1] = DECL
    if mode == 'apply':
        for f in by_file:
            tmp = f + '.gpatch.tmp'
            with open(tmp, 'w', encoding='utf-8', errors='surrogateescape') as fh:
                fh.write('\n'.join(cache[f]))
            os.replace(tmp, f)
    print('gpatch %s: %s: %d site copies %s, %d already in place, files: %s' % (
        game, mode, len(plan), 'written' if mode == 'apply' else 'to write', done,
        ' '.join(sorted(os.path.basename(f) for f in by_file)) or '-'))
    return 0
