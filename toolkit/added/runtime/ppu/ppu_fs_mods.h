/*
 * ps3recomp - mods overlay: replacement texture packs (included once, by
 * ppu_fs.cpp, after ppu_fs_lang.h)
 *
 * The three inFAMOUS games load their packs (i2.core.xpps, cole_default.xpps,
 * core.xpp, ...) through Sony's FIOS library. Its dearchiver looks a name up
 * in the table of contents of every mounted PSARC (infamous1/2.psarc_s,
 * patch1/3/4.psarc_s) by the MD5 of the upper-cased path; only a name that is
 * in no TOC is passed down to the file system, which then opens the loose
 * file: /dev_hdd0/game/<INSTALL>/USRDIR/<name>, then /dev_bdvd/PS3_GAME/USRDIR/
 * <name> (seen for Festival of Blood: thousands of imposter-*.xpps probes).
 *
 * So a pack is replaced in two steps, both under the guest:
 *  - hide: when an archive is opened, the TOC record of every replaced pack
 *    gets another MD5 (patched in the read buffer, like the language redirect
 *    in ppu_fs_lang.h; never on disk). The game's lookup misses in every
 *    archive and falls through to the loose path.
 *  - serve: a read-only open or stat of a loose path ending in /<name> is
 *    answered with <PS3_MODS_DIR>/<mod id>/<pack>.
 *
 *   PS3_MODS_DIR=<host dir>      folder holding one sub-folder per mod:
 *                                <id>/mod.json + the pack files it names
 *   PS3_MODS=<id>,<id>,...       the enabled mods, highest priority first
 *   PS3_MODS_VERIFY=1            also check each pack's SHA-256 against
 *                                mod.json (built_sha256) at start-up; costs
 *                                one full read + hash of every pack (an
 *                                electricity mod for inFAMOUS 2 is ~230 MB:
 *                                about 1 s on a Zen 2 core plus the read)
 *
 * Either of the first two unset or empty: nothing here runs, behaviour is as
 * before. Both are read at first use (the first archive open), not in a
 * static constructor: on the PS5 the environment is set inside main.
 *
 * mod.json (written by the launcher's mod builder): {"id": ..., "files":
 * [{"pack": <file in the mod folder>, "usrdir_path": <name in the archive TOC,
 * relative to USRDIR>, "size": <bytes>, "built_sha256": <hex>}, ...], ...};
 * other fields are ignored. A mod is used whole or not at all: a missing
 * file, a size that differs from mod.json, a failed hash, or a pack that an
 * earlier enabled mod already replaces drops the whole mod, with a log line.
 *
 * Archive names and their priority differ per game; nothing here knows them:
 * a replaced name is hidden in EVERY archive whose TOC lists it, and the mod
 * builder already started from the highest-priority copy of the pack.
 *
 * Delta mods (2026-11-17): a mod folder may hold <pack>.dlt instead of the full
 * <pack> (when both are there, the full pack is used, as before). The .dlt has
 * only the bytes the mod changes; the pack the game reads is the ORIGINAL pack,
 * read out of the game's own archive, with those bytes laid over it on every
 * read (no copy is written anywhere). The original is found at start-up: every
 * *.psarc / *.psarc_s under the VFS root (and PS3_HDD0_ROOT) whose TOC lists the
 * pack is a candidate, and a copy is used only when its size and its sample
 * hash (below) are the ones the .dlt was made from; no match drops the mod, with
 * a log line, before anything is hidden. Several mods on one pack combine as
 * before (first enabled = base, later ones' textures laid over it); when any of
 * them is a delta, the result is served the same way, without a .merged copy.
 * PS3_MODS_VERIFY=1 also rebuilds each delta mod's pack in memory and checks its
 * SHA-256 (mod.json built_sha256).
 *
 * <pack>.dlt, all numbers little-endian:
 *     0  char[8]  "MODDLT1\0"
 *     8  u32      version = 1
 *    12  u32      flags: bit 0 TEXTURES = the ranges are whole textures (as <pack>.rng lists them), so this
 *                 mod may share the pack with other mods; clear = a whole-pack mod. Other bits must be 0.
 *    16  u64      size of the modified pack (== mod.json "size")
 *    24  u64      orig_size: size of the original pack
 *    32  u32      n: ranges
 *    36  u32      sample_count (1..256)
 *    40  u32      sample_len (1..1 MB)
 *    44  u32      0
 *    48  u8[32]   SHA-256 of the whole original pack (tools; not read at run time)
 *    80  u8[32]   SHA-256 of the original's sample: sample_count windows of w = min(sample_len, orig_size)
 *                 bytes, window k at k * (orig_size - w) / (sample_count - 1) (at 0 when sample_count is 1),
 *                 concatenated
 *   112  u8[32]   SHA-256 of the modified pack (== mod.json built_sha256)
 *   144  u8[16]   0
 *   160  n x { u64 offset, u64 length }: sorted, not overlapping, length > 0, offset + length <= size
 *        then the modified pack's bytes of every range, in table order; the file ends there.
 * Modified pack = the original cut/extended to size, with every range's bytes laid over it; every byte past
 * orig_size must be inside a range. Made by moddelta notes
 */
#ifndef PPU_FS_MODS_H
#define PPU_FS_MODS_H

#include <algorithm>
#include <mutex>
#include <set>
#include <string>
#include <vector>

/* ---- MD5 (the PSARC TOC key) and SHA-256 (PS3_MODS_VERIFY) ---------------- */

static void mods_md5(const uint8_t* msg, size_t len, uint8_t out[16])
{
    static const uint32_t K[64] = {
        0xd76aa478,0xe8c7b756,0x242070db,0xc1bdceee,0xf57c0faf,0x4787c62a,0xa8304613,0xfd469501,
        0x698098d8,0x8b44f7af,0xffff5bb1,0x895cd7be,0x6b901122,0xfd987193,0xa679438e,0x49b40821,
        0xf61e2562,0xc040b340,0x265e5a51,0xe9b6c7aa,0xd62f105d,0x02441453,0xd8a1e681,0xe7d3fbc8,
        0x21e1cde6,0xc33707d6,0xf4d50d87,0x455a14ed,0xa9e3e905,0xfcefa3f8,0x676f02d9,0x8d2a4c8a,
        0xfffa3942,0x8771f681,0x6d9d6122,0xfde5380c,0xa4beea44,0x4bdecfa9,0xf6bb4b60,0xbebfbc70,
        0x289b7ec6,0xeaa127fa,0xd4ef3085,0x04881d05,0xd9d4d039,0xe6db99e5,0x1fa27cf8,0xc4ac5665,
        0xf4292244,0x432aff97,0xab9423a7,0xfc93a039,0x655b59c3,0x8f0ccc92,0xffeff47d,0x85845dd1,
        0x6fa87e4f,0xfe2ce6e0,0xa3014314,0x4e0811a1,0xf7537e82,0xbd3af235,0x2ad7d2bb,0xeb86d391 };
    static const uint8_t R[64] = {
        7,12,17,22,7,12,17,22,7,12,17,22,7,12,17,22, 5,9,14,20,5,9,14,20,5,9,14,20,5,9,14,20,
        4,11,16,23,4,11,16,23,4,11,16,23,4,11,16,23, 6,10,15,21,6,10,15,21,6,10,15,21,6,10,15,21 };
    uint32_t h0 = 0x67452301, h1 = 0xefcdab89, h2 = 0x98badcfe, h3 = 0x10325476;
    std::vector<uint8_t> m(msg, msg + len);
    m.push_back(0x80);
    while (m.size() % 64 != 56) m.push_back(0);
    const uint64_t bits = (uint64_t)len * 8;
    for (int i = 0; i < 8; i++) m.push_back((uint8_t)(bits >> (8 * i)));
    for (size_t c = 0; c < m.size(); c += 64) {
        uint32_t w[16];
        for (int i = 0; i < 16; i++)
            w[i] = (uint32_t)m[c + 4 * i] | ((uint32_t)m[c + 4 * i + 1] << 8) |
                   ((uint32_t)m[c + 4 * i + 2] << 16) | ((uint32_t)m[c + 4 * i + 3] << 24);
        uint32_t a = h0, b = h1, cc = h2, d = h3;
        for (int i = 0; i < 64; i++) {
            uint32_t f; int g;
            if (i < 16)      { f = (b & cc) | (~b & d);  g = i; }
            else if (i < 32) { f = (d & b) | (~d & cc);  g = (5 * i + 1) % 16; }
            else if (i < 48) { f = b ^ cc ^ d;           g = (3 * i + 5) % 16; }
            else             { f = cc ^ (b | ~d);        g = (7 * i) % 16; }
            const uint32_t t = d; d = cc; cc = b;
            const uint32_t x = a + f + K[i] + w[g];
            b = b + ((x << R[i]) | (x >> (32 - R[i])));
            a = t;
        }
        h0 += a; h1 += b; h2 += cc; h3 += d;
    }
    const uint32_t hs[4] = { h0, h1, h2, h3 };
    for (int i = 0; i < 4; i++)
        for (int j = 0; j < 4; j++) out[4 * i + j] = (uint8_t)(hs[i] >> (8 * j));
}

struct ModsSha256 { uint32_t h[8]; uint8_t buf[64]; size_t n; uint64_t len; };

static void mods_sha_block(ModsSha256& s, const uint8_t* p)
{
    static const uint32_t K[64] = {
        0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
        0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
        0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
        0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
        0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
        0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
        0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
        0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2 };
#define MODS_ROR(x, r) (((x) >> (r)) | ((x) << (32 - (r))))
    uint32_t w[64];
    for (int i = 0; i < 16; i++)
        w[i] = ((uint32_t)p[4 * i] << 24) | ((uint32_t)p[4 * i + 1] << 16) | ((uint32_t)p[4 * i + 2] << 8) | p[4 * i + 3];
    for (int i = 16; i < 64; i++) {
        const uint32_t s0 = MODS_ROR(w[i - 15], 7) ^ MODS_ROR(w[i - 15], 18) ^ (w[i - 15] >> 3);
        const uint32_t s1 = MODS_ROR(w[i - 2], 17) ^ MODS_ROR(w[i - 2], 19) ^ (w[i - 2] >> 10);
        w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }
    uint32_t a = s.h[0], b = s.h[1], c = s.h[2], d = s.h[3], e = s.h[4], f = s.h[5], g = s.h[6], h = s.h[7];
    for (int i = 0; i < 64; i++) {
        const uint32_t t1 = h + (MODS_ROR(e, 6) ^ MODS_ROR(e, 11) ^ MODS_ROR(e, 25)) + ((e & f) ^ (~e & g)) + K[i] + w[i];
        const uint32_t t2 = (MODS_ROR(a, 2) ^ MODS_ROR(a, 13) ^ MODS_ROR(a, 22)) + ((a & b) ^ (a & c) ^ (b & c));
        h = g; g = f; f = e; e = d + t1; d = c; c = b; b = a; a = t1 + t2;
    }
#undef MODS_ROR
    s.h[0] += a; s.h[1] += b; s.h[2] += c; s.h[3] += d; s.h[4] += e; s.h[5] += f; s.h[6] += g; s.h[7] += h;
}

static void mods_sha_init(ModsSha256& s)
{
    static const uint32_t H[8] = { 0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19 };
    memcpy(s.h, H, sizeof H); s.n = 0; s.len = 0;
}

static void mods_sha_add(ModsSha256& s, const uint8_t* p, size_t n)
{
    s.len += n;
    if (s.n) {
        while (n && s.n < 64) { s.buf[s.n++] = *p++; n--; }
        if (s.n < 64) return;
        mods_sha_block(s, s.buf); s.n = 0;
    }
    for (; n >= 64; p += 64, n -= 64) mods_sha_block(s, p);
    memcpy(s.buf, p, n); s.n = n;
}

static void mods_sha_hex(ModsSha256& s, char hex[65])
{
    const uint64_t bits = s.len * 8;
    uint8_t pad = 0x80;
    mods_sha_add(s, &pad, 1);
    pad = 0;
    while (s.n != 56) mods_sha_add(s, &pad, 1);
    uint8_t L[8];
    for (int i = 0; i < 8; i++) L[i] = (uint8_t)(bits >> (56 - 8 * i));
    mods_sha_add(s, L, 8);
    for (int i = 0; i < 32; i++) snprintf(hex + 2 * i, 3, "%02x", (unsigned)(uint8_t)(s.h[i / 4] >> (24 - 8 * (i % 4))));
}

/* ---- a JSON reader for mod.json ------------------------------------------- */

struct ModsJson {
    enum Type { NUL, BOOL, NUM, STR, ARR, OBJ } t = NUL;
    std::string s;                 /* STR */
    uint64_t n = 0; bool uint = false;   /* NUM: the value when it is a plain unsigned integer */
    std::vector<std::string> keys;   /* OBJ member names (ARR: empty) */
    std::vector<ModsJson> kids;      /* OBJ member values / ARR items */
    const ModsJson* get(const char* k) const;
};

inline const ModsJson* ModsJson::get(const char* k) const
{
    if (t != OBJ) return nullptr;
    for (size_t i = 0; i < keys.size() && i < kids.size(); i++) if (keys[i] == k) return &kids[i];
    return nullptr;
}

struct ModsJsonIn { const char* p; const char* e; int depth; };

static void mods_json_ws(ModsJsonIn& q)
{
    while (q.p < q.e && (*q.p == ' ' || *q.p == '\t' || *q.p == '\n' || *q.p == '\r')) q.p++;
}

static bool mods_json_str(ModsJsonIn& q, std::string& out)
{
    if (q.p >= q.e || *q.p != '"') return false;
    q.p++;
    while (q.p < q.e && *q.p != '"') {
        const char c = *q.p++;
        if ((unsigned char)c < 0x20) return false;
        if (c != '\\') { out += c; continue; }
        if (q.p >= q.e) return false;
        const char x = *q.p++;
        switch (x) {
        case '"': case '\\': case '/': out += x; break;
        case 'b': out += '\b'; break;
        case 'f': out += '\f'; break;
        case 'n': out += '\n'; break;
        case 'r': out += '\r'; break;
        case 't': out += '\t'; break;
        case 'u': {
            if (q.e - q.p < 4) return false;
            unsigned v = 0;
            for (int i = 0; i < 4; i++) {
                const char h = *q.p++;
                v <<= 4;
                if (h >= '0' && h <= '9') v |= (unsigned)(h - '0');
                else if (h >= 'a' && h <= 'f') v |= (unsigned)(h - 'a' + 10);
                else if (h >= 'A' && h <= 'F') v |= (unsigned)(h - 'A' + 10);
                else return false;
            }
            out += v < 0x80 ? (char)v : '?';   /* names and ids we use are ASCII */
            break;
        }
        default: return false;
        }
    }
    if (q.p >= q.e) return false;
    q.p++;
    return true;
}

static bool mods_json_val(ModsJsonIn& q, ModsJson& v)
{
    if (++q.depth > 32) return false;
    mods_json_ws(q);
    if (q.p >= q.e) return false;
    bool ok = true;
    const char c = *q.p;
    if (c == '{' || c == '[') {
        const bool obj = c == '{';
        const char close = obj ? '}' : ']';
        v.t = obj ? ModsJson::OBJ : ModsJson::ARR;
        q.p++;
        mods_json_ws(q);
        if (q.p < q.e && *q.p == close) q.p++;
        else for (;;) {
            std::string k;
            if (obj) {
                mods_json_ws(q);
                if (!mods_json_str(q, k)) { ok = false; break; }
                mods_json_ws(q);
                if (q.p >= q.e || *q.p != ':') { ok = false; break; }
                q.p++;
            }
            v.keys.push_back(std::move(k));
            v.kids.emplace_back();
            if (!mods_json_val(q, v.kids.back())) { ok = false; break; }
            mods_json_ws(q);
            if (q.p < q.e && *q.p == ',') { q.p++; continue; }
            if (q.p < q.e && *q.p == close) { q.p++; break; }
            ok = false; break;
        }
    } else if (c == '"') {
        v.t = ModsJson::STR;
        ok = mods_json_str(q, v.s);
    } else if (c == '-' || (c >= '0' && c <= '9')) {
        v.t = ModsJson::NUM;
        const char* s = q.p;
        bool plain = c != '-';
        uint64_t n = 0;
        if (*q.p == '-') q.p++;
        while (q.p < q.e && ((*q.p >= '0' && *q.p <= '9') || *q.p == '.' || *q.p == 'e' || *q.p == 'E' || *q.p == '+' || *q.p == '-')) {
            if (*q.p >= '0' && *q.p <= '9') { if (n > (UINT64_MAX - 9) / 10) plain = false; n = n * 10 + (uint64_t)(*q.p - '0'); }
            else plain = false;
            q.p++;
        }
        ok = q.p > s && !(q.p == s + 1 && c == '-');
        v.uint = plain; v.n = plain ? n : 0;
    } else {
        static const struct { const char* w; ModsJson::Type t; } lits[] = {
            { "true", ModsJson::BOOL }, { "false", ModsJson::BOOL }, { "null", ModsJson::NUL } };
        ok = false;
        for (const auto& l : lits) {
            const size_t n = strlen(l.w);
            if ((size_t)(q.e - q.p) >= n && !memcmp(q.p, l.w, n)) { q.p += n; v.t = l.t; ok = true; break; }
        }
    }
    q.depth--;
    return ok;
}

/* ---- state ------------------------------------------------------------------ */

/* Bytes laid over a pack: a later mod merged in (its full pack: bytes at the same offset; or its .dlt: bytes at
 * doff[i]), or a delta mod's own changes. */
struct ModsLayer {
    std::string file;
    bool delta = false;
    std::vector<std::pair<uint64_t, uint64_t>> rng;       /* (offset, length) */
    std::vector<uint64_t> doff;                            /* delta: where range i's bytes are in file */
};

/* An original pack inside a PSARC (delta mods read it block by block). */
struct ModsSrc {
    std::string arc;
    uint64_t usz = 0;
    uint32_t bsz = 0;
    std::vector<uint64_t> boff;    /* file offset of each block of the entry */
    std::vector<uint32_t> bcsz;    /* its stored size; 0 = a full raw block */
};

struct ModsRepl {
    std::string key;    /* usrdir_path, lower case, no leading '/': the TOC name and the loose path's tail */
    std::string host;   /* <PS3_MODS_DIR>/<id>/<pack> (a delta mod: <pack>.dlt) */
    uint64_t size;
    std::string mod;    /* id */
    /* merge (2026-11-14): the textures this pack changes, from <pack>.rng beside it ("RNG1 <size> <n>", then n
     * lines "<hex offset> <hex length>", sorted). With them, mods that change DIFFERENT textures of one pack are all
     * used: the pack served is the first mod's copy with the later mods' ranges copied in (<PS3_MODS_DIR>/.merged).
     * A pack without a .rng keeps the old rule (it replaces the whole pack; a later mod on that pack is dropped). */
    bool has_rng = false;
    std::vector<std::pair<uint64_t, uint64_t>> rng;       /* (offset, length) */
    std::vector<ModsLayer> more;                           /* later mods merged in (their file, their ranges) */
    std::string mods_all;                                  /* ids, for the log */
    /* delta (2026-11-17): this mod's pack is <pack>.dlt over the original (src); has_rng/rng = the .dlt's
     * TEXTURES flag/ranges. virt: served by the overlay reader (ModsVFile) instead of a host file: the first mod
     * or any merged-in one is a delta. */
    bool delta = false;
    ModsLayer own;
    uint64_t orig_size = 0;
    int src = -1;                                          /* g_mods.src index */
    bool virt = false;
};

/* <pack>.rng -> ranges; false when it is missing or not exactly right (then the pack is "whole pack only"). */
static bool mods_read_small(const std::string& path, std::string& out, size_t cap);
static bool mods_load_rng(const std::string& pack_path, uint64_t size, std::vector<std::pair<uint64_t, uint64_t>>& out)
{
    std::string t;
    if (!mods_read_small(pack_path + ".rng", t, 1u << 20)) return false;
    unsigned long long fsz = 0, n = 0; int used = 0;
    if (sscanf(t.c_str(), "RNG1 %llu %llu%n", &fsz, &n, &used) != 2 || fsz != size || n == 0 || n > 100000) return false;
    const char* p = t.c_str() + used;
    uint64_t prev_end = 0;
    for (unsigned long long i = 0; i < n; i++) {
        unsigned long long off = 0, len = 0; int u = 0;
        if (sscanf(p, " %llx %llx%n", &off, &len, &u) != 2 || !len || off < prev_end || off + len > size) return false;
        out.emplace_back((uint64_t)off, (uint64_t)len);
        prev_end = off + len;
        p += u;
    }
    return true;
}
static bool mods_rng_overlap(const std::vector<std::pair<uint64_t, uint64_t>>& a, const std::vector<std::pair<uint64_t, uint64_t>>& b)
{
    size_t i = 0, j = 0;
    while (i < a.size() && j < b.size()) {
        if (a[i].first + a[i].second <= b[j].first) i++;
        else if (b[j].first + b[j].second <= a[i].first) j++;
        else return true;
    }
    return false;
}

struct ModsArc;
static struct {
    std::once_flag once;
    bool active;                    /* written once inside call_once, read after it */
    std::vector<ModsRepl> repl;     /* idem */
    std::vector<ModsSrc> src;       /* idem: originals of delta mods */
    std::mutex mx;
    std::set<std::string> logged;
    /* start-up only (inside call_once): the game's archives, for delta mods' originals */
    bool walked = false;
    std::vector<ModsArc*> arcs;
} g_mods;

static void mods_log_once(const std::string& key, const char* fmt, ...) __attribute__((format(printf, 2, 3)));
static void mods_log_once(const std::string& key, const char* fmt, ...)
{
    {
        std::lock_guard<std::mutex> lk(g_mods.mx);
        if (!g_mods.logged.insert(key).second) return;
    }
    char line[1400];
    va_list ap; va_start(ap, fmt); vsnprintf(line, sizeof line, fmt, ap); va_end(ap);
    fprintf(stderr, "[mods] %s\n", line);
}

static std::string mods_lower(const std::string& s)
{
    std::string o(s);
    for (char& c : o) if (c >= 'A' && c <= 'Z') c = (char)(c - 'A' + 'a');
    return o;
}

/* A mod id is a folder name: letters, digits, '_', '-', '.', not starting with '.'. */
static bool mods_id_ok(const std::string& id)
{
    if (id.empty() || id.size() > 128 || id[0] == '.') return false;
    for (char c : id)
        if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_' || c == '-' || c == '.'))
            return false;
    return true;
}

/* A relative name inside a mod / USRDIR: no '..', no '\', no absolute path, no empty part. */
static bool mods_rel_ok(const std::string& p, bool allow_dirs)
{
    if (p.empty() || p.size() > 255 || p[0] == '/' || p.back() == '/') return false;
    if (p.find('\\') != std::string::npos || p.find(':') != std::string::npos || p.find("//") != std::string::npos) return false;
    if (!allow_dirs && p.find('/') != std::string::npos) return false;
    size_t s = 0;
    for (;;) {
        const size_t e = p.find('/', s);
        const std::string part = p.substr(s, e == std::string::npos ? std::string::npos : e - s);
        if (part == "." || part == "..") return false;
        if (e == std::string::npos) return true;
        s = e + 1;
    }
}

static bool mods_read_small(const std::string& path, std::string& out, size_t cap)
{
    FILE* f = fopen(path.c_str(), "rb");
    if (!f) return false;
    char b[16384];
    size_t n;
    while ((n = fread(b, 1, sizeof b, f)) > 0) {
        if (out.size() + n > cap) { fclose(f); return false; }
        out.append(b, n);
    }
    const bool ok = !ferror(f);
    fclose(f);
    return ok;
}

static bool mods_file_sha256(const std::string& path, char hex[65])
{
    FILE* f = fopen(path.c_str(), "rb");
    if (!f) return false;
    ModsSha256 s; mods_sha_init(s);
    std::vector<uint8_t> b(1u << 20);
    size_t n;
    while ((n = fread(b.data(), 1, b.size(), f)) > 0) mods_sha_add(s, b.data(), n);
    const bool ok = !ferror(f);
    fclose(f);
    if (ok) mods_sha_hex(s, hex);
    return ok;
}

/* ---- delta mods (2026-11-17): originals, the overlay reader ---------------- */

static uint64_t mods_le(const uint8_t* p, int n)
{
    uint64_t v = 0;
    for (int i = n - 1; i >= 0; i--) v = (v << 8) | p[i];
    return v;
}

static void mods_hex(const uint8_t* p, size_t n, char* out)
{
    for (size_t i = 0; i < n; i++) snprintf(out + 2 * i, 3, "%02x", p[i]);
}

/* Reads an original pack out of its PSARC: two decompressed blocks are kept (reads cross block edges). */
struct ModsSrcReader {
    const ModsSrc* s = nullptr;
    FILE* f = nullptr;
    long long blk[2] = { -1, -1 };
    std::vector<uint8_t> dat[2];
    int next = 0;
    std::vector<uint8_t> zin;
};

static const uint8_t* mods_src_block(ModsSrcReader& rd, uint64_t k, uint64_t& len)
{
    for (int i = 0; i < 2; i++)
        if (rd.blk[i] == (long long)k) { len = rd.dat[i].size(); return rd.dat[i].data(); }
    const ModsSrc& s = *rd.s;
    if (!rd.f || k >= s.boff.size()) return nullptr;
    const uint64_t left = s.usz - k * (uint64_t)s.bsz;
    const uint64_t want = left < s.bsz ? left : s.bsz;
    const uint32_t c = s.bcsz[k];
    const int slot = rd.next; rd.next ^= 1;
    rd.blk[slot] = -1;
    std::vector<uint8_t>& out = rd.dat[slot];
    out.resize((size_t)want);
    if (LANG_FSEEK(rd.f, s.boff[k]) != 0) return nullptr;
    if (!c || c == want) {                     /* stored (as packlib.py / PSARC readers do) */
        if (fread(out.data(), 1, (size_t)want, rd.f) != want) return nullptr;
    } else {
        rd.zin.resize(c);
        if (fread(rd.zin.data(), 1, c, rd.f) != c) return nullptr;
        if (stbi_zlib_decode_buffer((char*)out.data(), (int)want, (const char*)rd.zin.data(), (int)c) != (int)want) return nullptr;
    }
    rd.blk[slot] = (long long)k;
    len = want;
    return out.data();
}

static bool mods_src_read(ModsSrcReader& rd, uint64_t off, uint64_t n, uint8_t* dst)
{
    const ModsSrc& s = *rd.s;
    if (off > s.usz || n > s.usz - off) return false;
    while (n) {
        const uint64_t k = off / s.bsz, in = off % s.bsz;
        uint64_t len = 0;
        const uint8_t* b = mods_src_block(rd, k, len);
        if (!b || in >= len) return false;
        const uint64_t t = (len - in) < n ? (len - in) : n;
        memcpy(dst, b + in, (size_t)t);
        dst += t; off += t; n -= t;
    }
    return true;
}

/* SHA-256 (hex) of the sample windows (format in the header comment). */
static bool mods_src_sample(ModsSrcReader& rd, uint64_t size, uint32_t cnt, uint32_t slen, char hex[65])
{
    ModsSha256 s; mods_sha_init(s);
    const uint64_t w = slen < size ? slen : size;
    std::vector<uint8_t> b((size_t)w);
    for (uint32_t k = 0; k < cnt && w; k++) {
        const uint64_t at = cnt == 1 ? 0 : (uint64_t)k * (size - w) / (cnt - 1);
        if (!mods_src_read(rd, at, w, b.data())) return false;
        mods_sha_add(s, b.data(), (size_t)w);
    }
    mods_sha_hex(s, hex);
    return true;
}

/* One of the game's PSARCs, parsed at start-up (TOC + name list). */
struct ModsArc {
    std::string path;
    uint32_t n = 0, esz = 0, bsz = 0;
    int nb = 0;
    std::vector<uint8_t> toc;              /* without the 32-byte header */
    std::vector<std::string> names;        /* line i = entry i+1, lower case, no leading '/' (as given) */
};

static bool mods_arc_parse(const std::string& path, ModsArc& a)
{
    FILE* f = fopen(path.c_str(), "rb");
    if (!f) return false;
    bool ok = false;
    uint8_t h[32];
    do {
        if (fread(h, 1, 32, f) != 32 || memcmp(h, "PSAR", 4)) break;
        const uint32_t toclen = (uint32_t)lang_be(h + 12, 4), esz = (uint32_t)lang_be(h + 16, 4);
        const uint32_t n = (uint32_t)lang_be(h + 20, 4), bsz = (uint32_t)lang_be(h + 24, 4);
        if (memcmp(h + 8, "zlib", 4) || esz != 30 || n < 2 || n > 1000000 || toclen < 32 + n * esz ||
            toclen > (64u << 20) || bsz == 0 || bsz > (16u << 20))
            break;
        a.toc.resize(toclen - 32);
        if (fread(a.toc.data(), 1, a.toc.size(), f) != a.toc.size()) break;
        a.n = n; a.esz = esz; a.bsz = bsz;
        a.nb = bsz <= 0x10000 ? 2 : bsz <= 0x1000000 ? 3 : 4;
        const size_t tab = (size_t)n * esz, nblocks = (a.toc.size() - tab) / (size_t)a.nb;
        const uint8_t* e0 = a.toc.data();
        uint64_t blk = lang_be(e0 + 16, 4);
        const uint64_t usz = lang_be(e0 + 20, 5), off = lang_be(e0 + 25, 5);
        if (usz == 0 || usz > (16u << 20)) break;
        std::vector<char> names; names.reserve((size_t)usz);
        std::vector<char> in(bsz), dec(bsz);
        if (LANG_FSEEK(f, off) != 0) break;
        bool bad = false;
        while (names.size() < usz) {
            if (blk >= nblocks) { bad = true; break; }
            const uint32_t c = (uint32_t)lang_be(a.toc.data() + tab + blk * a.nb, a.nb);
            blk++;
            const uint32_t take = c ? c : bsz;
            if (take > bsz || fread(in.data(), 1, take, f) != take) { bad = true; break; }
            const size_t want = (size_t)(usz - names.size()) < bsz ? (size_t)(usz - names.size()) : bsz;
            int got = -1;
            if (c && (uint8_t)in[0] == 0x78)
                got = stbi_zlib_decode_buffer(dec.data(), (int)bsz, in.data(), (int)take);
            if (got > 0) names.insert(names.end(), dec.data(), dec.data() + (got < (int)want ? got : (int)want));
            else names.insert(names.end(), in.data(), in.data() + (take < want ? take : want));
        }
        if (bad) break;
        for (size_t s = 0; s < names.size() && a.names.size() + 1 < n;) {
            size_t e = s;
            while (e < names.size() && names[e] != '\n') e++;
            std::string line(names.data() + s, e - s);
            s = e + 1;
            if (!line.empty() && line.back() == '\r') line.pop_back();
            a.names.push_back(line);
        }
        a.path = path;
        ok = true;
    } while (0);
    fclose(f);
    return ok;
}

/* Every *.psarc / *.psarc_s under dir (depth and entry count capped; '.' names skipped). */
static void mods_walk(const std::string& dir, int depth, std::vector<std::string>& out, int& budget)
{
    if (depth > 10 || budget <= 0) return;
    DIR* d = opendir(dir.c_str());
    if (!d) return;
    std::vector<std::string> sub;
    while (struct dirent* e = readdir(d)) {
        if (--budget <= 0) break;
        const char* nm = e->d_name;
        if (nm[0] == '.') continue;
        const std::string p = dir + "/" + nm;
        struct stat st;
        if (stat(p.c_str(), &st) != 0) continue;
        if ((st.st_mode & S_IFMT) == S_IFDIR) { sub.push_back(p); continue; }
        if ((st.st_mode & S_IFMT) != S_IFREG) continue;
        const std::string low = mods_lower(nm);
        const size_t l = low.size();
        if ((l > 6 && !low.compare(l - 6, 6, ".psarc")) || (l > 8 && !low.compare(l - 8, 8, ".psarc_s"))) out.push_back(p);
    }
    closedir(d);
    for (const std::string& s : sub) mods_walk(s, depth + 1, out, budget);
}

static void mods_walk_archives(void)
{
    if (g_mods.walked) return;
    g_mods.walked = true;
    struct timespec t0, t1; clock_gettime(CLOCK_MONOTONIC, &t0);
    std::vector<std::string> roots;
    roots.push_back(ppu_vfs_root && *ppu_vfs_root ? ppu_vfs_root : ".");
    if (const char* h = getenv("PS3_HDD0_ROOT")) if (*h) roots.push_back(h);
    std::vector<std::string> files;
    int budget = 200000;
    std::string walked;
    for (size_t i = 0; i < roots.size(); i++) {
        bool inside = false;   /* PS3_HDD0_ROOT inside the VFS root: walked already */
        for (size_t j = 0; j < i; j++)
            inside |= roots[i].size() >= roots[j].size() && !roots[i].compare(0, roots[j].size(), roots[j]) &&
                      (roots[i].size() == roots[j].size() || roots[i][roots[j].size()] == '/');
        if (inside) continue;
        mods_walk(roots[i], 0, files, budget);
        walked += (walked.empty() ? "" : " and ") + roots[i];
    }
    std::sort(files.begin(), files.end());
    files.erase(std::unique(files.begin(), files.end()), files.end());
    for (const std::string& p : files) {
        ModsArc* a = new ModsArc;
        if (mods_arc_parse(p, *a)) g_mods.arcs.push_back(a);
        else delete a;
    }
    clock_gettime(CLOCK_MONOTONIC, &t1);
    fprintf(stderr, "[mods] delta mods: %zu of %zu archives under %s read for originals (%.0f ms)\n",
            g_mods.arcs.size(), files.size(), walked.c_str(), ((t1.tv_sec - t0.tv_sec) * 1e9 + (t1.tv_nsec - t0.tv_nsec)) / 1e6);
}

static void mods_walk_free(void)
{
    for (ModsArc* a : g_mods.arcs) delete a;
    g_mods.arcs.clear();
}

/* The entry of key in a: its blocks, or false. */
static bool mods_arc_entry(const ModsArc& a, const std::string& key, ModsSrc& s)
{
    for (size_t i = 0; i < a.names.size(); i++) {
        const std::string& line = a.names[i];
        if (mods_lower(!line.empty() && line[0] == '/' ? line.substr(1) : line) != key) continue;
        /* The key is MD5 of the upper-cased path (as mods_scan_psarc checks it): line i is entry i+1, else
         * the entry with that key. */
        std::string up(line);
        for (char& c : up) if (c >= 'a' && c <= 'z') c = (char)(c - 'a' + 'A');
        uint8_t want[16];
        mods_md5((const uint8_t*)up.data(), up.size(), want);
        uint32_t ent = (uint32_t)i + 1;
        if (memcmp(a.toc.data() + (size_t)ent * a.esz, want, 16) != 0) {
            ent = 0;
            for (uint32_t j = 1; j < a.n; j++)
                if (!memcmp(a.toc.data() + (size_t)j * a.esz, want, 16)) { ent = j; break; }
            if (!ent) continue;
        }
        const uint8_t* e = a.toc.data() + (size_t)ent * a.esz;
        const uint64_t blk0 = lang_be(e + 16, 4), usz = lang_be(e + 20, 5), off = lang_be(e + 25, 5);
        const size_t tab = (size_t)a.n * a.esz, nblocks = (a.toc.size() - tab) / (size_t)a.nb;
        const uint64_t nblk = (usz + a.bsz - 1) / a.bsz;
        if (blk0 + nblk > nblocks) continue;
        s = ModsSrc();
        s.arc = a.path; s.usz = usz; s.bsz = a.bsz;
        uint64_t at = off;
        for (uint64_t k = 0; k < nblk; k++) {
            const uint32_t c = (uint32_t)lang_be(a.toc.data() + tab + (blk0 + k) * a.nb, a.nb);
            if (c > a.bsz) { s.boff.clear(); break; }
            s.boff.push_back(at); s.bcsz.push_back(c);
            at += c ? c : a.bsz;
        }
        if (s.boff.size() != nblk) continue;
        return true;
    }
    return false;
}

/* <pack>.dlt -> r (delta, own, has_rng/rng, orig_size), the header's sample fields and built hash. */
struct ModsDltHdr { uint32_t scount, slen; uint8_t sample[32], built[32]; };
static bool mods_dlt_load(const std::string& path, ModsRepl& r, ModsDltHdr& dh, std::string& why)
{
    FILE* f = fopen(path.c_str(), "rb");
    if (!f) { why = "can't open " + path; return false; }
    uint8_t h[160];
    bool ok = fread(h, 1, 160, f) == 160 && !memcmp(h, "MODDLT1\0", 8) && mods_le(h + 8, 4) == 1;
    const uint32_t flags = (uint32_t)mods_le(h + 12, 4);
    const uint64_t size = mods_le(h + 16, 8), osz = mods_le(h + 24, 8);
    const uint64_t n = mods_le(h + 32, 4);
    dh.scount = (uint32_t)mods_le(h + 36, 4); dh.slen = (uint32_t)mods_le(h + 40, 4);
    memcpy(dh.sample, h + 80, 32); memcpy(dh.built, h + 112, 32);
    ok = ok && !(flags & ~1u) && n <= 4000000 && dh.scount >= 1 && dh.scount <= 256 && dh.slen >= 1 && dh.slen <= (1u << 20);
    std::vector<uint8_t> t;
    if (ok) { t.resize((size_t)n * 16); ok = fread(t.data(), 1, t.size(), f) == t.size(); }
    fclose(f);
    if (!ok) { why = path + " is not a delta this runtime reads (MODDLT1 version 1)"; return false; }
    r.own = ModsLayer();
    r.own.file = path; r.own.delta = true;
    uint64_t prev = 0, data = 160 + n * 16, tail = osz;   /* tail: bytes past the original must be covered */
    for (uint64_t i = 0; i < n; i++) {
        const uint64_t o = mods_le(t.data() + i * 16, 8), l = mods_le(t.data() + i * 16 + 8, 8);
        if (!l || o < prev || o > size || l > size - o) { why = path + ": bad range table"; return false; }
        if (o <= tail && o + l > tail) tail = o + l;
        r.own.rng.emplace_back(o, l);
        r.own.doff.push_back(data);
        data += l; prev = o + l;
    }
    if (tail < size) { why = path + ": bytes past the original's end are not all in the delta"; return false; }
    struct stat st;
    if (stat(path.c_str(), &st) != 0 || (uint64_t)st.st_size != data) { why = path + " is cut short or too long"; return false; }
    if (size != r.size) {
        char b[160];
        snprintf(b, sizeof b, " makes %llu bytes, mod.json says %llu", (unsigned long long)size, (unsigned long long)r.size);
        why = path + b; return false;
    }
    r.delta = true;
    r.orig_size = osz;
    r.has_rng = (flags & 1u) && size == osz && n > 0;
    r.rng = r.has_rng ? r.own.rng : std::vector<std::pair<uint64_t, uint64_t>>();
    return true;
}

/* The original r's delta was made from: a copy in the game's archives with that size and sample. */
static bool mods_dlt_find_orig(ModsRepl& r, const ModsDltHdr& dh, std::string& why)
{
    mods_walk_archives();
    char want[65]; mods_hex(dh.sample, 32, want);
    int tried = 0;
    for (const ModsArc* a : g_mods.arcs) {
        ModsSrc s;
        if (!mods_arc_entry(*a, r.key, s)) continue;
        tried++;
        if (s.usz != r.orig_size) continue;
        for (size_t i = 0; i < g_mods.src.size(); i++)   /* this copy is in use already (another delta) */
            if (g_mods.src[i].arc == s.arc && g_mods.src[i].boff == s.boff) { r.src = (int)i; break; }
        ModsSrcReader rd; rd.s = &s; rd.f = fopen(s.arc.c_str(), "rb");
        char hex[65] = {0};
        const bool got = rd.f && mods_src_sample(rd, s.usz, dh.scount, dh.slen, hex);
        if (rd.f) fclose(rd.f);
        if (!got || strcmp(hex, want)) { r.src = -1; continue; }
        if (r.src < 0) { g_mods.src.push_back(s); r.src = (int)g_mods.src.size() - 1; }
        return true;
    }
    char b[200];
    snprintf(b, sizeof b, "its original %s (%llu bytes) is not in this copy of the game (%d archive copies of it checked)",
             r.key.c_str(), (unsigned long long)r.orig_size, tried);
    why = b;
    return false;
}

/* An open delta-served pack: what the game's descriptor reads. */
struct ModsVFile {
    const ModsRepl* r = nullptr;
    std::mutex mx;
    uint64_t pos = 0;
    ModsSrcReader src;                     /* r->delta: the original */
    FILE* base = nullptr;                  /* else: the first mod's full pack */
    std::vector<const ModsLayer*> lay;     /* laid over the base in this order (later wins) */
    std::vector<FILE*> lf;
    bool said = false;
};
static ModsVFile* g_mods_vf[LANG_FD_MAX];

static void mods_vf_free(ModsVFile* v)
{
    if (!v) return;
    if (v->src.f) fclose(v->src.f);
    if (v->base) fclose(v->base);
    for (FILE* f : v->lf) if (f) fclose(f);
    delete v;
}

static ModsVFile* mods_vf_make(const ModsRepl* r)
{
    ModsVFile* v = new ModsVFile;
    v->r = r;
    bool ok = true;
    if (r->delta) {
        v->src.s = &g_mods.src[(size_t)r->src];
        ok = (v->src.f = fopen(v->src.s->arc.c_str(), "rb")) != nullptr;
        v->lay.push_back(&r->own);
    } else ok = (v->base = fopen(r->host.c_str(), "rb")) != nullptr;
    for (const ModsLayer& m : r->more) v->lay.push_back(&m);
    for (const ModsLayer* m : v->lay) { FILE* f = ok ? fopen(m->file.c_str(), "rb") : nullptr; v->lf.push_back(f); ok = ok && f; }
    if (!ok) { mods_vf_free(v); return nullptr; }
    return v;
}

/* n bytes at off of the served pack into dst (caller holds v->mx); the count read (short at the end). */
static size_t mods_vf_pread_locked(ModsVFile* v, uint64_t off, uint8_t* dst, uint64_t n)
{
    const ModsRepl* r = v->r;
    if (off >= r->size || !n) return 0;
    if (n > r->size - off) n = r->size - off;
    const uint64_t end = off + n;
    struct Hit { uint64_t lo, hi; size_t layer, i; };
    std::vector<Hit> hits;
    for (size_t L = 0; L < v->lay.size(); L++) {
        const auto& g = v->lay[L]->rng;
        size_t i = (size_t)(std::upper_bound(g.begin(), g.end(), std::make_pair(off, UINT64_MAX)) - g.begin());
        if (i) i--;
        for (; i < g.size() && g[i].first < end; i++) {
            const uint64_t lo = g[i].first > off ? g[i].first : off, hi = (g[i].first + g[i].second) < end ? (g[i].first + g[i].second) : end;
            if (lo < hi) hits.push_back({ lo, hi, L, i });
        }
    }
    /* the base, where no layer covers it */
    std::vector<std::pair<uint64_t, uint64_t>> cov;
    for (const Hit& h : hits) cov.emplace_back(h.lo, h.hi);
    std::sort(cov.begin(), cov.end());
    const uint64_t bsize = r->delta ? r->orig_size : r->size;
    bool ok = true;
    uint64_t at = off;
    size_t ci = 0;
    while (ok && at < end) {
        while (ci < cov.size() && cov[ci].second <= at) ci++;
        if (ci < cov.size() && cov[ci].first <= at) { at = cov[ci].second; continue; }
        const uint64_t gend = ci < cov.size() && cov[ci].first < end ? cov[ci].first : end;
        const uint64_t have = at < bsize ? ((gend < bsize ? gend : bsize) - at) : 0;
        if (have) {
            if (r->delta) ok = mods_src_read(v->src, at, have, dst + (at - off));
            else ok = LANG_FSEEK(v->base, at) == 0 && fread(dst + (at - off), 1, (size_t)have, v->base) == have;
        }
        if (gend > at + have) memset(dst + (at + have - off), 0, (size_t)(gend - at - have));   /* never, when validated */
        at = gend;
    }
    /* the layers, in order */
    for (size_t k = 0; ok && k < hits.size(); k++) {
        const Hit& h = hits[k];
        const ModsLayer& m = *v->lay[h.layer];
        const uint64_t from = m.delta ? m.doff[h.i] + (h.lo - m.rng[h.i].first) : h.lo;
        ok = LANG_FSEEK(v->lf[h.layer], from) == 0 && fread(dst + (h.lo - off), 1, (size_t)(h.hi - h.lo), v->lf[h.layer]) == h.hi - h.lo;
    }
    if (!ok) {
        if (!v->said) { v->said = true; fprintf(stderr, "[mods] %s: a read of %llu bytes at %llu failed (archive or mod file)\n",
                                                 r->key.c_str(), (unsigned long long)n, (unsigned long long)off); }
        return 0;
    }
    return (size_t)n;
}

/* ---- for ppu_fs.cpp: the descriptor of a delta-served pack ----------------- */

static ModsVFile* mods_vf(int fd)
{
    return (fd >= 0 && fd < LANG_FD_MAX) ? g_mods_vf[fd] : nullptr;
}

/* fd was opened on a virt replacement (mods_redirect_host returned r): false = it could not be set up. */
static bool mods_vf_open(int fd, const ModsRepl* r)
{
    if (fd < 0 || fd >= LANG_FD_MAX) return false;
    ModsVFile* v = mods_vf_make(r);
    if (!v) { fprintf(stderr, "[mods] %s: can't open the files it is served from\n", r->key.c_str()); return false; }
    mods_vf_free(g_mods_vf[fd]);
    g_mods_vf[fd] = v;
    return true;
}

static void mods_vf_close(int fd)
{
    if (fd < 0 || fd >= LANG_FD_MAX || !g_mods_vf[fd]) return;
    ModsVFile* v = g_mods_vf[fd];
    g_mods_vf[fd] = nullptr;
    mods_vf_free(v);
}

static uint64_t mods_vf_tell(ModsVFile* v) { std::lock_guard<std::mutex> lk(v->mx); return v->pos; }

/* cellFsRead: at the descriptor's position, which moves on. */
static size_t mods_vf_read(ModsVFile* v, uint8_t* dst, uint64_t n)
{
    std::lock_guard<std::mutex> lk(v->mx);
    const size_t got = mods_vf_pread_locked(v, v->pos, dst, n);
    v->pos += got;
    return got;
}

/* cellFsAioRead: at off; the position ends after what was read (as fseeko + fread on the host FILE do). */
static size_t mods_vf_pread(ModsVFile* v, uint64_t off, uint8_t* dst, uint64_t n)
{
    std::lock_guard<std::mutex> lk(v->mx);
    const size_t got = mods_vf_pread_locked(v, off, dst, n);
    v->pos = off + got;
    return got;
}

/* cellFsLseek: as fseek + ftell on a file of r->size bytes (a negative result leaves the position). */
static uint64_t mods_vf_seek(ModsVFile* v, int64_t off, int whence)
{
    std::lock_guard<std::mutex> lk(v->mx);
    const int64_t b = whence == SEEK_END ? (int64_t)v->r->size : whence == SEEK_CUR ? (int64_t)v->pos : 0;
    const int64_t p = b + off;
    if (p >= 0) v->pos = (uint64_t)p;
    return v->pos;
}

/* PS3_MODS_VERIFY: a delta mod's own pack (original + its delta), hashed. */
static bool mods_dlt_verify(const ModsRepl& r, const std::string& want_hex)
{
    ModsRepl t = r;
    t.more.clear();
    ModsVFile* v = mods_vf_make(&t);
    if (!v) return false;
    ModsSha256 s; mods_sha_init(s);
    std::vector<uint8_t> b(1u << 20);
    bool ok = true;
    for (uint64_t at = 0; ok && at < t.size;) {
        const uint64_t n = (t.size - at) < b.size() ? (t.size - at) : b.size();
        ok = mods_vf_pread_locked(v, at, b.data(), n) == n;
        mods_sha_add(s, b.data(), (size_t)n);
        at += n;
    }
    mods_vf_free(v);
    char hex[65] = {0};
    if (ok) mods_sha_hex(s, hex);
    return ok && mods_lower(want_hex) == hex;
}

/* One enabled mod: its replacements, or false with the reason in why. */
static bool mods_load_one(const std::string& dir, const std::string& id, bool verify,
                          std::vector<ModsRepl>& mine, std::string& why, double& hash_s)
{
    const std::string mj = dir + "/" + id + "/mod.json";
    std::string text;
    if (!mods_read_small(mj, text, 8u << 20)) { why = "no readable " + mj; return false; }
    ModsJson root;
    ModsJsonIn q = { text.data(), text.data() + text.size(), 0 };
    if (!mods_json_val(q, root) || root.t != ModsJson::OBJ) { why = mj + " is not valid JSON"; return false; }
    if (const ModsJson* jid = root.get("id"))
        if (jid->t == ModsJson::STR && jid->s != id)
            fprintf(stderr, "[mods] %s: mod.json says id \"%s\"; using the folder name\n", id.c_str(), jid->s.c_str());
    const ModsJson* files = root.get("files");
    if (!files || files->t != ModsJson::ARR || files->kids.empty()) { why = "mod.json lists no files"; return false; }
    for (const ModsJson& fo : files->kids) {
        const ModsJson* pk = fo.get("pack");
        const ModsJson* up = fo.get("usrdir_path");
        const ModsJson* sz = fo.get("size");
        const ModsJson* sh = fo.get("built_sha256");
        if (!pk || pk->t != ModsJson::STR || !mods_rel_ok(pk->s, false)) { why = "a files[] entry has no usable \"pack\""; return false; }
        const std::string rel = (up && up->t == ModsJson::STR) ? up->s : pk->s;
        if (!mods_rel_ok(rel, true)) { why = "bad usrdir_path \"" + rel + "\""; return false; }
        if (!sz || sz->t != ModsJson::NUM || !sz->uint) { why = pk->s + " has no size"; return false; }
        ModsRepl r;
        r.key = mods_lower(rel);
        r.host = dir + "/" + id + "/" + pk->s;
        r.size = sz->n;
        r.mod = id;
        if (r.host.size() >= 1000) { why = "path too long: " + r.host; return false; }
        struct stat st;
        if (stat(r.host.c_str(), &st) != 0 || (st.st_mode & S_IFMT) != S_IFREG) {
            /* delta (2026-11-17): no full pack, but <pack>.dlt over the game's original */
            const std::string dl = r.host + ".dlt";
            if (stat(dl.c_str(), &st) != 0 || (st.st_mode & S_IFMT) != S_IFREG) { why = "missing " + r.host; return false; }
            ModsDltHdr dh;
            if (!mods_dlt_load(dl, r, dh, why)) return false;
            if (!mods_dlt_find_orig(r, dh, why)) return false;
            r.host = dl;
            r.mods_all = id;
            if (verify) {
                if (!sh || sh->t != ModsJson::STR || sh->s.size() != 64) { why = pk->s + " has no built_sha256 to verify"; return false; }
                char hh[65]; mods_hex(dh.built, 32, hh);
                struct timespec t0, t1; clock_gettime(CLOCK_MONOTONIC, &t0);
                const bool ok = mods_lower(sh->s) == hh && mods_dlt_verify(r, sh->s);
                clock_gettime(CLOCK_MONOTONIC, &t1);
                hash_s += (double)(t1.tv_sec - t0.tv_sec) + (t1.tv_nsec - t0.tv_nsec) / 1e9;
                if (!ok) { why = pk->s + ".dlt over the original fails its SHA-256 check"; return false; }
                fprintf(stderr, "[mods] %s: %s: original + delta == built_sha256 (verified)\n", id.c_str(), r.key.c_str());
            }
            for (const ModsRepl& o : mine)
                if (o.key == r.key) { why = "lists " + rel + " twice"; return false; }
            mine.push_back(r);
            continue;
        }
        r.has_rng = mods_load_rng(r.host, r.size, r.rng);
        r.mods_all = id;
        if ((uint64_t)st.st_size != r.size) {
            char b[200];
            snprintf(b, sizeof b, "%s is %llu bytes, mod.json says %llu", pk->s.c_str(),
                     (unsigned long long)st.st_size, (unsigned long long)r.size);
            why = b; return false;
        }
        if (verify) {
            if (!sh || sh->t != ModsJson::STR || sh->s.size() != 64) { why = pk->s + " has no built_sha256 to verify"; return false; }
            struct timespec t0, t1; clock_gettime(CLOCK_MONOTONIC, &t0);
            char hex[65] = {0};
            const bool ok = mods_file_sha256(r.host, hex);
            clock_gettime(CLOCK_MONOTONIC, &t1);
            hash_s += (double)(t1.tv_sec - t0.tv_sec) + (t1.tv_nsec - t0.tv_nsec) / 1e9;
            if (!ok || mods_lower(sh->s) != hex) { why = pk->s + " fails its SHA-256 check"; return false; }
        }
        for (const ModsRepl& o : mine)
            if (o.key == r.key) { why = "lists " + rel + " twice"; return false; }
        mine.push_back(r);
    }
    return true;
}

/* The merged copy of one pack: <dir>/.merged/<pack name>.<md5 of what went in>; made once per combination (an older
 * combination's file for the same pack is removed). On any failure the first mod's own pack stays in use and the
 * later mods' textures of this pack are left out, with a log line. */
static void mods_merge_build(const std::string& dir, ModsRepl& r)
{
    std::string what = r.host;
    struct stat st;
    auto stamp = [&](const std::string& p) {
        char b[96] = "";
        if (stat(p.c_str(), &st) == 0) snprintf(b, sizeof b, ":%llu:%lld;", (unsigned long long)st.st_size, (long long)st.st_mtime);
        what += b;
    };
    stamp(r.host);
    for (const auto& m : r.more) {
        what += m.file; stamp(m.file);
        for (const auto& g : m.rng) { char b[48]; snprintf(b, sizeof b, "%llx+%llx,", (unsigned long long)g.first, (unsigned long long)g.second); what += b; }
    }
    uint8_t md[16]; mods_md5((const uint8_t*)what.data(), what.size(), md);
    char hex[33]; for (int i = 0; i < 16; i++) snprintf(hex + 2 * i, 3, "%02x", md[i]);
    std::string flat = r.key; for (char& c : flat) if (c == '/') c = '_';
    const std::string mdir = dir + "/.merged", out = mdir + "/" + flat + "." + hex, tmp = out + ".tmp";
    if (stat(out.c_str(), &st) == 0 && (uint64_t)st.st_size == r.size) {
        fprintf(stderr, "[mods] %s: merged copy of %s in use (%s)\n", r.key.c_str(), r.mods_all.c_str(), out.c_str());
        r.host = out; return;
    }
    mkdir(mdir.c_str(), 0777);
    if (DIR* dp = opendir(mdir.c_str())) {   /* older combinations of this pack */
        const std::string pre = flat + ".";
        while (struct dirent* de = readdir(dp))
            if (!strncmp(de->d_name, pre.c_str(), pre.size())) unlink((mdir + "/" + de->d_name).c_str());
        closedir(dp);
    }
    struct timespec t0, t1; clock_gettime(CLOCK_MONOTONIC, &t0);
    FILE* in = fopen(r.host.c_str(), "rb");
    FILE* o = fopen(tmp.c_str(), "wb+");
    bool ok = in && o;
    std::vector<uint8_t> b(1u << 20);
    uint64_t done = 0;
    while (ok && done < r.size) {
        const size_t n = fread(b.data(), 1, b.size(), in);
        if (!n) break;
        ok = fwrite(b.data(), 1, n, o) == n;
        done += n;
    }
    ok = ok && done == r.size;
    if (in) fclose(in);
    size_t ntex = 0;
    for (size_t m = 0; ok && m < r.more.size(); m++) {
        FILE* src = fopen(r.more[m].file.c_str(), "rb");
        ok = src != nullptr;
        for (size_t g = 0; ok && g < r.more[m].rng.size(); g++) {
            uint64_t off = r.more[m].rng[g].first, left = r.more[m].rng[g].second;
            ok = fseek(src, (long)off, SEEK_SET) == 0 && fseek(o, (long)off, SEEK_SET) == 0;
            while (ok && left) {
                const size_t want = left < b.size() ? (size_t)left : b.size();
                ok = fread(b.data(), 1, want, src) == want && fwrite(b.data(), 1, want, o) == want;
                left -= want;
            }
            ntex++;
        }
        if (src) fclose(src);
    }
    if (o) ok = (fclose(o) == 0) && ok;
    if (ok) ok = rename(tmp.c_str(), out.c_str()) == 0;
    clock_gettime(CLOCK_MONOTONIC, &t1);
    if (!ok) {
        unlink(tmp.c_str());
        fprintf(stderr, "[mods] %s: could not write the merged copy (%s): only %s's textures are used in this pack\n",
                r.key.c_str(), out.c_str(), r.mod.c_str());
        return;
    }
    fprintf(stderr, "[mods] %s: merged copy of %s written (%zu textures added, %.1f MB, %.1f s): %s\n", r.key.c_str(), r.mods_all.c_str(),
            ntex, r.size / 1048576.0, (double)(t1.tv_sec - t0.tv_sec) + (t1.tv_nsec - t0.tv_nsec) / 1e9, out.c_str());
    r.host = out;
}

static void mods_init(void)
{
    std::call_once(g_mods.once, [] {
        const char* dir = getenv("PS3_MODS_DIR");
        const char* list = getenv("PS3_MODS");
        if (!dir || !*dir || !list || !*list) return;
        const char* vf = getenv("PS3_MODS_VERIFY");
        const bool verify = vf && *vf && strcmp(vf, "0") != 0;
        std::string d(dir);
        while (d.size() > 1 && (d.back() == '/' || d.back() == '\\')) d.pop_back();
        int asked = 0, used = 0;
        double hash_s = 0;
        uint64_t bytes = 0;
        std::vector<std::string> seen;
        for (const char* p = list; *p;) {
            const char* e = strchr(p, ',');
            std::string id(p, e ? (size_t)(e - p) : strlen(p));
            p = e ? e + 1 : p + strlen(p);
            while (!id.empty() && (id[0] == ' ' || id[0] == '\t')) id.erase(0, 1);
            while (!id.empty() && (id.back() == ' ' || id.back() == '\t' || id.back() == '\r' || id.back() == '\n')) id.pop_back();
            if (id.empty()) continue;
            asked++;
            if (!mods_id_ok(id)) { fprintf(stderr, "[mods] \"%s\" is not a mod id (a folder name): skipped\n", id.c_str()); continue; }
            bool dup = false;
            for (const std::string& s : seen) dup |= s == id;
            if (dup) { fprintf(stderr, "[mods] %s is listed twice: the first counts\n", id.c_str()); continue; }
            seen.push_back(id);
            std::vector<ModsRepl> mine;
            std::string why;
            if (!mods_load_one(d, id, verify, mine, why, hash_s)) {
                fprintf(stderr, "[mods] %s: not used (%s)\n", id.c_str(), why.c_str());
                continue;
            }
            /* First wins, per texture (merge, 2026-11-14): a later mod on a pack an earlier one has is merged in
             * when both list their ranges (<pack>.rng) and none overlap; otherwise it is dropped whole, as before. */
            const ModsRepl* clash = nullptr; const ModsRepl* mine_clash = nullptr; bool clash_tex = false;
            for (const ModsRepl& r : mine)
                for (const ModsRepl& o : g_mods.repl) {
                    if (clash || o.key != r.key) continue;
                    const bool both = o.has_rng && r.has_rng && o.size == r.size;
                    bool ok = both && !mods_rng_overlap(o.rng, r.rng);
                    for (size_t m = 0; ok && m < o.more.size(); m++) ok = !mods_rng_overlap(o.more[m].rng, r.rng);
                    if (!ok) { clash = &o; mine_clash = &r; clash_tex = both; }
                }
            if (clash) {
                fprintf(stderr, clash_tex ? "[mods] %s: not used (%s: it changes textures that %s, enabled before it, already changes)\n"
                                          : "[mods] %s: not used (%s is already replaced whole by %s, enabled before it)\n",
                        id.c_str(), mine_clash->key.c_str(), clash->mods_all.c_str());
                continue;
            }
            for (const ModsRepl& r : mine) {
                ModsRepl* base = nullptr;
                for (ModsRepl& o : g_mods.repl) if (o.key == r.key) base = &o;
                if (base) {
                    if (r.delta) base->more.push_back(r.own);
                    else { ModsLayer L; L.file = r.host; L.rng = r.rng; base->more.push_back(L); }
                    base->mods_all += "+" + id;
                    fprintf(stderr, "[mods] %s: %s: %zu textures merged into %s's copy\n", id.c_str(), r.key.c_str(), r.rng.size(), base->mod.c_str());
                    continue;
                }
                if (r.delta) {
                    uint64_t db = 0;
                    for (const auto& g : r.own.rng) db += g.second;
                    fprintf(stderr, "[mods] %s: %s <- %s (%llu bytes: %zu ranges, %.1f KB over the original in %s)\n", id.c_str(),
                            r.key.c_str(), r.host.c_str(), (unsigned long long)r.size, r.own.rng.size(), db / 1024.0,
                            g_mods.src[(size_t)r.src].arc.c_str());
                } else
                fprintf(stderr, "[mods] %s: %s <- %s (%llu bytes)\n", id.c_str(), r.key.c_str(), r.host.c_str(),
                        (unsigned long long)r.size);
                bytes += r.size;
                g_mods.repl.push_back(r);
            }
            used++;
        }
        for (ModsRepl& r : g_mods.repl) {
            bool dl = r.delta;
            for (const ModsLayer& m : r.more) dl |= m.delta;
            if (dl) {   /* a delta in it: served by the overlay reader, nothing written */
                r.virt = true;
                if (!r.more.empty())
                    fprintf(stderr, "[mods] %s: %s served merged from %s's %s + %zu more mods' textures (no copy written)\n",
                            r.key.c_str(), r.mods_all.c_str(), r.mod.c_str(), r.delta ? "delta" : "pack", r.more.size());
            } else if (!r.more.empty()) mods_merge_build(d, r);
        }
        mods_walk_free();
        g_mods.active = !g_mods.repl.empty();
        char hs[80] = "";
        if (verify) snprintf(hs, sizeof hs, ", SHA-256 checked in %.1f s", hash_s);
        fprintf(stderr, "[mods] %d of %d enabled mods in use: %zu packs (%.1f MB) served from %s%s\n",
                used, asked, g_mods.repl.size(), bytes / 1048576.0, d.c_str(), hs);
    });
}

static bool mods_active(void)
{
    mods_init();
    return g_mods.active;
}

/* ---- hide: an archive was opened ------------------------------------------- */

/* Give the TOC record of every replaced pack in this PSARC another key. */
static void mods_scan_psarc(FILE* f, const char* hpath, std::vector<LangPatch>& out)
{
    if (!mods_active()) return;
    uint8_t h[32];
    if (LANG_FSEEK(f, 0) != 0 || fread(h, 1, 32, f) != 32 || memcmp(h, "PSAR", 4)) return;
    const uint32_t toclen = (uint32_t)lang_be(h + 12, 4), esz = (uint32_t)lang_be(h + 16, 4);
    const uint32_t n = (uint32_t)lang_be(h + 20, 4), bsz = (uint32_t)lang_be(h + 24, 4);
    if (memcmp(h + 8, "zlib", 4) || esz != 30 || n < 2 || n > 1000000 || toclen < 32 + n * esz ||
        toclen > (64u << 20) || bsz == 0 || bsz > (16u << 20))
        return;
    std::vector<uint8_t> toc(toclen - 32);
    if (fread(toc.data(), 1, toc.size(), f) != toc.size()) return;
    const int nb = bsz <= 0x10000 ? 2 : bsz <= 0x1000000 ? 3 : 4;
    const size_t tab = (size_t)n * esz, nblocks = (toc.size() - tab) / (size_t)nb;
    /* Entry 0 is the name list (as lang_scan_psarc reads it). */
    const uint8_t* e0 = toc.data();
    uint64_t blk = lang_be(e0 + 16, 4), usz = lang_be(e0 + 20, 5), off = lang_be(e0 + 25, 5);
    if (usz == 0 || usz > (16u << 20)) return;
    std::vector<char> names; names.reserve((size_t)usz);
    std::vector<char> in(bsz), dec(bsz);
    if (LANG_FSEEK(f, off) != 0) return;
    while (names.size() < usz) {
        if (blk >= nblocks) return;
        const uint32_t c = (uint32_t)lang_be(toc.data() + tab + blk * nb, nb);
        blk++;
        const uint32_t take = c ? c : bsz;
        if (take > bsz || fread(in.data(), 1, take, f) != take) return;
        const size_t want = (size_t)(usz - names.size()) < bsz ? (size_t)(usz - names.size()) : bsz;
        int got = -1;
        if (c && (uint8_t)in[0] == 0x78)
            got = stbi_zlib_decode_buffer(dec.data(), (int)bsz, in.data(), (int)take);
        if (got > 0) names.insert(names.end(), dec.data(), dec.data() + (got < (int)want ? got : (int)want));
        else names.insert(names.end(), in.data(), in.data() + (take < want ? take : want));
    }
    const char* base = strrchr(hpath, '/'); base = base ? base + 1 : hpath;
    uint32_t idx = 1;
    for (size_t s = 0; s < names.size() && idx < n; idx++) {
        size_t e = s;
        while (e < names.size() && names[e] != '\n') e++;
        std::string line(names.data() + s, e - s);
        s = e + 1;
        if (!line.empty() && line.back() == '\r') line.pop_back();
        if (line.empty()) continue;
        const std::string key = mods_lower(line[0] == '/' ? line.substr(1) : line);
        const ModsRepl* r = nullptr;
        for (const ModsRepl& x : g_mods.repl) if (x.key == key) { r = &x; break; }
        if (!r) continue;
        /* The key is MD5 of the upper-cased path (flags 3: ignore case, absolute). Check that
         * line i really is entry i+1; else find the entry by its key; never guess. */
        std::string up(line);
        for (char& c : up) if (c >= 'a' && c <= 'z') c = (char)(c - 'a' + 'A');
        uint8_t want[16];
        mods_md5((const uint8_t*)up.data(), up.size(), want);
        uint32_t ent = idx;
        if (memcmp(toc.data() + (size_t)ent * esz, want, 16) != 0) {
            ent = 0;
            for (uint32_t j = 1; j < n; j++)
                if (!memcmp(toc.data() + (size_t)j * esz, want, 16)) { ent = j; break; }
        }
        char lk[1200];
        snprintf(lk, sizeof lk, "hide:%s:%s", hpath, key.c_str());
        if (!ent) {
            mods_log_once(lk, "%s: no TOC entry has the key of %s; it stays the archive's", base, line.c_str());
            continue;
        }
        /* The new key: MD5 of a name no archive holds; checked against every entry of this one. */
        std::string alt = "MODS-HIDDEN:" + up;
        uint8_t nk[16];
        bool clash = true;
        for (int tries = 0; clash && tries < 8; tries++) {
            mods_md5((const uint8_t*)alt.data(), alt.size(), nk);
            clash = false;
            for (uint32_t j = 0; j < n && !clash; j++) clash = !memcmp(toc.data() + (size_t)j * esz, nk, 16);
            alt += '#';
        }
        if (clash) continue;
        lang_add_patch(out, 32 + (uint64_t)ent * esz, nk, 16);
        mods_log_once(lk, "hid %s in %s (entry %u of %u): the game now opens it loose, from %s",
                      line.c_str(), base, ent, n, r->mod.c_str());
    }
}

/* ---- serve: a loose lookup -------------------------------------------------- */

/* A read-only open / stat of a guest path whose tail is a replaced pack's
 * usrdir_path: hpath becomes the mod's file. Only game data mounts count.
 * Returns the replacement when it is served by the overlay reader (virt: a
 * delta mod): hpath is then its .dlt (or the first mod's pack), which the
 * caller opens as a placeholder; reads, seeks and sizes come from mods_vf_*. */
static const ModsRepl* mods_redirect_host(const char* gpath, char* hpath, size_t cap)
{
    if (!mods_active()) return nullptr;
    if (strncmp(gpath, "/dev_hdd0/game/", 15) && strncmp(gpath, "/dev_bdvd/", 10) && strncmp(gpath, "/app_home/", 10))
        return nullptr;
    const size_t gl = strlen(gpath);
    for (const ModsRepl& r : g_mods.repl) {
        const size_t kl = r.key.size();
        if (gl <= kl || gpath[gl - kl - 1] != '/') continue;
        bool same = true;
        for (size_t i = 0; i < kl && same; i++) {
            char c = gpath[gl - kl + i];
            if (c >= 'A' && c <= 'Z') c = (char)(c - 'A' + 'a');
            same = c == r.key[i];
        }
        if (!same || r.host.size() >= cap) continue;
        snprintf(hpath, cap, "%s", r.host.c_str());
        mods_log_once(std::string("serve:") + gpath, "%s -> %s (%s%s)", gpath, r.host.c_str(),
                      r.virt ? r.mods_all.c_str() : r.mod.c_str(), r.virt ? ", overlay" : "");
        return r.virt ? &r : nullptr;
    }
    return nullptr;
}

#endif /* PPU_FS_MODS_H */
