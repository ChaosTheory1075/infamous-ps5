#!/usr/bin/env python3
"""inFAMOUS 2 (NPUA80638, PPU-41a7d047...): the community code patches as native edits of the lifted code in
~/if2/infamous2-lle/recompiled, each behind g_gpatch[<flag index>] (game_patches.cpp, PS3_GPATCH).
usage: python3 -I gpatch_apply_if2.py check|apply|revert <recompiled dir> [--only id,...]
Run AFTER the post-lift steps (tools/postlift.sh, incl. work/ppu_sp_patch.py); idempotent; refuses (writes
nothing) when any copy of a site differs from the expected generated code. See gpatch_engine.py."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gpatch_engine import Site, main
from gpatch_native import (X, lis, lfs, NOP, thrusters_fast, thrusters_flight, black_lightning, cole_never_dies, ids_for)

LFS_F1_POOL = '{ uint32_t tmp = vm_read32(ctx->gpr[30] + -0x7FD4); float ftmp; memcpy(&ftmp, &tmp, 4); ctx->fpr[1] = ftmp; }'
FLIGHT_ORIG = ['ctx->gpr[9] = vm_read32(ctx->gpr[30] + -0x7FC8);',
               '{ uint64_t ea = (ctx->gpr[9]) & ~0xFULL; vm_raw_ld16(&ctx->vr[0], ea); }',
               '{ uint32_t* d = (uint32_t*)&ctx->vr[2]; uint32_t val = ((uint32_t*)&ctx->vr[0])[0]; d[0] = d[1] = d[2] = d[3] = val; }',
               'goto loc_0019B374;']

SITES = [
    Site('if2_expand_pack_buffer', 0x000DD900,
         [X(lis(26, 0x790)), X(lis(3, 0x790)), X(lis(28, 0x790))],
         [lis(26, 0x840), lis(3, 0x840), lis(28, 0x840)]),
    Site('if2_thr_fast', 0x0019B2EC, [X(LFS_F1_POOL), X('goto loc_0019B298;')],
         [('if2_thrusters_fast', thrusters_fast(2000.0, 'loc_0019B298')),
          ('if2_thrusters_fast_2555', thrusters_fast(2555.0, 'loc_0019B298'))]),
    Site('if2_thr_flight', 0x0019B388, [X(s) for s in FLIGHT_ORIG],
         [('if2_thrusters_flight', thrusters_flight(0x009A4CC0, 600.0, -1200.0, 'loc_0019B374')),
          ('if2_thrusters_flight_fast', thrusters_flight(0x009A4CC0, 1555.0, -2555.0, 'loc_0019B374'))]),
    Site('if2_black_lightning', 0x002CFA3C, [X('ctx->lr = 0x002CFA40; func_002BB874(ctx); DRAIN_TRAMPOLINE(ctx);')],
         black_lightning(0x002CFA40, 'func_002F96AC', 'func_002BB874', 0x00A80000, '0x104')),
    Site('if2_karma_instant', 0x0012FE34, [X('ctx->fpr[1] = ppu_fp_single(ppu_fadd(ctx->fpr[1], ctx->fpr[0]));')],
         ['ctx->fpr[1] = ppu_fp_single(ppu_fsub(ctx->fpr[1], ctx->fpr[0]));   /* fsubs f1,f1,f0 */']),
    Site('if2_karma_instant', 0x0012FE58, [X('ctx->lr = 0x0012FE5C; func_0012D4F0(ctx); DRAIN_TRAMPOLINE(ctx);')], [NOP]),
    Site('if2_karma_frozen', 0x0012FE50, [X('ctx->lr = 0x0012FE54; func_0012F6E0(ctx); DRAIN_TRAMPOLINE(ctx);')], [NOP]),
    Site('if2_no_harm_reaction', 0x0017AC7C, [X('vm_write32(ctx->gpr[28] + 0x0, ctx->gpr[0]);')], [NOP]),
    Site('if2_enemies_never_attack', 0x001F475C,
         [X('ctx->lr = 0x001F4760; func_001F5AB8(ctx); DRAIN_TRAMPOLINE(ctx);'), X('/* nop */;'), X(lis(0, 0xBF80))],
         ['/* jump 0x1F475C -> 0x1F4764: the call and the nop skipped */;', lis(0, 0x0) + '   /* lis r0,0 */']),
    Site('if2_attacks_free', 0x00154DAC,
         [X('{ float ftmp = (float)ctx->fpr[13]; uint32_t tmp; memcpy(&tmp, &ftmp, 4); vm_write32(ctx->gpr[9] + 0x1F68, tmp); }')], [NOP]),
    Site('if2_attacks_free', 0x00155F18,
         [X('{ float ftmp = (float)ctx->fpr[0]; uint32_t tmp; memcpy(&tmp, &ftmp, 4); vm_write32(ctx->gpr[3] + 0x1F68, tmp); }')], [NOP]),
    Site('if2_cole_never_dies', 0x0017AC50,
         [X(lfs(13, 9, 0x7F0)), X('ctx->gpr[26] = ppc_rldicl(ctx->gpr[27], 0, 32);'),
          X('{ double a = ctx->fpr[13]; double b = ctx->fpr[0]; uint32_t cr_val = (a != a || b != b) ? 1 : (a < b) ? 8 : (a > b) ? 4 : 2; ctx->cr = (ctx->cr & ~(0xFu << 0)) | (cr_val << 0); }')],
         cole_never_dies()),
    Site('if2_karma_side', 0x0012FE68,
         [X('{ double a = ctx->fpr[30]; double b = ctx->fpr[0]; uint32_t cr_val = (a != a || b != b) ? 1 : (a < b) ? 8 : (a > b) ? 4 : 2; ctx->cr = (ctx->cr & ~(0xFu << 0)) | (cr_val << 0); }')],
         [('if2_karma_evil_only', ['goto loc_0012FEA8;   /* b 0x12FF28, which holds b 0x12FEA8 */']),
          ('if2_karma_good_only', ['/* nop (patch): the compare dropped */;'])]),
    Site('if2_ai_speed_x2', 0x001D99BC, [X(lis(6, 0x3F80))], [lis(6, 0x4000)]),
    Site('if2_jump', 0x0022A104, [X(lis(0, 0x3F80))],
         [('if2_jump_x10', [lis(0, 0x4120)]), ('if2_jump_x2', [lis(0, 0x4000)]), ('if2_jump_x5', [lis(0, 0x40A0)])]),
    Site('if2_karma_fast', 0x00129724, [X('vm_sp_write64(ctx->gpr[1] + -0xD0, ctx->gpr[1]); ctx->gpr[1] += -0xD0;')], [NOP]),
    Site('if2_nothing_can_die', 0x0034E8E4, [X('vm_write32(ctx->gpr[31] + 0x4, ctx->gpr[0]);')], [NOP]),
]

if __name__ == '__main__':
    sys.exit(main('if2', SITES, ids_for('if2')))
