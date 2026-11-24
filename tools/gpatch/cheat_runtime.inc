/*
 * cheat_runtime.inc -- the launcher's CHEATS (data writes into guest memory) + the per-frame tick for them and for
 * gpatch_tick() (tools/gpatch, 2026-11-13). Included at the END of game_patches.cpp, after
 * gpatch_<game>.inc, through cheats_<game>.inc (which includes this game's cheat_table_<game>.inc first).
 *
 *   PS3_CHEATS=<id>,<id>,...   ids of k_cheats_<game>[] (= the launcher catalog ids, tools/gpatch/gen_mods_catalog.py)
 *
 * cheat_init(elf_path): once, from infamous2_apply_patches() right after gpatch_init() (EBOOT loaded, no guest code
 * run yet). Unknown ids are logged; the table is guarded by the EBOOT's PPU hash.
 *   CA_ONCE   ELF constants: written now, each word only where the EBOOT holds the expected value (else the cheat is off).
 *   CA_SET    save-state values (karma, unlocks): the save is loaded long after boot and would overwrite a boot-time
 *             write, so these are written ONCE, after the save has loaded: the tick snapshots the cheat's words at the
 *             first frame and writes when they have changed (the load) and then stayed unchanged for 150 frames
 *             (fallback: 5400 frames with no change, e.g. a new game whose values never move). Not held: holding
 *             unlock_all fought the game (it turns 0x5F into 0x27) and made it autosave ~3 times a second
 *             (BC run gpC1, 2026-11-13). The game keeps what was written; a save made afterwards keeps it.
 *   CA_FREEZE game state the game keeps rewriting: written every frame.
 * gp_frame(): called by the port's present path (main.cpp present_guest_frame) only while g_gp_frame_need != 0, so a
 * run without cheats and without a watched gpatch word pays one byte load per present and nothing else.
 *   bit 1: gpatch_tick() (a policy-1 gpatch data word is on: the FOV watch), bit 2: the held cheats.
 */
extern "C" unsigned char g_gp_frame_need;
unsigned char g_gp_frame_need;

#define CHEAT_N (sizeof k_cheats / sizeof k_cheats[0])
static unsigned char g_cheat_on[CHEAT_N];
static unsigned char g_cheat_said[CHEAT_N];
static struct { unsigned char phase; unsigned frames, still; uint32_t snap[64]; } g_cheat_set[CHEAT_N];   /* CA_SET one-shot state */

static uint32_t ch_rd(uint32_t ea, int w)
{
    const uint8_t* p = vm_base + ea;
    uint32_t v = 0;
    for (int i = 0; i < w; i++) v = v << 8 | p[i];
    return v;
}
static void ch_wr(uint32_t ea, int w, uint32_t v)
{
    uint8_t* p = vm_base + ea;
    for (int i = 0; i < w; i++) p[i] = (uint8_t)(v >> (8 * (w - 1 - i)));
}
static uint32_t ch_mask(int w) { return w >= 4 ? 0xFFFFFFFFu : ((1u << (8 * w)) - 1u); }

static const char* ch_mode(int a) { return a == CA_ONCE ? "written now" : a == CA_SET ? "written once after the save loads" : "held every frame"; }

extern "C" void cheat_init(const char* elf_path)
{
    static int done;
    if (done) return;
    done = 1;
    /* gpatch side: a policy-1 data word (camera) that is on gets gpatch_tick() once a frame (logs once if the game rewrites it) */
    for (size_t i = 0; i < GPATCH_DATA_N; i++)
        if (kGpatchData[i].policy && kGpatchData[i].k >= 0 && g_gpatch[kGpatchData[i].k]) g_gp_frame_need |= 1;
    const char* e = getenv("PS3_CHEATS");
    if (!e || !*e || !vm_base) return;
    char hash[41] = {0};
    if (!ppu_hash(elf_path, hash) || strcmp(hash, CHEAT_PPU_HASH)) {
        fprintf(stderr, "[cheat] PS3_CHEATS=%s: EBOOT PPU-%s is not the one these cheats were made for (" GPATCH_GAME "): all off\n", e, hash);
        return;
    }
    int asked = 0, on = 0;
    for (const char* p = e; *p;) {
        while (*p == ',' || *p == ' ') p++;
        const char* q = p;
        while (*q && *q != ',' && *q != ' ') q++;
        if (q > p) {
            asked++;
            int k = -1;
            for (size_t j = 0; j < CHEAT_N; j++)
                if (strlen(k_cheats[j].id) == (size_t)(q - p) && !strncmp(k_cheats[j].id, p, (size_t)(q - p))) k = (int)j;
            if (k < 0) fprintf(stderr, "[cheat] \"%.*s\": no such cheat for " GPATCH_GAME "\n", (int)(q - p), p);
            else if (!g_cheat_on[k]) {
                const cheat_def& c = k_cheats[k];
                int ok = 1;
                if (c.apply == CA_ONCE)
                    for (unsigned i = 0; i < c.n; i++) {
                        const cheat_write& w = c.w[i];
                        const uint32_t v = ch_rd(w.ea, w.width), m = ch_mask(w.width);
                        if (w.expect != CW_ANY && v != (w.expect & m) && v != (w.value & m)) {
                            fprintf(stderr, "[cheat] %s: 0x%08X holds 0x%X, not this EBOOT's 0x%X: off\n", c.id, w.ea, v, w.expect);
                            ok = 0;
                            break;
                        }
                    }
                if (ok) {
                    g_cheat_on[k] = 1;
                    on++;
                    if (c.apply == CA_ONCE) for (unsigned i = 0; i < c.n; i++) ch_wr(c.w[i].ea, c.w[i].width, c.w[i].value);
                    else g_gp_frame_need |= 2;
                    fprintf(stderr, "[cheat] on: %s \"%s\" (%s): %u write%s, %s\n", c.id, c.name, c.credit, c.n, c.n == 1 ? "" : "s", ch_mode(c.apply));
                }
            }
        }
        p = q;
    }
    fprintf(stderr, "[cheat] " GPATCH_GAME ": %d cheat%s on (%d id%s asked for; %d in this build)\n",
            on, on == 1 ? "" : "s", asked, asked == 1 ? "" : "s", (int)CHEAT_N);
}

/* The held cheats, once a frame. Logs once per cheat: the first frame it wrote, and the first time the game had put
 * another value there since (e.g. the save load), with the old value. */
/* CA_SET: 1 when it is time for the one write (the words changed after boot and then held still for 150 frames). */
static int cheat_set_due(size_t k)
{
    const cheat_def& c = k_cheats[k];
    auto& st = g_cheat_set[k];
    const unsigned n = c.n < 64 ? c.n : 64;
    if (st.phase == 0) {
        for (unsigned i = 0; i < n; i++) st.snap[i] = ch_rd(c.w[i].ea, c.w[i].width);
        st.phase = 1;
        return 0;
    }
    st.frames++;
    int moved = 0;
    for (unsigned i = 0; i < n; i++) {
        const uint32_t v = ch_rd(c.w[i].ea, c.w[i].width);
        if (v != st.snap[i]) { st.snap[i] = v; moved = 1; }
    }
    if (moved) { st.phase = 2; st.still = 0; return 0; }   /* phase 2: the save (or a new game) has written these */
    if (st.phase == 2 && ++st.still >= 150) return 1;
    return st.frames >= 5400;
}

static void cheat_tick(void)
{
    int live = 0;
    for (size_t k = 0; k < CHEAT_N; k++) {
        if (!g_cheat_on[k] || k_cheats[k].apply == CA_ONCE) continue;
        const cheat_def& c = k_cheats[k];
        if (c.apply == CA_SET) {
            if (g_cheat_set[k].phase == 3) continue;
            live = 1;
            if (!cheat_set_due(k)) continue;
            unsigned changed = 0;
            for (unsigned i = 0; i < c.n; i++) {
                const cheat_write& w = c.w[i];
                const uint32_t want = w.value & ch_mask(w.width);
                if (ch_rd(w.ea, w.width) != want) { ch_wr(w.ea, w.width, want); changed++; }
            }
            g_cheat_set[k].phase = 3;
            fprintf(stderr, "[cheat] %s: written once after the save loaded (frame %u, %s): %u of %u words changed\n", c.id,
                    g_cheat_set[k].frames, g_cheat_set[k].still >= 150 ? "values settled" : "no load seen, fallback", changed, c.n);
            continue;
        }
        live = 1;
        for (unsigned i = 0; i < c.n; i++) {
            const cheat_write& w = c.w[i];
            const uint32_t v = ch_rd(w.ea, w.width), want = w.value & ch_mask(w.width);
            if (v == want) continue;
            if (g_cheat_said[k] == 1) {
                g_cheat_said[k] = 2;
                fprintf(stderr, "[cheat] %s: the game set 0x%08X to 0x%X; put back to 0x%X (and every frame after)\n", c.id, w.ea, v, want);
            }
            ch_wr(w.ea, w.width, want);
        }
        if (!g_cheat_said[k]) { g_cheat_said[k] = 1; fprintf(stderr, "[cheat] %s: first frame, %u write%s held\n", c.id, c.n, c.n == 1 ? "" : "s"); }
    }
    if (!live) g_gp_frame_need &= (unsigned char)~2u;   /* only one-shot cheats, all written: the tick stops */
}

extern "C" void gp_frame(void)
{
    if (g_gp_frame_need & 1) gpatch_tick();
    if (g_gp_frame_need & 2) cheat_tick();
}
