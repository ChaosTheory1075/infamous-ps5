"""Error codes (0x8041xxxx / 0x8001xxxx) built in each libsre function of the LFQueue push path.
  python3 libsre_codes.py <func> ..."""
import re, sys
src = open(__import__("os").path.expanduser("~") + '/fob/infamous2-lle/lle/libsre/libsre_recomp_000.cpp').read()
funcs = {m.group(1): m.start() for m in re.finditer(r'void libsre_func_([0-9A-F]{8})\(ppu_context\* ctx\) \{', src)}
keys = sorted(funcs, key=lambda k: funcs[k])
for f in sys.argv[1:]:
    i = keys.index(f)
    b = src[funcs[f]:funcs[keys[i + 1]] if i + 1 < len(keys) else len(src)]
    out = []
    for m in re.finditer(r'\(uint32_t\)0x(80[0-9A-F]{2}) << 16\);\s*\n(?:[^\n]*\n){0,2}?[^\n]*\| (0x[0-9A-F]+);', b):
        out.append('0x%s%04X' % (m.group(1), int(m.group(2), 16)))
    print(f, sorted(set(out)))
