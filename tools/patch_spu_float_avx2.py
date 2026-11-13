
# SPU single-precision fa/fs/fm/fma/fms/fnms on x86 with AVX2 (the PS5's Zen 2 and any PC since
# 2013): the NEON fast path's method, four lanes as one f64x4 -- widen (exact), operate, clear the
# 29 low significand bits, narrow (exact) -- with the same per-lane tests and the same exact
# fix-up for the lanes that fail them. Without it every x86 build ran each lane through the
# integer emulation (spu__sf_sum, 128-bit arithmetic): the busiest SPU thread of an inFamous 2
# world frame spent ~25% in spu_fm / spu__fma_any / spu_fa / spu_fs / spu__sf_sum (perf, Linux),
# and that one SPU was 75% of the frame (PS3_FTRACE). tests: tools/test_spu_float_avx2.c.
edit("runtime/spu/spu_helpers.h", r'''#else
static inline u128 spu_fa(u128 a, u128 b) { return spu__fa_s(a, b); }''', r'''#elif defined(__AVX2__) && !defined(SPU_SCALAR_HELPERS)
#include <immintrin.h>
#define SPU_FLOAT_AVX2 1
#pragma clang fp contract(off)
#define SPU__XV_INLINE static inline __attribute__((always_inline))
#define SPU__XV_SLOW   static inline __attribute__((noinline, cold))
SPU__XV_INLINE __m128i spu__xv_ld(u128 v) { __m128i r; memcpy(&r, &v, 16); return r; }
SPU__XV_INLINE u128 spu__xv_st(__m128i v) { u128 r; memcpy(&r, &v, 16); return r; }
SPU__XV_INLINE __m128i spu__xv_bexp(__m128i x) { return _mm_srli_epi32(_mm_slli_epi32(x, 1), 24); }
SPU__XV_INLINE __m128i spu__xv_iszero(__m128i x) {   /* +-0.0 */
    return _mm_cmpeq_epi32(_mm_slli_epi32(x, 1), _mm_setzero_si128());
}
/* An ordinary single (biased exponent 1..254) or a true zero, as spu__nv_plain0. */
SPU__XV_INLINE __m128i spu__xv_plain0(__m128i x) {
    const __m128i be = spu__xv_bexp(x);
    const __m128i plain = _mm_and_si128(_mm_cmpgt_epi32(be, _mm_setzero_si128()),
                                        _mm_cmpgt_epi32(_mm_set1_epi32(255), be));
    return _mm_or_si128(plain, spu__xv_iszero(x));
}
SPU__XV_INLINE __m256d spu__xv_wide(__m128i x) { return _mm256_cvtps_pd(_mm_castsi128_ps(x)); }
/* spu__nv_trunc0 on four doubles: *ok marks the lanes whose result is a normal single or an exact
 * zero (and, with err, not both rounded and on a 24-bit boundary); *zm the zero lanes. */
SPU__XV_INLINE __m128i spu__xv_trunc0(__m256d d, __m128i* ok, __m128i* zm, const __m256d* err) {
    const __m256i u = _mm256_castpd_si256(d);
    const __m256i z64 = _mm256_setzero_si256();
    const __m256i az = _mm256_cmpeq_epi64(_mm256_slli_epi64(u, 1), z64);
    const __m256i e = _mm256_sub_epi64(_mm256_and_si256(_mm256_srli_epi64(u, 52), _mm256_set1_epi64x(0x7FF)),
                                       _mm256_set1_epi64x(1023));
    __m256i good = _mm256_and_si256(_mm256_cmpgt_epi64(e, _mm256_set1_epi64x(-127)),
                                    _mm256_cmpgt_epi64(_mm256_set1_epi64x(128), e));
    if (err) {
        const __m256i lowz = _mm256_cmpeq_epi64(_mm256_and_si256(u, _mm256_set1_epi64x(0x1FFFFFFFll)), z64);
        const __m256i errz = _mm256_castpd_si256(_mm256_cmp_pd(*err, _mm256_setzero_pd(), _CMP_EQ_OQ));
        good = _mm256_and_si256(good, _mm256_or_si256(_mm256_xor_si256(lowz, _mm256_set1_epi64x(-1)), errz));
    }
    const __m256i lo32 = _mm256_setr_epi32(0, 2, 4, 6, 0, 2, 4, 6);
    *ok = _mm256_castsi256_si128(_mm256_permutevar8x32_epi32(_mm256_or_si256(good, az), lo32));
    *zm = _mm256_castsi256_si128(_mm256_permutevar8x32_epi32(az, lo32));
    const __m256d t = _mm256_castsi256_pd(_mm256_and_si256(u, _mm256_set1_epi64x(~0x1FFFFFFFll)));
    return _mm_castps_si128(_mm256_cvtpd_ps(t));
}
SPU__XV_INLINE __m128i spu__xv_pos0(__m128i r, __m128i zm) {   /* the SPU never returns -0 */
    return _mm_andnot_si128(_mm_and_si128(zm, _mm_set1_epi32((int)0x80000000u)), r);
}
SPU__XV_INLINE int spu__xv_all4(__m128i m) { return _mm_movemask_ps(_mm_castsi128_ps(m)) == 0xF; }
SPU__XV_SLOW __m128i spu__xv_fa_fix(__m128i r, __m128i ok, __m128i a, __m128i b, uint32_t negb) {
    uint32_t o[4], m[4], x[4], y[4];
    memcpy(o, &r, 16); memcpy(m, &ok, 16); memcpy(x, &a, 16); memcpy(y, &b, 16);
    for (int i = 0; i < 4; i++) if (!m[i]) o[i] = spu__fa_any(x[i], y[i] ^ negb);
    __m128i v; memcpy(&v, o, 16); return v;
}
SPU__XV_SLOW __m128i spu__xv_fm_fix(__m128i r, __m128i ok, __m128i a, __m128i b) {
    uint32_t o[4], m[4], x[4], y[4];
    memcpy(o, &r, 16); memcpy(m, &ok, 16); memcpy(x, &a, 16); memcpy(y, &b, 16);
    for (int i = 0; i < 4; i++) if (!m[i]) o[i] = spu__fm_any(x[i], y[i]);
    __m128i v; memcpy(&v, o, 16); return v;
}
SPU__XV_SLOW __m128i spu__xv_fma_fix(__m128i r, __m128i ok, __m128i a, __m128i b, __m128i c,
                                     uint32_t negp, uint32_t negc) {
    uint32_t o[4], m[4], x[4], y[4], z[4];
    memcpy(o, &r, 16); memcpy(m, &ok, 16); memcpy(x, &a, 16); memcpy(y, &b, 16); memcpy(z, &c, 16);
    for (int i = 0; i < 4; i++) if (!m[i]) o[i] = spu__fma_any(x[i], y[i], z[i], negp, negc);
    __m128i v; memcpy(&v, o, 16); return v;
}
SPU__XV_INLINE u128 spu__xv_fa(u128 a, u128 b, uint32_t negb) {
    const __m128i xa = spu__xv_ld(a), yb = spu__xv_ld(b);
    const __m128i x = xa, y = _mm_xor_si128(yb, _mm_set1_epi32((int)negb));
    const __m128i gap = _mm_abs_epi32(_mm_sub_epi32(spu__xv_bexp(x), spu__xv_bexp(y)));
    const __m128i pre = _mm_and_si128(_mm_and_si128(spu__xv_plain0(x), spu__xv_plain0(y)),
                                      _mm_or_si128(_mm_cmpgt_epi32(_mm_set1_epi32(30), gap),
                                                   _mm_or_si128(spu__xv_iszero(x), spu__xv_iszero(y))));
    __m128i ok, zm;
    __m128i r = spu__xv_trunc0(_mm256_add_pd(spu__xv_wide(x), spu__xv_wide(y)), &ok, &zm, NULL);
    ok = _mm_and_si128(ok, pre);
    r = spu__xv_pos0(r, zm);
    if (!spu__xv_all4(ok)) r = spu__xv_fa_fix(r, ok, xa, yb, negb);
    return spu__xv_st(r);
}
SPU__XV_INLINE u128 spu_fa(u128 a, u128 b) { return spu__xv_fa(a, b, 0); }
SPU__XV_INLINE u128 spu_fs(u128 a, u128 b) { return spu__xv_fa(a, b, 0x80000000u); }
SPU__XV_INLINE u128 spu_fm(u128 a, u128 b) {
    const __m128i x = spu__xv_ld(a), y = spu__xv_ld(b);
    __m128i ok, zm;
    __m128i r = spu__xv_trunc0(_mm256_mul_pd(spu__xv_wide(x), spu__xv_wide(y)), &ok, &zm, NULL);
    ok = _mm_and_si128(ok, _mm_and_si128(spu__xv_plain0(x), spu__xv_plain0(y)));
    r = spu__xv_pos0(r, zm);
    if (!spu__xv_all4(ok)) r = spu__xv_fm_fix(r, ok, x, y);
    return spu__xv_st(r);
}
/* (+-a*b) + (+-c): the product is exact in double, one rounding in the add, TwoSum says whether. */
SPU__XV_INLINE u128 spu__xv_fma(u128 a, u128 b, u128 c, uint32_t negp, uint32_t negc) {
    const __m128i xa = spu__xv_ld(a), y = spu__xv_ld(b), zc = spu__xv_ld(c);
    const __m128i x = _mm_xor_si128(xa, _mm_set1_epi32((int)negp)), z = _mm_xor_si128(zc, _mm_set1_epi32((int)negc));
    const __m256d p = _mm256_mul_pd(spu__xv_wide(x), spu__xv_wide(y)), zd = spu__xv_wide(z);
    const __m256d s = _mm256_add_pd(p, zd), bb = _mm256_sub_pd(s, p);
    const __m256d err = _mm256_add_pd(_mm256_sub_pd(p, _mm256_sub_pd(s, bb)), _mm256_sub_pd(zd, bb));
    __m128i ok, zm;
    __m128i r = spu__xv_trunc0(s, &ok, &zm, &err);
    ok = _mm_and_si128(ok, _mm_and_si128(_mm_and_si128(spu__xv_plain0(x), spu__xv_plain0(y)), spu__xv_plain0(z)));
    r = spu__xv_pos0(r, zm);
    if (!spu__xv_all4(ok)) r = spu__xv_fma_fix(r, ok, xa, y, zc, negp, negc);
    return spu__xv_st(r);
}
SPU__XV_INLINE u128 spu_fma(u128 a, u128 b, u128 c)  { return spu__xv_fma(a, b, c, 0, 0); }
SPU__XV_INLINE u128 spu_fms(u128 a, u128 b, u128 c)  { return spu__xv_fma(a, b, c, 0, 0x80000000u); }
SPU__XV_INLINE u128 spu_fnms(u128 a, u128 b, u128 c) { return spu__xv_fma(a, b, c, 0x80000000u, 0); }
#pragma clang fp contract(on)
#else
static inline u128 spu_fa(u128 a, u128 b) { return spu__fa_s(a, b); }''', "spu float avx2")
