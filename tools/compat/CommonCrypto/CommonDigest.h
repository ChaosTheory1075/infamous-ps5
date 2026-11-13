/* Stand-in for Apple's <CommonCrypto/CommonDigest.h> off macOS: the SHA-1 subset game_patches.cpp
 * uses, header-only (FIPS 180-1), so the port needs no crypto library on Linux or the PS5. */
#pragma once
#include <stdint.h>
#include <string.h>

typedef uint32_t CC_LONG;
#define CC_SHA1_DIGEST_LENGTH 20

typedef struct {
    uint32_t h[5];
    uint64_t len;
    unsigned char buf[64];
    uint32_t n;
} CC_SHA1_CTX;

static inline uint32_t cc_rol(uint32_t x, int k) { return (x << k) | (x >> (32 - k)); }

static inline void cc_sha1_block(CC_SHA1_CTX* c, const unsigned char* p)
{
    uint32_t w[80];
    for (int i = 0; i < 16; i++)
        w[i] = (uint32_t)p[4 * i] << 24 | (uint32_t)p[4 * i + 1] << 16 | (uint32_t)p[4 * i + 2] << 8 | p[4 * i + 3];
    for (int i = 16; i < 80; i++) w[i] = cc_rol(w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16], 1);
    uint32_t a = c->h[0], b = c->h[1], cc = c->h[2], d = c->h[3], e = c->h[4];
    for (int i = 0; i < 80; i++) {
        uint32_t f, k;
        if (i < 20)      { f = (b & cc) | (~b & d);           k = 0x5A827999; }
        else if (i < 40) { f = b ^ cc ^ d;                    k = 0x6ED9EBA1; }
        else if (i < 60) { f = (b & cc) | (b & d) | (cc & d); k = 0x8F1BBCDC; }
        else             { f = b ^ cc ^ d;                    k = 0xCA62C1D6; }
        uint32_t t = cc_rol(a, 5) + f + e + k + w[i];
        e = d; d = cc; cc = cc_rol(b, 30); b = a; a = t;
    }
    c->h[0] += a; c->h[1] += b; c->h[2] += cc; c->h[3] += d; c->h[4] += e;
}

static inline int CC_SHA1_Init(CC_SHA1_CTX* c)
{
    static const uint32_t iv[5] = {0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476, 0xC3D2E1F0};
    memcpy(c->h, iv, sizeof iv);
    c->len = 0;
    c->n = 0;
    return 1;
}

static inline int CC_SHA1_Update(CC_SHA1_CTX* c, const void* data, CC_LONG size)
{
    const unsigned char* p = (const unsigned char*)data;
    c->len += size;
    while (size) {
        uint32_t take = 64 - c->n < size ? 64 - c->n : size;
        memcpy(c->buf + c->n, p, take);
        c->n += take; p += take; size -= take;
        if (c->n == 64) { cc_sha1_block(c, c->buf); c->n = 0; }
    }
    return 1;
}

static inline int CC_SHA1_Final(unsigned char* md, CC_SHA1_CTX* c)
{
    const uint64_t bits = c->len * 8;
    const unsigned char pad = 0x80, zero = 0;
    CC_SHA1_Update(c, &pad, 1);
    while (c->n != 56) CC_SHA1_Update(c, &zero, 1);
    unsigned char lenb[8];
    for (int i = 0; i < 8; i++) lenb[i] = (unsigned char)(bits >> (56 - 8 * i));
    CC_SHA1_Update(c, lenb, 8);
    for (int i = 0; i < 5; i++) {
        md[4 * i] = (unsigned char)(c->h[i] >> 24); md[4 * i + 1] = (unsigned char)(c->h[i] >> 16);
        md[4 * i + 2] = (unsigned char)(c->h[i] >> 8); md[4 * i + 3] = (unsigned char)c->h[i];
    }
    return 1;
}
