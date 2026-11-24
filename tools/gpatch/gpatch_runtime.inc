/*
 * gpatch_runtime.inc -- community RPCS3 game patches as on/off toggles (tools/gpatch).
 * Included at the END of game_patches.cpp through gpatch_<game>.inc (which holds this game's tables), so
 * it shares ppu_hash() and vm_base with the rest of that file. Nothing here runs unless PS3_GPATCH is set.
 *
 *   PS3_GPATCH=<id>,<id>,...   the toggles to switch on (ids from patch_catalog.json; unknown ids are logged)
 *
 * gpatch_init(elf_path) is called from infamous2_apply_patches(), i.e. once, right after ppu_load_elf() has
 * put the EBOOT into guest memory and before any guest code runs (not a static constructor: the launcher's
 * env.txt / launcher.ini values are in the environment by then on the console).
 *   - hook toggles: g_gpatch[k] = 1; the lifted code tests it at each patched site (gpatch_apply_<game>.py)
 *     and calls gpatch_first_fire(k) the first time a site runs (bit 2), which logs one line.
 *   - data toggles: their words are written now, each only where our EBOOT still holds the original value.
 *   - bundles switch their members on; toggles of one conflict group: the first listed wins.
 * gpatch_tick() (optional, once per frame from the present path) only WATCHES the policy-1 words (camera)
 * and logs once if the game rewrote one; RPCS3 also writes these patches once.
 */
extern "C" unsigned char g_gpatch[GPATCH_COUNT];
unsigned char g_gpatch[GPATCH_COUNT];

static uint32_t gp_rd(uint32_t ea, int w)
{
    const uint8_t* p = vm_base + ea;
    uint32_t v = 0;
    for (int i = 0; i < w; i++) v = v << 8 | p[i];
    return v;
}
static void gp_wr(uint32_t ea, int w, uint32_t v)
{
    uint8_t* p = vm_base + ea;
    for (int i = 0; i < w; i++) p[i] = (uint8_t)(v >> (8 * (w - 1 - i)));
}

extern "C" void gpatch_first_fire(int k)
{
    if (k < 0 || k >= GPATCH_COUNT) return;
    g_gpatch[k] |= 2;
    fprintf(stderr, "[gpatch] %s: first hit (patched code ran)\n", kGpatch[k].id);
}

static int gp_find(const char* s, size_t n)
{
    for (int k = 0; k < GPATCH_COUNT; k++)
        if (strlen(kGpatch[k].id) == n && !strncmp(kGpatch[k].id, s, n)) return k;
    return -1;
}

/* Write a data toggle's words; 0 if any word holds neither the original nor the patch value (other EBOOT). */
static int gp_data_apply(int k)
{
    int n = 0;
    for (size_t i = 0; i < GPATCH_DATA_N; i++) {
        const gpatch_data_t& d = kGpatchData[i];
        if (d.k != k) continue;
        const uint32_t v = gp_rd(d.ea, d.w);
        if (v != d.orig && v != d.value) {
            fprintf(stderr, "[gpatch] %s: 0x%08X holds 0x%08X, not this EBOOT's 0x%08X: nothing written\n",
                    kGpatch[k].id, d.ea, v, d.orig);
            return 0;
        }
    }
    for (size_t i = 0; i < GPATCH_DATA_N; i++)
        if (kGpatchData[i].k == k) { gp_wr(kGpatchData[i].ea, kGpatchData[i].w, kGpatchData[i].value); n++; }
    return n;
}

/* Put a data toggle's words back to the EBOOT's values (for an in-game switch later; not used at boot). */
extern "C" int gpatch_data_restore(int k)
{
    int n = 0;
    for (size_t i = 0; i < GPATCH_DATA_N; i++)
        if (kGpatchData[i].k == k) { gp_wr(kGpatchData[i].ea, kGpatchData[i].w, kGpatchData[i].orig); n++; }
    return n;
}

static void gp_switch_on(int k, int depth)
{
    const gpatch_toggle_t& t = kGpatch[k];
    if (g_gpatch[k]) return;
    if (t.group[0])
        for (int j = 0; j < GPATCH_COUNT; j++)
            if (j != k && g_gpatch[j] && !strcmp(kGpatch[j].group, t.group)) {
                fprintf(stderr, "[gpatch] %s: off, it conflicts with %s (on, listed first)\n", t.id, kGpatch[j].id);
                return;
            }
    if (t.kind == GPK_BUNDLE) {
        g_gpatch[k] = 1;
        fprintf(stderr, "[gpatch] on: %s \"%s\" (%s): bundle of %s\n", t.id, t.name, t.author, t.members);
        const char* m = t.members;
        while (*m && depth < 4) {
            const char* e = strchr(m, ',');
            const size_t n = e ? (size_t)(e - m) : strlen(m);
            const int j = gp_find(m, n);
            if (j >= 0) gp_switch_on(j, depth + 1);
            if (!e) break;
            m = e + 1;
        }
        return;
    }
    if (t.kind == GPK_DATA) {
        const int n = gp_data_apply(k);
        if (!n) return;
        g_gpatch[k] = 1;
        fprintf(stderr, "[gpatch] on: %s \"%s\" (%s): %d word%s written\n", t.id, t.name, t.author, n, n == 1 ? "" : "s");
        return;
    }
    g_gpatch[k] = 1;
    fprintf(stderr, "[gpatch] on: %s \"%s\" (%s): native hook armed\n", t.id, t.name, t.author);
}

extern "C" void gpatch_init(const char* elf_path)
{
    static int done;
    if (done) return;
    done = 1;
    const char* e = getenv("PS3_GPATCH");
    if (!e || !*e || !vm_base) return;
    char hash[41] = {0};
    if (!ppu_hash(elf_path, hash) || strcmp(hash, GPATCH_PPU_HASH)) {
        fprintf(stderr, "[gpatch] PS3_GPATCH=%s: EBOOT PPU-%s is not the one these patches were made for "
                        "(" GPATCH_GAME " PPU-" GPATCH_PPU_HASH "): all off\n", e, hash);
        return;
    }
    int asked = 0;
    for (const char* p = e; *p;) {
        while (*p == ',' || *p == ' ') p++;
        const char* q = p;
        while (*q && *q != ',' && *q != ' ') q++;
        if (q > p) {
            asked++;
            const int k = gp_find(p, (size_t)(q - p));
            if (k < 0) fprintf(stderr, "[gpatch] \"%.*s\": no such patch for " GPATCH_GAME "\n", (int)(q - p), p);
            else gp_switch_on(k, 0);
        }
        p = q;
    }
    int on = 0;
    for (int k = 0; k < GPATCH_COUNT; k++) on += g_gpatch[k] != 0;
    fprintf(stderr, "[gpatch] " GPATCH_GAME ": %d toggle%s on (%d id%s asked for, bundles count their members; %d in this build)\n",
            on, on == 1 ? "" : "s", asked, asked == 1 ? "" : "s", GPATCH_COUNT);
}

/* Optional, once a frame: watch the policy-1 words (a camera value the game may set from its options). */
extern "C" void gpatch_tick(void)
{
    static unsigned char warned[GPATCH_DATA_N];
    for (size_t i = 0; i < GPATCH_DATA_N; i++) {
        const gpatch_data_t& d = kGpatchData[i];
        if (d.k < 0 || !d.policy || warned[i] || !g_gpatch[d.k]) continue;
        const uint32_t v = gp_rd(d.ea, d.w);
        if (v != d.value) {
            warned[i] = 1;
            fprintf(stderr, "[gpatch] %s: the game changed 0x%08X to 0x%08X (patch value 0x%08X); left as the game set it\n",
                    kGpatch[d.k].id, d.ea, v, d.value);
        }
    }
}
