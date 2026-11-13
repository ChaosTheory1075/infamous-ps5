# spu ffast: SPU single-precision fm/fa/fs/fma/fms/fnms in native single precision, still bit exact
# PC FoB no-draw profile: lifted SPU code is ~64% of SPU-thread samples and ~26% of that is the
# AVX2 float emulation (widen to double, truncate the 29 low bits, range-check every operand: ~35
# instructions, half of them 256-bit, per spu_fm). The SPU rounds toward zero; the host rounds to
# nearest. The native result r = RN(v) differs from RZ(v) by at most one unit, and only when the
# exact residual v - r has the opposite sign to r -- then RZ(v) is r with its magnitude one unit
# lower (the bit pattern minus one, also across a power of two). The residual is exact:
#   fm:  fmsub(x, y, r)                       (TwoProduct; result kept >= 2^-79 so it is normal)
#   fa:  TwoSum(x, y)                         (exact; inputs kept below 2^126 so it cannot overflow)
#   fma: fma_pd(x, y, z - r) in double        (z - r exact in double when their exponents differ
#                                              by at most 28; the sign of the double rounding of
#                                              v - r is the sign of v - r)
# Every lane must have ordinary inputs (biased exponent 1..254 or +-0) and an ordinary result
# (or zero, which the SPU returns as +0); any other vector goes to the exact AVX2 path as before
# (out of line when on). The MXCSR stays at its default (round to nearest, no FTZ/DAZ): nothing in the
# runtime changes it. OFF by default (-DSPU_FFAST_ON): a micro-benchmark measured fm -10%, fa -7%, fma +10% time vs the
# exact AVX2 path, ~3% overall -- not worth the risk. tools/test_spu_ffast.c checks
# the new forms against the scalar exact forms (spu_*_ref) bit for bit.
SFH = "runtime/spu/spu_helpers.h"
edit(SFH,
     '''SPU__XV_INLINE u128 spu_fa(u128 a, u128 b) { return spu__xv_fa(a, b, 0); }
SPU__XV_INLINE u128 spu_fs(u128 a, u128 b) { return spu__xv_fa(a, b, 0x80000000u); }
SPU__XV_INLINE u128 spu_fm(u128 a, u128 b) {
    const __m128i x = spu__xv_ld(a), y = spu__xv_ld(b);''',
     '''#if defined(__FMA__) && defined(SPU_FFAST_ON)   /* measured ~3% faster only: off */
#define SPU_FFAST 1
#define SPU__FX SPU__XV_SLOW
#else
#define SPU__FX SPU__XV_INLINE
#endif
SPU__FX u128 spu__xv_fa_x(u128 a, u128 b, uint32_t negb) { return spu__xv_fa(a, b, negb); }
SPU__FX u128 spu__xv_fm_x(u128 a, u128 b) {
    const __m128i x = spu__xv_ld(a), y = spu__xv_ld(b);''',
     "spu ffast: exact fa/fm out of line")
edit(SFH,
     '''SPU__XV_INLINE u128 spu_fma(u128 a, u128 b, u128 c)  { return spu__xv_fma(a, b, c, 0, 0); }
SPU__XV_INLINE u128 spu_fms(u128 a, u128 b, u128 c)  { return spu__xv_fma(a, b, c, 0, 0x80000000u); }
SPU__XV_INLINE u128 spu_fnms(u128 a, u128 b, u128 c) { return spu__xv_fma(a, b, c, 0x80000000u, 0); }''',
     '''SPU__FX u128 spu__xv_fma_x(u128 a, u128 b, u128 c, uint32_t negp, uint32_t negc) {
    return spu__xv_fma(a, b, c, negp, negc);
}
#ifdef SPU_FFAST
/* Native single precision, corrected to round-toward-zero (tools/patch_spu_ffast.py). */
SPU__XV_INLINE __m128i spu__ff_range(__m128i r, int lo, int hi) {   /* biased exponent lo..hi, or +-0 */
    const __m128i t = _mm_sub_epi32(spu__xv_bexp(r), _mm_set1_epi32(lo));
    return _mm_or_si128(_mm_cmpeq_epi32(_mm_min_epu32(t, _mm_set1_epi32(hi - lo)), t), spu__xv_iszero(r));
}
/* r one unit toward zero where the residual e is nonzero, of the other sign, and r is not zero. */
SPU__XV_INLINE __m128i spu__ff_fix(__m128i r, __m128i e_sign_word, __m128i e_zero) {
    const __m128i fix = _mm_andnot_si128(_mm_or_si128(e_zero, spu__xv_iszero(r)),
                                         _mm_srai_epi32(_mm_xor_si128(e_sign_word, r), 31));
    return _mm_add_epi32(r, fix);
}
SPU__XV_INLINE u128 spu__ff_fa(u128 a, u128 b, uint32_t negb) {
    const __m128i xi = spu__xv_ld(a), yi = _mm_xor_si128(spu__xv_ld(b), _mm_set1_epi32((int)negb));
    const __m128 x = _mm_castsi128_ps(xi), y = _mm_castsi128_ps(yi);
    const __m128 s = _mm_add_ps(x, y), bb = _mm_sub_ps(s, x);
    const __m128i e = _mm_castps_si128(_mm_add_ps(_mm_sub_ps(x, _mm_sub_ps(s, bb)), _mm_sub_ps(y, bb)));
    const __m128i si = _mm_castps_si128(s);
    __m128i o = spu__ff_fix(si, e, spu__xv_iszero(e));
    /* inputs below 2^126: TwoSum's s - x cannot overflow */
    const __m128i ok = _mm_and_si128(_mm_and_si128(spu__ff_range(xi, 1, 252), spu__ff_range(yi, 1, 252)),
                                     _mm_and_si128(spu__ff_range(si, 1, 254), spu__ff_range(o, 1, 254)));
    if (__builtin_expect(!spu__xv_all4(ok), 0)) return spu__xv_fa_x(a, b, negb);
    return spu__xv_st(spu__xv_pos0(o, spu__xv_iszero(o)));
}
SPU__XV_INLINE u128 spu_fa(u128 a, u128 b) { return spu__ff_fa(a, b, 0); }
SPU__XV_INLINE u128 spu_fs(u128 a, u128 b) { return spu__ff_fa(a, b, 0x80000000u); }
SPU__XV_INLINE u128 spu_fm(u128 a, u128 b) {
    const __m128i xi = spu__xv_ld(a), yi = spu__xv_ld(b);
    const __m128 x = _mm_castsi128_ps(xi), y = _mm_castsi128_ps(yi);
    const __m128 r = _mm_mul_ps(x, y);
    const __m128i ri = _mm_castps_si128(r), e = _mm_castps_si128(_mm_fmsub_ps(x, y, r));
    const __m128i o = spu__ff_fix(ri, e, spu__xv_iszero(e));
    const __m128i ok = _mm_and_si128(_mm_and_si128(spu__xv_plain0(xi), spu__xv_plain0(yi)), spu__ff_range(ri, 48, 254));
    if (__builtin_expect(!spu__xv_all4(ok), 0)) return spu__xv_fm_x(a, b);
    return spu__xv_st(spu__xv_pos0(o, spu__xv_iszero(o)));
}
SPU__XV_INLINE u128 spu__ff_fma(u128 a, u128 b, u128 c, uint32_t negp, uint32_t negc) {
    const __m128i xi = _mm_xor_si128(spu__xv_ld(a), _mm_set1_epi32((int)negp)), yi = spu__xv_ld(b);
    const __m128i zi = _mm_xor_si128(spu__xv_ld(c), _mm_set1_epi32((int)negc));
    const __m128 r = _mm_fmadd_ps(_mm_castsi128_ps(xi), _mm_castsi128_ps(yi), _mm_castsi128_ps(zi));
    const __m128i ri = _mm_castps_si128(r);
    const __m256d w = _mm256_fmadd_pd(spu__xv_wide(xi), spu__xv_wide(yi),
                                      _mm256_sub_pd(spu__xv_wide(zi), spu__xv_wide(ri)));
    const __m256i hi32 = _mm256_setr_epi32(1, 3, 5, 7, 1, 3, 5, 7);
    const __m128i wsign = _mm256_castsi256_si128(_mm256_permutevar8x32_epi32(_mm256_castpd_si256(w), hi32));
    const __m128i wzero = _mm256_castsi256_si128(_mm256_permutevar8x32_epi32(
        _mm256_castpd_si256(_mm256_cmp_pd(w, _mm256_setzero_pd(), _CMP_EQ_OQ)), hi32));
    const __m128i o = spu__ff_fix(ri, wsign, wzero);
    /* z - r is exact in double when the exponents differ by at most 28 (or either is zero) */
    const __m128i gap = _mm_abs_epi32(_mm_sub_epi32(spu__xv_bexp(zi), spu__xv_bexp(ri)));
    const __m128i dex = _mm_or_si128(_mm_cmpgt_epi32(_mm_set1_epi32(29), gap),
                                     _mm_or_si128(spu__xv_iszero(zi), spu__xv_iszero(ri)));
    const __m128i ok = _mm_and_si128(_mm_and_si128(_mm_and_si128(spu__xv_plain0(xi), spu__xv_plain0(yi)),
                                                   _mm_and_si128(spu__xv_plain0(zi), dex)),
                                     _mm_and_si128(spu__ff_range(ri, 1, 254), spu__ff_range(o, 1, 254)));
    if (__builtin_expect(!spu__xv_all4(ok), 0)) return spu__xv_fma_x(a, b, c, negp, negc);
    return spu__xv_st(spu__xv_pos0(o, spu__xv_iszero(o)));
}
SPU__XV_INLINE u128 spu_fma(u128 a, u128 b, u128 c)  { return spu__ff_fma(a, b, c, 0, 0); }
SPU__XV_INLINE u128 spu_fms(u128 a, u128 b, u128 c)  { return spu__ff_fma(a, b, c, 0, 0x80000000u); }
SPU__XV_INLINE u128 spu_fnms(u128 a, u128 b, u128 c) { return spu__ff_fma(a, b, c, 0x80000000u, 0); }
#else
SPU__XV_INLINE u128 spu_fa(u128 a, u128 b) { return spu__xv_fa_x(a, b, 0); }
SPU__XV_INLINE u128 spu_fs(u128 a, u128 b) { return spu__xv_fa_x(a, b, 0x80000000u); }
SPU__XV_INLINE u128 spu_fm(u128 a, u128 b) { return spu__xv_fm_x(a, b); }
SPU__XV_INLINE u128 spu_fma(u128 a, u128 b, u128 c)  { return spu__xv_fma_x(a, b, c, 0, 0); }
SPU__XV_INLINE u128 spu_fms(u128 a, u128 b, u128 c)  { return spu__xv_fma_x(a, b, c, 0, 0x80000000u); }
SPU__XV_INLINE u128 spu_fnms(u128 a, u128 b, u128 c) { return spu__xv_fma_x(a, b, c, 0x80000000u, 0); }
#endif''',
     "spu ffast: native fast paths")
