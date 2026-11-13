/* udelta_dec.c - applies a UDP1 patch: rebuilds the Europe files from the USA files. Stream, 1 MB buffer.
   usage: udelta_dec <src_root> <out_root> <patch>      (out_root/subdirs must exist or be creatable by caller)
   Format (all integers big-endian):
     "UDP1"
     per output file: 'F' u16 nlen name[nlen] u16 slen src[slen] (slen 0 = new file) u64 size u32 crc32 u8 sha256[32]
                      then records:  'C' u64 src_offset u32 len   (copy from src file)
                                     'D' u32 len bytes[len]       (literal data)
                      'E' end of file
     'Z' end of patch
   The decoder checks size + CRC32 of every produced file (sha256 is there for installers that have one). */
#define _FILE_OFFSET_BITS 64
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#define BUF (1 << 20)
static uint8_t buf[BUF];
static uint32_t ctab[256];

static uint32_t crc(uint32_t c, const uint8_t *p, size_t n) {
    c = ~c;
    while (n--) c = ctab[(c ^ *p++) & 255] ^ (c >> 8);
    return ~c;
}
static int rd(FILE *f, void *p, size_t n) { return fread(p, 1, n, f) == n; }
static uint64_t be(FILE *f, int n, int *ok) {
    uint8_t b[8]; uint64_t v = 0;
    if (!rd(f, b, n)) { *ok = 0; return 0; }
    for (int i = 0; i < n; i++) v = v << 8 | b[i];
    return v;
}

int main(int argc, char **argv) {
    if (argc != 4) { fprintf(stderr, "usage: %s src_root out_root patch\n", argv[0]); return 2; }
    for (uint32_t i = 0; i < 256; i++) {
        uint32_t c = i;
        for (int k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320u ^ (c >> 1) : c >> 1;
        ctab[i] = c;
    }
    FILE *pf = fopen(argv[3], "rb");
    char magic[4];
    if (!pf || !rd(pf, magic, 4) || memcmp(magic, "UDP1", 4)) { fprintf(stderr, "bad patch\n"); return 1; }
    int ok = 1, bad = 0, nfiles = 0;
    for (;;) {
        int t = fgetc(pf);
        if (t == 'Z') break;
        if (t != 'F') { fprintf(stderr, "corrupt patch\n"); return 1; }
        char name[1024], src[1024], path[2200];
        uint64_t nl = be(pf, 2, &ok);
        if (!ok || nl >= sizeof name || !rd(pf, name, nl)) return 1;
        name[nl] = 0;
        uint64_t sl = be(pf, 2, &ok);
        if (!ok || sl >= sizeof src || !rd(pf, src, sl)) return 1;
        src[sl] = 0;
        uint64_t size = be(pf, 8, &ok);
        uint32_t want = (uint32_t)be(pf, 4, &ok);
        uint8_t sha[32];
        if (!ok || !rd(pf, sha, 32)) return 1;
        FILE *sf = NULL, *of;
        if (sl) {
            snprintf(path, sizeof path, "%s/%s", argv[1], src);
            if (!(sf = fopen(path, "rb"))) { fprintf(stderr, "missing source %s\n", path); return 1; }
        }
        snprintf(path, sizeof path, "%s/%s", argv[2], name);
        if (!(of = fopen(path, "wb"))) { fprintf(stderr, "cannot write %s\n", path); return 1; }
        uint32_t c = 0; uint64_t done = 0;
        for (;;) {
            t = fgetc(pf);
            if (t == 'E') break;
            if (t == 'C') {
                uint64_t off = be(pf, 8, &ok), len = be(pf, 4, &ok);
                if (!ok || !sf || fseek(sf, (long long)off, SEEK_SET)) { fprintf(stderr, "bad copy in %s\n", name); return 1; }
                while (len) {
                    size_t k = len > BUF ? BUF : len;
                    if (!rd(sf, buf, k)) { fprintf(stderr, "short source %s\n", src); return 1; }
                    fwrite(buf, 1, k, of); c = crc(c, buf, k); len -= k; done += k;
                }
            } else if (t == 'D') {
                uint64_t len = be(pf, 4, &ok);
                if (!ok) return 1;
                while (len) {
                    size_t k = len > BUF ? BUF : len;
                    if (!rd(pf, buf, k)) { fprintf(stderr, "short patch\n"); return 1; }
                    fwrite(buf, 1, k, of); c = crc(c, buf, k); len -= k; done += k;
                }
            } else { fprintf(stderr, "corrupt record in %s\n", name); return 1; }
        }
        if (sf) fclose(sf);
        if (fclose(of) || done != size || c != want) { fprintf(stderr, "FAIL %s\n", name); bad++; }
        nfiles++;
    }
    fclose(pf);
    printf("%d files written, %d bad\n", nfiles, bad);
    return bad ? 1 : 0;
}
