# eng texhash stable: a texture whose full content hash has matched 8 checks running is fully re-hashed
# every 32nd frame (a small one every 8th) instead of every 8th (small: every frame); the sampled check
# still runs every frame and any change -- sampled or full -- puts it back on the fast cadence. A
# whole-texture rewrite (video frame, streamed replacement, UI redraw) is caught the same frame as before;
# a small partial write into a long-unchanged texture can take up to 32 frames. The texture change hashes
# were ~7% of the RSX thread on inFAMOUS 1's route once the casters were replayed (2026-11-05).
# PS3RECOMP_ENG_TEXHASH_STABLE=0 = old.
import sys
C = __import__("os").path.expanduser("~") + "/if2/ps3recomp-fork/libs/video/rsx_draw_engine.c"
c = open(C).read()
if "eng texhash stable" in c: print("already"); sys.exit(0)
def edit(s, old, new):
    if s.count(old) != 1: print("NOT FOUND/UNIQUE:", old[:80]); sys.exit(1)
    return s.replace(old, new)
c = edit(c, '''    u32 last_full_frame;        /* the last full content hash (eng_texture_get) */''',
'''    u32 last_full_frame;        /* the last full content hash (eng_texture_get) */
    u8 th_stable;               /* eng texhash stable: full hashes in a row that matched */''')
c = edit(c, '''            const int full = full_always || span <= 16384u || g.frames - e->last_full_frame >= 8u;''',
'''            static int th_st = -1;   /* eng texhash stable */
            if (th_st < 0) { const char* ev = getenv("PS3RECOMP_ENG_TEXHASH_STABLE"); th_st = !(ev && *ev == '0'); }
            const int settled = th_st && e->th_stable >= 8u;
            const int full = full_always || (span <= 16384u && !settled) ||
                             g.frames - e->last_full_frame >= (settled ? (span <= 16384u ? 8u : 32u) : 8u);''')
c = edit(c, '''            if (readable && (full || sparse != e->sparse_hash)) {
                hash = eng_texture_content_hash(location, offset, span, &readable);
                e->last_full_frame = g.frames;
            }''', '''            if (readable && (full || sparse != e->sparse_hash)) {
                if (sparse != e->sparse_hash) e->th_stable = 0;   /* eng texhash stable */
                hash = eng_texture_content_hash(location, offset, span, &readable);
                e->last_full_frame = g.frames;
                if (readable) e->th_stable = hash == e->content_hash ? (u8)(e->th_stable < 255u ? e->th_stable + 1u : 255u) : 0u;
            }''')
open(C, "w").write(c); print("patched")
