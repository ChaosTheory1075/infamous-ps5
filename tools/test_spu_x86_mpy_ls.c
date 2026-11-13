/* The SSE4.1 16-bit multiplies and the pshufb local-store load/store (patch_spu_x86_mpy_ls.py)
 * against the scalar forms.
 *   clang -O2 -march=znver2 -I<fork>/runtime/spu -I<fork>/include -I<fork>/runtime test_spu_x86_mpy_ls.c
 */
#include "spu_context.h"
#include "spu_helpers.h"
#include <stdio.h>
#include <string.h>

int g_spu_ls_dbg = 0;
void spu_ls_watch_slow(const struct spu_context* c, uint32_t lsa, int is_write, const uint8_t* p, uint32_t pc, uint32_t lr)
{ (void)c; (void)lsa; (void)is_write; (void)p; (void)pc; (void)lr; }

static uint64_t s = 0x9E3779B97F4A7C15ull;
static uint32_t rnd(void)
{
    s ^= s << 13; s ^= s >> 7; s ^= s << 17;
    /* one in four lanes an edge value: 0, +-1, 0x7FFF, 0x8000, 0xFFFF in either half */
    static const uint16_t e[] = { 0, 1, 0xFFFF, 0x7FFF, 0x8000, 0x8001, 0x7FFE };
    uint32_t v = (uint32_t)(s >> 17);
    if ((s & 3) == 0) v = (v & 0xFFFF0000u) | e[(s >> 3) % 7];
    if ((s & 12) == 0) v = (v & 0xFFFFu) | (uint32_t)e[(s >> 7) % 7] << 16;
    return v;
}
static u128 rq(void) { u128 r; for (int i = 0; i < 4; i++) r._u32[i] = rnd(); return r; }

static spu_context ctx;

int main(void)
{
    unsigned long bad = 0;
    const unsigned long N = 4000000;
    for (unsigned long n = 0; n < N; n++) {
        const u128 a = rq(), b = rq(), c = rq();
        const int32_t imm = (int32_t)(rnd() & 0x3FF) - 512;
        #define CK(x, y) do { u128 _x = (x), _y = (y); if (memcmp(&_x, &_y, 16)) { if (bad++ < 8) printf("mismatch %s\n", #x); } } while (0)
        CK(spu_mpy(a, b), spu_mpy_ref(a, b));
        CK(spu_mpyu(a, b), spu_mpyu_ref(a, b));
        CK(spu_mpyh(a, b), spu_mpyh_ref(a, b));
        CK(spu_mpyhh(a, b), spu_mpyhh_ref(a, b));
        CK(spu_mpyi(a, imm), spu_mpyi_ref(a, imm));
        CK(spu_mpyui(a, imm), spu_mpyui_ref(a, imm));
        CK(spu_mpyui(a, (int32_t)(rnd() & 0xFFFF)), spu_mpyui_ref(a, (int32_t)(s & 0xFFFF)) ) ;
        CK(spu_mpya(a, b, c), spu_mpya_ref(a, b, c));
    }
    /* the mpyui pair above uses two different immediates by construction; check it properly */
    bad = 0;
    for (unsigned long n = 0; n < N; n++) {
        const u128 a = rq(), b = rq(), c = rq();
        const int32_t imm = (int32_t)(rnd() & 0x3FF) - 512, uimm = (int32_t)(rnd() & 0xFFFF);
        CK(spu_mpy(a, b), spu_mpy_ref(a, b));
        CK(spu_mpyu(a, b), spu_mpyu_ref(a, b));
        CK(spu_mpyh(a, b), spu_mpyh_ref(a, b));
        CK(spu_mpyhh(a, b), spu_mpyhh_ref(a, b));
        CK(spu_mpyi(a, imm), spu_mpyi_ref(a, imm));
        CK(spu_mpyui(a, uimm), spu_mpyui_ref(a, uimm));
        CK(spu_mpya(a, b, c), spu_mpya_ref(a, b, c));
    }
    printf("multiplies: %lu vectors x 7 ops, %lu mismatches\n", N, bad);
    /* local store: a load is the big-endian words, a store writes them back big-endian */
    unsigned long lbad = 0;
    static uint8_t ls[SPU_LS_SIZE];
    ctx.ls = ls;
    for (unsigned i = 0; i < SPU_LS_SIZE; i++) ctx.ls[i] = (uint8_t)rnd();
    for (unsigned long n = 0; n < 1000000; n++) {
        const uint32_t lsa = rnd() & SPU_LS_MASK;
        const uint8_t* p = &ctx.ls[lsa & (SPU_LS_MASK & ~0xFu)];
        u128 want;
        for (int i = 0; i < 4; i++)
            want._u32[i] = (uint32_t)p[i*4] << 24 | (uint32_t)p[i*4+1] << 16 | (uint32_t)p[i*4+2] << 8 | p[i*4+3];
        const u128 got = spu_ls_read128(&ctx, lsa);
        if (memcmp(&got, &want, 16) && lbad++ < 8) printf("read mismatch at 0x%05X\n", lsa);
        const u128 v = rq();
        spu_ls_write128(&ctx, lsa, v);
        for (int i = 0; i < 4; i++) {
            const uint32_t w = (uint32_t)p[i*4] << 24 | (uint32_t)p[i*4+1] << 16 | (uint32_t)p[i*4+2] << 8 | p[i*4+3];
            if (w != v._u32[i] && lbad++ < 8) printf("write mismatch at 0x%05X word %d\n", lsa, i);
        }
    }
    printf("local store: 1000000 loads + stores, %lu mismatches\n", lbad);
    return (bad || lbad) ? 1 : 0;
}
