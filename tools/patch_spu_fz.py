# spu fz: SPU single-precision fa/fs/fm/fma/fms/fnms as one native instruction, bit exact, under MXCSR RZ|FTZ|DAZ
# if2 boat-deck profile (2026-11-02): lifted SPU code is ~87% of the SPU threads' samples, and the
# hottest job module (jobmod_d0d15ec83992, 43% of them) is float code whose time is the AVX2 exact
# emulation (widen to double, truncate, range checks: ~25-35 instructions per op). The SPU rounds
# toward zero, flushes denormal operands and results to zero, and never returns -0. x86 does the
# same in hardware with MXCSR RC=toward zero, FTZ and DAZ (0xFFC0): a native addps/mulps/vfmadd*ps
# then gives the SPU's result for every operand except two cases, which take the exact path
# (with the default MXCSR restored around it):
#   - an operand with biased exponent 255 (SPU extended range; x86 Inf/NaN);
#   - a result of magnitude FLT_MAX (an RZ overflow; the SPU's extended range goes higher).
# A zero result is made +0. The instructions are inline asm so the compiler cannot constant-fold
# them in round-to-nearest. spu_run_with_halt (every lifted SPU run) sets the MXCSR on entry and
# restores the caller's on exit; the double-precision helpers (IEEE round to nearest) set the
# default MXCSR around themselves. SPU_FZ=0 = the previous exact AVX2 path (read once at startup).
# tools/test_spu_fz.c checks it bit for bit against the scalar exact forms (spu_*_ref).
SFH = "runtime/spu/spu_helpers.h"
edit(SFH,
     '''#else
SPU__XV_INLINE u128 spu_fa(u128 a, u128 b) { return spu__xv_fa_x(a, b, 0); }
SPU__XV_INLINE u128 spu_fs(u128 a, u128 b) { return spu__xv_fa_x(a, b, 0x80000000u); }
SPU__XV_INLINE u128 spu_fm(u128 a, u128 b) { return spu__xv_fm_x(a, b); }
SPU__XV_INLINE u128 spu_fma(u128 a, u128 b, u128 c)  { return spu__xv_fma_x(a, b, c, 0, 0); }
SPU__XV_INLINE u128 spu_fms(u128 a, u128 b, u128 c)  { return spu__xv_fma_x(a, b, c, 0, 0x80000000u); }
SPU__XV_INLINE u128 spu_fnms(u128 a, u128 b, u128 c) { return spu__xv_fma_x(a, b, c, 0x80000000u, 0); }
#endif''',
     '''#else
/* spu fz (tools/patch_spu_fz.py): native single precision under MXCSR RZ|FTZ|DAZ, bit exact. */
#define SPU_FZ_MXCSR 0xFFC0u
SPU_GATE int g_spu_fz = 0;   /* 1: lifted SPU runs set SPU_FZ_MXCSR (spu_run_with_halt); SPU_FZ=0 turns it off */
SPU__XV_INLINE __m128 spu__fz_m(u128 v) { __m128 r; memcpy(&r, &v, 16); return r; }
SPU__XV_INLINE u128 spu__fz_u(__m128 v) { u128 r; memcpy(&r, &v, 16); return r; }
/* any lane the hardware may get wrong: an operand with exponent 255, or a result of magnitude FLT_MAX */
SPU__XV_INLINE int spu__fz_bad(__m128 x, __m128 y, __m128 z, __m128 r) {
    const __m128i e = _mm_set1_epi32(0x7F800000);
    const __m128i bx = _mm_cmpeq_epi32(_mm_and_si128(_mm_castps_si128(x), e), e);
    const __m128i by = _mm_cmpeq_epi32(_mm_and_si128(_mm_castps_si128(y), e), e);
    const __m128i bz = _mm_cmpeq_epi32(_mm_and_si128(_mm_castps_si128(z), e), e);
    const __m128i br = _mm_cmpeq_epi32(_mm_and_si128(_mm_castps_si128(r), _mm_set1_epi32(0x7FFFFFFF)),
                                       _mm_set1_epi32(0x7F7FFFFF));
    const __m128i bad = _mm_or_si128(_mm_or_si128(bx, by), _mm_or_si128(bz, br));
    return !_mm_testz_si128(bad, bad);
}
SPU__XV_INLINE u128 spu__fz_pos0(__m128 r) {   /* the SPU never returns -0 (r is never NaN here) */
    return spu__fz_u(_mm_and_ps(r, _mm_cmpneq_ps(r, _mm_setzero_ps())));
}
/* the exact path, with the default MXCSR around it (it computes in double, round to nearest) */
SPU__XV_SLOW u128 spu__fz_slow(int op, u128 a, u128 b, u128 c) {
    const unsigned m = _mm_getcsr();
    _mm_setcsr(0x1F80u);
    u128 r;
    switch (op) {
    case 0: r = spu__xv_fa_x(a, b, 0); break;
    case 1: r = spu__xv_fa_x(a, b, 0x80000000u); break;
    case 2: r = spu__xv_fm_x(a, b); break;
    case 3: r = spu__xv_fma_x(a, b, c, 0, 0); break;
    case 4: r = spu__xv_fma_x(a, b, c, 0, 0x80000000u); break;
    default: r = spu__xv_fma_x(a, b, c, 0x80000000u, 0); break;
    }
    _mm_setcsr(m);
    return r;
}
#define SPU__FZ2(name, insn, op, exact)                                                        \\
SPU__XV_INLINE u128 name(u128 a, u128 b) {                                                     \\
    if (__builtin_expect(g_spu_fz != 0, 1)) {                                                  \\
        const __m128 x = spu__fz_m(a), y = spu__fz_m(b); __m128 r;                              \\
        __asm__(insn " %2, %1, %0" : "=x"(r) : "x"(x), "x"(y));                                 \\
        if (__builtin_expect(spu__fz_bad(x, y, y, r), 0)) return spu__fz_slow(op, a, b, b);     \\
        return spu__fz_pos0(r);                                                                \\
    }                                                                                          \\
    return exact;                                                                              \\
}
#define SPU__FZ3(name, insn, op, exact)                                                        \\
SPU__XV_INLINE u128 name(u128 a, u128 b, u128 c) {                                             \\
    if (__builtin_expect(g_spu_fz != 0, 1)) {                                                  \\
        const __m128 x = spu__fz_m(a), y = spu__fz_m(b), z = spu__fz_m(c); __m128 r;            \\
        __asm__(insn " %3, %2, %0" : "=x"(r) : "0"(x), "x"(y), "x"(z));                         \\
        if (__builtin_expect(spu__fz_bad(x, y, z, r), 0)) return spu__fz_slow(op, a, b, c);     \\
        return spu__fz_pos0(r);                                                                \\
    }                                                                                          \\
    return exact;                                                                              \\
}
SPU__FZ2(spu_fa, "vaddps", 0, spu__xv_fa_x(a, b, 0))
SPU__FZ2(spu_fs, "vsubps", 1, spu__xv_fa_x(a, b, 0x80000000u))
SPU__FZ2(spu_fm, "vmulps", 2, spu__xv_fm_x(a, b))
SPU__FZ3(spu_fma,  "vfmadd213ps",  3, spu__xv_fma_x(a, b, c, 0, 0))            /* a*b + c */
SPU__FZ3(spu_fms,  "vfmsub213ps",  4, spu__xv_fma_x(a, b, c, 0, 0x80000000u))  /* a*b - c */
SPU__FZ3(spu_fnms, "vfnmadd213ps", 5, spu__xv_fma_x(a, b, c, 0x80000000u, 0))  /* c - a*b */
#undef SPU__FZ2
#undef SPU__FZ3
#endif''',
     "spu fz: native float under RZ mxcsr")
# The double-precision helpers round to nearest: default MXCSR around them while spu fz is on.
edit(SFH,
     '''/* ---- double precision: IEEE, round to nearest (see the header of this section) ---- */''',
     '''/* ---- double precision: IEEE, round to nearest (see the header of this section) ---- */
#if defined(SPU_FLOAT_AVX2) && defined(SPU_FZ_MXCSR)   /* spu fz rn: default MXCSR around double math */
static inline unsigned spu__fz_rn_begin(void) {
    if (!g_spu_fz) return 0;
    const unsigned m = _mm_getcsr(); _mm_setcsr(0x1F80u); return m;
}
static inline void spu__fz_rn_end(unsigned m) { if (m) _mm_setcsr(m); }
#else
static inline unsigned spu__fz_rn_begin(void) { return 0; }
static inline void spu__fz_rn_end(unsigned m) { (void)m; }
#endif''',
     "spu fz: rn helpers")
edit(SFH,
     '''#define SPU__D_V2(name, op) static inline u128 name(u128 a, u128 b) { u128 r; for (int i = 0; i < 2; i++) { \\
    const uint64_t x = spu__dw_get(a, i), y = spu__dw_get(b, i); \\
    spu__dw_put(&r, i, (spu__d_isnan(x) || spu__d_isnan(y)) ? 0x7FF8000000000000ull \\
                       : spu__d_out(spu__d_in(x) op spu__d_in(y))); } return r; }''',
     '''#define SPU__D_V2(name, op) static inline u128 name(u128 a, u128 b) { u128 r; const unsigned fzm = spu__fz_rn_begin(); \\
    for (int i = 0; i < 2; i++) { /* spu fz rn: dfa/dfs/dfm */ \\
    const uint64_t x = spu__dw_get(a, i), y = spu__dw_get(b, i); \\
    spu__dw_put(&r, i, (spu__d_isnan(x) || spu__d_isnan(y)) ? 0x7FF8000000000000ull \\
                       : spu__d_out(spu__d_in(x) op spu__d_in(y))); } spu__fz_rn_end(fzm); return r; }''',
     "spu fz: rn dfa")
edit(SFH,
     '''static inline u128 spu__dfmx(u128 a, u128 b, u128 c, int negate, int subtract) { u128 r;
    for (int i = 0; i < 2; i++) {''',
     '''static inline u128 spu__dfmx(u128 a, u128 b, u128 c, int negate, int subtract) { u128 r;
    const unsigned fzm = spu__fz_rn_begin();   /* spu fz rn: dfma family */
    for (int i = 0; i < 2; i++) {''',
     "spu fz: rn dfmx begin")
edit(SFH,
     '''        spu__dw_put(&r, i, (negate && !spu__d_isnan(u)) ? u ^ 0x8000000000000000ull : u);
    }
    return r; }''',
     '''        spu__dw_put(&r, i, (negate && !spu__d_isnan(u)) ? u ^ 0x8000000000000000ull : u);
    }
    spu__fz_rn_end(fzm);   /* spu fz rn: dfma family end */
    return r; }''',
     "spu fz: rn dfmx end")
edit(SFH,
     '''static inline u128 spu_frds(u128 a) { u128 r;
    for (int i = 0; i < 2; i++) {''',
     '''static inline u128 spu_frds(u128 a) { u128 r;
    const unsigned fzm = spu__fz_rn_begin();   /* spu fz rn: frds */
    for (int i = 0; i < 2; i++) {''',
     "spu fz: rn frds begin")
edit(SFH,
     '''        r._u32[2*i] = w; r._u32[2*i+1] = 0;
    }
    return r; }''',
     '''        r._u32[2*i] = w; r._u32[2*i+1] = 0;
    }
    spu__fz_rn_end(fzm);   /* spu fz rn: frds end */
    return r; }''',
     "spu fz: rn frds end")
# The MXCSR for every lifted SPU run; SPU_FZ read before any SPU thread starts.
SCH = "runtime/spu/spu_channels.c"
edit(SCH,
     '''/* Run a lifted SPU entry with a halt landing pad. Returns 1 if the job halted
 * (via spu_halt), 0 if it returned normally. */
int spu_run_with_halt(void (*entry)(spu_context*), spu_context* ctx)
{
    int halted = 0;''',
     '''#if defined(SPU_FZ_MXCSR)   /* spu fz: SPU_FZ=0 keeps the exact AVX2 float path */
__attribute__((constructor)) static void spu_fz_init(void)
{
    const char* e = getenv("SPU_FZ");
    g_spu_fz = !(e && e[0] == '0');
    fprintf(stderr, "[spu] float: %s\\n", g_spu_fz ? "native, MXCSR round-toward-zero/FTZ/DAZ (SPU_FZ=0: exact AVX2 path)"
                                                  : "exact AVX2 path (SPU_FZ=0)");
}
#endif

/* Run a lifted SPU entry with a halt landing pad. Returns 1 if the job halted
 * (via spu_halt), 0 if it returned normally. */
int spu_run_with_halt(void (*entry)(spu_context*), spu_context* ctx)
{
    int halted = 0;
#if defined(SPU_FZ_MXCSR)
    const unsigned fz_outer = _mm_getcsr();   /* spu fz: the SPU's rounding for this run */
    if (g_spu_fz) _mm_setcsr(SPU_FZ_MXCSR);
#endif''',
     "spu fz: mxcsr in run_with_halt")
edit(SCH,
     '''    yz_lockstep_unregister(ctx);   /* leave the ring; hand the token onward */
    s_spu_halt_armed = outer_armed;
    if (outer_armed) memcpy(s_spu_halt_env, outer_env, sizeof(jmp_buf));
    return halted;''',
     '''    yz_lockstep_unregister(ctx);   /* leave the ring; hand the token onward */
    s_spu_halt_armed = outer_armed;
    if (outer_armed) memcpy(s_spu_halt_env, outer_env, sizeof(jmp_buf));
#if defined(SPU_FZ_MXCSR)
    _mm_setcsr(fz_outer);   /* spu fz: the caller's MXCSR back */
#endif
    return halted;''',
     "spu fz: mxcsr restore")
# spu fz: with SPU_FZ=0 the ops call the exact path out of line (spu__fz_slow: its MXCSR save/restore
# is a no-op then) instead of inlining it beside the native form at every site: inlined, every
# lifted float op carried ~40 instructions of dead code (the d0d15 chunk D8A8: ~4400 instructions).
edit(SFH,
     '''        return spu__fz_pos0(r);                                                                \\
    }                                                                                          \\
    return exact;                                                                              \\
}
#define SPU__FZ3(name, insn, op, exact)                                                        \\''',
     '''        return spu__fz_pos0(r);                                                                \\
    }                                                                                          \\
    return spu__fz_slow(op, a, b, b);   /* spu fz: exact path out of line */                    \\
}
#define SPU__FZ3(name, insn, op, exact)                                                        \\''',
     "spu fz: exact out of line 2")
edit(SFH,
     '''        return spu__fz_pos0(r);                                                                \\
    }                                                                                          \\
    return exact;                                                                              \\
}
SPU__FZ2(spu_fa,''',
     '''        return spu__fz_pos0(r);                                                                \\
    }                                                                                          \\
    return spu__fz_slow(op, a, b, c);   /* spu fz: exact path out of line (3) */                \\
}
SPU__FZ2(spu_fa,''',
     "spu fz: exact out of line 3")
