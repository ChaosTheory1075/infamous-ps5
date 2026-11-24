#!/usr/bin/env python3
"""inFAMOUS: Festival of Blood (NPUA80657, PPU-4f5ef92b...): the community code patches as native edits of the
lifted code in ~/fob/infamous2-lle/recompiled, behind g_gpatch[<flag index>] (game_patches.cpp, PS3_GPATCH).
The FoB block of the patch file carries inFAMOUS 2 addresses (it would corrupt FoB code); the sites below are the
FoB twins found by instruction pattern (evidence in patch_catalog.json).
usage: python3 -I gpatch_apply_fob.py check|apply|revert <recompiled dir> [--only id,...]"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gpatch_engine import Site, main
from gpatch_native import (X, lis, lfs, NOP, thrusters_fast, thrusters_flight, black_lightning, cole_never_dies, ids_for)

SITES = [
    Site('fob_cole_never_dies', 0x0018A438,
         [X(lfs(13, 9, 0x7F0)), X('ctx->gpr[26] = ppc_rldicl(ctx->gpr[27], 0, 32);'),
          X('{ double a = ctx->fpr[13]; double b = ctx->fpr[0]; uint32_t cr_val = (a != a || b != b) ? 1 : (a < b) ? 8 : (a > b) ? 4 : 2; ctx->cr = (ctx->cr & ~(0xFu << 0)) | (cr_val << 0); }')],
         cole_never_dies()),
    Site('fob_infinite_electricity', 0x0015D190, [X('ctx->fpr[13] = ppu_fp_single(ppu_fsub(ctx->fpr[13], ctx->fpr[0]));')],
         ['ctx->fpr[13] = ppu_fp_single(ppu_fadd(ctx->fpr[13], ctx->fpr[0]));   /* fadds f13,f13,f0 */']),
    Site('fob_expand_pack_buffer', 0x000E2798, [X(lis(26, 0x790)), X(lis(3, 0x790)), X(lis(28, 0x790))],
         [lis(26, 0x840), lis(3, 0x840), lis(28, 0x840)]),
    Site('fob_thrusters_fast', 0x001AB24C,
         [X('{ uint32_t tmp = vm_read32(ctx->gpr[30] + -0x7FD4); float ftmp; memcpy(&ftmp, &tmp, 4); ctx->fpr[1] = ftmp; }'),
          X('goto loc_001AB1F8;')],
         thrusters_fast(2555.0, 'loc_001AB1F8')),
    Site('fob_thrusters_flight', 0x001AB2E8,
         [X('ctx->gpr[9] = vm_read32(ctx->gpr[30] + -0x7FC8);'),
          X('{ uint64_t ea = (ctx->gpr[9]) & ~0xFULL; vm_raw_ld16(&ctx->vr[0], ea); }'),
          X('{ uint32_t* d = (uint32_t*)&ctx->vr[2]; uint32_t val = ((uint32_t*)&ctx->vr[0])[0]; d[0] = d[1] = d[2] = d[3] = val; }'),
          X('goto loc_001AB2D4;')],
         thrusters_flight(0x009EE9D8, 1555.0, -2555.0, 'loc_001AB2D4')),
    Site('fob_black_lightning', 0x002E6340, [X('ctx->lr = 0x002E6344; func_002D2108(ctx); DRAIN_TRAMPOLINE(ctx);')],
         black_lightning(0x002E6344, 'func_00310C10', 'func_002D2108', 0x00AD0000, '-0x118C')),
]

if __name__ == '__main__':
    sys.exit(main('fob', SITES, ids_for('fob')))
