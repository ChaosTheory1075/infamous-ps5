# spu dma fast: SPU transfer plumbing on x86 (vector copies, no mfence, inline channel field writes)
# PC FoB no-draw profile: SPU threads spent ~38% in runtime plumbing. The three biggest single costs:
# (1) gm_copy_from/gm_copy_to moved every DMA 8 bytes per iteration (relaxed atomics never
#     vectorize) -- the hottest instruction of mfc_do_transfer and spu_overlay_note_get;
# (2) mfc_submit put a full mfence on both sides of every command -- needed on ARM64, where host
#     loads and stores reorder across addresses; x86 is TSO (loads stay ordered with loads, stores
#     with stores) and the atomic line ops (GETLLAR/PUTLLC) go through locked instructions, so a
#     compiler barrier keeps the same order. PS3_SPU_DMA_FENCE=1 restores the mfence;
# (3) every wrch of MFC_LSA/EAH/EAL/Size/TagID/WrTagMask (5-6 per DMA) was a call into spu_wrch
#     plus the engine-slot lookup, only to store one field. The lifted code passes those channels as
#     constants, so spu_helpers.h now stores the field inline; MFC_Cmd and every other channel still
#     call spu_wrch. -DSPU_NO_INLINE_WRCH turns it off (spu_channels.c, which defines spu_wrch).
# gm_equal (the reservation-line compare) also compares 32 bytes at a time on x86.
GMA = "runtime/memory/guest_mem_atomic.h"
edit(GMA,
     '''#define GM_RELAXED __ATOMIC_RELAXED
''',
     '''#define GM_RELAXED __ATOMIC_RELAXED
/* x86 (AVX2): bulk copies and compares 32 bytes at a time. An aligned 8-byte part of a vector
 * access is never torn on x86, which is all the per-word atomics below promise. */
#if defined(__x86_64__) && defined(__AVX2__) && !defined(GM_SCALAR_COPY)
#include <immintrin.h>
#define GM_X86_VEC 1
#endif
''',
     "spu dma fast: gm vec include")
edit(GMA,
     '''    for (; i < n && (((uintptr_t)(g + i)) & 7u); i++) d[i] = gm_load8(g + i);
    for (; i + 8 <= n; i += 8) { uint64_t v = gm_load64(g + i); memcpy(d + i, &v, 8); }''',
     '''    for (; i < n && (((uintptr_t)(g + i)) & 7u); i++) d[i] = gm_load8(g + i);
#ifdef GM_X86_VEC
    for (; i + 32 <= n; i += 32)
        _mm256_storeu_si256((__m256i*)(d + i), _mm256_loadu_si256((const __m256i*)(g + i)));
#endif
    for (; i + 8 <= n; i += 8) { uint64_t v = gm_load64(g + i); memcpy(d + i, &v, 8); }''',
     "spu dma fast: gm_copy_from")
edit(GMA,
     '''    for (; i < n && (((uintptr_t)(g + i)) & 7u); i++) gm_store8(g + i, s[i]);
    for (; i + 8 <= n; i += 8) { uint64_t v; memcpy(&v, s + i, 8); gm_store64(g + i, v); }''',
     '''    for (; i < n && (((uintptr_t)(g + i)) & 7u); i++) gm_store8(g + i, s[i]);
#ifdef GM_X86_VEC
    for (; i + 32 <= n; i += 32)
        _mm256_storeu_si256((__m256i*)(g + i), _mm256_loadu_si256((const __m256i*)(s + i)));
#endif
    for (; i + 8 <= n; i += 8) { uint64_t v; memcpy(&v, s + i, 8); gm_store64(g + i, v); }''',
     "spu dma fast: gm_copy_to")
edit(GMA,
     '''static inline int gm_equal(const uint8_t* g, const void* snap, size_t n)
{
    uint8_t buf[256];''',
     '''static inline int gm_equal(const uint8_t* g, const void* snap, size_t n)
{
#ifdef GM_X86_VEC
    if (((uintptr_t)g & 7u) == 0 && (n & 31u) == 0) {
        const uint8_t* s = (const uint8_t*)snap;
        for (size_t i = 0; i < n; i += 32) {
            const __m256i x = _mm256_loadu_si256((const __m256i*)(g + i));
            const __m256i y = _mm256_loadu_si256((const __m256i*)(s + i));
            if ((unsigned)_mm256_movemask_epi8(_mm256_cmpeq_epi8(x, y)) != 0xFFFFFFFFu) return 0;
        }
        return 1;
    }
#endif
    uint8_t buf[256];''',
     "spu dma fast: gm_equal")

DMA = "runtime/spu/spu_dma.h"
edit(DMA,
     '''static inline int mfc_submit(mfc_engine* mfc, spu_context* spu, uint32_t cmd)
{
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    int r = mfc_submit_body(mfc, spu, cmd);
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    return r;
}''',
     '''#if defined(__x86_64__)
/* x86 is TSO: a compiler barrier keeps the order above (spu_channels.c; PS3_SPU_DMA_FENCE=1 = mfence). */
extern volatile int g_spu_dma_fence;
#define MFC_SUBMIT_FENCE() do { if (__builtin_expect(g_spu_dma_fence, 0)) __atomic_thread_fence(__ATOMIC_SEQ_CST); \\
                                else __atomic_signal_fence(__ATOMIC_SEQ_CST); } while (0)
#else
#define MFC_SUBMIT_FENCE() __atomic_thread_fence(__ATOMIC_SEQ_CST)
#endif
static inline int mfc_submit(mfc_engine* mfc, spu_context* spu, uint32_t cmd)
{
    MFC_SUBMIT_FENCE();
    int r = mfc_submit_body(mfc, spu, cmd);
    MFC_SUBMIT_FENCE();
    return r;
}''',
     "spu dma fast: x86 fence")

SCH = "runtime/spu/spu_channels.c"
edit(SCH,
     '''volatile int g_spu_dma_lean = 1;
''',
     '''volatile int g_spu_dma_lean = 1;
/* spu_dma.h, x86: 1 = a full fence around every MFC command (PS3_SPU_DMA_FENCE=1), as on ARM64. */
volatile int g_spu_dma_fence = 0;
''',
     "spu dma fast: fence var")
edit(SCH,
     '''    if (__atomic_exchange_n(&once, 1, __ATOMIC_ACQ_REL)) return;
    ps3_toggle_watch(PS3T_SPU_DMA_LEAN, spu_dma_lean_set);''',
     '''    if (__atomic_exchange_n(&once, 1, __ATOMIC_ACQ_REL)) return;
    { const char* e = getenv("PS3_SPU_DMA_FENCE"); if (e && e[0] == '1') g_spu_dma_fence = 1; }
    ps3_toggle_watch(PS3T_SPU_DMA_LEAN, spu_dma_lean_set);''',
     "spu dma fast: fence env")
edit(SCH,
     '''#include "spu_dma.h"
#include "../../include/ps3emu/log_first.h"   /* PS3_LOG_FIRST */''',
     '''#define SPU_NO_INLINE_WRCH   /* this file defines spu_wrch */
#include "spu_dma.h"
#include "../../include/ps3emu/log_first.h"   /* PS3_LOG_FIRST */''',
     "spu dma fast: wrch opt-out")

HLP = "runtime/spu/spu_helpers.h"
edit(HLP,
     '''#endif /* SPU_HELPERS_H */''',
     '''/* Channel writes that only store an MFC command field: inline when the channel is a constant (the
 * lifted code's case); the command itself and every other channel go to spu_wrch. */
#ifndef SPU_NO_INLINE_WRCH
#ifdef __cplusplus
extern "C"
#endif
void spu_wrch(spu_context* ctx, uint32_t channel, u128 value);
static inline __attribute__((always_inline)) void spu_wrch_inl(spu_context* ctx, uint32_t channel, u128 value)
{
    if (__builtin_constant_p(channel)) {
        switch (channel) {
        case MFC_LSA:       ctx->mfc_lsa = value._u32[0]; return;
        case MFC_EAH:       ctx->mfc_eah = value._u32[0]; return;
        case MFC_EAL:       ctx->mfc_eal = value._u32[0]; return;
        case MFC_Size:      ctx->mfc_size = value._u32[0]; return;
        case MFC_TagID:     ctx->mfc_tag = value._u32[0] & 0x1F; return;
        case MFC_WrTagMask: ctx->mfc_tag_mask = value._u32[0]; return;
        default: break;
        }
    }
    spu_wrch(ctx, channel, value);
}
#define spu_wrch(c, ch, v) spu_wrch_inl(c, ch, v)
#endif

#endif /* SPU_HELPERS_H */''',
     "spu dma fast: inline wrch")
