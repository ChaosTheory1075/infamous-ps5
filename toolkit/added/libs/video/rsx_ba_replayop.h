/* ba replay op (2026-11-11; PS3_BA_REPLAY_OP, default 0 = off: every replay makes today's calls).
 *
 * A draw-fast / draw-fast-N / caster-fast replay binds its template's state again: bind_targets, bind_pipeline,
 * bind_ps_constants, bind_textures, bind_vertex_textures, set_viewport, set_scissor, set_stencil_ref and
 * set_depth_bias -- exactly the nine kinds the async proxy's dedup (PS3_BA_DEDUP, rsx_be_async.c DD_*) remembers
 * and drops when the arguments equal the last queued call of the same kind. ~5000 replays a frame make ~45000 such
 * calls, nearly all dropped, each still an indirect call, the dd_piece marshalling and a memcmp (328 bytes for the
 * textures) on the RSX thread.
 *
 * State epoch (rsx_be_async.c, producer side): g_rsx_ba_ro.ep is incremented whenever the dedup memory changes --
 * a kind recorded (dd_check queued it), a kind forgotten for being too big (DD_CAP), or everything forgotten
 * (dd_reset: every synchronous call through ba_drain, every queued op other than these nine kinds, the vertex
 * constants and the draws). dd_valid is the proxy's s_dd_valid (bit k = kind k's memory is good), need = the kinds
 * whose backend entry exists. Nothing else writes the memory (s_dd_valid / s_dd_buf / s_dd_len).
 *
 * A template carries a tag {ep, zb, zb_on} taken right after its binds were last sent (full path or replay):
 * ep = g_rsx_ba_ro.ep if every needed kind is valid then, else 0. At that moment each kind's memory holds the last
 * call of that kind, i.e. this template's argument (each kind is called once per draw, all nine after the last
 * reset). If ep is unchanged at the next replay of the same template, the memory has not changed since, and the
 * template's arguments have not changed either (written only at its record, which retakes the tag), so each of the
 * eight template calls would be dropped. The depth bias is computed per replay from the registers and switches: it
 * is skipped only when also equal to the tagged one (zb).
 *  =1: skip the eight (and the bias when equal); vertex-constant range, hud (none on Vulkan), clip, draw as today.
 *  =2 (verify): make every call as today; when =1 would have skipped, check each expected call was dropped
 *      (g_rsx_ba_ro.dropped moves: the proxy's own skip counter, independent of the epoch) and count/log the rest.
 * vk depth clamp (PS3RECOMP_VK_DEPTH_CLAMP=1, the only case with a set_depth_clamp entry on Vulkan): the clamp is a
 * tenth dedup kind (DD_ZCLAMP), not a reset. It is not in need and never skipped (eng_apply_depth_clip runs on every
 * replay, before the retag), but a changed clamp is a record and moves the epoch: draws that alternate clamp/clip
 * (shadow casters vs the scene) lose their skips across the change, never correctness.
 * Inert: be async off (the engine's s_eng_ro = 0 unless g.be is the proxy), PS3_BA_DEDUP=0 (mode 0). PS3_BA_DEDUP=2
 * queues every call, so =1 there would change what the worker replays: it runs as =2.
 * One producer thread (rsx_be_async.c PS3_BA_NOLOCK note): no atomics. */
#ifndef RSX_BA_REPLAYOP_H
#define RSX_BA_REPLAYOP_H

typedef struct {
    unsigned long long ep;        /* proxy: dedup memory epoch (incremented on every change; starts at 1) */
    unsigned long long dropped;   /* proxy: calls dedup dropped / would drop (s_dd_skip; reset per 300 presents) */
    unsigned dd_valid;            /* proxy: s_dd_valid */
    unsigned need;                /* proxy: DD kinds whose backend entry exists (set in wrap) */
    int mode;                     /* 0 off, 1 skip, 2 verify (rsx_be_async_wrap) */
    unsigned long long replays, sets, saved, miss;   /* engine: per 300 presents (printed by the proxy) */
    unsigned miss_logged;
} rsx_ba_ro;
extern rsx_ba_ro g_rsx_ba_ro;

typedef struct { unsigned long long ep; float zb[2]; int zb_on; } rsx_ro_tag;   /* per template; ep 0 = no skip */

/* The epoch to tag a template with now: 0 unless every needed kind is remembered. */
static inline unsigned long long rsx_ro_now(void)
{
    const rsx_ba_ro* r = &g_rsx_ba_ro;
    return (r->dd_valid & r->need) == r->need ? r->ep : 0ull;
}
/* 1 = nothing in the dedup memory changed since t was tagged. */
static inline int rsx_ro_match(const rsx_ro_tag* t) { return t->ep && t->ep == g_rsx_ba_ro.ep; }
static inline int rsx_ro_zsame(const rsx_ro_tag* t, int zon, const float zb[2])
{
    if (zon != t->zb_on) return 0;
    if (!zon) return 1;
    unsigned a[2], b[2]; __builtin_memcpy(a, zb, 8); __builtin_memcpy(b, t->zb, 8);   /* bytes: what dd_check compares */
    return a[0] == b[0] && a[1] == b[1];
}
static inline void rsx_ro_tag_now(rsx_ro_tag* t, int zon, const float zb[2])
{
    t->ep = rsx_ro_now(); t->zb_on = zon; t->zb[0] = zon ? zb[0] : 0.0f; t->zb[1] = zon ? zb[1] : 0.0f;
}
enum { RO_K_TARGETS, RO_K_PIPE, RO_K_PS, RO_K_TEX, RO_K_VTEX, RO_K_VP, RO_K_SC, RO_K_SREF, RO_K_ZBIAS, RO_K_N };
#endif
