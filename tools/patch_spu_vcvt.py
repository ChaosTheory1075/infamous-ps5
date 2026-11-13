# spu vcvt: cflts/cfltu/csflt/cuflt, fi and the float compares as SSE vector code, bit exact (x86)
# After spu fz the scalar out-of-line helpers are the next float cost in the if2 SPU profile
# (spu_cflts 1.3%, spu_fi 0.8, spu_csflt 0.8, spu_cuflt 0.8 of all samples, called, not inlined).
#   cflts/cfltu: x * 2^scale is exact (or overflows/underflows, which saturates or truncates to 0
#     anyway); cvttps2dq truncates; positive overflow fixed to 0x7FFFFFFF, cfltu splits at 2^31;
#     exponent-0 lanes are the SPU's zero; exponent-255 lanes or a scale outside -126..127 take the
#     scalar path.
#   csflt/cuflt: cvtdq2ps under spu fz's round-toward-zero MXCSR is the SPU's truncation (cuflt:
#     hi*65536 + lo, one rounding); the 2^-scale is an exponent subtraction with the same
#     saturation and underflow as spu__sf_pack. Only with spu fz on (else the scalar path).
#   fi: the 33-bit fixed-point difference is formed as floor(m / 256) in 32-bit lanes, which keeps
#     every bit the truncated 23-bit fraction uses.
#   fceq/fcgt/fcmeq/fcmgt: zero/denormal -> 0, then sign-magnitude as two's complement.
# tools/test_spu_vcvt.c checks each against the scalar forms bit for bit.
SFH = "runtime/spu/spu_helpers.h"
edit(SFH,
     '''#else
static inline u128 spu_cflts(u128 a, int i8) { return spu_cflts_exact(a, i8); }
static inline u128 spu_cfltu(u128 a, int i8) { return spu_cfltu_exact(a, i8); }
#endif
static inline u128 spu_csflt(u128 a, int i8) { u128 r; for (int i = 0; i < 4; i++) { const int32_t v = a._s32[i];
    r._u32[i] = v ? spu__sf_pack(v < 0 ? 0x80000000u : 0, v < 0 ? 0u - (uint32_t)v : (uint32_t)v, -(155 - (i8 & 0xFF))) : 0; } return r; }
static inline u128 spu_cuflt(u128 a, int i8) { u128 r; for (int i = 0; i < 4; i++) { const uint32_t v = a._u32[i];
    r._u32[i] = v ? spu__sf_pack(0, v, -(155 - (i8 & 0xFF))) : 0; } return r; }''',
     '''#elif defined(SPU_FZ_MXCSR)   /* spu vcvt (tools/patch_spu_vcvt.py): SSE forms, bit exact */
static inline __m128i spu__vc_ld(u128 v) { __m128i r; memcpy(&r, &v, 16); return r; }
static inline u128 spu__vc_st(__m128i v) { u128 r; memcpy(&r, &v, 16); return r; }
static inline __m128i spu__vc_bexp(__m128i x) { return _mm_srli_epi32(_mm_slli_epi32(x, 1), 24); }
/* x * 2^scale, or 0 when a lane has exponent 255 or the scale is not a normal power of two */
static inline int spu__vc_scaled(__m128i x, int scale, __m128* f) {
    if (scale < -126 || scale > 127) return 0;
    const __m128i e255 = _mm_cmpeq_epi32(spu__vc_bexp(x), _mm_set1_epi32(255));
    if (!_mm_testz_si128(e255, e255)) return 0;
    *f = _mm_mul_ps(_mm_castsi128_ps(x), _mm_castsi128_ps(_mm_set1_epi32((127 + scale) << 23)));
    return 1;
}
static inline u128 spu_cflts(u128 a, int i8) {
    const __m128i x = spu__vc_ld(a); __m128 f;
    if (!spu__vc_scaled(x, 173 - (i8 & 0xFF), &f)) return spu_cflts_exact(a, i8);
    __m128i r = _mm_cvttps_epi32(f);
    const __m128i posov = _mm_and_si128(_mm_cmpeq_epi32(r, _mm_set1_epi32((int)0x80000000u)),
                                        _mm_cmpgt_epi32(x, _mm_set1_epi32(-1)));
    r = _mm_add_epi32(r, posov);                                          /* 0x80000000 -> 0x7FFFFFFF */
    return spu__vc_st(_mm_andnot_si128(_mm_cmpeq_epi32(spu__vc_bexp(x), _mm_setzero_si128()), r));
}
static inline u128 spu_cfltu(u128 a, int i8) {
    const __m128i x = spu__vc_ld(a); __m128 f;
    if (!spu__vc_scaled(x, 173 - (i8 & 0xFF), &f)) return spu_cfltu_exact(a, i8);
    const __m128 two31 = _mm_set1_ps(2147483648.0f);
    const __m128 big = _mm_cmpge_ps(f, two31);
    __m128i r = _mm_xor_si128(_mm_cvttps_epi32(_mm_sub_ps(f, _mm_and_ps(big, two31))),
                              _mm_and_si128(_mm_castps_si128(big), _mm_set1_epi32((int)0x80000000u)));
    r = _mm_or_si128(r, _mm_castps_si128(_mm_cmpge_ps(f, _mm_set1_ps(4294967296.0f))));
    const __m128i zero = _mm_or_si128(_mm_cmpeq_epi32(spu__vc_bexp(x), _mm_setzero_si128()),
                                      _mm_srai_epi32(x, 31));             /* SPU zero, or negative */
    return spu__vc_st(_mm_andnot_si128(zero, r));
}
static inline u128 spu_csflt_exact(u128 a, int i8) { u128 r; for (int i = 0; i < 4; i++) { const int32_t v = a._s32[i];
    r._u32[i] = v ? spu__sf_pack(v < 0 ? 0x80000000u : 0, v < 0 ? 0u - (uint32_t)v : (uint32_t)v, -(155 - (i8 & 0xFF))) : 0; } return r; }
static inline u128 spu_cuflt_exact(u128 a, int i8) { u128 r; for (int i = 0; i < 4; i++) { const uint32_t v = a._u32[i];
    r._u32[i] = v ? spu__sf_pack(0, v, -(155 - (i8 & 0xFF))) : 0; } return r; }
/* f = the truncated single of the integer (spu fz MXCSR); scaled by 2^-s as spu__sf_pack does */
static inline u128 spu__vc_unscale(__m128i v, __m128i fi, int s) {
    const __m128i e = _mm_sub_epi32(spu__vc_bexp(fi), _mm_set1_epi32(s));
    __m128i r = _mm_or_si128(_mm_and_si128(fi, _mm_set1_epi32((int)0x807FFFFFu)), _mm_slli_epi32(e, 23));
    const __m128i over = _mm_cmpgt_epi32(e, _mm_set1_epi32(255));
    r = _mm_blendv_epi8(r, _mm_or_si128(_mm_and_si128(fi, _mm_set1_epi32((int)0x80000000u)), _mm_set1_epi32(0x7FFFFFFF)), over);
    const __m128i under = _mm_or_si128(_mm_cmpgt_epi32(_mm_set1_epi32(1), e), _mm_cmpeq_epi32(v, _mm_setzero_si128()));
    return spu__vc_st(_mm_andnot_si128(under, r));
}
static inline u128 spu_csflt(u128 a, int i8) {
    if (!g_spu_fz) return spu_csflt_exact(a, i8);
    const __m128i v = spu__vc_ld(a);
    __m128 f; __asm__("vcvtdq2ps %1, %0" : "=x"(f) : "x"(v));        /* rounds per the MXCSR: toward zero */
    return spu__vc_unscale(v, _mm_castps_si128(f), 155 - (i8 & 0xFF));
}
static inline u128 spu_cuflt(u128 a, int i8) {
    if (!g_spu_fz) return spu_cuflt_exact(a, i8);
    const __m128i v = spu__vc_ld(a);
    const __m128i hi = _mm_srli_epi32(v, 16), lo = _mm_and_si128(v, _mm_set1_epi32(0xFFFF));
    __m128 fh, fl, f;
    __asm__("vcvtdq2ps %1, %0" : "=x"(fh) : "x"(hi));
    __asm__("vcvtdq2ps %1, %0" : "=x"(fl) : "x"(lo));
    fh = _mm_mul_ps(fh, _mm_set1_ps(65536.0f));                           /* exact */
    __asm__("vaddps %2, %1, %0" : "=x"(f) : "x"(fh), "x"(fl));            /* one rounding, toward zero */
    return spu__vc_unscale(v, _mm_castps_si128(f), 155 - (i8 & 0xFF));
}
#else
static inline u128 spu_cflts(u128 a, int i8) { return spu_cflts_exact(a, i8); }
static inline u128 spu_cfltu(u128 a, int i8) { return spu_cfltu_exact(a, i8); }
#endif
#ifndef SPU_FZ_MXCSR
static inline u128 spu_csflt(u128 a, int i8) { u128 r; for (int i = 0; i < 4; i++) { const int32_t v = a._s32[i];
    r._u32[i] = v ? spu__sf_pack(v < 0 ? 0x80000000u : 0, v < 0 ? 0u - (uint32_t)v : (uint32_t)v, -(155 - (i8 & 0xFF))) : 0; } return r; }
static inline u128 spu_cuflt(u128 a, int i8) { u128 r; for (int i = 0; i < 4; i++) { const uint32_t v = a._u32[i];
    r._u32[i] = v ? spu__sf_pack(0, v, -(155 - (i8 & 0xFF))) : 0; } return r; }
#endif''',
     "spu vcvt: cflt/csflt sse")
edit(SFH,
     '''static inline u128 spu_fi(u128 a, u128 b) {
    u128 r;''',
     '''static inline u128 spu_fi_exact(u128 a, u128 b) {   /* spu vcvt: the scalar form */
    u128 r;''',
     "spu vcvt: fi exact rename")
edit(SFH,
     '''        r._u32[i] = sign | ((uint32_t)exp << 23) | frac;
    }
    return r;
}''',
     '''        r._u32[i] = sign | ((uint32_t)exp << 23) | frac;
    }
    return r;
}
#if defined(SPU_FZ_MXCSR)   /* spu vcvt: fi in 32-bit lanes; m8 = floor(m / 256), m < 2^33 */
static inline u128 spu_fi(u128 a, u128 b) {
    const __m128i est = spu__vc_ld(b), y = _mm_and_si128(spu__vc_ld(a), _mm_set1_epi32(0x7FFFF));
    const __m128i exp = _mm_and_si128(_mm_srli_epi32(est, 23), _mm_set1_epi32(0xFF));
    const __m128i base = _mm_and_si128(_mm_srli_epi32(est, 10), _mm_set1_epi32(0x1FFF));
    const __m128i step = _mm_and_si128(est, _mm_set1_epi32(0x3FF));
    const __m128i a8 = _mm_slli_epi32(_mm_or_si128(base, _mm_set1_epi32(0x2000)), 11);
    const __m128i m8 = _mm_sub_epi32(a8, _mm_srli_epi32(_mm_add_epi32(_mm_mullo_epi32(step, y), _mm_set1_epi32(255)), 8));
    const __m128i lt1 = _mm_cmpgt_epi32(_mm_set1_epi32(1 << 24), m8);    /* magnitude below 1.0 */
    const __m128i frac = _mm_and_si128(_mm_blendv_epi8(_mm_srli_epi32(m8, 1), m8, lt1), _mm_set1_epi32(0x7FFFFF));
    const __m128i e2 = _mm_add_epi32(exp, lt1);
    const __m128i r = _mm_or_si128(_mm_or_si128(_mm_and_si128(est, _mm_set1_epi32((int)0x80000000u)), _mm_slli_epi32(e2, 23)), frac);
    const __m128i zero = _mm_or_si128(_mm_cmpeq_epi32(exp, _mm_setzero_si128()), _mm_cmpeq_epi32(e2, _mm_setzero_si128()));
    return spu__vc_st(_mm_andnot_si128(zero, r));
}
#else
static inline u128 spu_fi(u128 a, u128 b) { return spu_fi_exact(a, b); }
#endif''',
     "spu vcvt: fi sse")
edit(SFH,
     '''SPU__SF_V2(spu_fceq,  spu__sf_key(x) == spu__sf_key(y) ? 0xFFFFFFFFu : 0u)
SPU__SF_V2(spu_fcgt,  spu__sf_key(x) >  spu__sf_key(y) ? 0xFFFFFFFFu : 0u)
SPU__SF_V2(spu_fcmeq, spu__sf_mag(x) == spu__sf_mag(y) ? 0xFFFFFFFFu : 0u)
SPU__SF_V2(spu_fcmgt, spu__sf_mag(x) >  spu__sf_mag(y) ? 0xFFFFFFFFu : 0u)''',
     '''SPU__SF_V2(spu_fceq_ref,  spu__sf_key(x) == spu__sf_key(y) ? 0xFFFFFFFFu : 0u)   /* spu vcvt: scalar forms */
SPU__SF_V2(spu_fcgt_ref,  spu__sf_key(x) >  spu__sf_key(y) ? 0xFFFFFFFFu : 0u)
SPU__SF_V2(spu_fcmeq_ref, spu__sf_mag(x) == spu__sf_mag(y) ? 0xFFFFFFFFu : 0u)
SPU__SF_V2(spu_fcmgt_ref, spu__sf_mag(x) >  spu__sf_mag(y) ? 0xFFFFFFFFu : 0u)
#if defined(SPU_FZ_MXCSR)
static inline __m128i spu__fc_mag(u128 v) {   /* |x| with the SPU's zeros (exponent 0) as 0 */
    __m128i x; memcpy(&x, &v, 16);
    const __m128i m = _mm_and_si128(x, _mm_set1_epi32(0x7FFFFFFF));
    return _mm_and_si128(m, _mm_cmpgt_epi32(m, _mm_set1_epi32(0x7FFFFF)));
}
static inline __m128i spu__fc_key(u128 v) {   /* sign-magnitude as two's complement */
    __m128i x; memcpy(&x, &v, 16);
    const __m128i s = _mm_srai_epi32(x, 31);
    return _mm_sub_epi32(_mm_xor_si128(spu__fc_mag(v), s), s);
}
static inline u128 spu__fc_st(__m128i m) { u128 r; memcpy(&r, &m, 16); return r; }
static inline u128 spu_fceq(u128 a, u128 b)  { return spu__fc_st(_mm_cmpeq_epi32(spu__fc_key(a), spu__fc_key(b))); }
static inline u128 spu_fcgt(u128 a, u128 b)  { return spu__fc_st(_mm_cmpgt_epi32(spu__fc_key(a), spu__fc_key(b))); }
static inline u128 spu_fcmeq(u128 a, u128 b) { return spu__fc_st(_mm_cmpeq_epi32(spu__fc_mag(a), spu__fc_mag(b))); }
static inline u128 spu_fcmgt(u128 a, u128 b) { return spu__fc_st(_mm_cmpgt_epi32(spu__fc_mag(a), spu__fc_mag(b))); }
#else
static inline u128 spu_fceq(u128 a, u128 b)  { return spu_fceq_ref(a, b); }
static inline u128 spu_fcgt(u128 a, u128 b)  { return spu_fcgt_ref(a, b); }
static inline u128 spu_fcmeq(u128 a, u128 b) { return spu_fcmeq_ref(a, b); }
static inline u128 spu_fcmgt(u128 a, u128 b) { return spu_fcmgt_ref(a, b); }
#endif''',
     "spu vcvt: fc sse")
