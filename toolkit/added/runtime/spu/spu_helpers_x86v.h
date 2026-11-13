/* spu x86v (2026-11-10): SSE/AVX2 forms of the integer helpers that had only NEON forms, so x86 hosts
 * (the PS5, the BC-250) ran the scalar spu_X_ref loops (up to ~50 instructions for one SPU op).
 * Same results as spu_X_ref, lane for lane (our u128 is host-native: _u32[i] = SPU word i as a value,
 * so element-wise ops map 1:1; imm forms broadcast). tests: work/research_spu/test_x86v.c.
 * SPU_SCALAR_HELPERS / SPU_SCALAR_INT turn it off. */
#ifndef SPU_HELPERS_X86V_H
#define SPU_HELPERS_X86V_H
#if defined(__x86_64__) && defined(__AVX2__) && !defined(SPU_SCALAR_HELPERS) && !defined(SPU_SCALAR_INT)
#define SPU_X86V 1
#include <immintrin.h>
#define SPU__XVI static inline __attribute__((always_inline))
SPU__XVI __m128i spu__xi(u128 a) { __m128i x; memcpy(&x, &a, 16); return x; }
SPU__XVI u128 spu__xo(__m128i x) { u128 r; memcpy(&r, &x, 16); return r; }
#define XI spu__xi
#define XO spu__xo
/* 32-bit */
SPU__XVI u128 spu_x86_a(u128 a, u128 b)        { return XO(_mm_add_epi32(XI(a), XI(b))); }
SPU__XVI u128 spu_x86_sf(u128 a, u128 b)       { return XO(_mm_sub_epi32(XI(b), XI(a))); }
SPU__XVI u128 spu_x86_ai(u128 a, int32_t i)    { return XO(_mm_add_epi32(XI(a), _mm_set1_epi32(i))); }
SPU__XVI u128 spu_x86_sfi(u128 a, int32_t i)   { return XO(_mm_sub_epi32(_mm_set1_epi32(i), XI(a))); }
SPU__XVI u128 spu_x86_ceq(u128 a, u128 b)      { return XO(_mm_cmpeq_epi32(XI(a), XI(b))); }
SPU__XVI u128 spu_x86_ceqi(u128 a, int32_t i)  { return XO(_mm_cmpeq_epi32(XI(a), _mm_set1_epi32(i))); }
SPU__XVI u128 spu_x86_cgt(u128 a, u128 b)      { return XO(_mm_cmpgt_epi32(XI(a), XI(b))); }
SPU__XVI u128 spu_x86_cgti(u128 a, int32_t i)  { return XO(_mm_cmpgt_epi32(XI(a), _mm_set1_epi32(i))); }
SPU__XVI u128 spu_x86_clgt(u128 a, u128 b)     { const __m128i m = _mm_set1_epi32((int)0x80000000u);
    return XO(_mm_cmpgt_epi32(_mm_xor_si128(XI(a), m), _mm_xor_si128(XI(b), m))); }
SPU__XVI u128 spu_x86_clgti(u128 a, int32_t i) { const __m128i m = _mm_set1_epi32((int)0x80000000u);
    return XO(_mm_cmpgt_epi32(_mm_xor_si128(XI(a), m), _mm_xor_si128(_mm_set1_epi32(i), m))); }
SPU__XVI u128 spu_x86_and(u128 a, u128 b)      { return XO(_mm_and_si128(XI(a), XI(b))); }
SPU__XVI u128 spu_x86_or(u128 a, u128 b)       { return XO(_mm_or_si128(XI(a), XI(b))); }
SPU__XVI u128 spu_x86_xor(u128 a, u128 b)      { return XO(_mm_xor_si128(XI(a), XI(b))); }
SPU__XVI u128 spu_x86_rot(u128 a, u128 b)      { const __m128i c = _mm_and_si128(XI(b), _mm_set1_epi32(31)), x = XI(a);
    return XO(_mm_or_si128(_mm_sllv_epi32(x, c), _mm_srlv_epi32(x, _mm_sub_epi32(_mm_set1_epi32(32), c)))); }
SPU__XVI u128 spu_x86_roti(u128 a, int sh)     { sh &= 31; const __m128i x = XI(a);
    return XO(_mm_or_si128(_mm_sll_epi32(x, _mm_cvtsi32_si128(sh)), _mm_srl_epi32(x, _mm_cvtsi32_si128(32 - sh)))); }
SPU__XVI u128 spu_x86_rotm(u128 a, u128 b)     { return XO(_mm_srlv_epi32(XI(a), _mm_and_si128(_mm_sub_epi32(_mm_setzero_si128(), XI(b)), _mm_set1_epi32(0x3F)))); }
SPU__XVI u128 spu_x86_rotma(u128 a, u128 b)    { return XO(_mm_srav_epi32(XI(a), _mm_and_si128(_mm_sub_epi32(_mm_setzero_si128(), XI(b)), _mm_set1_epi32(0x3F)))); }
SPU__XVI u128 spu_x86_rotmi(u128 a, int i7)    { return XO(_mm_srl_epi32(XI(a), _mm_cvtsi32_si128((0 - i7) & 0x3F))); }
SPU__XVI u128 spu_x86_rotmai(u128 a, int i7)   { return XO(_mm_sra_epi32(XI(a), _mm_cvtsi32_si128((0 - i7) & 0x3F))); }
SPU__XVI u128 spu_x86_shl(u128 a, u128 b)      { return XO(_mm_sllv_epi32(XI(a), _mm_and_si128(XI(b), _mm_set1_epi32(0x3F)))); }
SPU__XVI u128 spu_x86_shli(u128 a, int sh)     { return XO(_mm_sll_epi32(XI(a), _mm_cvtsi32_si128(sh & 0x3F))); }
SPU__XVI u128 spu_x86_xshw(u128 a)             { return XO(_mm_srai_epi32(_mm_slli_epi32(XI(a), 16), 16)); }
/* 16-bit */
SPU__XVI u128 spu_x86_ah(u128 a, u128 b)       { return XO(_mm_add_epi16(XI(a), XI(b))); }
SPU__XVI u128 spu_x86_ahi(u128 a, int32_t i)   { return XO(_mm_add_epi16(XI(a), _mm_set1_epi16((short)(uint16_t)i))); }
SPU__XVI u128 spu_x86_sfh(u128 a, u128 b)      { return XO(_mm_sub_epi16(XI(b), XI(a))); }
SPU__XVI u128 spu_x86_sfhi(u128 a, int32_t i)  { return XO(_mm_sub_epi16(_mm_set1_epi16((short)(uint16_t)i), XI(a))); }
SPU__XVI u128 spu_x86_ceqh(u128 a, u128 b)     { return XO(_mm_cmpeq_epi16(XI(a), XI(b))); }
SPU__XVI u128 spu_x86_ceqhi(u128 a, int32_t i) { return XO(_mm_cmpeq_epi16(XI(a), _mm_set1_epi16((short)i))); }
SPU__XVI u128 spu_x86_cgth(u128 a, u128 b)     { return XO(_mm_cmpgt_epi16(XI(a), XI(b))); }
SPU__XVI u128 spu_x86_cgthi(u128 a, int32_t i) { return XO(_mm_cmpgt_epi16(XI(a), _mm_set1_epi16((short)i))); }
SPU__XVI u128 spu_x86_clgth(u128 a, u128 b)    { const __m128i m = _mm_set1_epi16((short)0x8000);
    return XO(_mm_cmpgt_epi16(_mm_xor_si128(XI(a), m), _mm_xor_si128(XI(b), m))); }
SPU__XVI u128 spu_x86_clgthi(u128 a, int32_t i){ const __m128i m = _mm_set1_epi16((short)0x8000);
    return XO(_mm_cmpgt_epi16(_mm_xor_si128(XI(a), m), _mm_xor_si128(_mm_set1_epi16((short)(uint16_t)i), m))); }
SPU__XVI u128 spu_x86_shlhi(u128 a, int sh)    { return XO(_mm_sll_epi16(XI(a), _mm_cvtsi32_si128(sh & 0x1F))); }
SPU__XVI u128 spu_x86_rothi(u128 a, int sh)    { sh &= 15; const __m128i x = XI(a);
    return XO(_mm_or_si128(_mm_sll_epi16(x, _mm_cvtsi32_si128(sh)), _mm_srl_epi16(x, _mm_cvtsi32_si128(16 - sh)))); }
SPU__XVI u128 spu_x86_rothmi(u128 a, int i7)   { return XO(_mm_srl_epi16(XI(a), _mm_cvtsi32_si128((0 - i7) & 0x1F))); }
SPU__XVI u128 spu_x86_rotmahi(u128 a, int i7)  { return XO(_mm_sra_epi16(XI(a), _mm_cvtsi32_si128((0 - i7) & 0x1F))); }
SPU__XVI u128 spu_x86_xsbh(u128 a)             { return XO(_mm_srai_epi16(_mm_slli_epi16(XI(a), 8), 8)); }
/* 8-bit */
SPU__XVI u128 spu_x86_ceqb(u128 a, u128 b)     { return XO(_mm_cmpeq_epi8(XI(a), XI(b))); }
SPU__XVI u128 spu_x86_ceqbi(u128 a, int32_t i) { return XO(_mm_cmpeq_epi8(XI(a), _mm_set1_epi8((char)(uint8_t)i))); }
SPU__XVI u128 spu_x86_cgtb(u128 a, u128 b)     { return XO(_mm_cmpgt_epi8(XI(a), XI(b))); }
SPU__XVI u128 spu_x86_cgtbi(u128 a, int32_t i) { return XO(_mm_cmpgt_epi8(XI(a), _mm_set1_epi8((char)(int8_t)i))); }
SPU__XVI u128 spu_x86_clgtb(u128 a, u128 b)    { const __m128i m = _mm_set1_epi8((char)0x80);
    return XO(_mm_cmpgt_epi8(_mm_xor_si128(XI(a), m), _mm_xor_si128(XI(b), m))); }
SPU__XVI u128 spu_x86_clgtbi(u128 a, int32_t i){ const __m128i m = _mm_set1_epi8((char)0x80);
    return XO(_mm_cmpgt_epi8(_mm_xor_si128(XI(a), m), _mm_xor_si128(_mm_set1_epi8((char)(uint8_t)i), m))); }
#undef XI
#undef XO
#endif
#endif
