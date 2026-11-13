# spu shufb2: shufb on host byte order: no byte swaps of the operands, control and result
# shufb is the most common SPU op in if2's job code (~20k sites). The SSE4.1 form swapped A, B, C into
# SPU byte order and the result back (4 pshufb) before selecting. SPU byte P is host byte P^3 and the
# control byte for result host byte h sits at host byte h, so selecting with (C & 0x0F) ^ 3 works in
# host order directly. pshufb already zeroes the bytes whose control has bit 7 set (the 10x
# selectors' 0x00); 110 -> 0xFF and 111 -> 0x80 are ORed in. ~12 instructions instead of ~20.
# tools/test_spu_shufb2.c checks it against spu_shufb_ref.
SFH = "runtime/spu/spu_helpers.h"
edit(SFH,
     '''static inline u128 spu_shufb(u128 a, u128 b, u128 c) {
    const __m128i sw = _mm_setr_epi8(3,2,1,0, 7,6,5,4, 11,10,9,8, 15,14,13,12);
    __m128i A, B, C; memcpy(&A, &a, 16); memcpy(&B, &b, 16); memcpy(&C, &c, 16);''',
     '''static inline u128 spu_shufb(u128 a, u128 b, u128 c) {   /* spu shufb2: host byte order */
    __m128i A, B, C; memcpy(&A, &a, 16); memcpy(&B, &b, 16); memcpy(&C, &c, 16);
    const __m128i idx = _mm_xor_si128(C, _mm_set1_epi8(3));           /* bit 7 kept: pshufb zeroes */
    __m128i r = _mm_blendv_epi8(_mm_shuffle_epi8(A, idx), _mm_shuffle_epi8(B, idx), _mm_slli_epi16(C, 3));
    const __m128i mC0 = _mm_cmpeq_epi8(_mm_and_si128(C, _mm_set1_epi8((char)0xC0)), _mm_set1_epi8((char)0xC0));
    const __m128i mE0 = _mm_cmpeq_epi8(_mm_and_si128(C, _mm_set1_epi8((char)0xE0)), _mm_set1_epi8((char)0xE0));
    r = _mm_or_si128(r, _mm_andnot_si128(_mm_and_si128(mE0, _mm_set1_epi8(0x7F)), mC0));
    u128 out; memcpy(&out, &r, 16); return out;
}
static inline u128 spu_shufb_sw(u128 a, u128 b, u128 c) {   /* spu shufb2: the previous form */
    const __m128i sw = _mm_setr_epi8(3,2,1,0, 7,6,5,4, 11,10,9,8, 15,14,13,12);
    __m128i A, B, C; memcpy(&A, &a, 16); memcpy(&B, &b, 16); memcpy(&C, &c, 16);''',
     "spu shufb2: host order")
