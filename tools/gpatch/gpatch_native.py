"""Shared pieces for gpatch_apply_<game>.py: expected-statement regexes and the native translations of the
community patches. Each helper returns C++ lines in the lifted code's own model: ctx->gpr/fpr/vr/cr/lr,
vm_read32/vm_write32 (big-endian guest memory), vm_sp_* for r1-relative accesses, cr field n at bits
(7-n)*4 (LT 8, GT 4, EQ 2, SO 1), lifted calls as `ctx->lr = <return>; func_X(ctx); DRAIN_TRAMPOLINE(ctx);`."""
import json, os, re, struct

HERE = os.path.dirname(os.path.abspath(__file__))


def ids_for(game):
    cat = json.load(open(os.path.join(HERE, 'patch_catalog.json')))
    tl = sorted((t for t in cat['toggles'] if game in t['games']), key=lambda t: t['flag_index'])
    assert [t['flag_index'] for t in tl] == list(range(len(tl)))
    return [t['id'] for t in tl]


def X(s):
    """An exact generated statement (r1 accesses may be vm_sp_* or plain vm_*: before/after work/ppu_sp_patch.py)."""
    return '^' + re.escape(s).replace('vm_sp_', 'vm(?:_sp)?_') + '$'


def lis(r, imm):
    return 'ctx->gpr[%d] = (int64_t)(int32_t)((uint32_t)0x%X << 16);' % (r, imm)


def lfs(fr, base, off):
    o = ('-0x%X' % -off) if off < 0 else ('0x%X' % off)
    return '{ uint32_t tmp = vm_read32(ctx->gpr[%d] + %s); float ftmp; memcpy(&ftmp, &tmp, 4); ctx->fpr[%d] = ftmp; }' % (base, o, fr)


def stfs(fr, base, off):
    o = ('-0x%X' % -off) if off < 0 else ('0x%X' % off)
    return '{ float ftmp = (float)ctx->fpr[%d]; uint32_t tmp; memcpy(&tmp, &ftmp, 4); vm_write32(ctx->gpr[%d] + %s, tmp); }' % (fr, base, o)


def fcmpu7(a, b):
    return ('{ double a = ctx->fpr[%d]; double b = ctx->fpr[%d]; uint32_t cr_val = (a != a || b != b) ? 1 : (a < b) ? 8 : (a > b) ? 4 : 2; '
            'ctx->cr = (ctx->cr & ~(0xFu << 0)) | (cr_val << 0); }' % (a, b))


def cmpwi(field, r):
    sh = (7 - field) * 4
    return ('{ int64_t a = (int32_t)ctx->gpr[%d]; int64_t b = (int64_t)0; uint32_t cr_val = ((a < b) ? 8 : (a > b) ? 4 : 2); '
            'ctx->cr = (ctx->cr & ~(0xFu << %d)) | (cr_val << %d); }' % (r, sh, sh))


def rec0(r):   # the CR0 update of a record-form (and.) result, 64-bit compare with 0 as in 64-bit mode
    return ('{ int64_t a = (int64_t)ctx->gpr[%d]; uint32_t cr_val = ((a < 0) ? 8 : (a > 0) ? 4 : 2); '
            'ctx->cr = (ctx->cr & ~(0xFu << 28)) | (cr_val << 28); }' % r)


NOP = '/* nop (patch) */;'


def be_floats(vals):
    return ', '.join('0x%02X' % b for v in vals for b in struct.pack('>f', v))


def thrusters_fast(speed, ret_label):
    """L_'s 3-instruction cave: lis r9,0x76; lfs f1,-0x5A0(r9) (= the cave's float); b <back>."""
    return ['/* Static Thrusters - Fast: cave lis r9,0x76; lfs f1,-0x5A0(r9) (= %g); b back */' % speed,
            lis(9, 0x76),
            'ctx->fpr[1] = (double)%sf;   /* the cave\'s float */' % repr(float(speed)),
            'goto %s;' % ret_label]


def thrusters_flight(pad_slot, up, down, ret_label):
    """L_'s 21-instruction cave (0x75FC40..0x75FC90): picks one of three 16-byte vectors by the pad buttons."""
    tbl = be_floats([5.5, 0, 0, 0] + [up] * 4 + [down] * 4)
    return [
        '/* Static Thrusters - Flight: the cave at 0x75FC40 (table at 0x75FC00: masks 0x20 Cross / 0x80 Circle, then 3 vectors) */',
        'ctx->gpr[9] = 0x0075FC10;   /* lis r9,0x76; addi r9,r9,-0x3F0 */',
        'ctx->gpr[11] = 0x%08X;   /* lis r11; ori r11: the pad pointer slot */' % pad_slot,
        'ctx->gpr[11] = vm_read32(ctx->gpr[11] + 0x0);   /* lwz r11,0(r11) */',
        cmpwi(0, 11) + '   /* cmpwi r11,0 */',
        'if (!((ctx->cr >> 29) & 1)) {   /* beq -> lvx */',
        '    ctx->gpr[11] = vm_read32(ctx->gpr[11] + 0x1C);   /* lwz r11,0x1C(r11): buttons */',
        '    ctx->gpr[12] = 0x0075FC00;   /* lis r12,0x76; addi r12,r12,-0x400 */',
        '    ctx->gpr[10] = 0x20;   /* lwz r10,0(r12): the Cross mask */',
        '    ctx->gpr[10] = ctx->gpr[11] & ctx->gpr[10];   /* and. r10,r11,r10 */',
        '    ' + rec0(10),
        '    if (!((ctx->cr >> 29) & 1)) {',
        '        ctx->gpr[9] = ctx->gpr[9] + (int64_t)(16);   /* addi r9,r9,16 (rise); b lvx */',
        '    } else {',
        '        ctx->gpr[10] = 0x80;   /* lwz r10,4(r12): the Circle mask */',
        '        ctx->gpr[10] = ctx->gpr[11] & ctx->gpr[10];   /* and. r10,r11,r10 */',
        '        ' + rec0(10),
        '        if (!((ctx->cr >> 29) & 1)) ctx->gpr[9] = ctx->gpr[9] + (int64_t)(32);   /* addi r9,r9,32 (sink) */',
        '    }',
        '}',
        '{ static const uint8_t gp_t[48] = { %s };' % tbl,
        '  memcpy(&ctx->vr[2], gp_t + (uint32_t)(ctx->gpr[9] - 0x0075FC10), 16); }   /* lvx v2,0,r9 (raw big-endian bytes, no splat) */',
        'goto %s;   /* b back */' % ret_label]


def black_lightning(ret, f_q, f_draw, glob_hi, glob_lo):
    """L_'s 44-instruction wrapper (cave 0x75FD00) around the draw call, inline."""
    def ld(r, o):
        return 'ctx->gpr[%d] = vm_sp_read64(ctx->gpr[1] + 0x%X);' % (r, o)
    return [
        '/* Black Lightning: bl 0x75FD00, the wrapper that swaps r5-r7 of the draw call */',
        'ctx->lr = 0x%08X;' % ret,
        'vm_sp_write64(ctx->gpr[1] + -0xB0, ctx->gpr[1]); ctx->gpr[1] += -0xB0;   /* stdu r1,-176(r1) */',
        'ctx->gpr[0] = ctx->lr;   /* mflr r0 */',
        'vm_sp_write64(ctx->gpr[1] + 0xC0, ctx->gpr[0]);   /* std r0,192(r1) */',
        ] + ['vm_sp_write64(ctx->gpr[1] + 0x%X, ctx->gpr[%d]);' % (0x70 + 8 * (r - 3), r) for r in range(3, 10)] + [
        'ctx->gpr[11] = vm_read32(ctx->gpr[3] + 0x14);   /* lwz r11,0x14(r3) */',
        'ctx->gpr[0] = vm_read32(ctx->gpr[11] + 0x11C);   /* lwz r0,0x11C(r11) */',
        cmpwi(7, 0),
        '{ int gp_sw = 0;',
        '  if (((ctx->cr >> 1) & 1)) {   /* bne cr7 -> keep the arguments */',
        '    ctx->gpr[11] = 0x%08X;   /* lis r11 */' % glob_hi,
        '    ctx->gpr[3] = vm_read32(ctx->gpr[11] + %s);   /* lwz r3: the global */' % glob_lo,
        '    ' + cmpwi(7, 3),
        '    if (!((ctx->cr >> 1) & 1)) {',
        '      ctx->lr = 0x0075FD4C; %s(ctx); DRAIN_TRAMPOLINE(ctx);   /* bl */' % f_q,
        '      ' + cmpwi(7, 3),
        '      if (!((ctx->cr >> 1) & 1)) {',
        '        ctx->gpr[5] = vm_read32(ctx->gpr[3] + 0x60);   /* lwz r5,0x60(r3) */',
        '        ' + cmpwi(7, 5),
        '        if (((ctx->cr >> 2) & 1)) {   /* r5 > 0 */',
        '          ctx->gpr[6] = vm_read32(ctx->gpr[3] + 0x5C);   /* lwz r6,0x5C(r3) */',
        '          ctx->gpr[11] = 0x%08X;' % glob_hi,
        '          ctx->gpr[7] = vm_read32(ctx->gpr[11] + %s);   /* lwz r7: the global */' % glob_lo,
        '          ' + ld(3, 0x70) + ' ' + ld(4, 0x78) + ' ' + ld(8, 0x98) + ' ' + ld(9, 0xA0),
        '          gp_sw = 1;',
        '        }',
        '      }',
        '    }',
        '  }',
        '  if (!gp_sw) { ' + ' '.join(ld(r, 0x70 + 8 * (r - 3)) for r in range(3, 10)) + ' }',
        '}',
        'ctx->lr = 0x0075FDA0; %s(ctx); DRAIN_TRAMPOLINE(ctx);   /* bl: the original draw call */' % f_draw,
        'ctx->gpr[0] = vm_sp_read64(ctx->gpr[1] + 0xC0);   /* ld r0,192(r1) */',
        'ctx->lr = ctx->gpr[0];   /* mtlr r0 */',
        'ctx->gpr[1] = ctx->gpr[1] + (int64_t)(0xB0);   /* addi r1,r1,176; blr -> 0x%08X */' % ret]


def cole_never_dies():
    return [lis(0, 0x7F7F) + '   /* lis r0,0x7F7F */',
            'vm_write32(ctx->gpr[9] + 0x7EC, ctx->gpr[0]);   /* stw r0,0x7EC(r9) */',
            'vm_write32(ctx->gpr[9] + 0x7F0, ctx->gpr[0]);   /* stw r0,0x7F0(r9) */']


def circular_stick():
    """artofaria's 'Circular Stick Mapping (2% Deadzone)' routine (BCUS98119 0x152538..0x152600) in C."""
    S = 'gp_s'
    return [
        '/* Circular Stick Mapping (artofaria): the patch replaces the whole calibration routine */',
        '{ auto gp_f = [](uint32_t u) { float f; memcpy(&f, &u, 4); return (double)f; };',
        '  auto gp_s = [](double d) { return (double)(float)d; };   /* round to single, as the *s instructions */',
        '  ctx->gpr[12] = 0x00152800;   /* lis r12,0x15; ori r12,r12,0x2800: the patch\'s constant table */',
        '  ctx->fpr[0] = gp_f(0x42FE0000u); ctx->fpr[1] = gp_f(0x43000000u); ctx->fpr[2] = gp_f(0x3CA3D70Au);   /* 127, 128, 0.02 */',
        '  ctx->fpr[3] = gp_f(0x3F7AE148u); ctx->fpr[4] = gp_f(0x3F800000u); ctx->fpr[5] = gp_f(0x00000000u);   /* 0.98, 1, 0 */',
        '  ctx->gpr[11] = ctx->gpr[4] & 0xFF;   /* clrlwi r11,r4,24 */',
        '  vm_sp_write64(ctx->gpr[1] + -0x60, ctx->gpr[11]);   /* std r11,-96(r1) */',
        '  ctx->fpr[6] = %s((double)(int64_t)ctx->gpr[11]);   /* lfd; fcfid; frsp */' % S,
        '  ctx->fpr[6] = %s(ctx->fpr[6] - ctx->fpr[1]);   /* fsubs f6,f6,f1 */' % S,
        '  ctx->fpr[6] = %s(ctx->fpr[6] / ctx->fpr[0]);   /* fdivs f6,f6,f0 */' % S,
        '  ctx->gpr[11] = ctx->gpr[5] & 0xFF;   /* clrlwi r11,r5,24 */',
        '  vm_sp_write64(ctx->gpr[1] + -0x60, ctx->gpr[11]);   /* std r11,-96(r1) */',
        '  ctx->fpr[7] = %s((double)(int64_t)ctx->gpr[11]);   /* lfd; fcfid; frsp */' % S,
        '  ctx->fpr[7] = %s(ctx->fpr[1] - ctx->fpr[7]);   /* fsubs f7,f1,f7 */' % S,
        '  ctx->fpr[7] = %s(ctx->fpr[7] / ctx->fpr[0]);   /* fdivs f7,f7,f0 */' % S,
        '  ctx->fpr[8] = %s(ctx->fpr[6] * ctx->fpr[6]);   /* fmuls f8,f6,f6 */' % S,
        '  ctx->fpr[8] = (double)fmaf((float)ctx->fpr[7], (float)ctx->fpr[7], (float)ctx->fpr[8]);   /* fmadds f8,f7,f7,f8 */',
        '  ctx->fpr[8] = (double)sqrtf((float)ctx->fpr[8]);   /* fsqrts f8,f8 */',
        '  ' + fcmpu7(8, 2) + '   /* fcmpu cr7,f8,f2 */',
        '  if (((ctx->cr >> 2) & 1)) {   /* outside the deadzone */',
        '    ctx->fpr[9] = %s(ctx->fpr[8] - ctx->fpr[2]);   /* fsubs f9,f8,f2 */' % S,
        '    ctx->fpr[9] = %s(ctx->fpr[9] / ctx->fpr[3]);   /* fdivs f9,f9,f3 */' % S,
        '    ' + fcmpu7(9, 4) + '   /* fcmpu cr7,f9,f4 */',
        '    if (((ctx->cr >> 2) & 1)) ctx->fpr[9] = ctx->fpr[4];   /* fmr f9,f4 */',
        '    ctx->fpr[10] = %s(ctx->fpr[9] / ctx->fpr[8]);   /* fdivs f10,f9,f8 */' % S,
        '    ctx->fpr[6] = %s(ctx->fpr[6] * ctx->fpr[10]);   /* fmuls f6,f6,f10 */' % S,
        '    ctx->fpr[7] = %s(ctx->fpr[7] * ctx->fpr[10]);   /* fmuls f7,f7,f10 */' % S,
        '    ctx->gpr[0] = 1;   /* li r0,1 */',
        '  } else {',
        '    ctx->fpr[6] = ctx->fpr[5]; ctx->fpr[7] = ctx->fpr[5]; ctx->fpr[9] = ctx->fpr[5];   /* fmr f6/f7/f9,f5 */',
        '    ctx->gpr[0] = 0;   /* li r0,0 */',
        '  }',
        '  ' + stfs(6, 6, 0) + '   /* stfs f6,0(r6) */',
        '  ' + stfs(7, 7, 0) + '   /* stfs f7,0(r7) */',
        '  ' + stfs(9, 8, 0) + '   /* stfs f9,0(r8) */',
        '  ' + stfs(9, 9, 0) + '   /* stfs f9,0(r9) */',
        '  vm_write8(ctx->gpr[10] + 0x0, (uint8_t)ctx->gpr[4]);   /* stb r4,0(r10) */',
        '  ctx->gpr[3] = vm_sp_read32(ctx->gpr[1] + 0x74);   /* lwz r3,116(r1) */',
        '  vm_write8(ctx->gpr[3] + 0x0, (uint8_t)ctx->gpr[5]);   /* stb r5,0(r3) */',
        '  ctx->gpr[3] = vm_sp_read32(ctx->gpr[1] + 0x7C);   /* lwz r3,124(r1) */',
        '  vm_write8(ctx->gpr[3] + 0x0, (uint8_t)ctx->gpr[0]);   /* stb r0,0(r3) */',
        '}',
        'return;   /* blr */']
