
# SPU quadword byte shifts/rotates (shlqby[i|bi], rotqby[i|bi], rotqmby[i|bi]) and cwd on x86 with
# SSSE3: one pshufb, the index computed per host byte as the NEON forms compute it per SPU byte.
# SPU byte P lives at host byte P^3, so host byte h takes SPU byte s = f(h^3) from host byte s^3;
# an index with the top bit set gives 0 (shifted-out bytes). Without it each was a 16-step byte
# loop with a branch per byte (perf: the hottest lines of the busiest inFamous 2 SPU job).
# tests: tools/test_spu_bytes_sse.c.
SPU_X86_BYTES = r'''
#if defined(__SSSE3__) && !defined(__ARM_NEON) && !defined(SPU_SCALAR_HELPERS) && !defined(SPU_SCALAR_INT)
#include <tmmintrin.h>
#define SPU_BYTES_SSSE3 1
/* host byte h -> the SPU byte index it holds (h ^ 3) */
static inline __m128i spu__xb_iota(void) { return _mm_setr_epi8(3,2,1,0, 7,6,5,4, 11,10,9,8, 15,14,13,12); }
static inline u128 spu__xb_perm(u128 a, __m128i s) {   /* s: SPU source byte per host byte; <0 or >15 -> 0 */
    const __m128i oor = _mm_or_si128(_mm_cmpgt_epi8(s, _mm_set1_epi8(15)), _mm_cmplt_epi8(s, _mm_setzero_si128()));
    const __m128i h = _mm_or_si128(_mm_xor_si128(s, _mm_set1_epi8(3)), _mm_and_si128(oor, _mm_set1_epi8((char)0x80)));
    __m128i A; memcpy(&A, &a, 16);
    const __m128i r = _mm_shuffle_epi8(A, h);
    u128 o; memcpy(&o, &r, 16); return o;
}
static inline u128 spu__xb_shl(u128 a, int sh) {        /* SPU byte i <- byte i+sh, 0 past the end */
    return spu__xb_perm(a, _mm_add_epi8(spu__xb_iota(), _mm_set1_epi8((char)(sh & 0x1F))));
}
static inline u128 spu__xb_rot(u128 a, int sh) {        /* SPU byte i <- byte (i+sh) & 15 */
    return spu__xb_perm(a, _mm_and_si128(_mm_add_epi8(spu__xb_iota(), _mm_set1_epi8((char)(sh & 0x0F))), _mm_set1_epi8(15)));
}
static inline u128 spu__xb_shr(u128 a, int sh) {        /* SPU byte i <- byte i-sh, 0 before the start */
    return spu__xb_perm(a, _mm_sub_epi8(spu__xb_iota(), _mm_set1_epi8((char)(sh & 0x1F))));
}
#endif
'''
edit("runtime/spu/spu_helpers.h", r'''static inline u128 spu_shlqbyi_ref(u128 a, int sh) {''', SPU_X86_BYTES + r'''static inline u128 spu_shlqbyi_ref(u128 a, int sh) {''', "spu bytes ssse3: base")
for name, args, call, body in [
    ("spu_shlqbyi",  "u128 a, int sh",  "spu_shlqbyi_ref(a, sh)",  "spu__xb_shl(a, sh)"),
    ("spu_rotqbyi",  "u128 a, int sh",  "spu_rotqbyi_ref(a, sh)",  "spu__xb_rot(a, sh)"),
    ("spu_shlqby",   "u128 a, u128 b",  "spu_shlqby_ref(a, b)",    "spu__xb_shl(a, (int)(b._u32[0] & 0x1F))"),
    ("spu_rotqby",   "u128 a, u128 b",  "spu_rotqby_ref(a, b)",    "spu__xb_rot(a, (int)b._u32[0])"),
    ("spu_shlqbybi", "u128 a, u128 b",  "spu_shlqbybi_ref(a, b)",  "spu__xb_shl(a, (int)((b._u32[0] >> 3) & 0x1F))"),
    ("spu_rotqbybi", "u128 a, u128 b",  "spu_rotqbybi_ref(a, b)",  "spu__xb_rot(a, (int)(b._u32[0] >> 3))"),
    ("spu_rotqmby",  "u128 a, u128 b",  "spu_rotqmby_ref(a, b)",   "spu__xb_shr(a, (0 - (int)b._u32[0]) & 0x1F)"),
    ("spu_rotqmbybi","u128 a, u128 b",  "spu_rotqmbybi_ref(a, b)", "spu__xb_shr(a, (0 - ((int)b._u32[0] >> 3)) & 0x1F)"),
    ("spu_rotqmbyi", "u128 a, int i7",  "spu_rotqmbyi_ref(a, i7)", "spu__xb_shr(a, (0 - i7) & 0x1F)"),
]:
    old = "#else\nstatic inline u128 %s(%s) { return %s; }\n#endif" % (name, args, call)
    new = ("#elif defined(SPU_BYTES_SSSE3)\nstatic inline u128 %s(%s) { return %s; }\n" % (name, args, body)
           + "#else\nstatic inline u128 %s(%s) { return %s; }\n#endif" % (name, args, call))
    edit("runtime/spu/spu_helpers.h", old, new, "spu bytes ssse3: " + name)
edit("runtime/spu/spu_helpers.h",
     "#else\nstatic inline u128 spu_cwd(u128 a, int i7) { return spu_cwd_ref(a, i7); }\n#endif",
     "#elif defined(SPU_BYTES_SSSE3)\n"
     "static inline u128 spu_cwd(u128 a, int i7) {   /* the word slot ((a+i7)>>2)&3 takes 00010203 */\n"
     "    const __m128i m = _mm_cmpeq_epi32(_mm_setr_epi32(0, 1, 2, 3), _mm_set1_epi32((int)((((uint32_t)a._u32[0] + (uint32_t)i7) >> 2) & 3)));\n"
     "    const __m128i base = _mm_setr_epi32(0x10111213, 0x14151617, 0x18191A1B, 0x1C1D1E1F);\n"
     "    const __m128i r = _mm_or_si128(_mm_and_si128(m, _mm_set1_epi32(0x00010203)), _mm_andnot_si128(m, base));\n"
     "    u128 o; memcpy(&o, &r, 16); return o;\n"
     "}\n"
     "#else\nstatic inline u128 spu_cwd(u128 a, int i7) { return spu_cwd_ref(a, i7); }\n#endif",
     "spu bytes ssse3: spu_cwd")
