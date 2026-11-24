/* qm_cheats_fob.inc -- Festival of Blood: the quick menu's CHEATS page (2026-11-14). { label, kind, id, requires, has_off, off } */
enum { QK_GP, QK_CHEAT };
struct qmc_entry { const char *label; int kind; const char *id, *req; int has_off; uint32_t off; };
static const qmc_entry kQmc[] = {
    { "Cole never dies",      QK_GP, "fob_cole_never_dies",      "", 0, 0 },
    { "Infinite electricity", QK_GP, "fob_infinite_electricity", "", 0, 0 },
};
#include "qm_cheats_runtime.inc"
