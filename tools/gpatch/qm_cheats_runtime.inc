/*
 * qm_cheats_runtime.inc -- the in-game CHEATS page of the quick menu (L3+R3), 2026-11-14.
 * The same file in all three games (as gpatch_runtime.inc); included at the END of game_patches.cpp through
 * qm_cheats_<game>.inc, which holds this game's list kQmc[] (label, kind, id, requires, value when switched off).
 *
 * The user's rule (console test 2026-11-14): a cheat (invincible, AI speed, karma side, free energy, unlocks) is
 * switched in game, in the quick menu, not in the launcher's MODS page. So the launcher no longer lists these ids
 * (MD_CATALOG_HIDE) and never passes them on; this file switches them:
 *   - QK_GP    a gpatch hook / data toggle: g_gpatch[k] set or cleared live (the lifted code tests the byte at each
 *              patched site); toggles of one conflict group: the one switched on turns the others off; "requires"
 *              is switched on with it and takes it along when switched off.
 *   - QK_CHEAT a cheat-table entry (inFAMOUS 2 only, QMC_HAVE_CHEATS): CA_FREEZE = held every frame while on
 *              (gp_frame), CA_SET = an action, written once when pressed (the save keeps it).
 * What is on is kept as `qm_cheats = id,id,...` in the game's own launcher ini (the first PS3_QM_INI file; the quick
 * menu writes it, the launcher keeps lines it does not know) and switched on again at the next start by
 * qm_cheats_init(), called from infamous2_apply_patches() after gpatch_init() / cheat_init().
 * PS3_QM_CHEATS=0: no CHEATS row. Nothing here touches guest memory or a flag unless the user switches a cheat on.
 */
extern "C" {
typedef struct {
    int n;
    const char* (*name)(int i);
    int (*state)(int i);
    const char* (*press)(int i);
    const char* (*saved)(void);
} ps3_qm_cheats_t;
void ps3_qm_cheats_register(const ps3_qm_cheats_t* t);   /* libs/video/vk_quickmenu.inc */
}

#define QMC_N ((int)(sizeof kQmc / sizeof kQmc[0]))
static int g_qmc_k[sizeof kQmc / sizeof kQmc[0]];   /* the gpatch / cheat-table index of each entry, -1 not in this build */
static char g_qmc_note[96];
static char g_qmc_saved[1024];

static int qmc_find(const char* id)
{
    for (int i = 0; i < QMC_N; i++) if (!strcmp(kQmc[i].id, id)) return i;
    return -1;
}

static int qmc_state(int i)
{
    const int k = g_qmc_k[i];
    if (k < 0) return 0;
    if (kQmc[i].kind == QK_GP) return g_gpatch[k] != 0;
#ifdef QMC_HAVE_CHEATS
    if (k_cheats[k].apply == CA_SET) return 2;
    return g_cheat_on[k] != 0;
#else
    return 0;
#endif
}

static int qmc_gp_set(int k, int on)
{
    const gpatch_toggle_t& t = kGpatch[k];
    if (on) {
        if (g_gpatch[k]) return 1;
        if (t.kind == GPK_DATA && !gp_data_apply(k)) return 0;
        g_gpatch[k] = 1;
    } else {
        if (!g_gpatch[k]) return 1;
        if (t.kind == GPK_DATA) gpatch_data_restore(k);
        g_gpatch[k] = 0;
    }
    fprintf(stderr, "[qm-cheat] %s \"%s\": %s\n", t.id, t.name, on ? "on" : "off");
    return 1;
}

/* Entry i on or off, with what goes with it. quiet: no note (the saved list at start). 0: could not. */
static int qmc_set(int i, int on, int quiet)
{
    const qmc_entry& e = kQmc[i];
    const int k = g_qmc_k[i];
    if (k < 0) return 0;
    if (e.kind == QK_GP) {
        if (on) {
            const char* grp = kGpatch[k].group;
            for (int j = 0; grp[0] && j < GPATCH_COUNT; j++)   /* one of a group */
                if (j != k && g_gpatch[j] && !strcmp(kGpatch[j].group, grp)) {
                    qmc_gp_set(j, 0);
                    const int m = qmc_find(kGpatch[j].id);
                    if (!quiet) snprintf(g_qmc_note, sizeof g_qmc_note, "Turned off: %s", m >= 0 ? kQmc[m].label : kGpatch[j].name);
                }
            if (e.req[0]) {
                const int r = qmc_find(e.req);
                if (r >= 0 && !qmc_state(r)) {
                    if (!qmc_set(r, 1, 1)) return 0;
                    if (!quiet) snprintf(g_qmc_note, sizeof g_qmc_note, "Also on: %s", kQmc[r].label);
                }
            }
            return qmc_gp_set(k, 1);
        }
        qmc_gp_set(k, 0);
        for (int j = 0; j < QMC_N; j++)   /* what needs this one goes off with it */
            if (j != i && kQmc[j].req[0] && !strcmp(kQmc[j].req, e.id) && qmc_state(j) == 1) {
                qmc_set(j, 0, 1);
                if (!quiet) snprintf(g_qmc_note, sizeof g_qmc_note, "Also off: %s", kQmc[j].label);
            }
        return 1;
    }
#ifdef QMC_HAVE_CHEATS
    const cheat_def& c = k_cheats[k];
    if (c.apply == CA_SET) {   /* an action: written now (the save is loaded: the menu only opens in game) */
        if (!on) return 1;
        unsigned changed = 0;
        for (unsigned w = 0; w < c.n; w++) {
            const uint32_t want = c.w[w].value & ch_mask(c.w[w].width);
            if (ch_rd(c.w[w].ea, c.w[w].width) != want) { ch_wr(c.w[w].ea, c.w[w].width, want); changed++; }
        }
        fprintf(stderr, "[qm-cheat] %s \"%s\": applied, %u of %u words changed\n", c.id, c.name, changed, (unsigned)c.n);
        if (!quiet) snprintf(g_qmc_note, sizeof g_qmc_note, "Applied. A save made now keeps it.");
        return 1;
    }
    if (c.apply != CA_FREEZE) return 0;
    if (on) { g_cheat_said[k] = 0; g_cheat_on[k] = 1; g_gp_frame_need |= 2; }
    else {
        g_cheat_on[k] = 0;
        if (e.has_off) for (unsigned w = 0; w < c.n; w++) ch_wr(c.w[w].ea, c.w[w].width, e.off);
    }
    fprintf(stderr, "[qm-cheat] %s \"%s\": %s\n", c.id, c.name, on ? "on (held every frame)" : "off");
    return 1;
#else
    return 0;
#endif
}

static const char* qmc_name(int i) { return kQmc[i].label; }
static const char* qmc_press(int i)
{
    g_qmc_note[0] = 0;
    if (i < 0 || i >= QMC_N) return NULL;
    const int st = qmc_state(i);
    if (!qmc_set(i, st != 1, 0)) return "Not possible in this version of the game.";
    return g_qmc_note[0] ? g_qmc_note : NULL;
}
static const char* qmc_saved(void)
{
    size_t n = 0;
    g_qmc_saved[0] = 0;
    for (int i = 0; i < QMC_N; i++) {
        if (qmc_state(i) != 1) continue;
        const size_t l = strlen(kQmc[i].id);
        if (n + l + 2 > sizeof g_qmc_saved) break;
        if (n) g_qmc_saved[n++] = ',';
        memcpy(g_qmc_saved + n, kQmc[i].id, l + 1);
        n += l;
    }
    return g_qmc_saved;
}

static const ps3_qm_cheats_t g_qmc_table = { QMC_N, qmc_name, qmc_state, qmc_press, qmc_saved };

extern "C" void qm_cheats_init(const char* elf_path)
{
    static int done;
    if (done) return;
    done = 1;
    const char* sw = getenv("PS3_QM_CHEATS");
    if ((sw && *sw == '0') || !vm_base) return;
    char hash[41] = {0};
    if (!ppu_hash(elf_path, hash) || strcmp(hash, GPATCH_PPU_HASH)) {
        fprintf(stderr, "[qm-cheat] EBOOT PPU-%s is not the one these cheats were made for (" GPATCH_GAME "): no CHEATS page\n", hash);
        return;
    }
    int have = 0;
    for (int i = 0; i < QMC_N; i++) {
        g_qmc_k[i] = -1;
        if (kQmc[i].kind == QK_GP) g_qmc_k[i] = gp_find(kQmc[i].id, strlen(kQmc[i].id));
#ifdef QMC_HAVE_CHEATS
        else for (size_t j = 0; j < CHEAT_N; j++) if (!strcmp(k_cheats[j].id, kQmc[i].id)) g_qmc_k[i] = (int)j;
#endif
        if (g_qmc_k[i] < 0) fprintf(stderr, "[qm-cheat] \"%s\": not in this build\n", kQmc[i].id);
        else have++;
    }
    /* what was on when the game was last closed: qm_cheats = id,id,... in the game's own launcher ini */
    int on = 0;
    const char* list = getenv("PS3_QM_INI");
    if (list && *list) {
        char path[512];
        size_t pl = 0;
        while (list[pl] && list[pl] != ':' && pl + 1 < sizeof path) { path[pl] = list[pl]; pl++; }
        path[pl] = 0;
        FILE* f = fopen(path, "r");
        if (f) {
            static char line[1200];
            while (fgets(line, sizeof line, f)) {
                const char* s = line;
                while (*s == ' ' || *s == '\t') s++;
                if (strncmp(s, "qm_cheats", 9)) continue;
                s += 9;
                while (*s == ' ' || *s == '\t') s++;
                if (*s != '=') continue;
                s++;
                while (*s) {
                    while (*s == ',' || *s == ' ' || *s == '\t' || *s == '\r' || *s == '\n') s++;
                    const char* q = s;
                    while (*q && *q != ',' && *q != ' ' && *q != '\t' && *q != '\r' && *q != '\n') q++;
                    if (q > s) {
                        char id[64];
                        const size_t l = (size_t)(q - s) < sizeof id - 1 ? (size_t)(q - s) : sizeof id - 1;
                        memcpy(id, s, l);
                        id[l] = 0;
                        const int i = qmc_find(id);
                        if (i < 0 || g_qmc_k[i] < 0) fprintf(stderr, "[qm-cheat] saved \"%s\": not a cheat of this build\n", id);
                        else if (qmc_state(i) == 0 && qmc_set(i, 1, 1)) on++;
                    }
                    s = q;
                }
            }
            fclose(f);
        }
    }
    ps3_qm_cheats_register(&g_qmc_table);
    fprintf(stderr, "[qm-cheat] " GPATCH_GAME ": %d cheats in the quick menu (L3+R3), %d on from the last session\n", have, on);
}
