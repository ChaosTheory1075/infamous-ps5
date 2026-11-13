# eng rt filter: sink_bind_textures scanned every depth buffer (twice) and every render target for each
# sampled unit, to find textures that are really a GPU-rendered target -- most are not. A 4096-bit set
# keyed by (location, offset) gets a bit whenever a render target or a depth buffer takes an address;
# bits are never cleared (a stale bit only means the old scans), so a clear bit proves no scan can match
# and they are skipped. Part of the texture stage that DRAWSTATS put at ~750 ns a draw on inFAMOUS 1's
# route (2026-11-05). Off with PS3RECOMP_ENG_TEX_LITE=0.
import sys, re
C = __import__("os").path.expanduser("~") + "/if2/ps3recomp-fork/libs/video/rsx_draw_engine.c"
c = open(C).read()
if "eng rt filter" in c: print("already"); sys.exit(0)
def edit(s, old, new):
    if s.count(old) != 1: print("NOT FOUND/UNIQUE:", old[:80]); sys.exit(1)
    return s.replace(old, new)
c = edit(c, '''static u64 eng_fnv1a(const void* data, u32 n, u64 hash)
{''', '''/* eng rt filter: addresses a render target or depth buffer has had */
static u64 s_rtf[64];
static inline u32 eng_rtf_bit(u32 location, u32 offset) { return ((offset ^ (location << 31)) * 2654435761u) >> 20; }
static inline void eng_rtf_add(u32 location, u32 offset) { const u32 b = eng_rtf_bit(location, offset); s_rtf[b >> 6] |= 1ull << (b & 63u); }
static inline int eng_rtf_maybe(u32 location, u32 offset) { const u32 b = eng_rtf_bit(location, offset); return (int)((s_rtf[b >> 6] >> (b & 63u)) & 1u); }

static u64 eng_fnv1a(const void* data, u32 n, u64 hash)
{''')
c = edit(c, '''    s->location = location; s->offset = offset;
    s->w = want_w; s->h = want_h; s->fmt = want_fmt;''', '''    s->location = location; s->offset = offset;
    eng_rtf_add(location, offset);   /* eng rt filter */
    s->w = want_w; s->h = want_h; s->fmt = want_fmt;''')
c = edit(c, '''    z->location = location; z->offset = offset;
    z->w = want_w; z->h = want_h;''', '''    z->location = location; z->offset = offset;
    eng_rtf_add(location, offset);   /* eng rt filter */
    z->w = want_w; z->h = want_h;''')
# inside sink_bind_textures only
i = c.index("static u32 sink_bind_textures(")
j = c.index("\n}\n", i)
body = c[i:j]
body = edit(body, '''        if (!t.enabled || !(fp_reads >> u & 1u)) continue;
        mask |= 1u << u;''', '''        if (!t.enabled || !(fp_reads >> u & 1u)) continue;
        mask |= 1u << u;
        const int rtm = !lite || eng_rtf_maybe(t.location, t.offset);   /* eng rt filter */''')
n1 = body.count("for (u32 i = 0; i < g.n_zdepths; i++)")
n2 = body.count("for (u32 i = 0; i < g.n_surfaces; i++)")
body = body.replace("for (u32 i = 0; i < g.n_zdepths; i++)", "for (u32 i = 0; rtm && i < g.n_zdepths; i++)")
body = body.replace("for (u32 i = 0; i < g.n_surfaces; i++)", "for (u32 i = 0; rtm && i < g.n_surfaces; i++)")
c = c[:i] + body + c[j:]
open(C, "w").write(c); print(f"patched ({n1} depth scans, {n2} target scans guarded)")
