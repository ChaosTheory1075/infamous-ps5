/* qm_cheats_if2.inc -- inFAMOUS 2: the quick menu's CHEATS page (2026-11-14). { label, kind, id, requires, has_off, off }
 * QK_CHEAT ids are k_cheats_if2[]'s (cheat_table_if2.inc): FREEZE = held while on, SET = an action (APPLY). */
enum { QK_GP, QK_CHEAT };
struct qmc_entry { const char *label; int kind; const char *id, *req; int has_off; uint32_t off; };
#define QMC_HAVE_CHEATS 1
static const qmc_entry kQmc[] = {
    { "Cole never dies",              QK_GP,    "if2_cole_never_dies",  "", 0, 0 },
    { "No hit reaction",              QK_GP,    "if2_no_harm_reaction", "if2_cole_never_dies", 0, 0 },
    { "Attacks cost no electricity",  QK_GP,    "if2_attacks_free",     "", 0, 0 },
    { "Ionic charges: always 3",      QK_CHEAT, "ionic3",               "", 0, 0 },
    { "Jump height x2",               QK_GP,    "if2_jump_x2",          "", 0, 0 },
    { "Jump height x5",               QK_GP,    "if2_jump_x5",          "", 0, 0 },
    { "Jump height x10",              QK_GP,    "if2_jump_x10",         "", 0, 0 },
    { "Enemies: speed x2",            QK_GP,    "if2_ai_speed_x2",      "", 0, 0 },
    { "Karma never changes",          QK_GP,    "if2_karma_frozen",     "", 0, 0 },
    { "Only good karma",              QK_GP,    "if2_karma_good_only",  "", 0, 0 },
    { "Only evil karma",              QK_GP,    "if2_karma_evil_only",  "", 0, 0 },
    { "Karma: max good now",          QK_CHEAT, "karma_good",           "", 0, 0 },
    { "Karma: max evil now",          QK_CHEAT, "karma_evil",           "", 0, 0 },
    { "Unlock all powers + upgrades", QK_CHEAT, "unlock_all",           "", 0, 0 },
    { "Hide HUD",                     QK_CHEAT, "hide_hud",             "", 1, 0 },
};
#include "qm_cheats_runtime.inc"
