
# spu x86 mpy and ls: SSE4.1 16-bit multiplies and one-pshufb local-store quadword loads/stores
# The x86 builds (Linux zen2, the PS5) ran mpy/mpyu/mpyh/mpyhh/mpyi/mpyui/mpya as four scalar imuls,
# and every lqd/stqd as four 32-bit loads + bswaps merged through 64-bit registers. Same results
# (tools/test_spu_x86_mpy_ls.c compares each against its _ref / the scalar form).
for name, args, body in [
    ("spu_mpy",   "u128 a, u128 b",          "_mm_mullo_epi32(SPU__LO16S(spu__m128(a)), SPU__LO16S(spu__m128(b)))"),
    ("spu_mpyu",  "u128 a, u128 b",          "_mm_mullo_epi32(SPU__LO16U(spu__m128(a)), SPU__LO16U(spu__m128(b)))"),
    ("spu_mpyh",  "u128 a, u128 b",          "_mm_slli_epi32(_mm_mullo_epi32(_mm_srai_epi32(spu__m128(a), 16), SPU__LO16S(spu__m128(b))), 16)"),
    ("spu_mpyhh", "u128 a, u128 b",          "_mm_mullo_epi32(_mm_srai_epi32(spu__m128(a), 16), _mm_srai_epi32(spu__m128(b), 16))"),
]:
    edit("runtime/spu/spu_helpers.h",
         "static inline u128 %s(%s) { return %s_ref(a, b); }" % (name, args, name),
         "#if defined(__SSE4_1__)\nstatic inline u128 %s(%s) { return spu__u128(%s); }\n#else\n"
         "static inline u128 %s(%s) { return %s_ref(a, b); }\n#endif" % (name, args, body, name, args, name),
         "spu x86 " + name)
edit("runtime/spu/spu_helpers.h",
     "static inline u128 spu_mpyi(u128 a, int32_t imm) { return spu_mpyi_ref(a, imm); }",
     "#if defined(__SSE4_1__)\nstatic inline u128 spu_mpyi(u128 a, int32_t imm) { return spu__u128(_mm_mullo_epi32(SPU__LO16S(spu__m128(a)), _mm_set1_epi32((int32_t)(int16_t)imm))); }\n#else\n"
     "static inline u128 spu_mpyi(u128 a, int32_t imm) { return spu_mpyi_ref(a, imm); }\n#endif",
     "spu x86 spu_mpyi")
edit("runtime/spu/spu_helpers.h",
     "static inline u128 spu_mpyui(u128 a, int32_t imm) { return spu_mpyui_ref(a, imm); }",
     "#if defined(__SSE4_1__)\nstatic inline u128 spu_mpyui(u128 a, int32_t imm) { return spu__u128(_mm_mullo_epi32(SPU__LO16U(spu__m128(a)), _mm_set1_epi32((int32_t)(uint16_t)imm))); }\n#else\n"
     "static inline u128 spu_mpyui(u128 a, int32_t imm) { return spu_mpyui_ref(a, imm); }\n#endif",
     "spu x86 spu_mpyui")
edit("runtime/spu/spu_helpers.h",
     "static inline u128 spu_mpya(u128 a, u128 b, u128 c) { return spu_mpya_ref(a, b, c); }",
     "#if defined(__SSE4_1__)\nstatic inline u128 spu_mpya(u128 a, u128 b, u128 c) { return spu__u128(_mm_add_epi32(spu__m128(spu_mpy(a, b)), spu__m128(c))); }\n#else\n"
     "static inline u128 spu_mpya(u128 a, u128 b, u128 c) { return spu_mpya_ref(a, b, c); }\n#endif",
     "spu x86 spu_mpya")
# The converters and lane masks the forms above use, next to the SSE4.1 shufb.
edit("runtime/spu/spu_helpers.h",
     '''#if defined(__SSE4_1__)
#include <smmintrin.h>''',
     '''#if defined(__SSE4_1__)
#include <smmintrin.h>
/* u128 <-> __m128i (the x86 integer forms; memcpy compiles to nothing) and the low halfword of
 * each word, sign- or zero-extended -- the operand of the 16-bit multiplies. */
static inline __m128i spu__m128(u128 a) { __m128i x; memcpy(&x, &a, 16); return x; }
static inline u128 spu__u128(__m128i x) { u128 r; memcpy(&r, &x, 16); return r; }
#define SPU__LO16S(x) _mm_srai_epi32(_mm_slli_epi32((x), 16), 16)
#define SPU__LO16U(x) _mm_and_si128((x), _mm_set1_epi32(0xFFFF))''',
     "spu x86 m128 converters")
# Local store: one unaligned load and a pshufb (each word's bytes reversed), and back.
edit("runtime/spu/spu_context.h",
     '''    const uint8_t* p = &ctx->ls[lsa];
#if SPU_LS_FAST
    uint32_t w0, w1, w2, w3;''',
     '''    const uint8_t* p = &ctx->ls[lsa];
#if SPU_LS_FAST && defined(__SSSE3__)
    { __m128i x = _mm_loadu_si128((const __m128i*)p);
      x = _mm_shuffle_epi8(x, _mm_setr_epi8(3,2,1,0, 7,6,5,4, 11,10,9,8, 15,14,13,12));
      memcpy(&v, &x, 16); }
#elif SPU_LS_FAST
    uint32_t w0, w1, w2, w3;''',
     "spu x86 ls read128")
edit("runtime/spu/spu_context.h",
     '''#if SPU_LS_FAST
    uint32_t w0 = SPU_BSWAP32(val._u32[0]), w1 = SPU_BSWAP32(val._u32[1]);''',
     '''#if SPU_LS_FAST && defined(__SSSE3__)
    { __m128i x; memcpy(&x, &val, 16);
      x = _mm_shuffle_epi8(x, _mm_setr_epi8(3,2,1,0, 7,6,5,4, 11,10,9,8, 15,14,13,12));
      _mm_storeu_si128((__m128i*)p, x); }
#elif SPU_LS_FAST
    uint32_t w0 = SPU_BSWAP32(val._u32[0]), w1 = SPU_BSWAP32(val._u32[1]);''',
     "spu x86 ls write128")
edit("runtime/spu/spu_context.h",
     '''static inline __attribute__((always_inline)) u128 spu_ls_read128(const spu_context* ctx, uint32_t lsa)''',
     '''#if defined(__SSSE3__)
#include <tmmintrin.h>   /* spu_ls_read128/write128: pshufb */
#endif
static inline __attribute__((always_inline)) u128 spu_ls_read128(const spu_context* ctx, uint32_t lsa)''',
     "spu x86 ls include")
