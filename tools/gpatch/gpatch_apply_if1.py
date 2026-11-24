#!/usr/bin/env python3
"""inFAMOUS (BCES00220 01.00, PPU-d0c3e2a1...): the community code patches as native edits of the lifted code in
~/if1/infamous2-lle/recompiled, behind g_gpatch[<flag index>] (game_patches.cpp, PS3_GPATCH). Patches written
for NPUA80480 / BCUS98119 sit at the BCES00220 addresses found by pattern (evidence in patch_catalog.json).
Independent of tools/patch_if1_unstable_audio.py (its inserted lines are skipped when counting statements).
usage: python3 -I gpatch_apply_if1.py check|apply|revert <recompiled dir> [--only id,...]"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gpatch_engine import Site, main
from gpatch_native import (X, lis, lfs, stfs, NOP, circular_stick, ids_for)

DMG = [lfs(3, 30, -0x7FF0), lfs(0, 25, 0x754),
       '{ double a = ctx->fpr[0]; double b = ctx->fpr[3]; uint32_t cr_val = (a != a || b != b) ? 1 : (a < b) ? 8 : (a > b) ? 4 : 2; ctx->cr = (ctx->cr & ~(0xFu << 0)) | (cr_val << 0); }',
       'if ((!((ctx->cr >> 2) & 1))) goto loc_0013FF78;']

SITES = [
    Site('if1_damage_site', 0x0013FCAC, [X(s) for s in DMG],
         [('if1_infinite_health', [lfs(0, 25, 0x750) + '   /* lfs f0,0x750(r25): max health */',
                                   stfs(0, 25, 0x754) + '   /* stfs f0,0x754(r25): current health = max */',
                                   lfs(3, 30, -0x7FF0) + '   /* lfs f3,-0x7FF0(r30) */',
                                   '/* nop: the ble is gone */;']),
          ('if1_enemies_die_on_fall', [lfs(0, 25, 0x750) + '   /* lfs f0,0x750(r25) */',
                                       lfs(3, 30, -0x7FF0) + '   /* lfs f3,-0x7FF0(r30) (the double write of 0x13FE28) */',
                                       '/* nop: the compare is gone, cr7 as left before */;',
                                       DMG[3] + '   /* ble kept */'])]),
    Site('if1_all_powers', 0x002D59D8, [X('if (((ctx->cr >> 29) & 1)) goto loc_002D5D88;')], [NOP]),
    Site('if1_all_powers', 0x002D59E4, [X('ctx->gpr[0] = ctx->gpr[0] | 0x1;')], ['ctx->gpr[0] = ctx->gpr[0] | 0x7F;   /* ori r0,r0,0x7F */']),
    Site('if1_no_shadows', 0x002578A8, [X('if (((ctx->cr >> 1) & 1)) goto loc_002578F8;')],
         ['if (((ctx->cr >> 1) & 1)) goto loc_00257998;   /* beq cr7,0x257998 */']),
    Site('if1_disable_vfx', 0x00192F54, [X('ctx->lr = 0x00192F58; func_0021D4B0(ctx); DRAIN_TRAMPOLINE(ctx);')], [NOP]),
    Site('if1_unstable_vfx', 0x0021FA64, [X('goto loc_0021F6C4;')], [NOP]),
    Site('if1_unstable_lighting', 0x00253F6C, [X('goto loc_00253EEC;')], [NOP]),
    Site('if1_unstable_lighting', 0x00258110, [X('if ((!((ctx->cr >> 1) & 1))) goto loc_00258148;')], [NOP]),
    Site('if1_cole_invincible', 0x001475E8, [X('ctx->lr = 0x001475EC; func_0013F998(ctx); DRAIN_TRAMPOLINE(ctx);')], [NOP]),
    Site('if1_unlimited_electricity', 0x00124414, [X('ctx->fpr[11] = ppu_fp_single(ppu_fsub(ctx->fpr[0], ctx->fpr[12]));')], [NOP]),
    Site('if1_karma_side', 0x0038B5B0, [X('ctx->gpr[3] = ctx->gpr[9] | ctx->gpr[9];')],
         [('if1_always_hero', ['ctx->gpr[3] = (int64_t)(int32_t)(0x0);   /* li r3,0 */']),
          ('if1_always_infamous', ['ctx->gpr[3] = (int64_t)(int32_t)(0x1);   /* li r3,1 */'])]),
    Site('if1_no_ai', 0x002DAF1C, [X('if ((!((ctx->cr >> 2) & 1))) goto loc_002DAF24;')], ['goto loc_002DAF24;   /* b +8 */']),
    Site('if1_no_ai', 0x002DAF48, [X('vm_sp_write64(ctx->gpr[1] + -0x80, ctx->gpr[1]); ctx->gpr[1] += -0x80;'), X('ctx->gpr[0] = ctx->lr;')],
         ['return;   /* blr at the entry */']),
    Site('if1_ai_speed', 0x0017E948, [X(lis(0, 0x3F80))],
         [('if1_ai_speed_stand', [lis(0, 0x0)]), ('if1_ai_speed_x2', [lis(0, 0x4000)]),
          ('if1_ai_speed_back', [lis(0, 0xBF80)]), ('if1_ai_speed_back_x2', [lis(0, 0xC000)])]),
    Site('if1_brightness', 0x003444B4, [X(lis(11, 0x3F80))],
         [('if1_brightness_125', [lis(11, 0x3FA0)]), ('if1_brightness_150', [lis(11, 0x3FC0)])]),
    Site('if1_circular_stick', 0x001523C0,
         [X('ctx->gpr[12] = vm_sp_read32(ctx->gpr[1] + 0x7C);'), X('ctx->gpr[11] = ppc_rlw64(ctx->gpr[4], 0, 24, 31, 0, 0);'),
          X('vm_sp_write64(ctx->gpr[1] + -0x8, ctx->gpr[31]);'), X('ctx->gpr[31] = ctx->gpr[6] | ctx->gpr[6];')],
         circular_stick()),
]

if __name__ == '__main__':
    sys.exit(main('if1', SITES, ids_for('if1')))
