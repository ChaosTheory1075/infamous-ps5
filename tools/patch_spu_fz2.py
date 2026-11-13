# spu fz2: the native float ops' check on the result only, and the exact path returning in an XMM register
# Two costs left in every spu fz float op (d0d15 chunk D8A8, objdump):
#  - the range check tested all three operands and the result (13 instructions). Under round toward
#    zero a finite operand never gives Inf/NaN (an overflow is FLT_MAX), and an Inf/NaN operand
#    (exponent 255) always gives Inf/NaN in add/mul/fma. So |r| >= FLT_MAX (as integers) catches
#    every lane the exact path must redo: 3 instructions.
#  - spu__fz_slow returned a u128 by value, which the SysV ABI returns in rax:rdx; the merge of the
#    fast and slow results then kept every result as two i64 halves (vmovq + vpextrq + two 64-bit
#    stores per op). It now returns an __m128.
SFH = "runtime/spu/spu_helpers.h"
edit(SFH,
     '''/* the exact path, with the default MXCSR around it (it computes in double, round to nearest) */
SPU__XV_SLOW u128 spu__fz_slow(int op, u128 a, u128 b, u128 c) {''',
     '''/* spu fz2: lanes the hardware result may be wrong in: Inf/NaN (an operand of exponent 255) or
 * FLT_MAX (an overflow). */
SPU__XV_INLINE int spu__fz_bad_r(__m128 r) {
    const __m128i m = _mm_cmpgt_epi32(_mm_and_si128(_mm_castps_si128(r), _mm_set1_epi32(0x7FFFFFFF)),
                                      _mm_set1_epi32(0x7F7FFFFE));
    return !_mm_testz_si128(m, m);
}
/* the exact path, with the default MXCSR around it (it computes in double, round to nearest) */
SPU__XV_SLOW u128 spu__fz_slow(int op, u128 a, u128 b, u128 c);
SPU__XV_SLOW __m128 spu__fz_slowv(int op, u128 a, u128 b, u128 c) {   /* spu fz2: returns in xmm0 */
    const u128 r = spu__fz_slow(op, a, b, c);
    __m128 v; memcpy(&v, &r, 16); return v;
}
SPU__XV_SLOW u128 spu__fz_slow(int op, u128 a, u128 b, u128 c) {''',
     "spu fz2: result check + xmm slow")
edit(SFH,
     '''        __asm__(insn " %2, %1, %0" : "=x"(r) : "x"(x), "x"(y));                                 \\
        if (__builtin_expect(spu__fz_bad(x, y, y, r), 0)) return spu__fz_slow(op, a, b, b);     \\
        return spu__fz_pos0(r);                                                                \\
    }                                                                                          \\
    return spu__fz_slow(op, a, b, b);   /* spu fz: exact path out of line */                    \\''',
     '''        __asm__(insn " %2, %1, %0" : "=x"(r) : "x"(x), "x"(y));                                 \\
        if (__builtin_expect(spu__fz_bad_r(r), 0)) r = spu__fz_slowv(op, a, b, b);             \\
        else r = _mm_and_ps(r, _mm_cmpneq_ps(r, _mm_setzero_ps()));   /* spu fz2: +0 */         \\
        return spu__fz_u(r);                                                                   \\
    }                                                                                          \\
    return spu__fz_u(spu__fz_slowv(op, a, b, b));   /* spu fz: exact path out of line */        \\''',
     "spu fz2: FZ2 macro")
edit(SFH,
     '''        __asm__(insn " %3, %2, %0" : "=x"(r) : "0"(x), "x"(y), "x"(z));                         \\
        if (__builtin_expect(spu__fz_bad(x, y, z, r), 0)) return spu__fz_slow(op, a, b, c);     \\
        return spu__fz_pos0(r);                                                                \\
    }                                                                                          \\
    return spu__fz_slow(op, a, b, c);   /* spu fz: exact path out of line (3) */                \\''',
     '''        __asm__(insn " %3, %2, %0" : "=x"(r) : "0"(x), "x"(y), "x"(z));                         \\
        if (__builtin_expect(spu__fz_bad_r(r), 0)) r = spu__fz_slowv(op, a, b, c);             \\
        else r = _mm_and_ps(r, _mm_cmpneq_ps(r, _mm_setzero_ps()));   /* spu fz2: +0 (3) */     \\
        return spu__fz_u(r);                                                                   \\
    }                                                                                          \\
    return spu__fz_u(spu__fz_slowv(op, a, b, c));   /* spu fz: exact path out of line (3) */    \\''',
     "spu fz2: FZ3 macro")
