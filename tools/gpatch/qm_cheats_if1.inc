/* qm_cheats_if1.inc -- inFAMOUS: the quick menu's CHEATS page (2026-11-14). { label, kind, id, requires, has_off, off } */
enum { QK_GP, QK_CHEAT };
struct qmc_entry { const char *label; int kind; const char *id, *req; int has_off; uint32_t off; };
static const qmc_entry kQmc[] = {
    { "Cole is invincible",     QK_GP, "if1_cole_invincible",       "", 0, 0 },
    { "Unlimited electricity",  QK_GP, "if1_unlimited_electricity", "", 0, 0 },
    { "All powers unlocked",    QK_GP, "if1_all_powers",            "", 0, 0 },
    { "Always hero (good)",     QK_GP, "if1_always_hero",           "", 0, 0 },
    { "Always infamous (evil)", QK_GP, "if1_always_infamous",       "", 0, 0 },
    { "Enemies: no AI",         QK_GP, "if1_no_ai",                 "", 0, 0 },
    { "Enemies: stand still",   QK_GP, "if1_ai_speed_stand",        "", 0, 0 },
    { "Enemies: speed x2",      QK_GP, "if1_ai_speed_x2",           "", 0, 0 },
};
#include "qm_cheats_runtime.inc"
