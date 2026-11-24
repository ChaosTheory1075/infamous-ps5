/*
 * ps3recomp - minimal TLS 1.2 client for the inFAMOUS 2 / FoB UGC server
 * (PS3_UGC_ONLINE path only; new file, no game sees it directly).
 *
 * Enough of TLS 1.2 to talk to the community server (gunicorn, self-signed
 * cert, cipher TLS_RSA_WITH_AES_128_CBC_SHA = 0x002F) over an already-connected
 * TCP socket. It offers only that one suite.
 *
 *   ClientHello (SNI + signature_algorithms + empty renegotiation_info)
 *   -> ServerHello + Certificate + ServerHelloDone
 *   -> ClientKeyExchange (RSA PKCS#1 v1.5 of the 48-byte premaster)
 *   -> ChangeCipherSpec + Finished (PRF-SHA256)
 *   <- ChangeCipherSpec + Finished
 *   then application data.
 * Record layer: AES-128-CBC + HMAC-SHA1, explicit per-record IV, MAC-then-
 * encrypt, PKCS#7-style TLS padding.
 *
 * SECURITY: this does NO certificate verification whatsoever. It extracts the
 * server's RSA public key from whatever certificate the server sends and uses
 * it; it authenticates nothing. That matches what the game does against this
 * self-signed server (and the launcher warns the player). A man in the middle
 * can read and alter everything. Do not reuse this for anything that needs a
 * trusted peer.
 *
 * AES uses AES-NI intrinsics (the BC-250 test box and the PS5 are both x86-64
 * with AES-NI); SHA-1/SHA-256/HMAC/PRF and the big-number RSA are portable C.
 * The only OS calls are socket send/recv (passed in) and, through
 * ugc_tls_random(), /dev/urandom -- both already used elsewhere in
 * libs/network, so no new PS5 import. ugc_tls_random() is the one place that
 * would change for a different platform (see its note).
 */

#include "ugc_tls.h"
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include <wmmintrin.h>
#include <emmintrin.h>
#include <tmmintrin.h>
#ifdef _WIN32
#  include <winsock2.h>
#else
#  include <sys/socket.h>
#  include <unistd.h>
#  include <fcntl.h>
#endif

/* ---- randomness: the one platform-specific spot ------------------------
 * Linux/test box and PS5 dev: /dev/urandom (the tree already reads it in
 * cellSsl.c). A different PS5 build would swap this for the system RNG; keep
 * everything else above it unchanged. */
static int s_rng_bad = 0;   /* set when no random source answered: the handshake is refused */
static void ugc_tls_random(uint8_t* buf, uint32_t n)
{
#ifndef _WIN32
    int fd = open("/dev/urandom", O_RDONLY);
    if (fd >= 0) {
        ssize_t r = read(fd, buf, n); close(fd);
        if (r == (ssize_t)n) return;
    }
#endif
    /* No random source: never fall back to a predictable pattern (it would make
     * the premaster secret guessable). Mark it; ugc_tls_connect refuses. */
    memset(buf, 0, n);
    if (!s_rng_bad) printf("[ugc tls] no random source (/dev/urandom): TLS refused\n");
    s_rng_bad = 1;
}

/* ================= AES-128 (AES-NI), from tools/ps5/launcher/installer.c ==== */
typedef struct { __m128i k[11]; } t_aes;
__attribute__((target("aes,sse2")))
static __m128i aes_exp(__m128i k, __m128i g)
{
    g = _mm_shuffle_epi32(g, 0xFF);
    k = _mm_xor_si128(k, _mm_slli_si128(k, 4));
    k = _mm_xor_si128(k, _mm_slli_si128(k, 4));
    k = _mm_xor_si128(k, _mm_slli_si128(k, 4));
    return _mm_xor_si128(k, g);
}
__attribute__((target("aes,sse2")))
static void aes_key(t_aes* a, const uint8_t key[16])
{
    a->k[0] = _mm_loadu_si128((const __m128i*)key);
#define X(i, r) a->k[i] = aes_exp(a->k[i - 1], _mm_aeskeygenassist_si128(a->k[i - 1], r))
    X(1, 0x01); X(2, 0x02); X(3, 0x04); X(4, 0x08); X(5, 0x10);
    X(6, 0x20); X(7, 0x40); X(8, 0x80); X(9, 0x1B); X(10, 0x36);
#undef X
}
typedef struct { __m128i k[11]; } t_aesd;
__attribute__((target("aes,sse2")))
static void aes_key_dec(t_aesd* d, const uint8_t key[16])
{
    t_aes e; aes_key(&e, key);
    d->k[0] = e.k[10]; d->k[10] = e.k[0];
    for (int i = 1; i < 10; i++) d->k[i] = _mm_aesimc_si128(e.k[10 - i]);
}
/* CBC encrypt in place (n a multiple of 16). */
__attribute__((target("aes,sse2")))
static void aes_cbc_enc(const t_aes* a, const uint8_t iv[16], uint8_t* buf, size_t n)
{
    __m128i v = _mm_loadu_si128((const __m128i*)iv);
    for (size_t o = 0; o + 16 <= n; o += 16) {
        __m128i x = _mm_xor_si128(_mm_loadu_si128((const __m128i*)(buf + o)), v);
        x = _mm_xor_si128(x, a->k[0]);
        for (int r = 1; r < 10; r++) x = _mm_aesenc_si128(x, a->k[r]);
        x = _mm_aesenclast_si128(x, a->k[10]);
        _mm_storeu_si128((__m128i*)(buf + o), x);
        v = x;
    }
}
/* CBC decrypt in place (n a multiple of 16). */
__attribute__((target("aes,sse2")))
static void aes_cbc_dec(const t_aesd* d, const uint8_t iv[16], uint8_t* buf, size_t n)
{
    __m128i v = _mm_loadu_si128((const __m128i*)iv);
    for (size_t o = 0; o + 16 <= n; o += 16) {
        const __m128i c = _mm_loadu_si128((const __m128i*)(buf + o));
        __m128i x = _mm_xor_si128(c, d->k[0]);
        for (int r = 1; r < 10; r++) x = _mm_aesdec_si128(x, d->k[r]);
        x = _mm_aesdeclast_si128(x, d->k[10]);
        _mm_storeu_si128((__m128i*)(buf + o), _mm_xor_si128(x, v));
        v = c;
    }
}

/* ================= SHA-256 (from installer.c) ============================ */
static const uint32_t K256[64] = {
    0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,
    0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
    0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,
    0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
    0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,
    0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2 };
#define ROR(x,n) ((x) >> (n) | (x) << (32 - (n)))
static void sha256_blk(uint32_t h[8], const uint8_t* p)
{
    uint32_t w[64], a=h[0],b=h[1],c=h[2],d=h[3],e=h[4],f=h[5],g=h[6],k=h[7];
    for (int i=0;i<16;i++) w[i]=(uint32_t)p[i*4]<<24|p[i*4+1]<<16|p[i*4+2]<<8|p[i*4+3];
    for (int i=16;i<64;i++)
        w[i]=w[i-16]+(ROR(w[i-15],7)^ROR(w[i-15],18)^w[i-15]>>3)+w[i-7]+(ROR(w[i-2],17)^ROR(w[i-2],19)^w[i-2]>>10);
    for (int i=0;i<64;i++){
        uint32_t t1=k+(ROR(e,6)^ROR(e,11)^ROR(e,25))+((e&f)^(~e&g))+K256[i]+w[i];
        uint32_t t2=(ROR(a,2)^ROR(a,13)^ROR(a,22))+((a&b)^(a&c)^(b&c));
        k=g;g=f;f=e;e=d+t1;d=c;c=b;b=a;a=t1+t2;
    }
    h[0]+=a;h[1]+=b;h[2]+=c;h[3]+=d;h[4]+=e;h[5]+=f;h[6]+=g;h[7]+=k;
}
static void sha256(const uint8_t* d, size_t n, uint8_t out[32])
{
    uint32_t h[8]={0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
    size_t o=0; for (;o+64<=n;o+=64) sha256_blk(h,d+o);
    uint8_t t[128]={0}; size_t r=n-o; memcpy(t,d+o,r); t[r]=0x80;
    size_t tl=r<56?64:128;
    for (int i=0;i<8;i++) t[tl-1-i]=(uint8_t)((uint64_t)n*8>>(i*8));
    for (size_t b=0;b<tl;b+=64) sha256_blk(h,t+b);
    for (int i=0;i<32;i++) out[i]=(uint8_t)(h[i/4]>>(24-i%4*8));
}
#undef ROR

/* ================= SHA-1 ================================================= */
#define ROL(x,n) ((x)<<(n)|(x)>>(32-(n)))
static void sha1_blk(uint32_t h[5], const uint8_t* p)
{
    uint32_t w[80], a=h[0],b=h[1],c=h[2],d=h[3],e=h[4];
    for (int i=0;i<16;i++) w[i]=(uint32_t)p[i*4]<<24|p[i*4+1]<<16|p[i*4+2]<<8|p[i*4+3];
    for (int i=16;i<80;i++) w[i]=ROL(w[i-3]^w[i-8]^w[i-14]^w[i-16],1);
    for (int i=0;i<80;i++){
        uint32_t f,k;
        if (i<20){f=(b&c)|(~b&d);k=0x5A827999;}
        else if (i<40){f=b^c^d;k=0x6ED9EBA1;}
        else if (i<60){f=(b&c)|(b&d)|(c&d);k=0x8F1BBCDC;}
        else {f=b^c^d;k=0xCA62C1D6;}
        uint32_t t=ROL(a,5)+f+e+k+w[i]; e=d;d=c;c=ROL(b,30);b=a;a=t;
    }
    h[0]+=a;h[1]+=b;h[2]+=c;h[3]+=d;h[4]+=e;
}
static void sha1(const uint8_t* d, size_t n, uint8_t out[20])
{
    uint32_t h[5]={0x67452301,0xEFCDAB89,0x98BADCFE,0x10325476,0xC3D2E1F0};
    size_t o=0; for (;o+64<=n;o+=64) sha1_blk(h,d+o);
    uint8_t t[128]={0}; size_t r=n-o; memcpy(t,d+o,r); t[r]=0x80;
    size_t tl=r<56?64:128;
    for (int i=0;i<8;i++) t[tl-1-i]=(uint8_t)((uint64_t)n*8>>(i*8));
    for (size_t b=0;b<tl;b+=64) sha1_blk(h,t+b);
    for (int i=0;i<20;i++) out[i]=(uint8_t)(h[i/4]>>(24-i%4*8));
}
#undef ROL

/* ================= HMAC (SHA-1 and SHA-256) ============================= */
typedef void (*hashfn)(const uint8_t*, size_t, uint8_t*);
static void hmac(hashfn H, int hlen, const uint8_t* key, int klen,
                 const uint8_t* msg, int mlen, uint8_t* out)
{
    uint8_t k[64]={0}, ip[64], op[64], ih[32], tmp[64+32];
    if (klen > 64) { H(key, klen, k); } else memcpy(k, key, klen);
    for (int i=0;i<64;i++){ ip[i]=k[i]^0x36; op[i]=k[i]^0x5c; }
    uint8_t* b = (uint8_t*)malloc(64+mlen);
    memcpy(b, ip, 64); memcpy(b+64, msg, mlen);
    H(b, 64+mlen, ih); free(b);
    memcpy(tmp, op, 64); memcpy(tmp+64, ih, hlen);
    H(tmp, 64+hlen, out);
}
static void hmac_sha1(const uint8_t* k,int kl,const uint8_t* m,int ml,uint8_t o[20]){hmac(sha1,20,k,kl,m,ml,o);}
static void hmac_sha256(const uint8_t* k,int kl,const uint8_t* m,int ml,uint8_t o[32]){hmac(sha256,32,k,kl,m,ml,o);}

/* ================= TLS 1.2 PRF (HMAC-SHA256) ============================ */
static void prf(const uint8_t* secret, int slen, const char* label,
                const uint8_t* seed, int seedlen, uint8_t* out, int outlen)
{
    uint8_t ls[128]; int ll = (int)strlen(label);
    memcpy(ls, label, ll); memcpy(ls+ll, seed, seedlen); int lsl = ll+seedlen;
    uint8_t a[32]; hmac_sha256(secret, slen, ls, lsl, a);   /* A(1) */
    int off=0;
    while (off < outlen) {
        uint8_t in[32+128]; memcpy(in, a, 32); memcpy(in+32, ls, lsl);
        uint8_t blk[32]; hmac_sha256(secret, slen, in, 32+lsl, blk);
        int n = outlen-off < 32 ? outlen-off : 32;
        memcpy(out+off, blk, n); off+=n;
        uint8_t a2[32]; hmac_sha256(secret, slen, a, 32, a2); memcpy(a, a2, 32);
    }
}

/* ================= big-number RSA (public-key, small e) ================= */
/* Little-endian uint32 limbs. MAXW limbs hold a product of two moduli. */
#define MAXW 136   /* > 2*64 for 2048-bit; also covers 3072-bit moduli */
typedef struct { uint32_t w[MAXW]; int n; } big;
static void big_zero(big* a){ memset(a->w,0,sizeof a->w); a->n=0; }
static void big_norm(big* a){ while(a->n>0 && a->w[a->n-1]==0) a->n--; }
static void big_from(big* a, const uint8_t* be, int len){
    big_zero(a);
    for (int i=0;i<len;i++){ int j=len-1-i; a->w[i>>2] |= (uint32_t)be[j]<<((i&3)*8); }
    a->n=(len+3)/4; big_norm(a);
}
static void big_to(const big* a, uint8_t* be, int len){
    for (int i=0;i<len;i++){ int j=len-1-i; be[j] = (i>>2)<a->n ? (uint8_t)(a->w[i>>2]>>((i&3)*8)) : 0; }
}
static int big_cmp(const big* a, const big* b){
    if (a->n!=b->n) return a->n<b->n?-1:1;
    for (int i=a->n-1;i>=0;i--) if (a->w[i]!=b->w[i]) return a->w[i]<b->w[i]?-1:1;
    return 0;
}
static void big_mul(const big* a, const big* b, big* r){
    uint64_t acc[MAXW]; memset(acc,0,sizeof acc);
    for (int i=0;i<a->n;i++){
        uint64_t carry=0;
        for (int j=0;j<b->n;j++){
            uint64_t cur = acc[i+j] + (uint64_t)a->w[i]*b->w[j] + carry;
            acc[i+j]=(uint32_t)cur; carry=cur>>32;
        }
        acc[i+b->n]+=carry;
    }
    big_zero(r);
    for (int i=0;i<MAXW;i++) r->w[i]=(uint32_t)acc[i];
    r->n=a->n+b->n; big_norm(r);
}
/* shift left by 1 bit */
static void big_shl1(big* a){
    uint32_t carry=0;
    for (int i=0;i<a->n;i++){ uint32_t nc=a->w[i]>>31; a->w[i]=(a->w[i]<<1)|carry; carry=nc; }
    if (carry){ a->w[a->n++]=1; }
}
static void big_sub(big* a, const big* b){   /* a -= b, a>=b */
    int64_t borrow=0;
    for (int i=0;i<a->n;i++){
        int64_t cur=(int64_t)a->w[i]-(i<b->n?b->w[i]:0)-borrow;
        if (cur<0){cur+=0x100000000LL;borrow=1;}else borrow=0;
        a->w[i]=(uint32_t)cur;
    }
    big_norm(a);
}
static int big_bit(const big* a, int i){ return (a->w[i>>5]>>(i&31))&1; }
/* r = x mod m  (binary long division; x and m fit in MAXW) */
static void big_mod(const big* x, const big* m, big* r){
    big rem; big_zero(&rem);
    int top = x->n*32-1;
    while (top>=0 && !big_bit(x,top)) top--;
    for (int i=top;i>=0;i--){
        big_shl1(&rem);
        rem.w[0]|=(uint32_t)big_bit(x,i);
        if (rem.n==0) rem.n=1; big_norm(&rem);
        if (big_cmp(&rem,m)>=0) big_sub(&rem,m);
    }
    *r=rem;
}
/* out = base^e mod m, e a small integer */
static void big_modexp_u32(const big* base, uint32_t e, const big* m, big* out){
    big result; big_zero(&result); result.w[0]=1; result.n=1;
    big b; big_mod(base,m,&b);
    int hib=31; while(hib>0 && !((e>>hib)&1)) hib--;
    for (int i=hib;i>=0;i--){
        big t; big_mul(&result,&result,&t); big_mod(&t,m,&result);
        if ((e>>i)&1){ big_mul(&result,&b,&t); big_mod(&t,m,&result); }
    }
    *out=result;
}

/* ---- extract RSA (modulus,exponent) from a DER X.509 certificate ------- */
/* Minimal walk: find the RSA-encryption OID, then the following BIT STRING,
 * then the inner SEQUENCE { INTEGER modulus, INTEGER exponent }. */
static int der_len(const uint8_t* p, int* lenbytes){
    if (p[0]<0x80){ *lenbytes=1; return p[0]; }
    int nb=p[0]&0x7f; int v=0;
    for (int i=0;i<nb;i++) v=(v<<8)|p[1+i];
    *lenbytes=1+nb; return v;
}
static int tls_cert_pubkey(const uint8_t* der, int dlen,
                           uint8_t* mod, int* modlen, uint32_t* exp)
{
    static const uint8_t rsaoid[]={0x06,0x09,0x2A,0x86,0x48,0x86,0xF7,0x0D,0x01,0x01,0x01};
    int i=0, found=-1;
    for (; i+11<=dlen; i++) if (!memcmp(der+i,rsaoid,11)){ found=i; break; }
    if (found<0) return -1;
    /* after AlgorithmIdentifier SEQUENCE comes BIT STRING (0x03). Scan ahead. */
    int j=found+11;
    while (j<dlen && der[j]!=0x03) j++;
    if (j>=dlen) return -1;
    int lb; der_len(der+j+1,&lb);
    int bitstart = j+1+lb;         /* first byte = unused-bits count (0) */
    const uint8_t* pk = der+bitstart+1;
    if (pk[0]!=0x30) return -1;    /* SEQUENCE */
    der_len(pk+1,&lb); const uint8_t* q = pk+1+lb;
    if (q[0]!=0x02) return -1;     /* INTEGER modulus */
    int ml = der_len(q+1,&lb); const uint8_t* mstart=q+1+lb;
    while (ml>0 && mstart[0]==0x00){ mstart++; ml--; }   /* strip leading 0 */
    if (ml>*modlen) return -1;
    memcpy(mod,mstart,ml); *modlen=ml;
    const uint8_t* ep=mstart+ml;
    if (ep[0]!=0x02) return -1;    /* INTEGER exponent */
    int el=der_len(ep+1,&lb); const uint8_t* es=ep+1+lb;
    uint32_t e=0; for (int k=0;k<el;k++) e=(e<<8)|es[k];
    *exp=e; return 0;
}
/* RSA PKCS#1 v1.5 encrypt `in` (inlen bytes) under (mod,exp) -> out[k]. */
static int rsa_enc(const uint8_t* mod,int modlen,uint32_t exp,
                   const uint8_t* in,int inlen,uint8_t* out)
{
    int k=modlen;
    if (inlen > k-11) return -1;
    uint8_t em[512]; if (k>512) return -1;
    em[0]=0x00; em[1]=0x02;
    int pslen=k-3-inlen;
    ugc_tls_random(em+2, pslen);
    for (int i=0;i<pslen;i++) if (em[2+i]==0) em[2+i]=0x01;   /* PS must be nonzero */
    em[2+pslen]=0x00;
    memcpy(em+3+pslen, in, inlen);
    big m,n,c; big_from(&m,em,k); big_from(&n,mod,modlen);
    big_modexp_u32(&m,exp,&n,&c);
    big_to(&c,out,k);
    return 0;
}

/* ================= TLS record / handshake =============================== */
#define REC_CCS 20
#define REC_ALERT 21
#define REC_HS 22
#define REC_APP 23

static int sock_send_all(int fd, const uint8_t* b, int n){
    int o=0; while(o<n){ int r=(int)send(fd,(const char*)b+o,n-o,0); if(r<=0) return -1; o+=r; } return 0;
}
static int sock_recv_n(int fd, uint8_t* b, int n){
    int o=0; while(o<n){ int r=(int)recv(fd,(char*)b+o,n-o,0); if(r<=0) return -1; o+=r; } return 0;
}

/* Send one plaintext record (handshake pre-cipher, or CCS). */
static int send_plain(ugc_tls* t, int type, const uint8_t* data, int len){
    uint8_t h[5]={(uint8_t)type,0x03,0x03,(uint8_t)(len>>8),(uint8_t)len};
    if (sock_send_all(t->fd,h,5)) return -1;
    return sock_send_all(t->fd,data,len);
}

/* Send one encrypted record (AES-CBC+HMAC-SHA1, explicit IV). */
static int send_enc(ugc_tls* t, int type, const uint8_t* data, int len){
    uint8_t mac[20];
    uint8_t seqhdr[13];
    for (int i=0;i<8;i++) seqhdr[i]=(uint8_t)(t->wseq>>(56-8*i));
    seqhdr[8]=(uint8_t)type; seqhdr[9]=0x03; seqhdr[10]=0x03;
    seqhdr[11]=(uint8_t)(len>>8); seqhdr[12]=(uint8_t)len;
    uint8_t* mb=(uint8_t*)malloc(13+len); memcpy(mb,seqhdr,13); memcpy(mb+13,data,len);
    hmac_sha1(t->cli_mac,20,mb,13+len,mac); free(mb);
    t->wseq++;
    int plen = len+20;
    int pad = 16-(plen%16);                 /* 1..16 */
    int total = plen+pad;
    uint8_t iv[16]; ugc_tls_random(iv,16);
    uint8_t* body=(uint8_t*)malloc(16+total);
    memcpy(body,iv,16);
    memcpy(body+16,data,len);
    memcpy(body+16+len,mac,20);
    for (int i=0;i<pad;i++) body[16+plen+i]=(uint8_t)(pad-1);
    t_aes a; aes_key(&a,t->cli_key);
    aes_cbc_enc(&a,iv,body+16,total);
    uint8_t rh[5]={(uint8_t)type,0x03,0x03,(uint8_t)((16+total)>>8),(uint8_t)(16+total)};
    int rc = sock_send_all(t->fd,rh,5) || sock_send_all(t->fd,body,16+total);
    free(body);
    return rc?-1:0;
}

/* Read one record header + body into t->rec (returns type, sets t->reclen). */
static int read_record(ugc_tls* t){
    uint8_t h[5];
    if (sock_recv_n(t->fd,h,5)) return -1;
    int len=(h[3]<<8)|h[4];
    if (len<0 || len>(int)sizeof t->rec) return -1;
    if (sock_recv_n(t->fd,t->rec,len)) return -1;
    t->reclen=len;
    return h[0];
}
/* Read + decrypt an encrypted record; leaves plaintext in t->rec/reclen. */
static int read_record_dec(ugc_tls* t, int* type){
    uint8_t h[5];
    if (sock_recv_n(t->fd,h,5)) return -1;
    int len=(h[3]<<8)|h[4];
    if (len<16 || len>(int)sizeof t->rec || (len%16)) return -1;
    static uint8_t buf[20000];   /* static: the guest HTTP thread stack may be small (PS5); one UGC connection at a time */ if (len>(int)sizeof buf) return -1;
    if (sock_recv_n(t->fd,buf,len)) return -1;
    t_aesd d; aes_key_dec(&d,t->srv_key);
    aes_cbc_dec(&d,buf,buf+16,len-16);
    int pad=buf[len-1]+1;
    int plain = len-16-20-pad;
    if (plain<0) return -1;
    memcpy(t->rec, buf+16, plain);
    t->reclen=plain; t->rseq++;
    *type=h[0];
    return 0;
}

/* accumulate handshake bytes for the Finished hash */
static void hs_add(ugc_tls* t, const uint8_t* b, int n){
    if (t->hslen+n <= (int)sizeof t->hsbuf){ memcpy(t->hsbuf+t->hslen,b,n); t->hslen+=n; }
}

int ugc_tls_connect(ugc_tls* t, int fd, const char* sni)
{
    memset(t,0,sizeof *t);
    t->fd=fd;
    uint8_t cr[32]; ugc_tls_random(cr,32); memcpy(t->cli_random,cr,32);
    if (s_rng_bad) return -7;   /* no usable randomness */

    /* ---- ClientHello ---- */
    uint8_t ch[512]; int p=0;
    ch[p++]=0x03; ch[p++]=0x03;                 /* client_version TLS1.2 */
    memcpy(ch+p,cr,32); p+=32;                  /* random */
    ch[p++]=0;                                  /* session id len */
    ch[p++]=0x00; ch[p++]=0x02;                 /* cipher suites len */
    ch[p++]=0x00; ch[p++]=0x2F;                 /* TLS_RSA_WITH_AES_128_CBC_SHA */
    ch[p++]=0x01; ch[p++]=0x00;                 /* compression: null */
    int extpos=p; p+=2;                         /* extensions length (fill later) */
    /* SNI */
    int snilen=(int)strlen(sni);
    ch[p++]=0x00; ch[p++]=0x00;                 /* server_name */
    ch[p++]=(uint8_t)((snilen+5)>>8); ch[p++]=(uint8_t)(snilen+5);
    ch[p++]=(uint8_t)((snilen+3)>>8); ch[p++]=(uint8_t)(snilen+3);
    ch[p++]=0x00;                               /* host_name */
    ch[p++]=(uint8_t)(snilen>>8); ch[p++]=(uint8_t)snilen;
    memcpy(ch+p,sni,snilen); p+=snilen;
    /* signature_algorithms (rsa_pkcs1_sha256, sha1) */
    ch[p++]=0x00; ch[p++]=0x0d; ch[p++]=0x00; ch[p++]=0x06; ch[p++]=0x00; ch[p++]=0x04;
    ch[p++]=0x04; ch[p++]=0x01; ch[p++]=0x02; ch[p++]=0x01;
    /* renegotiation_info (empty) */
    ch[p++]=0xff; ch[p++]=0x01; ch[p++]=0x00; ch[p++]=0x01; ch[p++]=0x00;
    int extlen=p-extpos-2; ch[extpos]=(uint8_t)(extlen>>8); ch[extpos+1]=(uint8_t)extlen;
    /* handshake header */
    uint8_t hs[600]; hs[0]=0x01; hs[1]=0; hs[2]=(uint8_t)(p>>8); hs[3]=(uint8_t)p;
    memcpy(hs+4,ch,p); int hslen=4+p;
    hs_add(t,hs,hslen);
    if (send_plain(t,REC_HS,hs,hslen)) return -1;

    /* ---- read ServerHello, Certificate, ServerHelloDone (may share records) */
    uint8_t modbuf[520]; int modlen=sizeof modbuf; uint32_t exp=0; int havekey=0, done=0;
    static uint8_t acc[20000]; int accn=0;   /* static: see ugc_tls record read */
    while (!done){
        int ty=read_record(t);
        if (ty!=REC_HS){ if(ty==REC_ALERT) return -2; return -1; }
        memcpy(acc+accn,t->rec,t->reclen); accn+=t->reclen;
        int off=0;
        while (off+4<=accn){
            int ht=acc[off]; int hl=(acc[off+1]<<16)|(acc[off+2]<<8)|acc[off+3];
            if (off+4+hl>accn) break;              /* need more */
            hs_add(t,acc+off,4+hl);
            const uint8_t* body=acc+off+4;
            if (ht==0x02){                          /* ServerHello */
                memcpy(t->srv_random, body+2, 32);
            } else if (ht==0x0b){                   /* Certificate */
                int cl=(body[3]<<16)|(body[4]<<8)|body[5];   /* first cert len */
                if (tls_cert_pubkey(body+6,cl,modbuf,&modlen,&exp)==0) havekey=1;
            } else if (ht==0x0e){                   /* ServerHelloDone */
                done=1;
            }
            off+=4+hl;
        }
        memmove(acc,acc+off,accn-off); accn-=off;
    }
    if (!havekey) return -3;

    /* ---- premaster, ClientKeyExchange ---- */
    uint8_t pms[48]; pms[0]=0x03; pms[1]=0x03; ugc_tls_random(pms+2,46);
    if (s_rng_bad) return -7;
    uint8_t enc[520]; if (rsa_enc(modbuf,modlen,exp,pms,48,enc)) return -4;
    uint8_t cke[600]; int cp=0;
    cke[cp++]=0x10; cke[cp++]=0; cke[cp++]=(uint8_t)((modlen+2)>>8); cke[cp++]=(uint8_t)(modlen+2);
    cke[cp++]=(uint8_t)(modlen>>8); cke[cp++]=(uint8_t)modlen;
    memcpy(cke+cp,enc,modlen); cp+=modlen;
    hs_add(t,cke,cp);
    if (send_plain(t,REC_HS,cke,cp)) return -1;

    /* ---- key schedule ---- */
    uint8_t seed[64]; memcpy(seed,t->cli_random,32); memcpy(seed+32,t->srv_random,32);
    uint8_t master[48]; prf(pms,48,"master secret",seed,64,master,48);
    memcpy(t->master,master,48);
    uint8_t seed2[64]; memcpy(seed2,t->srv_random,32); memcpy(seed2+32,t->cli_random,32);
    uint8_t kb[72]; prf(master,48,"key expansion",seed2,64,kb,72);
    memcpy(t->cli_mac,kb,20); memcpy(t->srv_mac,kb+20,20);
    memcpy(t->cli_key,kb+40,16); memcpy(t->srv_key,kb+56,16);

    /* ---- ChangeCipherSpec + Finished ---- */
    uint8_t ccs=0x01; if (send_plain(t,REC_CCS,&ccs,1)) return -1;
    uint8_t hh[32]; sha256(t->hsbuf,t->hslen,hh);
    uint8_t vd[12]; prf(master,48,"client finished",hh,32,vd,12);
    uint8_t fin[16]; fin[0]=0x14; fin[1]=0; fin[2]=0; fin[3]=12; memcpy(fin+4,vd,12);
    hs_add(t,fin,16);
    if (send_enc(t,REC_HS,fin,16)) return -1;

    /* ---- server ChangeCipherSpec + Finished ---- */
    int ty=read_record(t);                        /* CCS (plaintext) */
    if (ty!=REC_CCS){ if(ty==REC_ALERT) return -2; return -5; }
    int dt; if (read_record_dec(t,&dt)) return -6; /* server Finished (ignored) */
    t->ready=1;
    return 0;
}

int ugc_tls_write(ugc_tls* t, const void* buf, int len){
    return send_enc(t,REC_APP,(const uint8_t*)buf,len)?-1:len;
}
/* Returns bytes into buf, 0 on close_notify/EOF, -1 on error. */
int ugc_tls_read(ugc_tls* t, void* buf, int len){
    if (t->pend>0){
        int n = t->pend<len?t->pend:len;
        memcpy(buf,t->recbuf+t->recoff,n); t->recoff+=n; t->pend-=n; return n;
    }
    for (;;){
        int dt; if (read_record_dec(t,&dt)) return -1;
        if (dt==REC_ALERT) return 0;               /* close_notify or fatal */
        if (dt==REC_HS) continue;                  /* ignore (e.g. NewSessionTicket) */
        if (dt==REC_APP){
            if (t->reclen==0) continue;
            memcpy(t->recbuf,t->rec,t->reclen); t->recoff=0; t->pend=t->reclen;
            int n=t->pend<len?t->pend:len;
            memcpy(buf,t->recbuf,n); t->recoff=n; t->pend-=n; return n;
        }
    }
}
void ugc_tls_close(ugc_tls* t){
    if (t->ready){ uint8_t a[2]={0x01,0x00}; send_enc(t,REC_ALERT,a,2); }  /* warning close_notify */
}

/* ================= standalone test (UGC_TLS_TEST) ======================= */
#ifdef UGC_TLS_TEST
#include <netinet/in.h>
#include <arpa/inet.h>
int main(int argc, char** argv){
    if (argc<4){ fprintf(stderr,"usage: %s <ip> <port> <host> [path]\n",argv[0]); return 2; }
    const char* ip=argv[1]; int port=atoi(argv[2]); const char* host=argv[3];
    const char* path=argc>4?argv[4]:"/";
    int fd=socket(AF_INET,SOCK_STREAM,0);
    struct sockaddr_in sa; memset(&sa,0,sizeof sa);
    sa.sin_family=AF_INET; sa.sin_port=htons((uint16_t)port); inet_pton(AF_INET,ip,&sa.sin_addr);
    if (connect(fd,(struct sockaddr*)&sa,sizeof sa)){ perror("connect"); return 1; }
    ugc_tls t; int rc=ugc_tls_connect(&t,fd,host);
    fprintf(stderr,"handshake rc=%d\n",rc); if (rc) return 1;
    char req[512]; int rl=snprintf(req,sizeof req,
        "GET %s HTTP/1.1\r\nHost: %s\r\nAccept: */*\r\nConnection: close\r\n\r\n",path,host);
    ugc_tls_write(&t,req,rl);
    uint8_t b[8192]; int total=0;
    for (;;){ int n=ugc_tls_read(&t,b,sizeof b); if (n<=0) break;
        fwrite(b,1,n,stdout); total+=n; }
    fprintf(stderr,"\n[%d bytes]\n",total);
    ugc_tls_close(&t);
    return 0;
}
#endif
