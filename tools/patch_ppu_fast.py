# ppu fast: no fences on plain DMA in the atomic wrapper, hashed HLE dispatch, inlined stores, AVX VMX floats
# PC FoB no-draw profile after patch_spu_dma_fast.py:
# (1) spu_mfc_atomic -- called for EVERY MFC command -- put a full fence on both sides before its
#     body found out the command was not a lock-line op, so every plain GET/PUT paid four mfences
#     (two here, two in mfc_submit). Plain commands now return at once (mfc_submit orders them);
#     on x86 only a GETLLAR keeps the fence in front (its loads are the one thing TSO lets pass this
#     SPU's earlier stores; PUTLLC/PUTLLUC take the lock-line lock, a locked RMW).
#     PS3_SPU_DMA_FENCE=1 = both fences on every lock-line command, as before.
# (2) every HLE import call scanned the PRX export registry (up to 2048 entries, a full scan for
#     every import no PRX serves -- most of them) and then the context-handler table linearly; the
#     console's fios media threads spent 30-44% of their samples in prx_resolve_export. Both are
#     hashed now (rebuilt when the registry changes / the handler table grows; first entry wins).
# (3) the inline guest stores were emitted out of line (vm_write64_inl 8%, vm_write32_inl 4% of the
#     main thread): always_inline.
# (4) vmx_vmaddfp / vaddfp / vsubfp / vnmsubfp worked byte by byte, one lane at a time (vmaddfp alone
#     5.5% of the main thread): AVX2/FMA forms with the same flush (VSCR NJ), NaN rules and fused
#     rounding (the scalar forms stay as *_ref; tools/test_vmx_fast.c compares them bit for bit).
SCH = "runtime/spu/spu_channels.c"
edit(SCH,
     '''static int spu_mfc_atomic(spu_context* ctx, uint32_t cmd)
{
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    int r = spu_mfc_atomic_body(ctx, cmd);
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    return r;
}''',
     '''static int spu_mfc_atomic(spu_context* ctx, uint32_t cmd)
{
    if (cmd != MFC_GETLLAR_CMD && cmd != MFC_PUTLLC_CMD &&
        cmd != MFC_PUTLLUC_CMD && cmd != MFC_PUTQLLUC_CMD)
        return 0;   /* a plain command: mfc_submit orders it */
#if defined(__x86_64__)
    if (g_spu_dma_fence || cmd == MFC_GETLLAR_CMD) __atomic_thread_fence(__ATOMIC_SEQ_CST);
    int r = spu_mfc_atomic_body(ctx, cmd);
    if (g_spu_dma_fence) __atomic_thread_fence(__ATOMIC_SEQ_CST);
    else __atomic_signal_fence(__ATOMIC_SEQ_CST);
    return r;
#else
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    int r = spu_mfc_atomic_body(ctx, cmd);
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    return r;
#endif
}''',
     "ppu fast: atomic fences")

PRX = "runtime/prx/prx_loader.c"
edit(PRX,
     '''uint32_t prx_resolve_export(uint32_t nid)
{
    for (uint32_t i = 0; i < s_export_reg_n; i++)
        if (s_export_reg[i].nid == nid)
            return s_export_reg[i].guest_addr;
    return 0;
}''',
     '''/* NID -> guest address, open addressing over a copy of the registry (nid 0 = empty slot; NID 0
 * is never registered). Rebuilt on the first lookup after the registry changed (s_xhash_gen).
 * Old tables are never freed: a reader may still hold one, and they change only on module loads. */
typedef struct { uint32_t gen, mask; uint32_t kv[]; } prx_xhash;
static prx_xhash* s_xhash;
static uint32_t s_xhash_gen = 1;
static int s_xhash_lock;
static uint32_t prx_resolve_export_scan(uint32_t nid)
{
    for (uint32_t i = 0; i < s_export_reg_n; i++)
        if (s_export_reg[i].nid == nid)
            return s_export_reg[i].guest_addr;
    return 0;
}
uint32_t prx_resolve_export(uint32_t nid)
{
    const uint32_t gen = __atomic_load_n(&s_xhash_gen, __ATOMIC_ACQUIRE);
    prx_xhash* h = __atomic_load_n(&s_xhash, __ATOMIC_ACQUIRE);
    if (!h || h->gen != gen) {
        while (__atomic_exchange_n(&s_xhash_lock, 1, __ATOMIC_ACQUIRE)) { }
        h = __atomic_load_n(&s_xhash, __ATOMIC_ACQUIRE);
        if (!h || h->gen != gen) {
            const uint32_t n = s_export_reg_n;
            uint32_t size = 64;
            while (size < 2 * n) size <<= 1;
            prx_xhash* nx = (prx_xhash*)calloc(1, sizeof(prx_xhash) + 2 * size * sizeof(uint32_t));
            if (!nx) { __atomic_store_n(&s_xhash_lock, 0, __ATOMIC_RELEASE); return prx_resolve_export_scan(nid); }
            nx->gen = gen; nx->mask = size - 1;
            for (uint32_t i = 0; i < n; i++) {
                const uint32_t k = s_export_reg[i].nid;
                if (!k) continue;
                for (uint32_t s = (k * 2654435761u) & nx->mask;; s = (s + 1) & nx->mask)
                    if (!nx->kv[2 * s] || nx->kv[2 * s] == k) { nx->kv[2 * s] = k; nx->kv[2 * s + 1] = s_export_reg[i].guest_addr; break; }
            }
            __atomic_store_n(&s_xhash, nx, __ATOMIC_RELEASE);
            h = nx;
        }
        __atomic_store_n(&s_xhash_lock, 0, __ATOMIC_RELEASE);
    }
    if (!nid) return prx_resolve_export_scan(nid);
    for (uint32_t s = (nid * 2654435761u) & h->mask;; s = (s + 1) & h->mask) {
        const uint32_t k = h->kv[2 * s];
        if (k == nid) return h->kv[2 * s + 1];
        if (!k) return 0;
    }
}''',
     "ppu fast: prx export hash")
edit(PRX,
     '''    if (s_export_reg_n < PRX_EXPORT_REG_CAP)
        s_export_reg[s_export_reg_n++] = (prx_export_reg_entry){ nid, guest_addr };''',
     '''    __atomic_add_fetch(&s_xhash_gen, 1, __ATOMIC_RELEASE);   /* prx_resolve_export rebuilds */
    if (s_export_reg_n < PRX_EXPORT_REG_CAP)
        s_export_reg[s_export_reg_n++] = (prx_export_reg_entry){ nid, guest_addr };''',
     "ppu fast: prx gen on add")
edit(PRX,
     '''        if (s_export_reg[i].nid == nid) {
            s_export_reg[i].guest_addr = guest_addr;
            return;
        }''',
     '''        if (s_export_reg[i].nid == nid) {
            s_export_reg[i].guest_addr = guest_addr;
            __atomic_add_fetch(&s_xhash_gen, 1, __ATOMIC_RELEASE);
            return;
        }''',
     "ppu fast: prx gen on replace")
edit(PRX,
     '''        if (s_export_reg[i].nid == nid && s_export_reg[i].guest_addr == guest_addr) {
            s_export_reg[i] = s_export_reg[--s_export_reg_n];''',
     '''        if (s_export_reg[i].nid == nid && s_export_reg[i].guest_addr == guest_addr) {
            s_export_reg[i] = s_export_reg[--s_export_reg_n];
            __atomic_add_fetch(&s_xhash_gen, 1, __ATOMIC_RELEASE);''',
     "ppu fast: prx gen on remove")
# The hash and its generation counter are declared above prx_export_register.
edit(PRX,
     '''static void prx_export_register(uint32_t nid, uint32_t guest_addr)
{''',
     '''static uint32_t s_xhash_gen;
static void prx_export_register(uint32_t nid, uint32_t guest_addr)
{''',
     "ppu fast: prx gen forward")

HLE = "runtime/ppu/ppu_hle.cpp"
edit(HLE,
     '''extern "C" void ps3_hle_register_ctx(uint32_t nid, const char* name, hle_ctx_fn fn)
{''',
     '''/* NID -> g_ctx index, rebuilt when the table has grown (entries are only appended); the first
 * entry for a NID wins, as with the linear scan. */
struct HleCtxIndex { uint32_t count, mask; int32_t slot[1]; };
static std::atomic<const HleCtxIndex*> g_ctx_index{nullptr};
static int hle_ctx_find(uint32_t nid)
{
    const uint32_t n = g_ctx_count.load(std::memory_order_acquire);
    const HleCtxIndex* ix = g_ctx_index.load(std::memory_order_acquire);
    if (!ix || ix->count != n) {
        std::lock_guard<std::mutex> lk(g_hle_index_lock);
        ix = g_ctx_index.load(std::memory_order_acquire);
        if (!ix || ix->count != n) {
            uint32_t size = 16;
            while (size < 2 * n) size <<= 1;
            HleCtxIndex* nx = (HleCtxIndex*)malloc(sizeof(HleCtxIndex) + (size - 1) * sizeof(int32_t));
            if (!nx) { for (uint32_t i = 0; i < n; i++) if (g_ctx[i].nid == nid) return (int)i; return -1; }
            nx->count = n; nx->mask = size - 1;
            for (uint32_t i = 0; i < size; i++) nx->slot[i] = -1;
            for (uint32_t i = 0; i < n; i++)
                for (uint32_t h = (g_ctx[i].nid * 2654435761u) & nx->mask;; h = (h + 1) & nx->mask) {
                    if (nx->slot[h] < 0) { nx->slot[h] = (int32_t)i; break; }
                    if (g_ctx[nx->slot[h]].nid == g_ctx[i].nid) break;
                }
            g_ctx_index.store(nx, std::memory_order_release);
            ix = nx;
        }
    }
    for (uint32_t h = (nid * 2654435761u) & ix->mask;; h = (h + 1) & ix->mask) {
        const int32_t k = ix->slot[h];
        if (k < 0) return -1;
        if (g_ctx[k].nid == nid) return k;
    }
}

extern "C" void ps3_hle_register_ctx(uint32_t nid, const char* name, hle_ctx_fn fn)
{''',
     "ppu fast: ctx index")
edit(HLE,
     '''    for (uint32_t i = 0; i < g_ctx_count; i++)
        if (g_ctx[i].nid == nid) {
            ps3_msf("hle:%s", g_ctx[i].name);''',
     '''    if (const int i = hle_ctx_find(nid); i >= 0) {
            ps3_msf("hle:%s", g_ctx[i].name);''',
     "ppu fast: ctx dispatch")

for _g in ("if1", "if2", "fob"):
    H = __import__("os").path.expanduser("~") + f"/{_g}/infamous2-lle/recompiled/ppu_recomp.h"
    for _n in ("8_inl (", "16_inl(", "32_inl(", "64_inl("):
        edit(H, f"static inline void vm_write{_n}", f"static inline __attribute__((always_inline)) void vm_write{_n}",
             f"ppu fast: always_inline store {_n[:2].strip('_')} {_g}")

VMX = "runtime/ppu/ppu_vmx.h"
edit(VMX,
     '''VMX_FBIN(vmx_vaddfp, vmx_f(x) + vmx_f(y), 1)
VMX_FBIN(vmx_vsubfp, vmx_f(x) - vmx_f(y), 1)''',
     '''VMX_FBIN(vmx_vaddfp_ref, vmx_f(x) + vmx_f(y), 1)
VMX_FBIN(vmx_vsubfp_ref, vmx_f(x) - vmx_f(y), 1)''',
     "ppu fast: vmx add ref")
edit(VMX,
     '''VMX_INL void vmx_vmaddfp(VMX_D, VMX_A, VMX_B, VMX_C, uint32_t vscr) {''',
     '''VMX_INL void vmx_vmaddfp_ref(VMX_D, VMX_A, VMX_B, VMX_C, uint32_t vscr) {''',
     "ppu fast: vmx madd ref")
edit(VMX,
     '''VMX_INL void vmx_vnmsubfp(VMX_D, VMX_A, VMX_B, VMX_C, uint32_t vscr) {''',
     '''VMX_INL void vmx_vnmsubfp_ref(VMX_D, VMX_A, VMX_B, VMX_C, uint32_t vscr) {''',
     "ppu fast: vmx nmsub ref")
edit(VMX,
     '''        vmx_sw(r, i, vmx_flush(vmx_fix(vmx_u(-fmaf(x, z, -y))), vscr)); } VMX_OUT; }
''',
     '''        vmx_sw(r, i, vmx_flush(vmx_fix(vmx_u(-fmaf(x, z, -y))), vscr)); } VMX_OUT; }

/* AVX2/FMA forms of the four hot float ops: the same lane results as the *_ref forms above. */
#if defined(__AVX2__) && defined(__FMA__) && !defined(VMX_SCALAR_FLOAT)
#include <immintrin.h>
#define VMX_XV static inline __attribute__((always_inline))
VMX_XV __m128i vmx__ld(const void* p) {      /* big-endian words -> host lanes */
    return _mm_shuffle_epi8(_mm_loadu_si128((const __m128i*)p), _mm_setr_epi8(3,2,1,0, 7,6,5,4, 11,10,9,8, 15,14,13,12));
}
VMX_XV void vmx__st(void* p, __m128i v) {
    _mm_storeu_si128((__m128i*)p, _mm_shuffle_epi8(v, _mm_setr_epi8(3,2,1,0, 7,6,5,4, 11,10,9,8, 15,14,13,12)));
}
VMX_XV __m128i vmx__flush(__m128i x, uint32_t vscr) {   /* NJ: a zero exponent becomes a signed zero */
    if (!(vscr & VMX_NJ)) return x;
    const __m128i den = _mm_cmpeq_epi32(_mm_and_si128(x, _mm_set1_epi32(0x7F800000)), _mm_setzero_si128());
    return _mm_blendv_epi8(x, _mm_and_si128(x, _mm_set1_epi32((int)0x80000000u)), den);
}
VMX_XV __m128i vmx__isnan(__m128i x) {
    return _mm_cmpgt_epi32(_mm_and_si128(x, _mm_set1_epi32(0x7FFFFFFF)), _mm_set1_epi32(0x7F800000));
}
VMX_XV __m128i vmx__fix(__m128i r) {
    return _mm_blendv_epi8(r, _mm_set1_epi32(0x7FC00000), vmx__isnan(r));
}
VMX_XV __m128i vmx__nan2(__m128i r, __m128i a, __m128i b) {  /* NaN precedence: A, B (quieted), else fixed */
    const __m128i q = _mm_set1_epi32(0x7FC00000);
    r = _mm_blendv_epi8(vmx__fix(r), _mm_or_si128(b, q), vmx__isnan(b));
    return _mm_blendv_epi8(r, _mm_or_si128(a, q), vmx__isnan(a));
}
VMX_XV void vmx_vaddfp(VMX_D, VMX_A, VMX_B, uint32_t vscr) {
    const __m128i x = vmx__flush(vmx__ld(a_), vscr), y = vmx__flush(vmx__ld(b_), vscr);
    const __m128i z = _mm_castps_si128(_mm_add_ps(_mm_castsi128_ps(x), _mm_castsi128_ps(y)));
    vmx__st(d_, vmx__flush(vmx__nan2(z, x, y), vscr));
}
VMX_XV void vmx_vsubfp(VMX_D, VMX_A, VMX_B, uint32_t vscr) {
    const __m128i x = vmx__flush(vmx__ld(a_), vscr), y = vmx__flush(vmx__ld(b_), vscr);
    const __m128i z = _mm_castps_si128(_mm_sub_ps(_mm_castsi128_ps(x), _mm_castsi128_ps(y)));
    vmx__st(d_, vmx__flush(vmx__nan2(z, x, y), vscr));
}
VMX_XV void vmx_vmaddfp(VMX_D, VMX_A, VMX_B, VMX_C, uint32_t vscr) {   /* a*c + b, one rounding */
    const __m128 x = _mm_castsi128_ps(vmx__flush(vmx__ld(a_), vscr)), y = _mm_castsi128_ps(vmx__flush(vmx__ld(b_), vscr)),
                 z = _mm_castsi128_ps(vmx__flush(vmx__ld(c_), vscr));
    vmx__st(d_, vmx__flush(vmx__fix(_mm_castps_si128(_mm_fmadd_ps(x, z, y))), vscr));
}
VMX_XV void vmx_vnmsubfp(VMX_D, VMX_A, VMX_B, VMX_C, uint32_t vscr) {  /* -(a*c - b), one rounding */
    const __m128 x = _mm_castsi128_ps(vmx__flush(vmx__ld(a_), vscr)), y = _mm_castsi128_ps(vmx__flush(vmx__ld(b_), vscr)),
                 z = _mm_castsi128_ps(vmx__flush(vmx__ld(c_), vscr));
    const __m128i m = _mm_xor_si128(_mm_castps_si128(_mm_fmsub_ps(x, z, y)), _mm_set1_epi32((int)0x80000000u));
    vmx__st(d_, vmx__flush(vmx__fix(m), vscr));
}
#else
#define vmx_vaddfp   vmx_vaddfp_ref
#define vmx_vsubfp   vmx_vsubfp_ref
#define vmx_vmaddfp  vmx_vmaddfp_ref
#define vmx_vnmsubfp vmx_vnmsubfp_ref
#endif
''',
     "ppu fast: vmx avx")
