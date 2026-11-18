/* The installer: turns the player's own dumps into <app>/<game>/game, the layout the games read.
 * #included by launcher.c (the INSTALL button); built alone with -DINST_MAIN for the PC test
 * (inst_host.sh), which installs into a scratch app folder and compares it with a known-good one.
 *
 * What it reads (from <app>/install, or the top of a USB drive /mnt/usb0..7, one folder deep too):
 *   - a decrypted disc ISO (.iso; ISO 9660, Joliet names; an encrypted Redump ISO is refused),
 *   - a PS3 .pkg (retail, AES-CTR with the public PS3 package key: the data files come out plain),
 *   - a folder: a disc's (PS3_GAME/PARAM.SFO inside) or an installed game's (PARAM.SFO + USRDIR).
 *   - Festival of Blood's licence: its .rap file (any *.rap, one with NPUA80657 in its name first), next to the .pkg.
 * The game's EBOOT.BIN is decrypted here into USRDIR/EBOOT.elf (inFAMOUS: the disc's; inFAMOUS 2: update 1.04's;
 * FoB: the package's, with the .rap) and checked against the sha256 of the one each build was made from.
 *
 * What it writes, per game (all proven layouts: the folders the user installed by hand, 2026-11-08):
 *   game/PS3_GAME                  every source's files, updates laid over the base in version order,
 *                                  minus USRDIR/EBOOT.BIN, plus USRDIR/EBOOT.elf. Written as PS3_GAME.part, renamed at the end
 *                                  (the launcher calls a game installed once game/PS3_GAME exists).
 *   game/dev_hdd0/game/<TID>       inFAMOUS 2: PARAM.SFO + USRDIR/patch;  FoB: PARAM.SFO + USRDIR/dlc
 *   game/dev_hdd0/game/<X>_INSTALL inFAMOUS 2 / FoB: the files the game itself would copy there during
 *                                  play (on the console that copy froze the game for seconds), + ne.bv.
 * Saves (game/dev_hdd0/home) are never touched. */
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>
#include <immintrin.h>

/* ---------------------------------------------------------------- AES-128 (AES-NI, Zen 2 has it) */
typedef struct { __m128i k[11]; } inst_aes_t;
__attribute__((target("aes,sse2")))
static __m128i inst_aes_exp(__m128i k, __m128i g)
{
    g = _mm_shuffle_epi32(g, 0xFF);
    k = _mm_xor_si128(k, _mm_slli_si128(k, 4));
    k = _mm_xor_si128(k, _mm_slli_si128(k, 4));
    k = _mm_xor_si128(k, _mm_slli_si128(k, 4));
    return _mm_xor_si128(k, g);
}
__attribute__((target("aes,sse2")))
static void inst_aes_key(inst_aes_t* a, const uint8_t key[16])
{
    a->k[0] = _mm_loadu_si128((const __m128i*)key);
#define X(i, r) a->k[i] = inst_aes_exp(a->k[i - 1], _mm_aeskeygenassist_si128(a->k[i - 1], r))
    X(1, 0x01); X(2, 0x02); X(3, 0x04); X(4, 0x08); X(5, 0x10);
    X(6, 0x20); X(7, 0x40); X(8, 0x80); X(9, 0x1B); X(10, 0x36);
#undef X
}
/* CTR: buf ^= E(ctr0 + blk), ctr0 a 128-bit big-endian counter; blk the 16-byte block index of buf[0]
 * (buf starts on a block boundary). */
__attribute__((target("aes,sse2,ssse3")))
static void inst_aes_ctr(const inst_aes_t* a, const uint8_t ctr0[16], uint64_t blk, uint8_t* buf, size_t n)
{
    uint64_t hi = 0, lo = 0;
    for (int i = 0; i < 8; i++) { hi = hi << 8 | ctr0[i]; lo = lo << 8 | ctr0[8 + i]; }
    const __m128i bswap = _mm_set_epi8(0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15);
    for (size_t off = 0; off < n; off += 16, blk++) {
        uint64_t l = lo + blk, h = hi + (l < lo);
        __m128i c = _mm_shuffle_epi8(_mm_set_epi64x((long long)h, (long long)l), bswap);
        c = _mm_xor_si128(c, a->k[0]);
        for (int r = 1; r < 10; r++) c = _mm_aesenc_si128(c, a->k[r]);
        c = _mm_aesenclast_si128(c, a->k[10]);
        uint8_t ks[16]; _mm_storeu_si128((__m128i*)ks, c);
        const size_t m = n - off < 16 ? n - off : 16;
        for (size_t i = 0; i < m; i++) buf[off + i] ^= ks[i];
    }
}

/* ---------------------------------------------------------------- AES decrypt (AES-128/256 CBC; the EBOOT's keys) */
typedef struct { __m128i k[15]; int nr; } inst_aesd_t;
__attribute__((target("aes,sse2")))
static void inst_aesd_inv(inst_aesd_t* d, const __m128i* ek, int nr)   /* the encrypt schedule -> the decrypt one */
{
    d->nr = nr; d->k[0] = ek[nr]; d->k[nr] = ek[0];
    for (int i = 1; i < nr; i++) d->k[i] = _mm_aesimc_si128(ek[nr - i]);
}
static void inst_aesd_key128(inst_aesd_t* d, const uint8_t key[16]) { inst_aes_t e; inst_aes_key(&e, key); inst_aesd_inv(d, e.k, 10); }
__attribute__((target("aes,sse2")))
static __m128i inst_aes_exp2(__m128i k, __m128i g)   /* AES-256's odd round keys: SubWord, no rotate, no rcon */
{
    g = _mm_shuffle_epi32(g, 0xAA);
    k = _mm_xor_si128(k, _mm_slli_si128(k, 4));
    k = _mm_xor_si128(k, _mm_slli_si128(k, 4));
    k = _mm_xor_si128(k, _mm_slli_si128(k, 4));
    return _mm_xor_si128(k, g);
}
__attribute__((target("aes,sse2")))
static void inst_aesd_key256(inst_aesd_t* d, const uint8_t key[32])
{
    __m128i e[15];
    e[0] = _mm_loadu_si128((const __m128i*)key); e[1] = _mm_loadu_si128((const __m128i*)(key + 16));
#define X(i, r) e[i] = inst_aes_exp(e[i - 2], _mm_aeskeygenassist_si128(e[i - 1], r)); \
                if (i < 14) e[i + 1] = inst_aes_exp2(e[i - 1], _mm_aeskeygenassist_si128(e[i], 0))
    X(2, 0x01); X(4, 0x02); X(6, 0x04); X(8, 0x08); X(10, 0x10); X(12, 0x20); X(14, 0x40);
#undef X
    inst_aesd_inv(d, e, 14);
}
/* CBC decrypt in place (n a multiple of 16; ECB of one block = a zero iv). */
__attribute__((target("aes,sse2")))
static void inst_aes_cbc_dec(const inst_aesd_t* d, const uint8_t iv[16], uint8_t* buf, size_t n)
{
    __m128i v = _mm_loadu_si128((const __m128i*)iv);
    for (size_t o = 0; o + 16 <= n; o += 16) {
        const __m128i c = _mm_loadu_si128((const __m128i*)(buf + o));
        __m128i x = _mm_xor_si128(c, d->k[0]);
        for (int r = 1; r < d->nr; r++) x = _mm_aesdec_si128(x, d->k[r]);
        x = _mm_aesdeclast_si128(x, d->k[d->nr]);
        _mm_storeu_si128((__m128i*)(buf + o), _mm_xor_si128(x, v));
        v = c;
    }
}

/* ---------------------------------------------------------------- SHA-256 (the decrypted EBOOT's check) */
static const uint32_t kSha256K[64] = {
    0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,
    0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
    0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,
    0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
    0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,
    0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2 };
#define ROR32(x, n) ((x) >> (n) | (x) << (32 - (n)))
static void inst_sha256_blk(uint32_t h[8], const uint8_t* p)
{
    uint32_t w[64], a = h[0], b = h[1], c = h[2], d = h[3], e = h[4], f = h[5], g = h[6], k = h[7];
    for (int i = 0; i < 16; i++) w[i] = (uint32_t)p[i * 4] << 24 | p[i * 4 + 1] << 16 | p[i * 4 + 2] << 8 | p[i * 4 + 3];
    for (int i = 16; i < 64; i++)
        w[i] = w[i - 16] + (ROR32(w[i - 15], 7) ^ ROR32(w[i - 15], 18) ^ w[i - 15] >> 3) + w[i - 7]
             + (ROR32(w[i - 2], 17) ^ ROR32(w[i - 2], 19) ^ w[i - 2] >> 10);
    for (int i = 0; i < 64; i++) {
        const uint32_t t1 = k + (ROR32(e, 6) ^ ROR32(e, 11) ^ ROR32(e, 25)) + ((e & f) ^ (~e & g)) + kSha256K[i] + w[i];
        const uint32_t t2 = (ROR32(a, 2) ^ ROR32(a, 13) ^ ROR32(a, 22)) + ((a & b) ^ (a & c) ^ (b & c));
        k = g; g = f; f = e; e = d + t1; d = c; c = b; b = a; a = t1 + t2;
    }
    h[0] += a; h[1] += b; h[2] += c; h[3] += d; h[4] += e; h[5] += f; h[6] += g; h[7] += k;
}
static void inst_sha256(const uint8_t* d, size_t n, uint8_t out[32])
{
    uint32_t h[8] = { 0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19 };
    size_t o = 0;
    for (; o + 64 <= n; o += 64) inst_sha256_blk(h, d + o);
    uint8_t t[128] = { 0 }; const size_t r = n - o;
    memcpy(t, d + o, r); t[r] = 0x80;
    const size_t tl = r < 56 ? 64 : 128;
    for (int i = 0; i < 8; i++) t[tl - 1 - i] = (uint8_t)((uint64_t)n * 8 >> (i * 8));
    for (size_t b = 0; b < tl; b += 64) inst_sha256_blk(h, t + b);
    for (int i = 0; i < 32; i++) out[i] = (uint8_t)(h[i / 4] >> (24 - i % 4 * 8));
}
#undef ROR32

/* ---------------------------------------------------------------- the games */
enum { INST_IF1, INST_IF2, INST_FOB, INST_NGAMES };
static const char* const kInstDir[INST_NGAMES] = { "if1", "if2", "fob" };
/* The editions: base (disc or PSN game) or update. tested = the edition our builds were made and
 * played with. Each game's own EBOOT is built in, so another region's data may well work, but only
 * a tested one is promised. */
typedef struct { const char* tid; int game; int update; const char* ver; int tested; const char* what; } inst_known_t;
static const inst_known_t kInstKnown[] = {
    { "BCES00220", INST_IF1, 0, NULL, 1, "inFAMOUS (Europe, disc)" },
    { "BCUS98119", INST_IF1, 0, NULL, 1, "inFAMOUS (USA, disc)" },   /* v01.00 / v02.00: its EBOOT is patched into the Europe one */
    { "BCUS98125", INST_IF2, 0, NULL, 1, "inFAMOUS 2 (USA, disc)" },
    { "BCUS98125", INST_IF2, 1, "01.01", 1, "inFAMOUS 2 update 1.01" },
    { "BCUS98125", INST_IF2, 1, "01.02", 1, "inFAMOUS 2 update 1.02" },
    { "BCUS98125", INST_IF2, 1, "01.03", 1, "inFAMOUS 2 update 1.03" },
    { "BCUS98125", INST_IF2, 1, "01.04", 1, "inFAMOUS 2 update 1.04" },
    { "NPUA80657", INST_FOB, 0, NULL, 1, "inFAMOUS: Festival of Blood (USA, PSN)" },
};
enum { INST_NKNOWN = sizeof kInstKnown / sizeof kInstKnown[0] };
/* What each game needs: its base, and inFAMOUS 2 all four updates (they are not cumulative). */
static const char* const kInstIf2Updates[] = { "01.01", "01.02", "01.03", "01.04" };

/* The <X>_INSTALL folders (USRDIR paths, copied from PS3_GAME/USRDIR) and their ne.bv markers,
 * as the games leave them on the BC-250 (byte copies, checked 2026-11-08). */
static const char* const kIf2InstallFiles[] = {
    "cache/psarc/brazilian_text.psarc", "cache/psarc/british_text.psarc", "cache/psarc/chinese_text.psarc",
    "cache/psarc/dutch_text.psarc", "cache/psarc/english_text.psarc", "cache/psarc/french_text.psarc",
    "cache/psarc/german_text.psarc", "cache/psarc/install1/infamous1.psarc_s",
    "cache/psarc/install2/infamous2.psarc_s", "cache/psarc/italian_text.psarc",
    "cache/psarc/japanese_text.psarc", "cache/psarc/korean_text.psarc", "cache/psarc/latino_text.psarc",
    "cache/psarc/polish_text.psarc", "cache/psarc/portuguese_text.psarc", "cache/psarc/russian_text.psarc",
    "cache/psarc/spanish_text.psarc", "cache/psarc/turkish_text.psarc", "movies/cutscene/splash_america.bik",
    "movies/tv/tv_default_feed_2x2_b.bik", "movies/tv/tv_default_feed_2x2.bik", "movies/tv/v_mrg_bertrand1_tv.bik",
    "movies/tv/v_psa_01.bik", "movies/tv/v_psa_02.bik", "movies/tv/v_psa_03.bik", "movies/tv/v_psa_04.bik",
    "movies/tv/v_psa_05.bik", "movies/tv/v_psa_06.bik", "movies/tv/v_psa_07.bik", "movies/tv/v_psa_08.bik",
    "movies/tv/v_ustv_01_aftermath.bik", "movies/tv/v_ustv_02_moving_south.bik",
    "movies/tv/v_ustv_03_felt_around_world.bik", "movies/tv/v_ustv_04_theories.bik",
    "movies/tv/v_ustv_05_unrest.bik", "movies/tv/v_ustv_06_supernatural.bik",
    "movies/tv/v_ustv_07_heading_for_nm.bik", "movies/tv/v_ustv_08_military_attacks.bik",
    "movies/tv/v_ustv_09_mystery_disease.bik", "movies/tv/v_ustv_10_nm_evacuated.bik",
    "movies/tv/v_ustv_11_threat_reaches_nm.bik", "movies/tv/v_ustv_11_threat_reaches_nm_jpn.bik",
    "movies/tv/v_ustv_12_global_pandemic.bik", "movies/tv/v_zeke_date.bik", NULL };
static const char* const kFobInstallFiles[] = {
    "cache_fob/psarc/brazilian(fob)_text.psarc", "cache_fob/psarc/english(fob)_text.psarc",
    "cache_fob/psarc/french(fob)_text.psarc", "cache_fob/psarc/install1/infamous1.psarc_s",
    "cache_fob/psarc/latino(fob)_text.psarc", "movies/cutscene/splash_fob_america.bik",
    "movies/tv/bar_tv.bik", "movies/tv/tv_fob_feed_2x2.bik", NULL };
static const uint8_t kIf2NeBv[62] = { 0x42,0x56,0x45,0x52,0x00,0x00,0x00,0x01,0x00,0x00,0x00,0x02,0x05,0x50,0x41,0x54,
    0x43,0x48,0x05,0x62,0x75,0x69,0x6c,0x64,0x09,0x31,0x30,0x31,0x37,0x2e,0x31,0x35,0x32,0x36,0x04,0x73,0x68,0x69,0x70,
    0x00,0x11,0x52,0x45,0x54,0x41,0x49,0x4c,0x20,0x62,0x75,0x69,0x6c,0x64,0x20,0x73,0x68,0x69,0x70,0xba,0xdb,0xad,0x13 };
static const uint8_t kFobNeBv[63] = { 0x42,0x56,0x45,0x52,0x00,0x00,0x00,0x01,0x00,0x00,0x00,0x02,0x06,0x52,0x45,0x54,
    0x41,0x49,0x4c,0x05,0x62,0x75,0x69,0x6c,0x64,0x09,0x31,0x30,0x30,0x34,0x2e,0x31,0x30,0x34,0x33,0x04,0x73,0x68,0x69,
    0x70,0x00,0x11,0x52,0x45,0x54,0x41,0x49,0x4c,0x20,0x62,0x75,0x69,0x6c,0x64,0x20,0x73,0x68,0x69,0x70,0xba,0xdb,0xad,0x13 };

/* inFAMOUS 1 copies these from the disc into dev_hdd0/game/BCES00220/USRDIR during its first boot (1.3 GB, as the
 * game leaves them on the BC-250: byte copies of PS3_GAME/USRDIR, checked 2026-11-09) and then writes ne.bv; done
 * inside the app the PS5 slows that to ~1 MB/s (hours of stutter), so the installer does it here. */
static const char* const kIf1InstallFiles[] = {
    "cache/psarc/install1/infamous1.psarc_s", "cache/psarc/install2/infamous2.psarc_s",
    "movies/tv/broken_screen.bik", "movies/tv/dallas_i1_01.bik", "movies/tv/dallas_i1_02.bik",
    "movies/tv/dallas_i1_03.bik", "movies/tv/dallas_i1_04.bik", "movies/tv/dallas_i1_05.bik",
    "movies/tv/dallas_i1_06.bik", "movies/tv/dallas_i1_07.bik", "movies/tv/dallas_i1_08.bik",
    "movies/tv/dallas_i1_09.bik", "movies/tv/dallas_i1_10.bik", "movies/tv/dallas_i2_01.bik",
    "movies/tv/dallas_i2_02.bik", "movies/tv/dallas_i2_03.bik", "movies/tv/dallas_i2_04.bik",
    "movies/tv/dallas_i2_05.bik", "movies/tv/dallas_i2_06.bik", "movies/tv/dallas_i2_07.bik",
    "movies/tv/dallas_i2_08.bik", "movies/tv/dallas_i2_09.bik", "movies/tv/dallas_i2_10.bik",
    "movies/tv/dallas_i3_01.bik", "movies/tv/dallas_i3_02.bik", "movies/tv/dallas_i3_03.bik",
    "movies/tv/dallas_i3_04.bik", "movies/tv/dallas_intro_static.bik", "movies/tv/jumbotron_dallas.bik",
    "movies/tv/news_i1_a01.bik", "movies/tv/news_i1_a02.bik", "movies/tv/news_i1_a03.bik",
    "movies/tv/news_i1_a04.bik", "movies/tv/news_i1_a05.bik", "movies/tv/news_i1_a06.bik",
    "movies/tv/news_i2_a01.bik", "movies/tv/news_i2_a02.bik", "movies/tv/news_i2_a03.bik",
    "movies/tv/news_i2_a04.bik", "movies/tv/news_i2_a05.bik", "movies/tv/news_i3_a01.bik",
    "movies/tv/news_i3_a02.bik", "movies/tv/tv_default_feed_2x2.bik", "movies/tv/zekes_tv_cartoon.bik",
    "movies/tv/zekes_tv_dallas_feed.bik", "sounds/streaming_grains/0/airplanedrone.mp3",
    "sounds/streaming_grains/0/airplanepassoverzekesroof_long.mp3",
    "sounds/streaming_grains/0/reaperbossthroneclosev2.mp3", "sounds/streaming_grains/0/roofrattle.mp3",
    "sounds/streaming_grains/1/reaperbossambience.mp3", "sounds/streaming_grains/1/sewerdarknessstream.mp3",
    "sounds/streaming_grains/10/3citybattleamb1.mp3", "sounds/streaming_grains/10/3groundzero1.mp3",
    "sounds/streaming_grains/12/mob_ldr_001.mp3", "sounds/streaming_grains/12/mob_ldr_002.mp3",
    "sounds/streaming_grains/12/mob_ldr_003.mp3", "sounds/streaming_grains/15/x_dialog_stream_test_01.mp3",
    "sounds/streaming_grains/2/abovebridgeambiencev2.mp3", "sounds/streaming_grains/2/bridgeramp.mp3",
    "sounds/streaming_grains/2/bridgeunderside_gulls.mp3",
    "sounds/streaming_grains/2/bridgeundersidetransitionandview_gulls.mp3",
    "sounds/streaming_grains/2/sewerspookywater_v2.mp3", "sounds/streaming_grains/2/wateryfalls.mp3",
    "sounds/streaming_grains/3/hallucinagins4816.mp3", "sounds/streaming_grains/3/jbintro_gz_amb.mp3",
    "sounds/streaming_grains/3/raysphereloop.mp3", "sounds/streaming_grains/4/3parkamb.mp3",
    "sounds/streaming_grains/4/interiorhelicopteraccel.mp3", "sounds/streaming_grains/4/jbintro_blastinitial.mp3",
    "sounds/streaming_grains/4/jbintro_blastwall.mp3",
    "sounds/streaming_grains/4/jbintro_blastwall_no_screams_v2.mp3",
    "sounds/streaming_grains/4/jbintro_blastwave.mp3", "sounds/streaming_grains/4/jbintro_electroblast_v1.mp3",
    "sounds/streaming_grains/4/jbintro_electroblast_v2.mp3", "sounds/streaming_grains/4/jbintro_electroblast_v3.mp3",
    "sounds/streaming_grains/5/tmdisthowl_01.mp3", "sounds/streaming_grains/5/tmdisthowl_02.mp3",
    "sounds/streaming_grains/5/tmdisthowl_03.mp3", "sounds/streaming_grains/5/tmdisthowl_04.mp3",
    "sounds/streaming_grains/8/i1_basic_grnd_day_nonpwrd.mp3",
    "sounds/streaming_grains/8/i1_basic_grnd_day_pwrd.mp3",
    "sounds/streaming_grains/8/i1_basic_grnd_nite_nonpwrd.mp3",
    "sounds/streaming_grains/8/i1_basic_grnd_nite_pwrd.mp3",
    "sounds/streaming_grains/8/i1_basic_high_day_nonpwrd.mp3",
    "sounds/streaming_grains/8/i1_basic_high_day_pwrd.mp3",
    "sounds/streaming_grains/8/i1_basic_high_nite_nonpwrd.mp3",
    "sounds/streaming_grains/8/i1_basic_high_nite_pwrd.mp3",
    "sounds/streaming_grains/8/i1_basic_med_day_nonpwrd.mp3", "sounds/streaming_grains/8/i1_basic_med_day_pwrd.mp3",
    "sounds/streaming_grains/8/i1_basic_med_nite_nonpwrd.mp3",
    "sounds/streaming_grains/8/i1_basic_med_nite_pwrd.mp3", "sounds/streaming_grains/8/i1_park_grnd_day_nonpwrd.mp3",
    "sounds/streaming_grains/8/i1_park_grnd_nite_nonpwrd.mp3",
    "sounds/streaming_grains/8/i1_wtrfrnt_grnd_day_nonpwrd.mp3",
    "sounds/streaming_grains/8/i1_wtrfrnt_grnd_day_pwrd.mp3",
    "sounds/streaming_grains/8/i1_wtrfrnt_grnd_nite_nonpwrd.mp3",
    "sounds/streaming_grains/8/i1_wtrfrnt_grnd_nite_pwrd.mp3",
    "sounds/streaming_grains/8/i1_wtrfrnt_med_day_nonpwrd.mp3",
    "sounds/streaming_grains/8/i1_wtrfrnt_med_day_pwrd.mp3",
    "sounds/streaming_grains/8/i1_wtrfrnt_med_nite_nonpwrd.mp3",
    "sounds/streaming_grains/8/i1_wtrfrnt_med_nite_pwrd.mp3",
    "sounds/streaming_grains/9/i2 cmaze nonpowered day_ground.mp3",
    "sounds/streaming_grains/9/i2 cmaze nonpowered day_rooftop.mp3",
    "sounds/streaming_grains/9/i2 cmaze nonpowered night_ground.mp3",
    "sounds/streaming_grains/9/i2 cmaze nonpowered night_rooftop.mp3",
    "sounds/streaming_grains/9/i2 cmaze powered day_ground.mp3",
    "sounds/streaming_grains/9/i2 cmaze powered day_rooftop.mp3",
    "sounds/streaming_grains/9/i2 cmaze powered night_ground.mp3",
    "sounds/streaming_grains/9/i2 cmaze powered night_rooftop.mp3", NULL };
static const char* const kIf1InstallDirs[] = { "sounds/streaming_grains/11", "sounds/streaming_grains/13", "sounds/streaming_grains/14", "sounds/streaming_grains/6", "sounds/streaming_grains/7", NULL };   /* empty folders the game also makes */
static const uint8_t kIf1NeBv[110] = { 0x42,0x56,0x45,0x52,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x02,0x00,0x06,0x00,0x52,0x00,0x45,0x00,0x54,0x00,0x41,0x00,0x49,0x00,0x4c,0x00,0x05,0x00,0x62,0x00,0x75,0x00,0x69,0x00,0x6c,0x00,0x64,0x00,0x09,0x00,0x30,0x00,0x34,0x00,0x32,0x00,0x32,0x00,0x2e,0x00,0x31,0x00,0x35,0x00,0x34,0x00,0x37,0x00,0x04,0x00,0x73,0x00,0x68,0x00,0x69,0x00,0x70,0x00,0x00,0x00,0x11,0x00,0x52,0x00,0x45,0x00,0x54,0x00,0x41,0x00,0x49,0x00,0x4c,0x00,0x20,0x00,0x62,0x00,0x75,0x00,0x69,0x00,0x6c,0x00,0x64,0x00,0x20,0x00,0x73,0x00,0x68,0x00,0x69,0x00,0x70,0xba,0xdb,0xad,0x13 };
/* 109 files */

/* ---------------------------------------------------------------- sources */
enum { SRC_DIR, SRC_ISO, SRC_PKG };
enum { INST_MAXEXT = 8 };
typedef struct {
    char* rel;                      /* path under the game root (the folder that holds PARAM.SFO) */
    uint64_t size;
    uint64_t off[INST_MAXEXT], len[INST_MAXEXT]; int next;   /* ISO extents; PKG: off[0] in the data area */
} inst_ent_t;
typedef struct {
    int kind;
    char path[512];                 /* the .iso / .pkg / folder (the game root for a folder) */
    char name[96];                  /* what the player sees: the file or folder name */
    int fd;
    char tid[16], ver[8], cat[4], title[96];
    int known;                      /* kInstKnown index, -1 unknown */
    inst_ent_t* e; int n, cap;
    uint64_t total;
    uint64_t pkg_data;              /* PKG: the data area's file offset */
    uint8_t pkg_riv[16]; inst_aes_t pkg_aes;
    /* disc (2026-11-17): an encrypted PS3 disc image or the PS5's own drive (/dev/cd0): the sectors between the
     * disc's plain regions are AES-128-CBC with the disc key, IV = the sector number */
    int enc; inst_aesd_t dkey; uint32_t nplain, plain[2 * 32];   /* plain regions: [plain[2i], plain[2i+1]] inclusive */
    int disc_mnt;                   /* /mnt/disc seen from the app: identifies the disc; its files read encrypted */
    uint8_t* sec;                   /* raw sector buffer for the reads (INST_SECBUF) */
} inst_src_t;

static void inst_add(inst_src_t* s, const char* rel, uint64_t size)
{
    if (s->n == s->cap) { s->cap = s->cap ? s->cap * 2 : 256; s->e = realloc(s->e, s->cap * sizeof *s->e); }
    inst_ent_t* e = &s->e[s->n++];
    memset(e, 0, sizeof *e);
    e->rel = strdup(rel); e->size = size;
    s->total += size;
}
static void inst_src_free(inst_src_t* s)
{
    free(s->sec); s->sec = NULL;
    for (int i = 0; i < s->n; i++) free(s->e[i].rel);
    free(s->e); s->e = NULL; s->n = s->cap = 0;
    if (s->fd >= 0) close(s->fd);
    s->fd = -1;
}
/* lseek + read, not pread: the games never import pread, and an import the console lacks stops the
 * launcher from starting at all. (One thread reads a source at a time: the scan, or the install.) */
static int inst_pread(int fd, void* b, size_t n, uint64_t off)
{
    uint8_t* p = b;
    if (lseek(fd, (off_t)off, SEEK_SET) != (off_t)off) return -1;
    while (n) {
        const ssize_t r = read(fd, p, n);
        if (r <= 0) return -1;
        p += r; n -= (size_t)r;
    }
    return 0;
}
/* disc: n bytes at byte a of an ISO source, always as whole sectors (the PS5's drive, /dev/cd0, takes nothing else),
 * the encrypted ones decrypted. */
enum { INST_SECBUF = 512 };   /* sectors per raw read: 1 MB */
static int inst_sec_enc(const inst_src_t* s, uint32_t sec)
{
    if (!s->enc) return 0;
    for (uint32_t i = 0; i < s->nplain; i++) if (sec >= s->plain[2 * i] && sec <= s->plain[2 * i + 1]) return 0;
    return 1;
}
static int inst_iso_rd(inst_src_t* s, uint64_t a, uint8_t* buf, size_t n)
{
    if (!s->sec && !(s->sec = malloc((size_t)INST_SECBUF * 2048))) return -1;
    while (n) {
        const uint64_t sec = a / 2048; const size_t in = (size_t)(a % 2048);
        size_t ns = (in + n + 2047) / 2048; if (ns > INST_SECBUF) ns = INST_SECBUF;
        if (inst_pread(s->fd, s->sec, ns * 2048, sec * 2048)) return -1;
        for (size_t j = 0; j < ns; j++)
            if (inst_sec_enc(s, (uint32_t)(sec + j))) {
                uint8_t iv[16] = { 0 }; const uint32_t v = (uint32_t)(sec + j);
                iv[12] = (uint8_t)(v >> 24); iv[13] = (uint8_t)(v >> 16); iv[14] = (uint8_t)(v >> 8); iv[15] = (uint8_t)v;
                inst_aes_cbc_dec(&s->dkey, iv, s->sec + j * 2048, 2048);
            }
        size_t m = ns * 2048 - in; if (m > n) m = n;
        memcpy(buf, s->sec + in, m);
        buf += m; n -= m; a += m;
    }
    return 0;
}
/* Read size bytes at off of entry e. */
static int inst_read(inst_src_t* s, const inst_ent_t* e, uint64_t off, uint8_t* buf, size_t n)
{
    if (s->kind == SRC_DIR) {
        char p[1024]; snprintf(p, sizeof p, "%s/%s", s->path, e->rel);
        const int fd = open(p, O_RDONLY);
        if (fd < 0) return -1;
        const int r = inst_pread(fd, buf, n, off);
        close(fd);
        return r;
    }
    if (s->kind == SRC_ISO) {
        uint64_t base = 0;
        for (int x = 0; x < e->next && n; x++) {
            if (off < base + e->len[x]) {
                const uint64_t in = off - base;
                size_t m = (size_t)(e->len[x] - in < n ? e->len[x] - in : n);
                if (inst_iso_rd(s, e->off[x] + in, buf, m)) return -1;
                buf += m; n -= m; off += m;
            }
            base += e->len[x];
        }
        return n ? -1 : 0;
    }
    /* PKG: CTR over the data area, block index from the data area's start */
    const uint64_t a = e->off[0] + off, a0 = a & ~15ull, head = a - a0;
    uint8_t tmp[16];
    if (head) {   /* (never with the 1 MB-aligned chunks the copy uses; kept for completeness) */
        if (inst_pread(s->fd, tmp, 16, s->pkg_data + a0)) return -1;
        inst_aes_ctr(&s->pkg_aes, s->pkg_riv, a0 / 16, tmp, 16);
        const size_t m = 16 - head < n ? 16 - head : n;
        memcpy(buf, tmp + head, m); buf += m; n -= m;
        if (!n) return 0;
        return inst_read(s, e, off + m, buf, n);
    }
    if (inst_pread(s->fd, buf, n, s->pkg_data + a)) return -1;
    inst_aes_ctr(&s->pkg_aes, s->pkg_riv, a / 16, buf, n);
    return 0;
}

/* PARAM.SFO: string value of key k, "" if none. */
static void inst_sfo(const uint8_t* d, size_t n, const char* k, char* out, size_t outn)
{
    out[0] = 0;
    if (n < 20 || memcmp(d, "\0PSF", 4)) return;
    const uint32_t kt = d[8] | d[9] << 8 | d[10] << 16 | (uint32_t)d[11] << 24;
    const uint32_t dt = d[12] | d[13] << 8 | d[14] << 16 | (uint32_t)d[15] << 24;
    const uint32_t cnt = d[16] | d[17] << 8 | d[18] << 16 | (uint32_t)d[19] << 24;
    for (uint32_t i = 0; i < cnt && 20 + i * 16 + 16 <= n; i++) {
        const uint8_t* e = d + 20 + i * 16;
        const uint32_t ko = e[0] | e[1] << 8, fmt = e[2] | e[3] << 8;
        const uint32_t ln = e[4] | e[5] << 8 | e[6] << 16 | (uint32_t)e[7] << 24;
        const uint32_t dof = e[12] | e[13] << 8 | e[14] << 16 | (uint32_t)e[15] << 24;
        if (kt + ko >= n || strncmp((const char*)d + kt + ko, k, n - kt - ko)) continue;
        if (fmt == 0x0404 || dt + dof + ln > n) return;
        size_t m = ln < outn - 1 ? ln : outn - 1;
        memcpy(out, d + dt + dof, m); out[m] = 0;
        return;
    }
}
/* Rewrite string key k in place (same-or-shorter value, inside its max length). */
static int inst_sfo_set(uint8_t* d, size_t n, const char* k, const char* v)
{
    if (n < 20 || memcmp(d, "\0PSF", 4)) return -1;
    const uint32_t kt = d[8] | d[9] << 8 | d[10] << 16 | (uint32_t)d[11] << 24;
    const uint32_t dt = d[12] | d[13] << 8 | d[14] << 16 | (uint32_t)d[15] << 24;
    const uint32_t cnt = d[16] | d[17] << 8 | d[18] << 16 | (uint32_t)d[19] << 24;
    for (uint32_t i = 0; i < cnt && 20 + i * 16 + 16 <= n; i++) {
        uint8_t* e = d + 20 + i * 16;
        const uint32_t ko = e[0] | e[1] << 8;
        const uint32_t mx = e[8] | e[9] << 8 | e[10] << 16 | (uint32_t)e[11] << 24;
        const uint32_t dof = e[12] | e[13] << 8 | e[14] << 16 | (uint32_t)e[15] << 24;
        if (kt + ko >= n || strcmp((const char*)d + kt + ko, k)) continue;
        const size_t l = strlen(v);
        if (l >= mx || dt + dof + mx > n) return -1;
        memset(d + dt + dof, 0, mx); memcpy(d + dt + dof, v, l);
        const uint32_t nl = (uint32_t)l + 1;
        e[4] = nl & 0xFF; e[5] = nl >> 8 & 0xFF; e[6] = nl >> 16 & 0xFF; e[7] = nl >> 24;
        return 0;
    }
    return -1;
}
static int inst_find(const inst_src_t* s, const char* rel)
{
    for (int i = 0; i < s->n; i++) if (!strcmp(s->e[i].rel, rel)) return i;
    return -1;
}
static void inst_identify(inst_src_t* s)
{
    s->known = -1;
    const int i = inst_find(s, "PARAM.SFO");
    if (i < 0 || s->e[i].size > 65536) return;
    uint8_t* d = malloc((size_t)s->e[i].size);
    if (d && !inst_read(s, &s->e[i], 0, d, (size_t)s->e[i].size)) {
        inst_sfo(d, (size_t)s->e[i].size, "TITLE_ID", s->tid, sizeof s->tid);
        inst_sfo(d, (size_t)s->e[i].size, "APP_VER", s->ver, sizeof s->ver);
        inst_sfo(d, (size_t)s->e[i].size, "CATEGORY", s->cat, sizeof s->cat);
        inst_sfo(d, (size_t)s->e[i].size, "TITLE", s->title, sizeof s->title);
    }
    free(d);
    const int upd = !strcmp(s->cat, "GP") || !strcmp(s->cat, "GD");   /* a patch (GD: a disc game's, GP: a PSN one's) */
    for (int k = 0; k < INST_NKNOWN; k++) {
        const inst_known_t* q = &kInstKnown[k];
        if (strcmp(q->tid, s->tid) || q->update != upd) continue;
        if (upd && strcmp(q->ver, s->ver)) continue;
        s->known = k; break;
    }
}

/* -- folder */
static void inst_dir_walk(inst_src_t* s, const char* abs, const char* rel)
{
    DIR* d = opendir(abs);
    if (!d) return;
    struct dirent* de;
    while ((de = readdir(d))) {
        if (de->d_name[0] == '.' ) continue;
        if (strstr(de->d_name, ":Zone.Identifier") || strstr(de->d_name, "Zone.Identifier")) continue;
        char a[1024], r[768];
        snprintf(a, sizeof a, "%s/%s", abs, de->d_name);
        snprintf(r, sizeof r, "%s%s%s", rel, rel[0] ? "/" : "", de->d_name);
        struct stat st;
        if (stat(a, &st)) continue;
        if (S_ISDIR(st.st_mode)) inst_dir_walk(s, a, r);
        else if (S_ISREG(st.st_mode)) inst_add(s, r, (uint64_t)st.st_size);
    }
    closedir(d);
}
static int inst_open_dir(inst_src_t* s, const char* path)
{
    char p[600];
    snprintf(p, sizeof p, "%s/PS3_GAME/PARAM.SFO", path);
    struct stat st;
    if (!stat(p, &st)) snprintf(s->path, sizeof s->path, "%s/PS3_GAME", path);
    else {
        snprintf(p, sizeof p, "%s/PARAM.SFO", path);
        if (stat(p, &st)) return -1;
        snprintf(s->path, sizeof s->path, "%s", path);
    }
    s->kind = SRC_DIR;
    inst_dir_walk(s, s->path, "");
    return s->n ? 0 : -1;
}

/* -- ISO 9660 (Joliet when there, else the primary names minus ";1") */
static uint32_t le32(const uint8_t* p) { return p[0] | p[1] << 8 | p[2] << 16 | (uint32_t)p[3] << 24; }
static uint32_t be32(const uint8_t* p) { return (uint32_t)p[0] << 24 | p[1] << 16 | p[2] << 8 | p[3]; }
static uint64_t be64(const uint8_t* p) { return (uint64_t)be32(p) << 32 | be32(p + 4); }
static void inst_iso_name(const uint8_t* r, int joliet, char* out, size_t outn)
{
    const int ln = r[32];
    const uint8_t* n = r + 33;
    size_t o = 0;
    if (joliet) {
        for (int i = 0; i + 1 < ln && o + 4 < outn; i += 2) {   /* UCS-2 BE -> UTF-8 */
            const unsigned c = (unsigned)n[i] << 8 | n[i + 1];
            if (c < 0x80) out[o++] = (char)c;
            else if (c < 0x800) { out[o++] = (char)(0xC0 | c >> 6); out[o++] = (char)(0x80 | (c & 0x3F)); }
            else { out[o++] = (char)(0xE0 | c >> 12); out[o++] = (char)(0x80 | (c >> 6 & 0x3F)); out[o++] = (char)(0x80 | (c & 0x3F)); }
        }
    } else {
        for (int i = 0; i < ln && o + 1 < outn; i++) out[o++] = (char)n[i];
    }
    out[o] = 0;
    char* sc = strchr(out, ';'); if (sc) *sc = 0;
    o = strlen(out); if (o && out[o - 1] == '.') out[o - 1] = 0;
}
static void inst_iso_walk(inst_src_t* s, uint32_t lba, uint32_t len, int joliet, const char* rel, int depth)
{
    if (depth > 16 || len > (64u << 20)) return;
    uint8_t* d = malloc(len);
    if (!d || inst_pread(s->fd, d, len, (uint64_t)lba * 2048)) { free(d); return; }
    char last[512] = ""; int lastidx = -1;
    for (uint32_t o = 0; o < len;) {
        const uint8_t* r = d + o;
        if (!r[0]) { o = (o / 2048 + 1) * 2048; continue; }   /* records never cross a sector */
        const uint32_t rl = r[0];
        if (o + rl > len) break;
        const uint32_t elba = le32(r + 2), elen = le32(r + 10);
        const int flags = r[25];
        if (!(r[32] == 1 && (r[33] == 0 || r[33] == 1))) {     /* not . or .. */
            char nm[512], rr[768];
            inst_iso_name(r, joliet, nm, sizeof nm);
            snprintf(rr, sizeof rr, "%s%s%s", rel, rel[0] ? "/" : "", nm);
            if (flags & 2) inst_iso_walk(s, elba, elen, joliet, rr, depth + 1);
            else if (lastidx >= 0 && !strcmp(last, rr) && s->e[lastidx].next < INST_MAXEXT) {
                inst_ent_t* e = &s->e[lastidx];          /* the next extent of a multi-extent file */
                e->off[e->next] = (uint64_t)elba * 2048; e->len[e->next] = elen; e->next++;
                e->size += elen; s->total += elen;
            } else {
                inst_add(s, rr, elen);
                inst_ent_t* e = &s->e[s->n - 1];
                e->off[0] = (uint64_t)elba * 2048; e->len[0] = elen; e->next = 1;
                snprintf(last, sizeof last, "%s", rr); lastidx = s->n - 1;
            }
        }
        o += rl;
    }
    free(d);
}
static int inst_disc_key(inst_src_t* s, const inst_ent_t* eb);   /* disc (below) */
static int inst_open_iso(inst_src_t* s, const char* path, char* why, size_t whyn)
{
    s->kind = SRC_ISO;
    snprintf(s->path, sizeof s->path, "%s", path);
    s->fd = open(path, O_RDONLY);
    if (s->fd < 0) return -1;
    uint8_t vd[2048]; const uint8_t* root = NULL; int joliet = 0; uint8_t pvd[2048]; int have_pvd = 0;
    for (int i = 16; i < 32; i++) {
        if (inst_pread(s->fd, vd, 2048, (uint64_t)i * 2048) || memcmp(vd + 1, "CD001", 5)) break;
        if (vd[0] == 255) break;
        if (vd[0] == 1 && !have_pvd) { memcpy(pvd, vd, 2048); have_pvd = 1; }
        if (vd[0] == 2 && vd[88] == 0x25 && vd[89] == 0x2F && (vd[90] == 0x40 || vd[90] == 0x43 || vd[90] == 0x45)) {
            static uint8_t svd[2048]; memcpy(svd, vd, 2048); root = svd + 156; joliet = 1;
        }
    }
    if (!root && have_pvd) root = pvd + 156;
    if (!root) { snprintf(why, whyn, "not a disc image"); return -1; }
    /* walk everything, then keep PS3_GAME's files with the prefix taken off */
    inst_src_t all = { .fd = s->fd };
    inst_iso_walk(&all, le32(root + 2), le32(root + 10), joliet, "", 0);
    for (int i = 0; i < all.n; i++) {
        if (strncasecmp(all.e[i].rel, "PS3_GAME/", 9)) continue;
        inst_add(s, all.e[i].rel + 9, 0);
        inst_ent_t* e = &s->e[s->n - 1];
        char* r = e->rel;
        *e = all.e[i]; e->rel = r;
        s->total += e->size;
    }
    for (int i = 0; i < all.n; i++) free(all.e[i].rel);
    free(all.e);
    if (!s->n) { snprintf(why, whyn, "no PS3_GAME folder in it"); return -1; }
    /* An encrypted (Redump) image or the disc itself: EBOOT.BIN is a SELF ("SCE\0") only once decrypted; then the
     * disc key that makes it one (kInstDiscKeys), and every read decrypts. */
    const int eb = inst_find(s, "USRDIR/EBOOT.BIN");
    if (eb >= 0) {
        uint8_t m[4] = { 0 };
        if (inst_read(s, &s->e[eb], 0, m, 4) || memcmp(m, "SCE\0", 4)) {
            if (inst_disc_key(s, &s->e[eb]) || inst_read(s, &s->e[eb], 0, m, 4) || memcmp(m, "SCE\0", 4)) {
                snprintf(why, whyn, "this disc / ISO is encrypted with a key this doesn't have (a decrypted .iso works)");
                return -1;
            }
        }
    }
    return 0;
}

/* disc keys (Redump's published PS3 disc keys, 2026-11-17): each inFAMOUS / inFAMOUS 2 pressing. A disc or an
 * encrypted image is tried with each; the right one turns EBOOT.BIN's first sector into a SELF ("SCE\0"). */
static const uint8_t kInstDiscKeys[][16] = {
    { 0x55,0x9c,0x30,0xf3,0x46,0x8c,0xd2,0xcb,0xdf,0x09,0xb1,0xaf,0xa8,0x09,0x3a,0xdc },   /* inFAMOUS 2 (Asia) */
    { 0xb8,0x95,0x44,0x7f,0x05,0x75,0x40,0xc7,0x28,0x74,0xbd,0xc6,0xae,0xba,0xb1,0x99 },   /* inFAMOUS 2 (Europe, Australia) */
    { 0x7e,0x40,0xb7,0x93,0xcb,0x5d,0xd7,0xbc,0x4c,0x89,0x2e,0x9e,0x9c,0x45,0x5c,0x2d },   /* inFAMOUS 2 (Japan) */
    { 0x1a,0x4e,0x94,0x45,0x88,0x14,0xf0,0x5b,0x11,0x2e,0x3f,0xa2,0xed,0x90,0x12,0x38 },   /* inFAMOUS 2 (Turkey) */
    { 0x79,0x6c,0xa3,0xc1,0x99,0xae,0xac,0xb2,0xc3,0x08,0x64,0xc5,0x11,0xab,0x0a,0x83 },   /* inFAMOUS 2 (UK) */
    { 0xc6,0x13,0x7e,0x41,0xa0,0xf4,0xd2,0x9f,0x8c,0x12,0x5d,0x7a,0x5f,0x35,0x20,0x8b },   /* inFAMOUS 2 (USA) v01.00 / v02.00, BCUS98125 */
    { 0xdd,0xa0,0xab,0xdc,0xe4,0x5d,0x5f,0x22,0xc9,0x68,0x5d,0x4d,0x48,0xc8,0x63,0x88 },   /* inFAMOUS (Japan) */
    { 0x34,0x29,0x17,0x03,0xa6,0x22,0xed,0x1d,0x81,0xd2,0x8a,0x7e,0xcb,0xae,0x5a,0x8d },   /* inFAMOUS (Asia) */
    { 0x23,0x33,0xc4,0x6d,0x2d,0xeb,0xff,0xf6,0xfb,0x83,0x2d,0x68,0xff,0xee,0x14,0xad },   /* inFAMOUS (Europe, Australia) */
    { 0x43,0x57,0x8e,0x5c,0x93,0x0c,0xa9,0x74,0xd5,0xa4,0x75,0x32,0x0c,0xea,0x6b,0x7a },   /* inFAMOUS (Europe, Fr/De/Es/It/Nl) */
    { 0x07,0x94,0x46,0x53,0x69,0xa9,0xc0,0xf2,0x89,0x50,0xb7,0x7c,0x31,0x8d,0xb8,0x58 },   /* inFAMOUS (Poland) */
    { 0x2d,0x91,0xb0,0xba,0x66,0xc3,0x8d,0x54,0xf7,0x69,0x75,0xea,0xd6,0x51,0x89,0x6d },   /* inFAMOUS (USA) v01.00 / v02.00, BCUS98119 */
};
/* An encrypted image / disc: its plain regions from sector 0, then the key that decrypts EBOOT.BIN. 0 = found. */
static int inst_disc_key(inst_src_t* s, const inst_ent_t* eb)
{
    uint8_t h[2048];
    if (inst_pread(s->fd, h, 2048, 0)) return -1;
    const uint32_t n = be32(h);
    if (!n || n > 32) return -1;
    s->nplain = n;
    for (uint32_t i = 0; i < 2 * n; i++) s->plain[i] = be32(h + 8 + 4 * i);
    s->enc = 1;
    const uint32_t lba = (uint32_t)(eb->off[0] / 2048);
    uint8_t c[2048];
    if (inst_pread(s->fd, c, 2048, (uint64_t)lba * 2048) || !inst_sec_enc(s, lba)) { s->enc = 0; return -1; }
    for (unsigned k = 0; k < sizeof kInstDiscKeys / sizeof kInstDiscKeys[0]; k++) {
        inst_aesd_t d; inst_aesd_key128(&d, kInstDiscKeys[k]);
        uint8_t b[32]; memcpy(b, c, 32);
        uint8_t iv[16] = { 0 }; iv[12] = (uint8_t)(lba >> 24); iv[13] = (uint8_t)(lba >> 16); iv[14] = (uint8_t)(lba >> 8); iv[15] = (uint8_t)lba;
        inst_aes_cbc_dec(&d, iv, b, 32);
        if (!memcmp(b, "SCE\0", 4)) { s->dkey = d; return 0; }
    }
    s->enc = 0;
    return -1;
}

/* -- PKG (retail: AES-128-CTR, the public PS3 package key; the file table and data in one stream) */
static const uint8_t kPs3PkgKey[16] = { 0x2e,0x7b,0x71,0xd7,0xc9,0xc9,0xa1,0x4e,0xa3,0x22,0x1f,0x18,0x88,0x28,0xb8,0xf8 };
static int inst_open_pkg(inst_src_t* s, const char* path, char* why, size_t whyn)
{
    s->kind = SRC_PKG;
    snprintf(s->path, sizeof s->path, "%s", path);
    s->fd = open(path, O_RDONLY);
    if (s->fd < 0) return -1;
    uint8_t h[0x80];
    if (inst_pread(s->fd, h, sizeof h, 0) || memcmp(h, "\x7FPKG", 4)) { snprintf(why, whyn, "not a PS3 package"); return -1; }
    if (!(h[4] & 0x80)) { snprintf(why, whyn, "a debug package (not supported)"); return -1; }
    const uint32_t items = be32(h + 0x14);
    s->pkg_data = be64(h + 0x20);
    const uint64_t dsize = be64(h + 0x28);
    memcpy(s->pkg_riv, h + 0x70, 16);
    inst_aes_key(&s->pkg_aes, kPs3PkgKey);
    if (items == 0 || items > 200000) { snprintf(why, whyn, "a damaged package"); return -1; }
    uint64_t tl = (uint64_t)items * 32 + (1u << 20);
    if (tl > dsize) tl = dsize;
    uint8_t* t = malloc((size_t)tl);
    if (!t || inst_pread(s->fd, t, (size_t)tl, s->pkg_data)) { free(t); snprintf(why, whyn, "can't read the package"); return -1; }
    inst_aes_ctr(&s->pkg_aes, s->pkg_riv, 0, t, (size_t)tl);
    for (uint32_t i = 0; i < items; i++) {
        const uint8_t* e = t + i * 32;
        const uint32_t no = be32(e), ns = be32(e + 4);
        const uint64_t fo = be64(e + 8), fs = be64(e + 16);
        const uint32_t flags = be32(e + 24);
        if (flags & 0x10000000) { free(t); snprintf(why, whyn, "a PSP package (not supported)"); return -1; }
        if (no + ns > tl || ns == 0 || ns > 500) { free(t); snprintf(why, whyn, "can't read the package's file list"); return -1; }
        char nm[512]; memcpy(nm, t + no, ns); nm[ns] = 0;
        for (uint32_t c = 0; c < ns; c++) if ((uint8_t)nm[c] < 0x20 || (uint8_t)nm[c] > 0x7E) { free(t); snprintf(why, whyn, "can't read the package's file list"); return -1; }
        const int type = flags & 0xFF;
        if (type == 4 || fs == 0) continue;   /* folders */
        inst_add(s, nm, fs);
        s->e[s->n - 1].off[0] = fo;
    }
    free(t);
    return s->n ? 0 : -1;
}

#define INST_DISC_DEV "/dev/cd0"    /* the PS5's Blu-ray drive, raw (a payload can read it; the app may not) */
#define INST_DISC_MNT "/mnt/disc"   /* the same disc as the system mounts it: its files come back still encrypted */
/* Open whatever path is (a .iso, a .pkg or a folder). 0 = a usable source (s->known may still be -1). */
static int inst_open(inst_src_t* s, const char* path, char* why, size_t whyn)
{
    memset(s, 0, sizeof *s); s->fd = -1; s->known = -1; why[0] = 0;
    const char* b = strrchr(path, '/'); b = b ? b + 1 : path;
    snprintf(s->name, sizeof s->name, "%s", b);
    const size_t l = strlen(path);
    int r;
    if ((l > 4 && !strcasecmp(path + l - 4, ".iso")) || !strcmp(path, INST_DISC_DEV)) r = inst_open_iso(s, path, why, whyn);
    else if (l > 4 && !strcasecmp(path + l - 4, ".pkg")) r = inst_open_pkg(s, path, why, whyn);
    else r = inst_open_dir(s, path);
    if (r) { inst_src_free(s); return -1; }
    inst_identify(s);
    return 0;
}

/* ---------------------------------------------------------------- scan */
enum { INST_MAXSRC = 32 };
static inst_src_t s_inst_src[INST_MAXSRC];
static int s_inst_nsrc;
static char s_inst_notes[8][200]; static int s_inst_nnotes;   /* files that couldn't be used, and why */
static char s_inst_rap[512];      /* Festival of Blood's .rap licence file ("" none found) */

static int inst_is_candidate(const char* dir, const char* nm, int* is_dir)
{
    char p[1024]; snprintf(p, sizeof p, "%s/%s", dir, nm);
    struct stat st;
    if (stat(p, &st)) return 0;
    *is_dir = S_ISDIR(st.st_mode);
    if (*is_dir) {
        char q[1100];
        snprintf(q, sizeof q, "%s/PS3_GAME/PARAM.SFO", p); if (!stat(q, &st)) return 1;
        snprintf(q, sizeof q, "%s/PARAM.SFO", p); if (!stat(q, &st)) return 1;
        return 2;   /* a plain folder: look one level inside */
    }
    const size_t l = strlen(nm);
    return l > 4 && (!strcasecmp(nm + l - 4, ".iso") || !strcasecmp(nm + l - 4, ".pkg"));
}
static void inst_scan_dir(const char* dir, int depth)
{
    DIR* d = opendir(dir);
    if (!d) return;
    struct dirent* de;
    while ((de = readdir(d)) && s_inst_nsrc < INST_MAXSRC) {
        if (de->d_name[0] == '.' || !strcmp(de->d_name, "$RECYCLE.BIN") || !strcmp(de->d_name, "System Volume Information")) continue;
        int isdir = 0;
        const int c = inst_is_candidate(dir, de->d_name, &isdir);
        char p[1024]; snprintf(p, sizeof p, "%s/%s", dir, de->d_name);
        const size_t nl = strlen(de->d_name);
        if (nl > 4 && !strcasecmp(de->d_name + nl - 4, ".rap")) {   /* a licence: the first, or the first FoB one */
            struct stat st;
            if (!stat(p, &st) && S_ISREG(st.st_mode) && st.st_size >= 16
                && (!s_inst_rap[0] || (strstr(de->d_name, "NPUA80657") && !strstr(s_inst_rap, "NPUA80657"))))
                snprintf(s_inst_rap, sizeof s_inst_rap, "%s", p);
            continue;
        }
        if (c == 2) { if (depth < 1) inst_scan_dir(p, depth + 1); continue; }
        if (!c) continue;
        char why[160];
        inst_src_t* s = &s_inst_src[s_inst_nsrc];
        if (inst_open(s, p, why, sizeof why) == 0) {
            if (s->known >= 0) { s_inst_nsrc++; continue; }
            if (s_inst_nnotes < 8) snprintf(s_inst_notes[s_inst_nnotes++], sizeof s_inst_notes[0], "%s: %s %s isn't an inFAMOUS edition this knows",
                                            s->name, s->tid[0] ? s->tid : "(no title ID)", s->ver);
            inst_src_free(s);
        } else if (why[0] && s_inst_nnotes < 8) {
            snprintf(s_inst_notes[s_inst_nnotes++], sizeof s_inst_notes[0], "%s: %s", de->d_name, why);
        }
    }
    closedir(d);
}
/* Where to look: <app>/install and the USB drives (overridable for the PC test: INST_DIRS=a:b). */
static void inst_scan(const char* app)
{
    for (int i = 0; i < s_inst_nsrc; i++) inst_src_free(&s_inst_src[i]);
    s_inst_nsrc = 0; s_inst_nnotes = 0; s_inst_rap[0] = 0;
    const char* env = getenv("INST_DIRS");
    if (env && *env) {
        char buf[2048]; snprintf(buf, sizeof buf, "%s", env);
        for (char* t = strtok(buf, ":"); t; t = strtok(NULL, ":")) inst_scan_dir(t, 0);
        return;
    }
    char p[512];
    /* disc: the PS3 disc in the PS5's drive. Raw (decrypted here) where we may read the drive (the install payload);
     * else, seen from the app, the mounted disc only says which game it is (the install then needs the payload). */
    {
        struct stat st; char why[160];
        if (!stat(INST_DISC_MNT "/PS3_GAME/PARAM.SFO", &st) && s_inst_nsrc < INST_MAXSRC) {
            inst_src_t* s = &s_inst_src[s_inst_nsrc];
            if (!inst_open(s, INST_DISC_DEV, why, sizeof why) && s->known >= 0) {
                snprintf(s->name, sizeof s->name, "the disc in the PS5's drive");
                s_inst_nsrc++;
            } else {
                if (s->fd >= 0 || s->n) inst_src_free(s);
                if (!inst_open(s, INST_DISC_MNT, why, sizeof why) && s->known >= 0) {
                    snprintf(s->name, sizeof s->name, "the disc in the PS5's drive");
                    s->disc_mnt = 1;
                    s_inst_nsrc++;
                } else inst_src_free(s);
            }
        }
    }
    snprintf(p, sizeof p, "%s/install", app); inst_scan_dir(p, 0);
    for (int u = 0; u < 8; u++) { snprintf(p, sizeof p, "/mnt/usb%d", u); inst_scan_dir(p, 0); }
    for (int u = 0; u < 2; u++) { snprintf(p, sizeof p, "/mnt/ext%d", u); inst_scan_dir(p, 0); }
}

/* For game g: the sources to install from, in order (base first, updates by version), or what is
 * missing. Returns the count, 0 if something is missing (need says what). */
static int inst_plan(int g, inst_src_t** out, char* need, size_t needn)
{
    need[0] = 0;
    int n = 0;
    inst_src_t* base = NULL;
    for (int i = 0; i < s_inst_nsrc; i++) {
        const inst_known_t* q = &kInstKnown[s_inst_src[i].known];
        if (q->game == g && !q->update && (!base || (q->tested && !kInstKnown[base->known].tested)
                                           || (!strcmp(s_inst_src[i].tid, "BCES00220") && strcmp(base->tid, "BCES00220")))) base = &s_inst_src[i];   /* inFAMOUS: the Europe disc first */
    }
    if (!base) {
        snprintf(need, needn, g == INST_IF1 ? "the inFAMOUS disc (BCES00220 Europe or BCUS98119 USA: in the PS5's drive, an ISO or its folder)"
                            : g == INST_IF2 ? "the inFAMOUS 2 disc (BCUS98125, USA: in the PS5's drive, an ISO or its folder)"
                            : "the Festival of Blood package (NPUA80657, USA PSN .pkg) and its licence file (the .rap, next to the .pkg)");
        return 0;
    }
    if (g == INST_FOB && !s_inst_rap[0]) {
        snprintf(need, needn, "Festival of Blood's licence file (the .rap with NPUA80657 in its name, next to the .pkg)");
        return 0;
    }
    out[n++] = base;
    if (g == INST_IF2) {
        char miss[64] = "";
        for (int u = 0; u < 4; u++) {
            inst_src_t* f = NULL;
            for (int i = 0; i < s_inst_nsrc; i++) {
                const inst_known_t* q = &kInstKnown[s_inst_src[i].known];
                if (q->game == g && q->update && !strcmp(q->ver, kInstIf2Updates[u])) f = &s_inst_src[i];
            }
            if (f) out[n++] = f;
            else { size_t l = strlen(miss); snprintf(miss + l, sizeof miss - l, "%s%s", l ? ", " : "", kInstIf2Updates[u] + 1); }
        }
        if (miss[0]) {
            snprintf(need, needn, "inFAMOUS 2's update packages %s (BCUS98125, all four are needed: they are not cumulative)", miss);
            return 0;
        }
    }
    return n;
}
/* inFAMOUS 2 with its disc found but updates missing: which (bit u = kInstIf2Updates[u]); 0 = no disc, or none missing. */
static unsigned inst_if2_missing(void)
{
    int base = 0; unsigned have = 0;
    for (int i = 0; i < s_inst_nsrc; i++) {
        const inst_known_t* q = &kInstKnown[s_inst_src[i].known];
        if (q->game != INST_IF2) continue;
        if (!q->update) { base = 1; continue; }
        for (int u = 0; u < 4; u++) if (!strcmp(q->ver, kInstIf2Updates[u])) have |= 1u << u;
    }
    return base ? ~have & 0xFu : 0;
}

/* ---------------------------------------------------------------- the install (a thread) */
typedef struct {
    volatile int state;             /* 0 idle, 1 running, 2 done, 3 failed */
    volatile uint64_t done, total;
    char cur[160];
    char err[256];
    int game;
    char app[256];
    inst_src_t* src[8]; int nsrc;
    char rap[512];                  /* FoB: the .rap licence file */
} inst_job_t;
static inst_job_t s_inst;
/* inFAMOUS 1 from the USA disc (BCUS98119): installed in the Europe layout (EBOOT.elf patched, TITLE_ID BCES00220). */
static int inst_if1_usa(const inst_job_t* J) { return J->game == INST_IF1 && J->nsrc > 0 && !strcmp(J->src[0]->tid, "BCUS98119"); }

static int inst_mkdirs(const char* path)   /* mkdir -p of path's directories (not the last part) */
{
    char p[1024]; snprintf(p, sizeof p, "%s", path);
    for (char* c = p + 1; *c; c++) {
        if (*c != '/') continue;
        *c = 0;
        if (mkdir(p, 0777) && errno != EEXIST) { *c = '/'; return -1; }
        *c = '/';
    }
    return 0;
}
/* rm -rf. 2026-11-12: SAVES' delete removed nothing on the console. lstat was this file's only lstat user (stat,
 * opendir and readdir are proven by the backup copy), and every return code was dropped. Now: lstat first (a link
 * is unlinked, never followed), stat if lstat fails for any reason but ENOENT; the first failure is kept in
 * s_rm_err/s_rm_op/s_rm_path for the caller's log and message. 0 = gone (or never there). */
static int s_rm_err; static const char* s_rm_op = ""; static char s_rm_path[300];
static int inst_rm_fail(const char* op, const char* path)
{
    if (!s_rm_err) { s_rm_err = errno ? errno : EIO; s_rm_op = op; snprintf(s_rm_path, sizeof s_rm_path, "%s", path); }
    return -1;
}
static int inst_rmtree(const char* path)
{
    if (!path || !path[0] || !strcmp(path, "/")) { errno = EINVAL; return -1; }
    struct stat st;
    if (lstat(path, &st)) {
        if (errno == ENOENT) return 0;
        if (stat(path, &st)) return errno == ENOENT ? 0 : inst_rm_fail("stat", path);
    }
    if (!S_ISDIR(st.st_mode)) return unlink(path) ? inst_rm_fail("unlink", path) : 0;
    DIR* d = opendir(path);
    if (!d) return inst_rm_fail("opendir", path);
    struct dirent* de; int r = 0;
    while ((de = readdir(d))) {
        if (!strcmp(de->d_name, ".") || !strcmp(de->d_name, "..")) continue;
        char p[1024]; snprintf(p, sizeof p, "%s/%s", path, de->d_name);
        r |= inst_rmtree(p);
    }
    closedir(d);
    if (rmdir(path)) return inst_rm_fail("rmdir", path);
    return r;
}
static uint8_t* s_inst_buf;
enum { INST_BUF = 4 << 20 };
static int inst_fail(const char* fmt, const char* a)
{
    snprintf(s_inst.err, sizeof s_inst.err, fmt, a);
    s_inst.state = 3;
    return -1;
}
/* overlap (2026-11-17): a reader thread fills one buffer while this thread writes the other, so the source (a
 * disc drive above all: ~26 MB/s, idle during every write before) never waits for the destination. Only calls the
 * launcher and the payload already import (pthread_create / pthread_detach, usleep): no new import. */
static uint8_t* s_inst_buf2;
typedef struct {
    inst_src_t* s; const inst_ent_t* e;
    uint8_t* buf[2]; size_t len[2];
    int full[2];                    /* 1: buf[i] holds data for the writer (set by the reader, cleared by the writer) */
    int stop, err, quit;            /* writer -> reader: stop; reader -> writer: a read failed / the thread has ended */
} inst_rd_t;
static void* inst_reader(void* arg)
{
    inst_rd_t* R = arg;
    uint64_t off = 0;
    for (int k = 0; off < R->e->size && !__atomic_load_n(&R->stop, __ATOMIC_ACQUIRE); k ^= 1) {
        while (__atomic_load_n(&R->full[k], __ATOMIC_ACQUIRE) && !__atomic_load_n(&R->stop, __ATOMIC_ACQUIRE)) usleep(200);
        if (__atomic_load_n(&R->stop, __ATOMIC_ACQUIRE)) break;
        const size_t m = (size_t)(R->e->size - off < INST_BUF ? R->e->size - off : INST_BUF);
        if (inst_read(R->s, R->e, off, R->buf[k], m)) { __atomic_store_n(&R->err, 1, __ATOMIC_RELEASE); break; }
        R->len[k] = m;
        __atomic_store_n(&R->full[k], 1, __ATOMIC_RELEASE);
        off += m;
    }
    __atomic_store_n(&R->quit, 1, __ATOMIC_RELEASE);
    return NULL;
}
static int inst_copy_ent(inst_src_t* s, const inst_ent_t* e, const char* dst)
{
    if (inst_mkdirs(dst)) return inst_fail("Couldn't make the folder for %s", dst);
    const int fd = open(dst, O_WRONLY | O_CREAT | O_TRUNC, 0666);
    if (fd < 0) return inst_fail("Couldn't create %s", dst);
    if (!s_inst_buf2) s_inst_buf2 = malloc(INST_BUF);
    inst_rd_t R; memset(&R, 0, sizeof R);
    R.s = s; R.e = e; R.buf[0] = s_inst_buf; R.buf[1] = s_inst_buf2;
    pthread_t th;
    const int threaded = e->size > INST_BUF && s_inst_buf2 && !pthread_create(&th, NULL, inst_reader, &R);
    if (threaded) pthread_detach(th);
    int rc = 0;
    if (threaded) {
        for (int k = 0; ; k ^= 1) {
            while (!__atomic_load_n(&R.full[k], __ATOMIC_ACQUIRE) && !__atomic_load_n(&R.quit, __ATOMIC_ACQUIRE)) usleep(200);
            if (!__atomic_load_n(&R.full[k], __ATOMIC_ACQUIRE)) {   /* the reader ended: done, or a read failed */
                if (__atomic_load_n(&R.err, __ATOMIC_ACQUIRE)) rc = inst_fail("Couldn't read %s from the source", e->rel);
                break;
            }
            const size_t m = R.len[k];
            for (size_t w = 0; w < m && !rc;) {
                const ssize_t r = write(fd, R.buf[k] + w, m - w);
                if (r <= 0) rc = inst_fail(errno == ENOSPC ? "Not enough free space (writing %s)" : "Couldn't write %s", dst);
                else w += (size_t)r;
            }
            if (rc) break;
            s_inst.done += m;
            __atomic_store_n(&R.full[k], 0, __ATOMIC_RELEASE);
        }
        __atomic_store_n(&R.stop, 1, __ATOMIC_RELEASE);
        while (!__atomic_load_n(&R.quit, __ATOMIC_ACQUIRE)) usleep(200);   /* R lives on this stack: let the reader end */
        close(fd);
        return rc;
    }
    for (uint64_t off = 0; off < e->size;) {   /* small files (one buffer), or no second buffer / thread */
        const size_t m = (size_t)(e->size - off < INST_BUF ? e->size - off : INST_BUF);
        if (inst_read(s, e, off, s_inst_buf, m)) { close(fd); return inst_fail("Couldn't read %s from the source", e->rel); }
        for (size_t w = 0; w < m;) {
            const ssize_t r = write(fd, s_inst_buf + w, m - w);
            if (r <= 0) { close(fd); return inst_fail(errno == ENOSPC ? "Not enough free space (writing %s)" : "Couldn't write %s", dst); }
            w += (size_t)r;
        }
        off += m; s_inst.done += m;
    }
    close(fd);
    return 0;
}
static int inst_copy_file(const char* src, const char* dst)   /* inside the new install (copies of copies) */
{
    inst_src_t f = { .kind = SRC_DIR, .fd = -1 };
    struct stat st;
    if (stat(src, &st)) return inst_fail("Missing %s", src);
    const char* sl = strrchr(src, '/');
    snprintf(f.path, sizeof f.path, "%.*s", (int)(sl - src), src);
    inst_ent_t e = { .rel = (char*)(sl + 1), .size = (uint64_t)st.st_size };
    return inst_copy_ent(&f, &e, dst);
}
static int inst_write(const char* dst, const void* d, size_t n)
{
    if (inst_mkdirs(dst)) return inst_fail("Couldn't make the folder for %s", dst);
    FILE* f = fopen(dst, "wb");
    if (!f || fwrite(d, 1, n, f) != n) { if (f) fclose(f); return inst_fail("Couldn't write %s", dst); }
    fclose(f);
    return 0;
}
/* ---------------------------------------------------------------- EBOOT.BIN (SELF) -> EBOOT.elf
 * The player's own EBOOT.BIN, decrypted the way RPCS3 does it (its unself.cpp / key_vault.cpp; the prototype is
 * work/eboot_decrypt/unself.py). Keys: the public ones from RPCS3's key_vault, only those these three EBOOTs use. */
typedef struct { int npdrm; uint16_t rev; uint8_t erk[32], riv[16]; } inst_selfkey_t;
static const inst_selfkey_t kInstSelfKeys[] = {
    { 0, 0x0001, { 0x79,0x48,0x18,0x39,0xc4,0x06,0xa6,0x32,0xbd,0xb4,0xac,0x09,0x3d,0x73,0xd9,0x9a,0xe1,0x58,0x7f,0x24,0xce,0x7e,0x69,0x19,0x2c,0x1c,0xd0,0x01,0x02,0x74,0xa8,0xab },
                 { 0x6f,0x0f,0x25,0xe1,0xc8,0xc4,0xb7,0xae,0x70,0xdf,0x96,0x8b,0x04,0x52,0x1d,0xda } },   /* APP 0x0001: inFAMOUS disc */
    { 0, 0x001C, { 0xcf,0xf0,0x25,0x37,0x5b,0xa0,0x07,0x92,0x26,0xbe,0x01,0xf4,0xa3,0x1f,0x34,0x6d,0x79,0xf6,0x2c,0xfb,0x64,0x3c,0xa9,0x10,0xe1,0x6c,0xf6,0x0b,0xd9,0x09,0x27,0x52 },
                 { 0xfd,0x40,0x66,0x4e,0x2e,0xbb,0xa0,0x1b,0xf3,0x59,0xb0,0xdc,0xdf,0x54,0x3d,0xa4 } },   /* APP 0x001C: inFAMOUS USA disc v02.00 */
    { 1, 0x000A, { 0x03,0xc2,0x1a,0xd7,0x8f,0xbb,0x6a,0x3d,0x42,0x5e,0x9a,0xab,0x12,0x98,0xf9,0xfd,0x70,0xe2,0x9f,0xd4,0xe6,0xe3,0xa3,0xc1,0x51,0x20,0x5d,0xa5,0x0c,0x41,0x3d,0xe4 },
                 { 0x0a,0x99,0xd4,0xd4,0xf8,0x30,0x1a,0x88,0x05,0x2d,0x71,0x4a,0xd2,0xfb,0x56,0x5e } },   /* NPDRM 0x000A: Festival of Blood */
    { 1, 0x0010, { 0x4b,0x3c,0xd1,0x0f,0x6a,0x6a,0xa7,0xd9,0x9f,0x9b,0x3a,0x66,0x0c,0x35,0xad,0xe0,0x8e,0xf0,0x1c,0x2c,0x33,0x6b,0x9e,0x46,0xd1,0xbb,0x56,0x78,0xb4,0x26,0x1a,0x61 },
                 { 0xc0,0xf2,0xab,0x86,0xe6,0xe0,0x45,0x75,0x52,0xdb,0x50,0xd7,0x21,0x93,0x71,0xc5 } },   /* NPDRM 0x0010: inFAMOUS 2 update 1.04 */
};
static const uint8_t kNpKlicKey[16]  = { 0xf2,0xfb,0xca,0x7a,0x75,0xb0,0x4e,0xdc,0x13,0x90,0x63,0x8c,0xcd,0xfd,0xd1,0xee };   /* NP_KLIC_KEY */
static const uint8_t kNpKlicFree[16] = { 0x72,0xf9,0x90,0x78,0x8f,0x9c,0xff,0x74,0x57,0x25,0xf0,0x8e,0x4c,0x12,0x83,0x87 };   /* NP_KLIC_FREE */
static const uint8_t kRapKey[16]     = { 0x86,0x9f,0x77,0x45,0xc1,0x3f,0xd8,0x90,0xcc,0xf2,0x91,0x88,0xe3,0xcc,0x3e,0xdf };   /* RAP_KEY */
static const uint8_t kRapPbox[16] = { 0x0C,0x03,0x06,0x04,0x01,0x0B,0x0F,0x08,0x02,0x07,0x00,0x05,0x0A,0x0E,0x0D,0x09 };
static const uint8_t kRapE1[16] = { 0xA9,0x3E,0x1F,0xD6,0x7C,0x55,0xA3,0x29,0xB7,0x5F,0xDD,0xA6,0x2A,0x95,0xC7,0xA5 };
static const uint8_t kRapE2[16] = { 0x67,0xD4,0x5D,0xA3,0x29,0x6D,0x00,0x6A,0x4E,0x7C,0x53,0x7B,0xF5,0x53,0x8C,0x74 };
/* sha256 of the EBOOT.elf each game's build was made from (the tested editions: inFAMOUS EU disc, inFAMOUS 2 1.04, FoB). */
static const uint8_t kInstEbootSha[INST_NGAMES][32] = {
    { 0x09,0x5d,0x85,0x14,0x32,0xf3,0xb5,0x51,0x79,0xcd,0x72,0x5b,0x46,0x83,0x8f,0xfe,0xdb,0x3e,0x5e,0xb9,0xf7,0x38,0x89,0xe5,0x2b,0x6f,0x11,0xf3,0xd3,0xf4,0x94,0xfd },
    { 0x3b,0xfe,0x08,0xdf,0x4e,0x2e,0xd1,0x20,0x1a,0x83,0xbe,0x3d,0x38,0xf1,0x3a,0x66,0xe9,0x00,0x15,0x3d,0xd4,0x07,0x1f,0x25,0xa3,0x5c,0x3c,0x95,0xa1,0x71,0x72,0x98 },
    { 0x55,0xa5,0x80,0x11,0xc8,0x87,0xca,0x19,0xe9,0x56,0x67,0xe6,0xd4,0x1f,0xcb,0xf7,0x53,0x03,0x90,0x17,0x75,0xf7,0x6b,0x58,0x18,0xc3,0x7b,0x6a,0x5c,0x65,0x5d,0x51 } };

static uint16_t be16(const uint8_t* p) { return (uint16_t)(p[0] << 8 | p[1]); }
/* The USA disc (BCUS98119 v01.00 and v02.00: the same ELF) -> the Europe EBOOT.elf above: a UDP1 patch, applied in memory. */
static const uint8_t kIf1UsaElfSha[32] = { 0x4f,0x2d,0xb3,0xfb,0x7c,0x76,0xfb,0xb4,0xf8,0x0c,0xbc,0x84,0x45,0xcf,0x0e,0xa1,0x57,0x0a,0x66,0x49,0x96,0xa7,0x78,0x7e,0x69,0x0e,0xfc,0xc1,0xa3,0x9b,0xef,0xb4 };
#include "if1_usa_eboot.inc"
/* UDP1 (big-endian; work/agent_delta1/udelta_dec.c): "UDP1", 'F' u16 n name u16 n src u64 size u32 crc32 sha256[32],
 * records 'C' u64 src_off u32 len | 'D' u32 len bytes, 'E', 'Z'. One file. *out = the result (malloc'd), checked against
 * its size, CRC32 and sha256; returns NULL, or why not. */
static const char* inst_udp1(const uint8_t* src, size_t srcn, const uint8_t* p, size_t pn, uint8_t** out, size_t* outn)
{
    *out = NULL; *outn = 0;
    size_t i = 4;
#define UDP_NEED(k) do { if ((k) > pn - i) { free(o); return "a damaged patch"; } } while (0)
    uint8_t* o = NULL;
    if (pn < 5 || memcmp(p, "UDP1", 4) || p[i++] != 'F') return "a damaged patch";
    for (int k = 0; k < 2; k++) { UDP_NEED(2); const size_t l = be16(p + i); UDP_NEED(2 + l); i += 2 + l; }   /* name, source name */
    UDP_NEED(8 + 4 + 32);
    const uint64_t size = be64(p + i); const uint32_t crc_want = be32(p + i + 8); const uint8_t* sha_want = p + i + 12;
    i += 8 + 4 + 32;
    if (size > (256u << 20)) return "a damaged patch";
    o = malloc((size_t)size ? (size_t)size : 1);
    if (!o) return "out of memory";
    uint64_t w = 0;
    for (;;) {
        UDP_NEED(1);
        const uint8_t t = p[i++];
        if (t == 'E') break;
        if (t == 'C') {
            UDP_NEED(12);
            const uint64_t off = be64(p + i); const uint32_t len = be32(p + i + 8); i += 12;
            if (off > srcn || len > srcn - off || len > size - w) { free(o); return "a patch that doesn't fit this EBOOT"; }
            memcpy(o + w, src + off, len); w += len;
        } else if (t == 'D') {
            UDP_NEED(4);
            const uint32_t len = be32(p + i); i += 4;
            UDP_NEED(len);
            if (len > size - w) { free(o); return "a damaged patch"; }
            memcpy(o + w, p + i, len); i += len; w += len;
        } else { free(o); return "a damaged patch"; }
    }
    UDP_NEED(1);
    if (p[i] != 'Z' || w != size) { free(o); return "a damaged patch"; }
#undef UDP_NEED
    uint32_t c = 0xFFFFFFFFu;
    for (uint64_t j = 0; j < size; j++) { c ^= o[j]; for (int b = 0; b < 8; b++) c = c & 1 ? 0xEDB88320u ^ (c >> 1) : c >> 1; }
    uint8_t sha[32]; inst_sha256(o, (size_t)size, sha);
    if (~c != crc_want || memcmp(sha, sha_want, 32)) { free(o); return "a patch result with the wrong checksum"; }
    *out = o; *outn = (size_t)size;
    return NULL;
}

static void inst_rap_to_rif(const uint8_t rap[16], uint8_t key[16])   /* RPCS3 key_vault.cpp rap_to_rif */
{
    inst_aesd_t a; static const uint8_t z[16];
    inst_aesd_key128(&a, kRapKey);
    memcpy(key, rap, 16); inst_aes_cbc_dec(&a, z, key, 16);
    for (int round = 0; round < 5; round++) {
        for (int i = 0; i < 16; i++) key[kRapPbox[i]] ^= kRapE1[kRapPbox[i]];
        for (int i = 15; i > 0; i--) key[kRapPbox[i]] ^= key[kRapPbox[i - 1]];
        int o = 0;
        for (int i = 0; i < 16; i++) {
            const int p = kRapPbox[i];
            const uint8_t kc = (uint8_t)(key[p] - o), ec2 = kRapE2[p];
            if (o != 1 || kc != 0xFF) o = kc < ec2;
            key[p] = (uint8_t)(kc - ec2);
        }
    }
}
/* d = the SELF (n bytes), rap = the .rap's 16 bytes (NULL if none). On success *out = the ELF (malloc'd), returns NULL;
 * else returns why not. */
static const char* inst_unself(const uint8_t* d, size_t n, const uint8_t* rap, uint8_t** out, size_t* outn)
{
    *out = NULL; *outn = 0;
    if (n < 0x70 || memcmp(d, "SCE\0", 4)) return "not a PS3 executable (SELF)";
    const uint16_t rev = be16(d + 8);
    const uint64_t meta = 0x20 + (uint64_t)be32(d + 12), hlen = be64(d + 16);
    const uint64_t app = be64(d + 0x28), elf = be64(d + 0x30), phoff = be64(d + 0x38), shoff_s = be64(d + 0x40);
    const uint64_t ctrl = be64(d + 0x58), ctrln = be64(d + 0x60);
    if (app + 16 > n || elf + 0x40 > n || meta + 0x40 > hlen || hlen > n || ctrl + ctrln > n) return "a damaged EBOOT.BIN";
    const uint32_t ptype = be32(d + app + 12);
    const uint8_t* eh = d + elf;
    const uint64_t e_shoff = be64(eh + 0x28);
    const unsigned phnum = be16(eh + 0x38), shnum = be16(eh + 0x3C);
    if (phoff + phnum * 0x38ull > n || shoff_s + shnum * 0x40ull > n) return "a damaged EBOOT.BIN";
    const inst_selfkey_t* sk = NULL;
    for (unsigned i = 0; i < sizeof kInstSelfKeys / sizeof kInstSelfKeys[0]; i++)
        if (kInstSelfKeys[i].rev == rev && kInstSelfKeys[i].npdrm == (ptype == 8) && (ptype == 4 || ptype == 8)) sk = &kInstSelfKeys[i];
    if (!sk) return "an EBOOT.BIN of another version (its keys aren't known)";
    uint8_t info[64]; memcpy(info, d + meta, 64);
    inst_aesd_t a;
    for (uint64_t i = ctrl; i + 0x40 <= ctrl + ctrln; i++) {
        if (memcmp(d + i, "NPD\0", 4)) continue;
        uint8_t klic[16]; static const uint8_t z[16];
        if (be32(d + i + 8) == 3) memcpy(klic, kNpKlicFree, 16);   /* licence type 3: free */
        else if (rap) inst_rap_to_rif(rap, klic);
        else return "no licence (.rap) file";
        inst_aesd_key128(&a, kNpKlicKey); inst_aes_cbc_dec(&a, z, klic, 16);
        inst_aesd_key128(&a, klic); inst_aes_cbc_dec(&a, z, info, 64);
        break;
    }
    inst_aesd_key256(&a, sk->erk); inst_aes_cbc_dec(&a, sk->riv, info, 64);
    static const uint8_t z16[16];
    if (memcmp(info + 16, z16, 16) || memcmp(info + 48, z16, 16)) return rap ? "the .rap licence doesn't fit this EBOOT.BIN" : "the EBOOT.BIN didn't decrypt";
    const size_t hn = (size_t)(hlen - meta - 0x40);
    uint8_t* h = malloc(hn ? hn : 1);
    if (!h) return "out of memory";
    memcpy(h, d + meta + 0x40, hn);
    inst_aes_t ca; inst_aes_key(&ca, info); inst_aes_ctr(&ca, info + 32, 0, h, hn);
    const uint32_t nsec = hn >= 0x20 ? be32(h + 0x0C) : 0, nkeys = hn >= 0x20 ? be32(h + 0x10) : 0;
    if (!nsec || 0x20 + nsec * 0x30ull + nkeys * 16ull > hn) { free(h); return "a damaged EBOOT.BIN"; }
    const uint8_t* keys = h + 0x20 + nsec * 0x30;
    /* the ELF: header, phdrs at 0x40, each segment at its p_offset, shdrs at e_shoff; the gaps zero */
    uint64_t size = 0x40 + phnum * 0x38ull;
    if (shnum && e_shoff + shnum * 0x40ull > size) size = e_shoff + shnum * 0x40ull;
    for (uint32_t j = 0; j < nsec; j++) {
        const uint8_t* s = h + 0x20 + j * 0x30;
        if (be32(s + 0x10) != 2) continue;
        const uint64_t off = be64(s), sz = be64(s + 8); const uint32_t pi = be32(s + 0x14);
        if (be32(s + 0x2C) == 2) { free(h); return "a compressed EBOOT.BIN (not supported)"; }
        if (pi >= phnum || off + sz > n || be32(s + 0x24) >= nkeys || be32(s + 0x28) >= nkeys) { free(h); return "a damaged EBOOT.BIN"; }
        const uint64_t po = be64(d + phoff + pi * 0x38 + 8);
        if (po + sz > size) size = po + sz;
    }
    if (size > (256u << 20)) { free(h); return "a damaged EBOOT.BIN"; }
    uint8_t* o = calloc(1, (size_t)size);
    if (!o) { free(h); return "out of memory"; }
    memcpy(o, eh, 0x40);
    memcpy(o + 0x40, d + phoff, phnum * 0x38u);
    for (uint32_t j = 0; j < nsec; j++) {
        const uint8_t* s = h + 0x20 + j * 0x30;
        if (be32(s + 0x10) != 2) continue;
        const uint64_t off = be64(s), sz = be64(s + 8);
        uint8_t* dst = o + be64(d + phoff + be32(s + 0x14) * 0x38 + 8);
        memcpy(dst, d + off, (size_t)sz);
        if (be32(s + 0x20) == 3) {
            inst_aes_t sa; inst_aes_key(&sa, keys + be32(s + 0x24) * 16);
            inst_aes_ctr(&sa, keys + be32(s + 0x28) * 16, 0, dst, (size_t)sz);
        }
    }
    if (shnum) memcpy(o + e_shoff, d + shoff_s, shnum * 0x40u);
    free(h);
    *out = o; *outn = (size_t)size;
    return NULL;
}
/* Where game g's EBOOT.BIN comes from: inFAMOUS 2's 1.04 update, else the base (disc / package). */
static inst_src_t* inst_eboot_src(const inst_job_t* J, int* ent)
{
    inst_src_t* s = J->src[0];
    if (J->game == INST_IF2) {
        s = NULL;
        for (int i = 0; i < J->nsrc; i++) {
            const inst_known_t* q = &kInstKnown[J->src[i]->known];
            if (q->update && !strcmp(q->ver, "01.04")) s = J->src[i];
        }
    }
    *ent = s ? inst_find(s, "USRDIR/EBOOT.BIN") : -1;
    return *ent >= 0 ? s : NULL;
}
/* Decrypt game g's EBOOT.BIN (read through its source) into part/USRDIR/EBOOT.elf, checked against the known hash. */
static int inst_eboot(const char* part)
{
    inst_job_t* J = &s_inst;
    int k; inst_src_t* s = inst_eboot_src(J, &k);
    if (!s) return inst_fail("No USRDIR/EBOOT.BIN in %s", J->game == INST_IF2 ? "the 1.04 update" : J->src[0]->name);
    const inst_ent_t* e = &s->e[k];
    snprintf(J->cur, sizeof J->cur, "USRDIR/EBOOT.BIN (decrypting)");
    uint8_t rap[16]; int have_rap = 0;
    if (J->rap[0]) {
        const int fd = open(J->rap, O_RDONLY);
        if (fd >= 0) { have_rap = !inst_pread(fd, rap, 16, 0); close(fd); }
        if (!have_rap) return inst_fail("Couldn't read the licence file %s", J->rap);
    }
    if (e->size > (256u << 20)) return inst_fail("%s: EBOOT.BIN is too big", s->name);
    uint8_t* d = malloc((size_t)e->size ? (size_t)e->size : 1);
    if (!d) return inst_fail("Out of memory%s", "");
    if (inst_read(s, e, 0, d, (size_t)e->size)) { free(d); return inst_fail("Couldn't read USRDIR/EBOOT.BIN from %s", s->name); }
    uint8_t* elf; size_t n;
    const char* why = inst_unself(d, (size_t)e->size, have_rap ? rap : NULL, &elf, &n);
    free(d);
    if (why) { char m[256]; snprintf(m, sizeof m, "%s: %s", s->name, why); return inst_fail("Can't use the EBOOT.BIN of %s", m); }
    uint8_t sha[32]; inst_sha256(elf, n, sha);
    if (inst_if1_usa(J) && !memcmp(sha, kIf1UsaElfSha, 32)) {   /* the USA executable -> the Europe one the build needs */
        uint8_t* eu; size_t eun;
        why = inst_udp1(elf, n, kIf1UsaEbootPatch, sizeof kIf1UsaEbootPatch, &eu, &eun);
        free(elf);
        if (why) return inst_fail("Couldn't turn the USA EBOOT.BIN of %s into the Europe one", s->name);   /* (why: out of memory, or a damaged build) */
        elf = eu; n = eun;
        inst_sha256(elf, n, sha);
    }
    if (memcmp(sha, kInstEbootSha[J->game], 32)) {
        free(elf);
        return inst_fail(J->game == INST_FOB ? "The EBOOT.BIN of %s isn't the expected one (another edition, or the .rap of another game)"
                                             : "The EBOOT.BIN of %s isn't the expected one (another edition or version)", s->name);
    }
    char p[700]; snprintf(p, sizeof p, "%s/USRDIR/EBOOT.elf", part);
    const int r = inst_write(p, elf, n);
    free(elf);
    if (!r) J->done += e->size;
    return r;
}
static int inst_skip(const char* rel)
{
    return !strcmp(rel, "USRDIR/EBOOT.BIN") || strstr(rel, "Zone.Identifier") != NULL;
}
static void* inst_main(void* arg)
{
    (void)arg;
    inst_job_t* J = &s_inst;
    const int g = J->game;
    char root[512], part[600], fin[600], p[1024], q[1024];
    snprintf(root, sizeof root, "%s/%s/game", J->app, kInstDir[g]);
    snprintf(part, sizeof part, "%s/PS3_GAME.part", root);
    snprintf(fin, sizeof fin, "%s/PS3_GAME", root);
    if (!s_inst_buf) s_inst_buf = malloc(INST_BUF);
    if (!s_inst_buf) { inst_fail("Out of memory%s", ""); return NULL; }
    /* The files: each source's, later ones over earlier ones (the updates over the disc). */
    int total_n = 0;
    for (int i = 0; i < J->nsrc; i++) total_n += J->src[i]->n;
    struct pick { inst_src_t* s; int i; } * pk = calloc((size_t)total_n + 1, sizeof *pk);
    int np = 0;
    for (int i = 0; i < J->nsrc; i++)
        for (int k = 0; k < J->src[i]->n; k++) {
            const char* rel = J->src[i]->e[k].rel;
            if (inst_skip(rel)) continue;
            if (inst_if1_usa(J) && (!strncmp(rel, "LICDIR/", 7) || !strncmp(rel, "PKGDIR/", 7))) continue;   /* USA v02.00's disc licence + manual package: not in the Europe layout */
            int j = 0;
            for (; j < np; j++) if (!strcmp(pk[j].s->e[pk[j].i].rel, rel)) break;
            pk[j].s = J->src[i]; pk[j].i = k;
            if (j == np) np++;
        }
    uint64_t total = 0;
    for (int j = 0; j < np; j++) total += pk[j].s->e[pk[j].i].size;
    { int k; const inst_src_t* es = inst_eboot_src(J, &k); if (es) total += es->e[k].size; }   /* EBOOT.BIN -> EBOOT.elf */
    const char* const* inst_list = g == INST_IF2 ? kIf2InstallFiles : g == INST_FOB ? kFobInstallFiles : kIf1InstallFiles;
    if (inst_list)
        for (int k = 0; inst_list[k]; k++) {
            char rel[300]; snprintf(rel, sizeof rel, "USRDIR/%s", inst_list[k]);
            for (int j = 0; j < np; j++) if (!strcmp(pk[j].s->e[pk[j].i].rel, rel)) total += pk[j].s->e[pk[j].i].size;
        }
    J->total = total; J->done = 0;
    inst_rmtree(part);   /* (a run that stopped half way) */
    if (inst_eboot(part)) { free(pk); return NULL; }   /* first: a wrong edition or .rap fails before the long copy */
    for (int j = 0; j < np; j++) {
        const inst_ent_t* e = &pk[j].s->e[pk[j].i];
        snprintf(J->cur, sizeof J->cur, "%s", e->rel);
        snprintf(p, sizeof p, "%s/%s", part, e->rel);
        if (inst_copy_ent(pk[j].s, e, p)) { free(pk); return NULL; }
    }
    free(pk);
    if (inst_if1_usa(J)) {   /* the title ID the build, its BCES00220 first-boot folder and the saves use; the rest stays the disc's */
        snprintf(p, sizeof p, "%s/PARAM.SFO", part);
        FILE* f = fopen(p, "rb");
        uint8_t sfo[4096]; size_t n = f ? fread(sfo, 1, sizeof sfo, f) : 0;
        if (f) fclose(f);
        if (!n || inst_sfo_set(sfo, n, "TITLE_ID", "BCES00220") || inst_write(p, sfo, n)) {
            if (s_inst.state != 3) inst_fail("Couldn't update %s", p);
            return NULL;
        }
    }
    /* inFAMOUS 2: PARAM.SFO as the PSN release has it (the build's NPUA80638 1.03), and its game-data
     * folder: PARAM.SFO + the updates' archives. FoB: PARAM.SFO + dlc. */
    const char* tid2 = g == INST_IF2 ? "NPUA80638" : g == INST_FOB ? "NPUA80657" : NULL;
    if (g == INST_IF2) {
        snprintf(p, sizeof p, "%s/PARAM.SFO", part);
        FILE* f = fopen(p, "rb");
        uint8_t sfo[4096]; size_t n = f ? fread(sfo, 1, sizeof sfo, f) : 0;
        if (f) fclose(f);
        if (!n || inst_sfo_set(sfo, n, "TITLE_ID", "NPUA80638") || inst_sfo_set(sfo, n, "APP_VER", "01.03")
            || inst_sfo_set(sfo, n, "CATEGORY", "HG") || inst_write(p, sfo, n)) {
            if (s_inst.state != 3) inst_fail("Couldn't update %s", p);
            return NULL;
        }
    }
    if (tid2) {
        snprintf(q, sizeof q, "%s/dev_hdd0/game/%s", root, tid2);
        inst_rmtree(q);
        snprintf(p, sizeof p, "%s/PARAM.SFO", part);
        char d[1100]; snprintf(d, sizeof d, "%s/PARAM.SFO", q);
        if (inst_copy_file(p, d)) return NULL;
        const char* sub = g == INST_IF2 ? "USRDIR/patch" : "USRDIR/dlc";
        for (int i = 0; i < J->nsrc; i++)
            for (int k = 0; k < J->src[i]->n; k++) {
                const char* rel = J->src[i]->e[k].rel;
                if (strncmp(rel, sub, strlen(sub)) || inst_skip(rel)) continue;
                snprintf(p, sizeof p, "%s/%s", part, rel);
                snprintf(d, sizeof d, "%s/%s", q, rel);
                const uint64_t before = J->done;
                if (inst_copy_file(p, d)) return NULL;
                J->done = before;
            }
    }
    /* The <X>_INSTALL copy + its marker, so the game never starts that copy itself. */
    if (inst_list) {
        snprintf(q, sizeof q, "%s/dev_hdd0/game/%s/USRDIR", root, g == INST_IF2 ? "BCUS98125_INSTALL" : g == INST_FOB ? "NPUA80657_INSTALL" : "BCES00220");
        for (int k = 0; inst_list[k]; k++) {
            snprintf(J->cur, sizeof J->cur, "%s", inst_list[k]);
            snprintf(p, sizeof p, "%s/USRDIR/%s", part, inst_list[k]);
            char d[1200]; snprintf(d, sizeof d, "%s/%s", q, inst_list[k]);
            if (inst_copy_file(p, d)) return NULL;
        }
        if (g == INST_IF1) for (int k = 0; kIf1InstallDirs[k]; k++) { char d[1200]; snprintf(d, sizeof d, "%s/%s/", q, kIf1InstallDirs[k]); inst_mkdirs(d); }
        char d[1200]; snprintf(d, sizeof d, "%s/ne.bv", q);
        if (g == INST_IF2 ? inst_write(d, kIf2NeBv, sizeof kIf2NeBv) : g == INST_FOB ? inst_write(d, kFobNeBv, sizeof kFobNeBv)
                          : inst_write(d, kIf1NeBv, sizeof kIf1NeBv)) return NULL;
    }
    /* The saves' folder, then the switch: PS3_GAME.part -> PS3_GAME. */
    snprintf(p, sizeof p, "%s/dev_hdd0/home/00000001/savedata/", root); inst_mkdirs(p);
    if (rename(part, fin)) { inst_fail("Couldn't finish (rename to %s)", fin); return NULL; }
    snprintf(p, sizeof p, "%s/%s/installed.txt", J->app, kInstDir[g]);
    FILE* f = fopen(p, "w");
    if (f) {
        for (int i = 0; i < J->nsrc; i++) fprintf(f, "%s %s %s %s\n", J->src[i]->tid, J->src[i]->ver, J->src[i]->cat, J->src[i]->name);
        fclose(f);
    }
    snprintf(J->cur, sizeof J->cur, "done");
    J->state = 2;
    return NULL;
}
/* Repair (2026-11-09): only the first-boot data (the <X>_INSTALL / BCES00220 folder + ne.bv), copied from the
 * already installed PS3_GAME, for a game installed before the installer wrote it (inFAMOUS 1 before test 4). */
static const char* inst_cache_dir(int g) { return g == INST_IF2 ? "BCUS98125_INSTALL" : g == INST_FOB ? "NPUA80657_INSTALL" : "BCES00220"; }
static int inst_needs_eboot(const char* app, int g)   /* installed, but without USRDIR/EBOOT.elf */
{
    char p[600]; struct stat st;
    snprintf(p, sizeof p, "%s/%s/game/PS3_GAME/PARAM.SFO", app, kInstDir[g]); if (stat(p, &st)) return 0;
    snprintf(p, sizeof p, "%s/%s/game/PS3_GAME/USRDIR/EBOOT.elf", app, kInstDir[g]);
    return stat(p, &st) != 0;
}
static int inst_needs_cache(const char* app, int g)
{
    char p[600]; struct stat st;
    snprintf(p, sizeof p, "%s/%s/game/PS3_GAME/PARAM.SFO", app, kInstDir[g]); if (stat(p, &st)) return 0;   /* not installed */
    snprintf(p, sizeof p, "%s/%s/game/PS3_GAME/USRDIR/EBOOT.elf", app, kInstDir[g]);
    if (stat(p, &st)) return 1;   /* installed before the installer decrypted the EBOOT (builds had it built in) */
    snprintf(p, sizeof p, "%s/%s/game/dev_hdd0/game/%s/USRDIR/ne.bv", app, kInstDir[g], inst_cache_dir(g));
    return stat(p, &st) != 0;
}
static void* inst_cache_main(void* arg)
{
    (void)arg;
    inst_job_t* J = &s_inst;
    const int g = J->game;
    const char* const* list = g == INST_IF2 ? kIf2InstallFiles : g == INST_FOB ? kFobInstallFiles : kIf1InstallFiles;
    char src[600], q[600], p[1200], d[1200]; struct stat st;
    snprintf(src, sizeof src, "%s/%s/game/PS3_GAME/USRDIR", J->app, kInstDir[g]);
    snprintf(q, sizeof q, "%s/%s/game/dev_hdd0/game/%s/USRDIR", J->app, kInstDir[g], inst_cache_dir(g));
    if (!s_inst_buf) s_inst_buf = malloc(INST_BUF);
    if (!s_inst_buf) { inst_fail("Out of memory%s", ""); return NULL; }
    {   /* the EBOOT.elf first (a game installed while the builds carried it) */
        char gd[600]; snprintf(gd, sizeof gd, "%s/%s/game/PS3_GAME", J->app, kInstDir[g]);
        snprintf(p, sizeof p, "%s/USRDIR/EBOOT.elf", gd);
        if (stat(p, &st)) { int k; const inst_src_t* es = inst_eboot_src(J, &k); J->total = es ? es->e[k].size : 0; if (inst_eboot(gd)) return NULL; }
    }
    snprintf(p, sizeof p, "%s/ne.bv", q);
    if (!stat(p, &st)) { snprintf(J->cur, sizeof J->cur, "done"); J->state = 2; return NULL; }
    uint64_t total = 0;
    for (int k = 0; list[k]; k++) { snprintf(p, sizeof p, "%s/%s", src, list[k]); if (!stat(p, &st)) total += (uint64_t)st.st_size; }
    J->total = total; J->done = 0;
    for (int k = 0; list[k]; k++) {
        snprintf(J->cur, sizeof J->cur, "%s", list[k]);
        snprintf(p, sizeof p, "%s/%s", src, list[k]); snprintf(d, sizeof d, "%s/%s", q, list[k]);
        if (inst_copy_file(p, d)) return NULL;
    }
    if (g == INST_IF1) for (int k = 0; kIf1InstallDirs[k]; k++) { snprintf(d, sizeof d, "%s/%s/", q, kIf1InstallDirs[k]); inst_mkdirs(d); }
    snprintf(d, sizeof d, "%s/ne.bv", q);
    if (g == INST_IF2 ? inst_write(d, kIf2NeBv, sizeof kIf2NeBv) : g == INST_FOB ? inst_write(d, kFobNeBv, sizeof kFobNeBv)
                      : inst_write(d, kIf1NeBv, sizeof kIf1NeBv)) return NULL;
    snprintf(J->cur, sizeof J->cur, "done");
    J->state = 2;
    return NULL;
}
static int inst_start_cache(const char* app, int g)
{
    if (s_inst.state == 1) return -1;
    memset(&s_inst, 0, sizeof s_inst);
    s_inst.game = g; snprintf(s_inst.app, sizeof s_inst.app, "%s", app);
    {   /* a missing EBOOT.elf is made from the dump, as the install does */
        char p[600]; struct stat st;
        snprintf(p, sizeof p, "%s/%s/game/PS3_GAME/USRDIR/EBOOT.elf", app, kInstDir[g]);
        if (stat(p, &st)) {
            char need[300];
            s_inst.nsrc = inst_plan(g, s_inst.src, need, sizeof need);
            if (!s_inst.nsrc) { snprintf(s_inst.err, sizeof s_inst.err, "Missing %s", need); s_inst.state = 3; return -1; }
            if (g == INST_FOB) snprintf(s_inst.rap, sizeof s_inst.rap, "%s", s_inst_rap);
        }
    }
    s_inst.state = 1;
    pthread_t t;
    if (pthread_create(&t, NULL, inst_cache_main, NULL)) { s_inst.state = 3; snprintf(s_inst.err, sizeof s_inst.err, "Couldn't start"); return -1; }
    pthread_detach(t);
    return 0;
}
static int inst_start(const char* app, int g)
{
    if (s_inst.state == 1) return -1;
    memset(&s_inst, 0, sizeof s_inst);
    s_inst.game = g;
    snprintf(s_inst.app, sizeof s_inst.app, "%s", app);
    char need[300];
    s_inst.nsrc = inst_plan(g, s_inst.src, need, sizeof need);
    if (!s_inst.nsrc) { snprintf(s_inst.err, sizeof s_inst.err, "Missing %s", need); s_inst.state = 3; return -1; }
    for (int i = 0; i < s_inst.nsrc; i++)
        if (s_inst.src[i]->disc_mnt) {
            snprintf(s_inst.err, sizeof s_inst.err, "Installing from the disc needs the payload loader (port 9021: etaHEN / elfldr)");
            s_inst.state = 3; return -1;
        }
    if (g == INST_FOB) snprintf(s_inst.rap, sizeof s_inst.rap, "%s", s_inst_rap);
    s_inst.state = 1;
    pthread_t t;
    if (pthread_create(&t, NULL, inst_main, NULL)) { s_inst.state = 3; snprintf(s_inst.err, sizeof s_inst.err, "Couldn't start the install"); return -1; }
    pthread_detach(t);
    return 0;
}

#ifndef INST_PAYLOAD
/* ---------------------------------------------------------------- inFAMOUS 2's updates from PSN (a thread)
 * The four update packages from Sony's public PS3 update server (plain HTTP, as the PS3 fetches them; listed in
 * a0.ww.np.dl.playstation.net/tpl/np/BCUS98125/BCUS98125-ver.xml), into <app>/install/<name>: <name>.part first,
 * renamed when its size and SHA-1 check out. Sony's sha1 is over the file minus its last 32 bytes (those hold the
 * same SHA-1 and 12 zero bytes; checked on all four, 2026-11-12). A .part left behind resumes (Range) next time.
 * Only what the launcher already imports (socket connect send read poll fcntl setsockopt close: a new import can
 * stop the launcher loading): no getaddrinfo, so the name is resolved by a DNS query of our own over UDP. */
#include <sys/socket.h>
#include <netinet/in.h>
#include <poll.h>
#include <sys/time.h>
#include <time.h>
typedef struct { const char* ver; const char* name; uint64_t size; const char* sha1; } updl_pkg_t;
static const char kUpdlHost[] = "b0.ww.np.dl.playstation.net";
static const char kUpdlDir[] = "/tppkg/np/BCUS98125/BCUS98125_T24/53b9709ebcdaded3/";
static const updl_pkg_t kUpdlPkgs[4] = {
    { "01.01", "UP9000-BCUS98125_00-P001SHIP05231325-A0101-V0100-PE.pkg", 111695440, "917b373f1e442ac1a61648c320a6c28f0ed2cdee" },
    { "01.02", "UP9000-BCUS98125_00-P002SHIP07051444-A0102-V0100-PE.pkg", 10361440, "54aebe6a7596d9bfb65ab76db375825d55b7f5d8" },
    { "01.03", "UP9000-BCUS98125_00-P003SHIP08231456-A0103-V0100-PE.pkg", 23580256, "89036aeb39bf6d62542e7d73dc474caa2cf4f99e" },
    { "01.04", "UP9000-BCUS98125_00-P004SHIP10171526-A0104-V0100-PE.pkg", 112134048, "53279626bd9fb037ecb271420207a01cbb5b148e" },
};
/* What the UI reads (written by the thread only). */
typedef struct {
    volatile int state;             /* 0 idle, 1 running, 2 done, 3 failed */
    volatile uint64_t done, total;  /* bytes, all the wanted files */
    volatile int file, nfiles;      /* the one in progress (1-based) of how many */
    char cur[160];                  /* "update 1.03" */
    char err[256];
    char dir[512];                  /* <app>/install */
    unsigned want;                  /* bit u: kUpdlPkgs[u] */
    uint32_t ip; char ip_host[128]; /* the last name resolved (host order) */
    char via[48];                   /* who gave ip: "public resolver 1.1.1.1", "fallback address", ... (for the log) */
    uint32_t fip; int http;         /* this file: the address its last request went to (fvia: from whom), the last HTTP status */
    char fvia[48];
    uint64_t net;                   /* this file: bytes that came over the network */
} updl_job_t;
static updl_job_t s_updl;
/* The download's log lines: launcher.c points this at its logf_ (logs/launcher.log); the PC builds print to stderr.
 * Only the server, addresses, HTTP status, sizes and checks: nothing about the user or the console. */
static void (*s_updl_logf)(const char* fmt, ...);
#ifdef INST_MAIN
#define UPDL_LOG(...) (s_updl_logf ? s_updl_logf(__VA_ARGS__) : (void)fprintf(stderr, __VA_ARGS__))
#else   /* (no stderr in the launcher: it isn't imported) */
#define UPDL_LOG(...) (s_updl_logf ? s_updl_logf(__VA_ARGS__) : (void)0)
#endif
#define UPDL_IP(v) (unsigned)((v) >> 24), (unsigned)((v) >> 16 & 255), (unsigned)((v) >> 8 & 255), (unsigned)((v) & 255)
/* An address for the log: a private / loopback / link-local / CGNAT one (a DNS blocker or captive portal on the
 * user's network answering for Sony's server) is the user's own network, so only "a local address". b: 16 bytes. */
static const char* updl_ipstr(uint32_t v, char* b)
{
    const unsigned a = v >> 24;
    if (a == 0 || a == 10 || a == 127 || (v >> 16) == 0xC0A8 || (v >> 20) == 0xAC1 || (v >> 16) == 0xA9FE || (v >> 22) == 0x191)
        return "a local address";
    snprintf(b, 16, "%u.%u.%u.%u", UPDL_IP(v));
    return b;
}
static const char* s_updl_host = kUpdlHost; static const char* s_updl_path = kUpdlDir;   /* (the PC test points them elsewhere) */
enum { UPDL_TIMEOUT_MS = 20000, UPDL_BUF = 256 << 10 };

typedef struct { uint32_t h[5]; uint64_t n; uint8_t b[64]; } updl_sha1_t;
#define ROL32(x, r) ((x) << (r) | (x) >> (32 - (r)))
static void updl_sha1_blk(uint32_t h[5], const uint8_t* p)
{
    uint32_t w[80];
    for (int i = 0; i < 16; i++) w[i] = (uint32_t)p[i * 4] << 24 | p[i * 4 + 1] << 16 | p[i * 4 + 2] << 8 | p[i * 4 + 3];
    for (int i = 16; i < 80; i++) w[i] = ROL32(w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16], 1);
    uint32_t a = h[0], b = h[1], c = h[2], d = h[3], e = h[4];
    for (int i = 0; i < 80; i++) {
        const uint32_t f = i < 20 ? (b & c) | (~b & d) : i < 40 ? b ^ c ^ d : i < 60 ? (b & c) | (b & d) | (c & d) : b ^ c ^ d;
        const uint32_t k = i < 20 ? 0x5A827999 : i < 40 ? 0x6ED9EBA1 : i < 60 ? 0x8F1BBCDC : 0xCA62C1D6;
        const uint32_t t = ROL32(a, 5) + f + e + k + w[i];
        e = d; d = c; c = ROL32(b, 30); b = a; a = t;
    }
    h[0] += a; h[1] += b; h[2] += c; h[3] += d; h[4] += e;
}
#undef ROL32
static void updl_sha1_init(updl_sha1_t* c)
{
    static const uint32_t h0[5] = { 0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476, 0xC3D2E1F0 };
    memcpy(c->h, h0, sizeof h0); c->n = 0;
}
static void updl_sha1_add(updl_sha1_t* c, const uint8_t* d, size_t n)
{
    size_t k = (size_t)(c->n & 63);
    c->n += n;
    if (k) {
        const size_t m = 64 - k < n ? 64 - k : n;
        memcpy(c->b + k, d, m); d += m; n -= m; k += m;
        if (k < 64) return;
        updl_sha1_blk(c->h, c->b);
    }
    for (; n >= 64; d += 64, n -= 64) updl_sha1_blk(c->h, d);
    memcpy(c->b, d, n);
}
static void updl_sha1_hex(updl_sha1_t* c, char out[41])
{
    const uint64_t bits = c->n * 8;
    uint8_t pad[72] = { 0x80 }; const size_t pn = (size_t)((c->n & 63) < 56 ? 56 - (c->n & 63) : 120 - (c->n & 63));
    updl_sha1_add(c, pad, pn);
    uint8_t L[8]; for (int i = 0; i < 8; i++) L[i] = (uint8_t)(bits >> (56 - i * 8));
    updl_sha1_add(c, L, 8);
    for (int i = 0; i < 20; i++) snprintf(out + i * 2, 3, "%02x", (unsigned)(uint8_t)(c->h[i / 4] >> (24 - i % 4 * 8)));
}
/* Bytes [off, off+n) of package k into the hash: Sony's covers all but the last 32. */
static void updl_hash(updl_sha1_t* c, const updl_pkg_t* k, uint64_t off, const uint8_t* d, size_t n)
{
    const uint64_t end = k->size - 32;
    if (off >= end) return;
    updl_sha1_add(c, d, off + n > end ? (size_t)(end - off) : n);
}

static int updl_fail(const char* fmt, const char* a) { snprintf(s_updl.err, sizeof s_updl.err, fmt, a); return -1; }
static int updl_wait(int s, short ev, int ms) { struct pollfd p = { s, ev, 0 }; return poll(&p, 1, ms) == 1 && (p.revents & (ev | POLLHUP | POLLERR)); }
static uint32_t updl_ip4(const char* t)   /* "a.b.c.d" (host order), 0 if it isn't one (no inet_pton import) */
{
    uint32_t ip = 0; int parts = 0;
    while (parts < 4) {
        if (*t < '0' || *t > '9') return 0;
        unsigned v = 0; while (*t >= '0' && *t <= '9') { v = v * 10 + (unsigned)(*t++ - '0'); if (v > 255) return 0; }
        ip = ip << 8 | v; parts++;
        if (parts < 4 && *t++ != '.') return 0;
    }
    return *t && *t != '\n' && *t != '\r' && *t != ' ' && *t != '\t' ? 0 : ip;
}
static int updl_socket(int type, uint32_t ip, int port)   /* connected (20 s at most), blocking again; -1 on failure */
{
    const int s = socket(AF_INET, type, 0);
    if (s < 0) return -1;
    struct sockaddr_in sa; memset(&sa, 0, sizeof sa);
    sa.sin_family = AF_INET; sa.sin_port = htons((uint16_t)port); sa.sin_addr.s_addr = htonl(ip);
    const int fl = fcntl(s, F_GETFL, 0);
    fcntl(s, F_SETFL, fl | O_NONBLOCK);
    int r = connect(s, (struct sockaddr*)&sa, sizeof sa);
    if (r && errno == EINPROGRESS && updl_wait(s, POLLOUT, UPDL_TIMEOUT_MS)) {   /* (no getsockopt import: connect again says how it went) */
        r = connect(s, (struct sockaddr*)&sa, sizeof sa);
        if (r && errno == EISCONN) r = 0;
    }
    if (r) { close(s); return -1; }
    fcntl(s, F_SETFL, fl);
    struct timeval tv = { UPDL_TIMEOUT_MS / 1000, 0 };
    setsockopt(s, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof tv);
    return s;
}
/* One DNS A query (RFC 1035, UDP 53) of name to server; the first A record of the answer (CNAMEs followed), 0 none. */
static uint32_t updl_dns(uint32_t server, const char* name)
{
    uint8_t q[300], a[1500]; size_t n = 12;
    static uint16_t seq; const uint16_t id = (uint16_t)(time(NULL) * 2654435761u + ++seq * 40503u);
    memset(q, 0, 12); q[0] = (uint8_t)(id >> 8); q[1] = (uint8_t)id; q[2] = 0x01; q[5] = 1;   /* RD, one question */
    for (const char* p = name; *p; ) {
        const char* e = strchr(p, '.'); const size_t l = e ? (size_t)(e - p) : strlen(p);
        if (l == 0 || l > 63 || n + l + 6 > sizeof q) return 0;
        q[n++] = (uint8_t)l; memcpy(q + n, p, l); n += l; p += l; if (*p == '.') p++;
    }
    q[n++] = 0; q[n++] = 0; q[n++] = 1; q[n++] = 0; q[n++] = 1;   /* QTYPE A, QCLASS IN */
    for (int tries = 0; tries < 2; tries++) {
        const int s = updl_socket(SOCK_DGRAM, server, 53);
        if (s < 0) return 0;
        ssize_t got = -1;
        if (send(s, q, n, 0) == (ssize_t)n && updl_wait(s, POLLIN, 2500)) got = read(s, a, sizeof a);
        close(s);
        if (got < 12 || a[0] != q[0] || a[1] != q[1] || !(a[2] & 0x80) || (a[3] & 0x0F)) continue;
        const int qd = a[4] << 8 | a[5], an = a[6] << 8 | a[7];
        size_t at = 12;
        for (int i = 0; i < qd + an; i++) {
            while (at < (size_t)got && a[at] && (a[at] & 0xC0) != 0xC0) at += a[at] + 1u;   /* the name */
            at += at < (size_t)got && a[at] ? 2 : 1;
            if (i < qd) { at += 4; continue; }
            if (at + 10 > (size_t)got) break;
            const int type = a[at] << 8 | a[at + 1], cls = a[at + 2] << 8 | a[at + 3], rl = a[at + 8] << 8 | a[at + 9];
            at += 10;
            if (at + (size_t)rl > (size_t)got) break;
            if (type == 1 && cls == 1 && rl == 4) return (uint32_t)a[at] << 24 | a[at + 1] << 16 | a[at + 2] << 8 | a[at + 3];
            at += (size_t)rl;
        }
        return 0;
    }
    return 0;
}
/* host -> IPv4 (host order), 0 = couldn't. The console's own resolver isn't importable: /etc/resolv.conf if there
 * is one (PC; UPDL_DNS overrides), then public resolvers; for Sony's server, edge addresses seen 2026-11-12 last
 * (any copy that isn't the real file fails the SHA-1). */
static uint32_t updl_resolve(const char* host)
{
    uint32_t ip = updl_ip4(host);
    if (ip) return ip;
    if (s_updl.ip && !strcmp(s_updl.ip_host, host)) return s_updl.ip;
    uint32_t sv[8]; int ns = 0;
    const char* env = getenv("UPDL_DNS");
    if (env && updl_ip4(env)) sv[ns++] = updl_ip4(env);
    FILE* f = fopen("/etc/resolv.conf", "r");
    if (f) { char l[256]; while (ns < 4 && fgets(l, sizeof l, f)) { const char* p = l; while (*p == ' ' || *p == '\t') p++;
                 if (!strncmp(p, "nameserver", 10)) { p += 10; while (*p == ' ' || *p == '\t') p++; const uint32_t v = updl_ip4(p); if (v) sv[ns++] = v; } }
             fclose(f); }
    const int nlocal = ns;   /* (UPDL_DNS + resolv.conf: the user's own network, so their addresses aren't logged) */
    sv[ns++] = 0x01010101; sv[ns++] = 0x08080808; sv[ns++] = 0x09090909;   /* 1.1.1.1 8.8.8.8 9.9.9.9 */
    char via[48] = "";
    for (int i = 0; i < ns && !ip; i++)
        if ((ip = updl_dns(sv[i], host))) {
            if (i < nlocal) snprintf(via, sizeof via, "local resolver %d of %d", i + 1, nlocal);
            else snprintf(via, sizeof via, "public resolver %u.%u.%u.%u", UPDL_IP(sv[i]));
        }
    if (!ip && !strcmp(host, kUpdlHost)) { ip = 0x1701FEE1; snprintf(via, sizeof via, "fallback address"); }   /* 23.1.254.225 (a150.d.akamai.net) */
    if (ip) {
        s_updl.ip = ip; snprintf(s_updl.ip_host, sizeof s_updl.ip_host, "%s", host); snprintf(s_updl.via, sizeof s_updl.via, "%s", via);
        char ib[16]; UPDL_LOG("updates: %s -> %s (%s)\n", host, updl_ipstr(ip, ib), via);
    } else UPDL_LOG("updates: %s: no address (%d local and 3 public resolvers asked)\n", host, nlocal);
    return ip;
}

/* One GET of package k from *have on (appended to fd, hashed): 0 = the whole file is there, 1 = try again (no
 * data for 20 s, the connection dropped: resumes), 2 = start over (the .part was emptied), 3 = redirected (host and
 * path changed), -1 = give up (err). */
static int updl_fetch(const updl_pkg_t* k, int fd, uint64_t* have, updl_sha1_t* sha, uint8_t* buf, char* host, size_t hostn, char* path, size_t pathn)
{
    char hn_[128]; int port = 80;   /* host[:port] */
    snprintf(hn_, sizeof hn_, "%s", host);
    char* pc = strchr(hn_, ':'); if (pc) { *pc = 0; port = atoi(pc + 1); if (port <= 0 || port > 65535) port = 80; }
    const uint32_t ip = updl_resolve(hn_);
    if (!ip) return updl_fail("Couldn't find %s (no internet connection, or DNS blocked?)", hn_);
    s_updl.fip = ip; snprintf(s_updl.fvia, sizeof s_updl.fvia, "%s", updl_ip4(hn_) ? "address given" : s_updl.via);
    const int s = updl_socket(SOCK_STREAM, ip, port);
    if (s < 0) { char ib[16]; UPDL_LOG("updates: couldn't connect to %s:%d\n", updl_ipstr(ip, ib), port); s_updl.ip = 0; snprintf(s_updl.err, sizeof s_updl.err, "Couldn't connect to %s", host); return 1; }
    char rq[1024], rg[64] = "";
    if (*have) snprintf(rg, sizeof rg, "Range: bytes=%llu-\r\n", (unsigned long long)*have);
    const int rn = snprintf(rq, sizeof rq, "GET %s HTTP/1.1\r\nHost: %s\r\nUser-Agent: Mozilla/5.0\r\nAccept: */*\r\n%sConnection: close\r\n\r\n", path, host, rg);
    if (rn <= 0 || rn >= (int)sizeof rq || send(s, rq, (size_t)rn, 0) != rn) { close(s); snprintf(s_updl.err, sizeof s_updl.err, "The connection to %s dropped", host); return 1; }
    /* the header */
    size_t hn = 0; char* eoh = NULL;
    while (!eoh) {
        if (hn >= 8192 || !updl_wait(s, POLLIN, UPDL_TIMEOUT_MS)) { close(s); snprintf(s_updl.err, sizeof s_updl.err, "%s didn't answer", host); return 1; }
        const ssize_t r = read(s, buf + hn, 8192 - hn);
        if (r <= 0) { close(s); snprintf(s_updl.err, sizeof s_updl.err, "The connection to %s dropped", host); return 1; }
        hn += (size_t)r; buf[hn] = 0;
        eoh = strstr((char*)buf, "\r\n\r\n");
    }
    *eoh = 0;
    const char* body = eoh + 4; size_t bn = hn - (size_t)((const uint8_t*)body - buf);
    int code = 0; long long cl = -1, crs = -1; char loc[512] = ""; int chunked = 0;
    if (strncmp((char*)buf, "HTTP/1.", 7) || !(code = atoi((char*)buf + 9))) { close(s); return updl_fail("%s sent something that isn't HTTP", host); }
    s_updl.http = code;
    {   /* (Sony's own URL in full; a redirect's host only by name and its path without the query, which a captive
         *  portal fills with the console's own address) */
        const int own = !strcmp(host, s_updl_host); char ib[16];
        UPDL_LOG("updates: GET http://%s%.*s from byte %llu: %.*s\n", own || !updl_ip4(hn_) ? host : updl_ipstr(updl_ip4(hn_), ib),
                 own ? (int)strlen(path) : (int)strcspn(path, "?"), path, (unsigned long long)*have, (int)strcspn((char*)buf, "\r\n"), (char*)buf);
    }
    for (char* l = strstr((char*)buf, "\r\n"); l; l = strstr(l, "\r\n")) {
        l += 2;
        if (!strncasecmp(l, "Content-Length:", 15)) cl = strtoll(l + 15, NULL, 10);
        else if (!strncasecmp(l, "Content-Range:", 14)) { const char* p = strstr(l, "bytes"); if (p) crs = strtoll(p + 5, NULL, 10); }
        else if (!strncasecmp(l, "Location:", 9)) { const char* p = l + 9; while (*p == ' ') p++; snprintf(loc, sizeof loc, "%.*s", (int)strcspn(p, "\r\n"), p); }
        else if (!strncasecmp(l, "Transfer-Encoding:", 18) && strstr(l, "chunked")) chunked = 1;
    }
    if (code >= 301 && code <= 308 && code != 304 && loc[0]) {   /* a redirect: http://host/path only */
        close(s);
        if (strncasecmp(loc, "http://", 7)) { loc[strcspn(loc, "?")] = 0; return updl_fail("The server sent the download elsewhere (%s): not supported", loc); }
        const char* h = loc + 7; const size_t hl = strcspn(h, "/");
        snprintf(host, hostn, "%.*s", (int)hl, h); snprintf(path, pathn, "%s", h[hl] ? h + hl : "/");
        return 3;
    }
    if (code == 416 && *have == k->size) { close(s); return 0; }
    if (code == 416 || (code == 200 && *have)) {   /* no resume: from the start */
        if (ftruncate(fd, 0) || lseek(fd, 0, SEEK_SET)) { close(s); return updl_fail("Couldn't write %s", k->name); }
        s_updl.done -= *have; *have = 0; updl_sha1_init(sha);
        if (code == 416) { close(s); return 2; }
    }
    if (code != 200 && code != 206) { close(s); char t[16]; snprintf(t, sizeof t, "%d", code); return updl_fail("The server answered HTTP %s", t); }
    if (chunked) { close(s); return updl_fail("The server sent %s in an unexpected form (chunked)", k->name); }
    if (code == 206 && crs != (long long)*have) { close(s); return updl_fail("The server resumed %s at the wrong place", k->name); }
    if (cl >= 0 && (uint64_t)cl != k->size - *have) { close(s); return updl_fail("The server's %s isn't the size it should be (an updated package?)", k->name); }
    const uint64_t want = k->size - *have;
    uint64_t got = 0;
    for (;;) {
        if (bn) {
            if (bn > want - got) bn = (size_t)(want - got);
            size_t at = 0;
            while (at < bn) {
                const ssize_t w = write(fd, body + at, bn - at);
                if (w <= 0) { close(s); return updl_fail(errno == ENOSPC ? "Not enough free space (writing %s)" : "Couldn't write %s", k->name); }
                at += (size_t)w;
            }
            updl_hash(sha, k, *have, (const uint8_t*)body, bn);
            *have += bn; got += bn; s_updl.done += bn; s_updl.net += bn;
        }
        if (got >= want) break;
        if (!updl_wait(s, POLLIN, UPDL_TIMEOUT_MS)) { close(s); snprintf(s_updl.err, sizeof s_updl.err, "No data from %s for 20 seconds", host); return 1; }
        const ssize_t r = read(s, buf, UPDL_BUF);
        if (r <= 0) { close(s); snprintf(s_updl.err, sizeof s_updl.err, "The connection to %s dropped", host); return 1; }
        body = (const char*)buf; bn = (size_t)r;
    }
    close(s);
    return 0;
}
/* Package k into dir/<name>: 0 ok (or already there and good), -1 failed (err). */
static int updl_get(const updl_pkg_t* k, uint8_t* buf)
{
    char dst[700], part[720];
    snprintf(dst, sizeof dst, "%s/%s", s_updl.dir, k->name); snprintf(part, sizeof part, "%s.part", dst);
    updl_sha1_t sha; updl_sha1_init(&sha);
    char hex[41];
    struct stat st;
    if (!stat(dst, &st) && (uint64_t)st.st_size == k->size) {   /* already there: only if it checks out */
        const int fd = open(dst, O_RDONLY);
        uint64_t off = 0;
        while (fd >= 0 && off < k->size) { const ssize_t r = read(fd, buf, UPDL_BUF); if (r <= 0) break; updl_hash(&sha, k, off, buf, (size_t)r); off += (size_t)r; }
        if (fd >= 0) close(fd);
        updl_sha1_hex(&sha, hex);
        if (off == k->size && !strcmp(hex, k->sha1)) { s_updl.done += k->size; UPDL_LOG("updates: %s already in install/, SHA-1 ok\n", k->name); return 0; }
        UPDL_LOG("updates: %s in install/ fails its SHA-1: downloading it again\n", k->name);
        updl_sha1_init(&sha);
    }
    int fd = open(part, O_RDWR | O_CREAT, 0666);
    if (fd < 0) return updl_fail("Couldn't create %s", part);
    uint64_t have = 0;
    if (!fstat(fd, &st) && (uint64_t)st.st_size <= k->size) {   /* a .part from before: hash it and go on from its end */
        while (have < (uint64_t)st.st_size) { const ssize_t r = read(fd, buf, UPDL_BUF); if (r <= 0) break; updl_hash(&sha, k, have, buf, (size_t)r); have += (size_t)r; }
    }
    if (ftruncate(fd, (off_t)have) || lseek(fd, (off_t)have, SEEK_SET) != (off_t)have) { close(fd); return updl_fail("Couldn't write %s", part); }
    s_updl.done += have;
    char host[128], path[512];
    snprintf(host, sizeof host, "%s", s_updl_host); snprintf(path, sizeof path, "%s%s", s_updl_path, k->name);
    int fails = 0, hops = 0, restarts = 0, r = have == k->size ? 0 : 1;   /* (a whole .part from before: just check it) */
    while (r) {
        const uint64_t before = have;
        r = updl_fetch(k, fd, &have, &sha, buf, host, sizeof host, path, sizeof path);
        if (r < 0) break;
        if (r == 3 && ++hops > 4) { r = updl_fail("Too many redirects for %s", k->name); break; }
        if (r == 2 && ++restarts > 2) { r = updl_fail("The server won't send %s", k->name); break; }
        if (r == 1 && have == before && ++fails >= 5) { r = -1; break; }   /* (err says why) */
        if (have > before) fails = 0;
        if (r == 1 && have == before) usleep(1000000);
    }
    close(fd);
    if (r < 0) return -1;
    updl_sha1_hex(&sha, hex);
    if (have != k->size || strcmp(hex, k->sha1)) {   /* damaged: the next try starts over */
        UPDL_LOG("updates: %s: %llu of %llu bytes, SHA-1 FAILED (%s, expected %s): .part deleted\n", k->name, (unsigned long long)have, (unsigned long long)k->size, hex, k->sha1);
        unlink(part); s_updl.done -= have;
        return updl_fail("%s arrived damaged (SHA-1 mismatch): try again", k->name);
    }
    fd = open(part, O_RDONLY);   /* the last 32 bytes are the same SHA-1 */
    uint8_t tail[32]; char th[41];
    if (fd < 0 || inst_pread(fd, tail, 32, k->size - 32)) { if (fd >= 0) close(fd); return updl_fail("Couldn't read %s back", part); }
    close(fd);
    for (int i = 0; i < 20; i++) snprintf(th + i * 2, 3, "%02x", tail[i]);
    if (strcmp(th, k->sha1)) { UPDL_LOG("updates: %s: its own checksum FAILED (%s): .part deleted\n", k->name, th); unlink(part); s_updl.done -= have; return updl_fail("%s arrived damaged (its own checksum): try again", k->name); }
    if (rename(part, dst)) return updl_fail("Couldn't rename %s", part);
    UPDL_LOG("updates: %s: %llu bytes, SHA-1 ok\n", k->name, (unsigned long long)have);
    return 0;
}
static void* updl_main(void* arg)
{
    (void)arg;
    uint8_t* buf = malloc(UPDL_BUF + 1);
    if (!buf) { snprintf(s_updl.err, sizeof s_updl.err, "Out of memory"); s_updl.state = 3; return NULL; }
    mkdir(s_updl.dir, 0777);
    for (int u = 0; u < 4; u++) {
        if (!(s_updl.want & 1u << u)) continue;
        s_updl.file++;
        snprintf(s_updl.cur, sizeof s_updl.cur, "update %c.%c%c", kUpdlPkgs[u].ver[1], kUpdlPkgs[u].ver[3], kUpdlPkgs[u].ver[4]);
        s_updl.err[0] = 0; s_updl.fip = 0; s_updl.fvia[0] = 0; s_updl.http = 0; s_updl.net = 0;
        UPDL_LOG("updates: file %d of %d: %s (%s, %llu bytes)\n", s_updl.file, s_updl.nfiles, s_updl.cur, kUpdlPkgs[u].name, (unsigned long long)kUpdlPkgs[u].size);
        int r = updl_get(&kUpdlPkgs[u], buf);
        if (r && strstr(s_updl.err, "damaged")) { s_updl.err[0] = 0; r = updl_get(&kUpdlPkgs[u], buf); }   /* (once more, from the start) */
        char ib[16];
        UPDL_LOG("updates: %s %s: %llu bytes downloaded, server %s (%s), last HTTP %d%s%s\n", s_updl.cur, r ? "STOPPED" : "ok",
                 (unsigned long long)s_updl.net, s_updl.fip ? updl_ipstr(s_updl.fip, ib) : "none", s_updl.fip ? s_updl.fvia : "not reached", s_updl.http, r ? ": " : "", r ? s_updl.err : "");
        if (r) { free(buf); s_updl.state = 3; return NULL; }
    }
    free(buf);
    s_updl.err[0] = 0;
    UPDL_LOG("updates: all %d done (%llu MB)\n", s_updl.nfiles, (unsigned long long)(s_updl.total / 1000000));
    snprintf(s_updl.cur, sizeof s_updl.cur, "done");
    s_updl.state = 2;
    return NULL;
}
/* Download the updates in want (bit u: kInstIf2Updates[u]) into <app>/install; follow s_updl, inst_scan when it's 2. */
static int updl_start(const char* app, unsigned want)
{
    if (s_updl.state == 1 || !(want & 0xF)) return -1;
    const uint32_t ip = s_updl.ip; char ih[128], via[48]; snprintf(ih, sizeof ih, "%s", s_updl.ip_host); snprintf(via, sizeof via, "%s", s_updl.via);
    memset(&s_updl, 0, sizeof s_updl);
    s_updl.ip = ip; snprintf(s_updl.ip_host, sizeof s_updl.ip_host, "%s", ih); snprintf(s_updl.via, sizeof s_updl.via, "%s", via);
    snprintf(s_updl.dir, sizeof s_updl.dir, "%s/install", app);
    s_updl.want = want & 0xF;
    for (int u = 0; u < 4; u++) if (s_updl.want & 1u << u) { s_updl.total += kUpdlPkgs[u].size; s_updl.nfiles++; }
    s_updl.state = 1;
    pthread_t t;
    if (pthread_create(&t, NULL, updl_main, NULL)) { s_updl.state = 3; snprintf(s_updl.err, sizeof s_updl.err, "Couldn't start the download"); return -1; }
    pthread_detach(t);
    return 0;
}
#endif

/* ---------------------------------------------------------------- the installer payload
 * The PS5 lets an app write about a gigabyte quickly, then slows its writes to a couple of MB/s, so a
 * whole game copied from inside the launcher crawls (MGR RePlatinum / GTA IV for PS5 found the same).
 * The same install code is also built as a payload (-DINST_PAYLOAD -> payloads/inst-payload.elf), which
 * the launcher sends to the console's payload loader on 127.0.0.1:9021 (etaHEN, elfldr, ...): a process of
 * its own that writes at the drive's speed. The launcher leaves it <app>/.inst-job/job.txt ("game=if2"),
 * the payload takes it (rename to job.taken) and keeps status.txt there current; with no loader, or nobody
 * taking the job, the launcher installs by itself as before. */
#define INST_JOBDIR ".inst-job"
static const char* const kInstApps[] = { "/data/homebrew", "/user/data/homebrew", "/mnt/ext0/homebrew", "/mnt/ext1/homebrew",
    "/mnt/usb0/homebrew", "/mnt/usb1/homebrew", "/mnt/usb2/homebrew", "/mnt/usb3/homebrew" };

#ifdef INST_PAYLOAD
static void inst_status(const char* dir)
{
    char p[600], q[600]; snprintf(p, sizeof p, "%s/status.tmp", dir); snprintf(q, sizeof q, "%s/status.txt", dir);
    FILE* f = fopen(p, "w"); if (!f) return;
    fprintf(f, "state=%d\ndone=%llu\ntotal=%llu\ncur=%s\nerr=%s\n", s_inst.state, (unsigned long long)s_inst.done,
            (unsigned long long)s_inst.total, s_inst.cur, s_inst.err);
    fclose(f); rename(p, q);
}
int main(void)
{
    char app[300] = "", dir[600], p[700];
    const char* test = getenv("INST_APP");               /* PC test: the app folder itself */
    if (test) snprintf(app, sizeof app, "%s", test);
    for (unsigned i = 0; i < sizeof kInstApps / sizeof kInstApps[0] && !app[0]; i++) {
        struct stat st;
        snprintf(p, sizeof p, "%s/PPSA95463/" INST_JOBDIR "/job.txt", kInstApps[i]);
        if (!stat(p, &st)) snprintf(app, sizeof app, "%s/PPSA95463", kInstApps[i]);
    }
    if (!app[0]) return 1;
    snprintf(dir, sizeof dir, "%s/" INST_JOBDIR, app);
    char job[700], taken[700]; snprintf(job, sizeof job, "%s/job.txt", dir); snprintf(taken, sizeof taken, "%s/job.taken", dir);
    char want[16] = "";
    FILE* f = fopen(job, "r");
    int cache_only = 0;
    if (f) { char l[64]; while (fgets(l, sizeof l, f)) { if (!strncmp(l, "game=", 5)) { snprintf(want, sizeof want, "%s", l + 5); want[strcspn(want, "\r\n")] = 0; }
                                                      if (!strncmp(l, "mode=cache", 10)) cache_only = 1; } fclose(f); }
    if (rename(job, taken)) return 1;                     /* the launcher took it back first */
    int g = -1;
    for (int i = 0; i < INST_NGAMES; i++) if (!strcmp(want, kInstDir[i])) g = i;
    inst_scan(app);   /* a repair may need the dump too (EBOOT.elf) */
    if (g < 0 || (cache_only ? inst_start_cache(app, g) : inst_start(app, g))) { if (!s_inst.err[0]) snprintf(s_inst.err, sizeof s_inst.err, "Unknown game '%s'", want); s_inst.state = 3; }
    while (s_inst.state == 1) { inst_status(dir); usleep(500000); }
    inst_status(dir);
    unlink(taken);
    return s_inst.state == 2 ? 0 : 1;
}
#elif !defined(INST_MAIN)
#include <sys/socket.h>
#include <netinet/in.h>
#include <time.h>
static int s_inst_remote;                 /* 1 while the payload has (or may take) the job */
static int s_inst_remote_cache;           /* that job is a repair (first-boot data only) */
static double s_inst_sent;
static double inst_now(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec + t.tv_nsec / 1e9; }
/* Hand the install of game g to the payload; 0 = sent (follow it with inst_poll_remote), -1 = install in the app. */
static int inst_start_remote_mode(const char* app, int g, int cache_only);
static int inst_start_remote(const char* app, int g) { return inst_start_remote_mode(app, g, 0); }
static int inst_start_remote_mode(const char* app, int g, int cache_only)
{
    if (s_inst.state == 1) return -1;
    char dir[400], p[500];
    snprintf(dir, sizeof dir, "%s/" INST_JOBDIR, app); mkdir(dir, 0777);
    snprintf(p, sizeof p, "%s/status.txt", dir); unlink(p);
    snprintf(p, sizeof p, "%s/payloads/inst-payload.elf", app);
    int fd = open(p, O_RDONLY); if (fd < 0) return -1;
    struct stat st; if (fstat(fd, &st) || st.st_size <= 0 || st.st_size > (64 << 20)) { close(fd); return -1; }
    char* elf = (char*)malloc((size_t)st.st_size); size_t got = 0;
    while (elf && got < (size_t)st.st_size) { ssize_t r = read(fd, elf + got, (size_t)st.st_size - got); if (r <= 0) break; got += (size_t)r; }
    close(fd);
    if (!elf || got != (size_t)st.st_size) { free(elf); return -1; }
    snprintf(p, sizeof p, "%s/job.txt", dir);
    FILE* f = fopen(p, "w"); if (!f) { free(elf); return -1; }
    fprintf(f, "game=%s\n%s", kInstDir[g], cache_only ? "mode=cache\n" : ""); fclose(f);
    int s = socket(AF_INET, SOCK_STREAM, 0), ok = 0;
    if (s >= 0) {
        struct timeval tv = { 3, 0 };
        setsockopt(s, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof tv);
        struct sockaddr_in sa; memset(&sa, 0, sizeof sa);
        sa.sin_family = AF_INET; sa.sin_port = htons(9021); sa.sin_addr.s_addr = htonl(0x7F000001);
        if (!connect(s, (struct sockaddr*)&sa, sizeof sa)) {
            size_t at = 0;
            while (at < got) { ssize_t w = send(s, elf + at, got - at, 0); if (w <= 0) break; at += (size_t)w; }
            ok = at == got;
        }
        close(s);
    }
    free(elf);
    if (!ok) { unlink(p); return -1; }
    memset(&s_inst, 0, sizeof s_inst);
    s_inst.game = g; snprintf(s_inst.app, sizeof s_inst.app, "%s", app);
    snprintf(s_inst.cur, sizeof s_inst.cur, "starting the installer");
    s_inst.state = 1; s_inst_remote = 1; s_inst_remote_cache = cache_only; s_inst_sent = inst_now();
    return 0;
}
/* Each frame while the payload has the job: its status.txt into s_inst. Takes the job back (and installs
 * in the app) when no payload took it within 8 s. */
static void inst_poll_remote(const char* app)
{
    if (!s_inst_remote) return;
    char p[500], l[300];
    snprintf(p, sizeof p, "%s/" INST_JOBDIR "/status.txt", app);
    FILE* f = fopen(p, "r");
    if (f) {
        while (fgets(l, sizeof l, f)) {
            l[strcspn(l, "\r\n")] = 0;
            if (!strncmp(l, "state=", 6)) s_inst.state = atoi(l + 6);
            else if (!strncmp(l, "done=", 5)) s_inst.done = strtoull(l + 5, 0, 10);
            else if (!strncmp(l, "total=", 6)) s_inst.total = strtoull(l + 6, 0, 10);
            else if (!strncmp(l, "cur=", 4)) snprintf(s_inst.cur, sizeof s_inst.cur, "%s", l + 4);
            else if (!strncmp(l, "err=", 4)) snprintf(s_inst.err, sizeof s_inst.err, "%s", l + 4);
        }
        fclose(f);
        if (s_inst.state != 1) s_inst_remote = 0;
        return;
    }
    snprintf(p, sizeof p, "%s/" INST_JOBDIR "/job.txt", app);
    if (inst_now() - s_inst_sent > 8.0 && !unlink(p)) {   /* nobody took it: install in the app */
        const int g = s_inst.game;
        s_inst_remote = 0; s_inst.state = 0;
        if (s_inst_remote_cache) inst_start_cache(app, g); else inst_start(app, g);
    }
}
#endif

#ifdef INST_MAIN
/* PC test: inst <app> scan | inst <app> install <if1|if2|fob> */
int main(int argc, char** argv)
{
    if (argc < 3) { fprintf(stderr, "usage: %s <app> scan|install <game>|download [all]\n", argv[0]); return 2; }
    inst_scan(argv[1]);
    if (!strcmp(argv[2], "download")) {   /* inFAMOUS 2's missing updates (all four with "all") into <app>/install */
        const unsigned want = argc > 3 && !strcmp(argv[3], "all") ? 0xF : inst_if2_missing();
        printf("download: want mask 0x%X\n", want);
        if (updl_start(argv[1], want)) { fprintf(stderr, "can't start: %s\n", s_updl.err[0] ? s_updl.err : "nothing to download (no disc, or no update missing)"); return 1; }
        while (s_updl.state == 1) {
            usleep(2000000);
            fprintf(stderr, "  %5.1f%%  %d/%d %s  %.1f of %.1f MB  %s\n", s_updl.total ? 100.0 * s_updl.done / s_updl.total : 0.0,
                    s_updl.file, s_updl.nfiles, s_updl.cur, s_updl.done / 1e6, s_updl.total / 1e6, s_updl.err);
        }
        printf("download: %s %s (server %u.%u.%u.%u)\n", s_updl.state == 2 ? "DONE" : "FAILED", s_updl.err, s_updl.ip >> 24, s_updl.ip >> 16 & 255, s_updl.ip >> 8 & 255, s_updl.ip & 255);
        if (s_updl.state != 2) return 1;
        inst_scan(argv[1]);
    }
    for (int i = 0; i < s_inst_nsrc; i++) {
        const inst_src_t* s = &s_inst_src[i];
        printf("source: %-60s %s %s %s  %d files %.2f GB  -> %s%s\n", s->name, s->tid, s->ver, s->cat, s->n, s->total / 1e9,
               kInstKnown[s->known].what, kInstKnown[s->known].tested ? "" : " (untested edition)");
    }
    for (int i = 0; i < s_inst_nnotes; i++) printf("note: %s\n", s_inst_notes[i]);
    if (s_inst_rap[0]) printf("licence: %s\n", s_inst_rap);
    for (int g = 0; g < INST_NGAMES; g++) {
        inst_src_t* o[8]; char need[300];
        const int n = inst_plan(g, o, need, sizeof need);
        printf("%s: %s%s\n", kInstDir[g], n ? "ready" : "missing ", n ? "" : need);
    }
    if (!strcmp(argv[2], "install") && argc > 3) {
        int g = -1;
        for (int i = 0; i < INST_NGAMES; i++) if (!strcmp(argv[3], kInstDir[i])) g = i;
        if (g < 0 || inst_start(argv[1], g)) { fprintf(stderr, "can't start: %s\n", s_inst.err); return 1; }
        while (s_inst.state == 1) {
            usleep(2000000);
            fprintf(stderr, "  %5.1f%%  %s\n", s_inst.total ? 100.0 * s_inst.done / s_inst.total : 0.0, s_inst.cur);
        }
        printf("%s: %s %s\n", argv[3], s_inst.state == 2 ? "INSTALLED" : "FAILED", s_inst.err);
        return s_inst.state == 2 ? 0 : 1;
    }
    return 0;
}
#endif
