/* ba vs delta (2026-11-11; PS3_BA_VS_DELTA, default 0 = off): only the vertex-constant rows that changed go
 * into the be-async queue.
 *
 * Today every draw's bind_vs_constants_range copies the whole row range its program reads (~2.28 KB, 13-17 MB a
 * frame) from the engine's rsx_dispatch.constants[512][4] into the queue (rsx_be_async.c px_vs_range) and the
 * worker copies it again into its persistent row array s_vs_rows before calling the backend with that array.
 * Between two draws the game rewrites only a few rows.
 *
 * The map: g_rsx_vsd_stale, one bit per row (512 rows of 16 bytes = RSX_DSP_NUM_CONSTANTS vec4). Bit set = the
 * worker's s_vs_rows row may differ from the engine's row, as of the queue's end. Invariant: bit clear =>
 * the worker, when it replays the next queued op, has exactly the engine's current bytes for that row.
 *  - set by EVERY writer of the constant array (rsx_dispatch.c: the 0x1F00 window in rsx_dispatch_method -- which
 *    the per-word walker, gcm fast words, the 0x1EFC load of gcm const fast, gcm fast2's non-plain words and every
 *    other subchannel reach --, rsx_dispatch_const_words (gcm const fast bursts), rsx_dispatch_init (memset: all),
 *    rsx_dispatch_seed_transform_constants (live draw's own instance: all, conservative)) when the value changes;
 *  - all set at start, at the proxy's init/shutdown and when the engine hands in another array;
 *  - cleared by the proxy only for rows it queues (rows in the draw's range whose bit is set). A row changed while
 *    outside one draw's range keeps its bit and goes with the first later draw whose range includes it.
 * Rows outside every range are never sent; the worker's copy then holds what it would hold today (the value at
 * the last draw whose range covered it), so s_vs_rows is the same as today's at every replayed op, all 512 rows.
 *
 * Packed delta: runs, each a u32 (start | len << 16) followed by len * 16 bytes of row data. */
#ifndef RSX_VS_DELTA_H
#define RSX_VS_DELTA_H
#include <string.h>

#define VSD_ROWS  512u
#define VSD_WORDS (VSD_ROWS / 64u)

extern unsigned long long g_rsx_vsd_stale[VSD_WORDS];   /* rsx_dispatch.c; FIFO-walker thread only (see rsx_be_async.c) */
extern int g_rsx_vsd_track;                             /* rsx_dispatch.c: writers mark (PS3_BA_VS_DELTA=1/2, read at init) */

/* writers: row `slot` (< VSD_ROWS, checked by the caller) gets `nv` where it held `ov`; branch-free */
#define VSD_MARK_IF_CHANGED(slot, ov, nv) \
    (g_rsx_vsd_stale[(slot) >> 6] |= (unsigned long long)((ov) != (nv)) << ((slot) & 63u))
/* writers: bits (bit j = row r0 + j; rows mod 512, so a u32 wrap or a base past 511 still lands right) ORed into
 * the map's two words that rows r0..r0+63 can touch; branch-free */
#define VSD_OR_RUN(r0, bits) \
    ((void)(g_rsx_vsd_stale[((r0) >> 6) & (VSD_WORDS - 1u)] |= (bits) << ((r0) & 63u)), \
     (void)(g_rsx_vsd_stale[(((r0) >> 6) + 1u) & (VSD_WORDS - 1u)] |= ((bits) >> 1) >> (63u - ((r0) & 63u))))

static inline void vsd_mark(unsigned long long* bm, unsigned row)
{
    if (row < VSD_ROWS) bm[row >> 6] |= 1ull << (row & 63u);
}
static inline void vsd_mark_all(unsigned long long* bm)
{
    memset(bm, 0xFF, VSD_WORDS * sizeof *bm);   /* a call, not a loop: rsx_dispatch_init keeps its PGO profile */
}
/* first row in [pos, end) whose bit is `set` (1/0); end if none */
static inline unsigned vsd_find(const unsigned long long* bm, unsigned pos, unsigned end, int set)
{
    while (pos < end) {
        const unsigned w = pos >> 6;
        unsigned long long v = set ? bm[w] : ~bm[w];
        v &= ~0ull << (pos & 63u);
        if (v) { const unsigned p = (w << 6) + (unsigned)__builtin_ctzll(v); return p < end ? p : end; }
        pos = (w + 1u) << 6;
    }
    return end;
}
static inline void vsd_clear(unsigned long long* bm, unsigned lo, unsigned hi)   /* rows [lo, hi) */
{
    while (lo < hi) {
        const unsigned w = lo >> 6, b = lo & 63u, n = (hi - lo < 64u - b) ? hi - lo : 64u - b;
        const unsigned long long m = (n == 64u ? ~0ull : ((1ull << n) - 1ull)) << b;
        bm[w] &= ~m; lo += n;
    }
}
/* stale rows / runs inside [first, first + count) (first + count <= VSD_ROWS) */
static inline void vsd_measure(const unsigned long long* bm, unsigned first, unsigned count, unsigned* nrows, unsigned* nruns)
{
    const unsigned end = first + count;
    unsigned r = 0, k = 0, p = first;
    for (;;) {
        const unsigned s = vsd_find(bm, p, end, 1);
        if (s >= end) break;
        const unsigned e = vsd_find(bm, s, end, 0);
        r += e - s; k++; p = e;
    }
    *nrows = r; *nruns = k;
}
/* Writes the stale rows of [first, first + count) from `rows` (512 x 16 bytes) as runs into `out` and clears
 * their bits. Returns the bytes written (= nruns * 4 + nrows * 16 of vsd_measure). */
static inline unsigned vsd_pack(unsigned long long* bm, const unsigned char* rows, unsigned first, unsigned count, unsigned char* out)
{
    const unsigned end = first + count;
    unsigned char* o = out; unsigned p = first;
    for (;;) {
        const unsigned s = vsd_find(bm, p, end, 1);
        if (s >= end) break;
        const unsigned e = vsd_find(bm, s, end, 0);
        const unsigned hd = s | ((e - s) << 16);
        memcpy(o, &hd, 4); memcpy(o + 4, rows + (size_t)s * 16u, (size_t)(e - s) * 16u);
        o += 4u + (e - s) * 16u;
        vsd_clear(bm, s, e); p = e;
    }
    return (unsigned)(o - out);
}
/* Patches `dst` (512 x 16 bytes) with `nruns` packed runs; returns the bytes read (a run past row 512: stops). */
static inline unsigned vsd_apply(unsigned char* dst, const unsigned char* pk, unsigned nruns)
{
    const unsigned char* p = pk;
    for (unsigned i = 0; i < nruns; i++) {
        unsigned hd; memcpy(&hd, p, 4);
        const unsigned s = hd & 0xFFFFu, n = hd >> 16;
        if (s + n > VSD_ROWS) break;
        memcpy(dst + (size_t)s * 16u, p + 4, (size_t)n * 16u);
        p += 4u + n * 16u;
    }
    return (unsigned)(p - pk);
}
#endif
