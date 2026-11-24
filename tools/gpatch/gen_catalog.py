#!/usr/bin/env python3
"""Builds the gameplay-patch catalog and the generated tables from one list (TOGGLES below):
  patch_catalog.json        every toggle (+ the entries that could not be ported, with the reason)
  gpatch_<game>.inc         the run-time toggle table + flag count for game_patches.cpp
  gpatch_data_<game>.inc    the data writes (address, width, value, ORIGINAL value read from our EBOOT)
  gpatch_menu_<game>.inc    the launcher's list (id, name, description, category, risk)
Original values come from the port's own EBOOT.elf (read only). The RPCS3 patch files are not read here: the
values were taken from a parsed copy of the RPCS3 patch files (not included) (parsed as data) and checked by hand against the files.
Run: python3 -I gen_catalog.py"""
import json, os, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ELF = {'if1': __import__("os").path.expanduser("~") + '/if1/infamous2/vfs/PS3_GAME/USRDIR/EBOOT.elf',
       'if2': __import__("os").path.expanduser("~") + '/if2/infamous2/vfs/dev_hdd0/game/NPUA80638/USRDIR/EBOOT.elf',
       'fob': __import__("os").path.expanduser("~") + '/fob/infamous2/vfs/PS3_GAME/USRDIR/EBOOT.elf'}
PPU = {'if1': 'd0c3e2a107c47d20d3316325ce6f75464a8f4f1d', 'if2': '41a7d047c573c78c0307506c9d1b52d15a66e4f5',
       'fob': '4f5ef92b0175310104dc0c1dd7f9d0f387c818ea'}
SRC_COM2 = 'community patches (inFAMOUS 2)/imported_patch.yml'
SRC_COM1 = 'community patches (inFAMOUS)/imported_patch.yml'
SRC_ZIP = 'community mods archive/imported_patch.yml'
SRC_RP = 'community mods archive/patch.yml (RPCS3)'
BUNG = 'bungholio (remix by STALKER)'


class Elf:
    def __init__(s, path):
        d = open(path, 'rb').read(); s.d = d
        phoff = struct.unpack('>Q', d[0x20:0x28])[0]; n = struct.unpack('>H', d[0x38:0x3a])[0]
        s.segs = []
        for i in range(n):
            o = phoff + i * 56
            t, f, off, va, pa, fs, ms, al = struct.unpack('>IIQQQQQQ', d[o:o + 56])
            if t == 1 and ms: s.segs.append((va, fs, ms, off))
    def rd(s, a, n):
        for va, fs, ms, off in s.segs:
            if va <= a and a + n <= va + fs:
                return int.from_bytes(s.d[off + a - va:off + a - va + n], 'big')
        raise ValueError('0x%X not in a file-backed segment' % a)

def f2u(x): return struct.unpack('>I', struct.pack('>f', x))[0]
def u2f(x): return struct.unpack('>f', struct.pack('>I', x))[0]

# ---------------------------------------------------------------------------------------------------------
# One record per toggle. kind: data (guest writes at boot) | hook (native edit of the lifted code, needs the
# game program rebuilt once) | bundle (switches other toggles on). group: toggles sharing a group conflict
# (only the first one listed in PS3_GPATCH stays on). sites: (guest address, original PPC, patch PPC).
T = []
def tog(**k):
    k.setdefault('requires', []); k.setdefault('group', ''); k.setdefault('data', []); k.setdefault('sites', [])
    k.setdefault('members', []); k.setdefault('evidence', ''); k.setdefault('translation', ''); k.setdefault('risk', 'low')
    T.append(k)

# ============================== inFAMOUS 2 (NPUA80638, PPU-41a7d047...) ==============================
tog(id='if2_skip_intro', game='if2', name='Skip intro movie', cat='misc', kind='data', author='FlexBy', src=SRC_RP + ':54714',
    desc='The splash movie at start-up is skipped.', data=[(0x007CDBA8, 4, 0x00000000)],
    translation='be32 0x007CDBA8 = 0: the first word of the movie name "splash_%s" in rodata, so the name is empty.',
    risk='low: the launcher SKIP INTRO setting does the same through PS3_SKIP_MOVIES')
tog(id='if2_extended_fov', game='if2', name='Extended FOV', cat='camera', kind='data', author='illusion', src=SRC_RP + ':54721',
    desc='Wider field of view.', data=[(0x0096DE14, 4, f2u(0.65))],
    translation='bef32 0x0096DE14 = 0.65.',
    risk='medium: in our EBOOT the word holds the integer 4, not a float (the patch comment: game settings may need "li" instead); reproduced as published, check the picture')
tog(id='if2_no_mesh_trim', game='if2', name='Disable mesh trimming', cat='visuals', kind='data', author='Yahfz', src=SRC_RP + ':54728',
    desc='Stops distant meshes being trimmed at resolutions above the PS3\'s.', data=[(0x008875C0, 4, 0x4020007F)],
    translation='be32 0x008875C0 = 0x4020007F (a table word in .data).', risk='low (visual)')
tog(id='if2_expand_pack_buffer', game='if2', name='Expand pack buffer', cat='fix', kind='hook', author='L_ (copy: ' + BUNG + ')',
    src=SRC_COM2 + ':4 / ' + SRC_ZIP + ':191', desc='Bigger streaming buffer for asset packs (121 MB to 132 MB).',
    sites=[(0x000DD900, 'lis r26/r3/r28,0x0790 (3 words)', 'lis r26/r3/r28,0x0840')],
    translation='3 statements `rN = (int32)(0x790 << 16)` -> `0x840 << 16` (r26, r3, r28).',
    risk='medium: 11 MB more guest memory for the pack buffer; check the boot log for allocation failures')
tog(id='if2_thrusters_fast', game='if2', name='Static Thrusters - Fast (2000)', cat='movement', kind='hook', author='L_', src=SRC_COM2 + ':67',
    group='if2_thr_fast', requires=['in game: the Improved Static Thrusters upgrade'],
    desc='Gliding with Static Thrusters is faster (forward speed 1350 to 2000).',
    sites=[(0x0019B2EC, 'lfs f1,-0x7FD4(r30)  (pool float 1350.0)', 'b cave: lis r9,0x76; lfs f1,-0x5A0(r9) (=2000.0); b 0x19B298')],
    translation='the lfs statement -> r9 = 0x760000; f1 = 2000.0f; the following `goto loc_0019B298` is the cave\'s branch back.')
tog(id='if2_thrusters_fast_2555', game='if2', name='Static Thrusters - Fast (2555)', cat='movement', kind='hook', author=BUNG, src=SRC_ZIP + ':253',
    group='if2_thr_fast', requires=['in game: the Improved Static Thrusters upgrade'],
    desc='Gliding with Static Thrusters is much faster (forward speed 1350 to 2555).',
    sites=[(0x0019B2EC, 'lfs f1,-0x7FD4(r30)', 'cave as above with 2555.0')], translation='as if2_thrusters_fast, f1 = 2555.0f.')
tog(id='if2_thrusters_flight', game='if2', name='Static Thrusters - Flight', cat='movement', kind='hook', author='L_', src=SRC_COM2 + ':14',
    group='if2_thr_flight', requires=['in game: the Improved Static Thrusters upgrade'],
    desc='While gliding: hold Cross to rise, Circle to sink (rise 600, sink 1200).',
    sites=[(0x0019B388, 'lwz r9,-0x7FC8(r30); lvx v0; vspltw v2 (the {-1000,0,0,0} lift vector)',
            'b cave: r9 = table {5.5,0,0,0}; pad = *(0x009A4CC0); buttons = pad+0x1C; Cross 0x20 -> +16 {600 x4}, Circle 0x80 -> +32 {-1200 x4}; lvx v2,0,r9; b 0x19B374')],
    translation='lwz statement -> native cave: r9/r10/r11/r12 and cr0 as the cave leaves them, v2 = the 16 table bytes '
                '(big-endian, no splat), then `goto loc_0019B374`. The 12 floats and the two masks are constants in the native code '
                'instead of the cave\'s rodata copy (nothing else reads those bytes); the pad is read from guest memory exactly as the cave does.')
tog(id='if2_thrusters_flight_fast', game='if2', name='Static Thrusters - Flight (fast)', cat='movement', kind='hook', author=BUNG, src=SRC_ZIP + ':201',
    group='if2_thr_flight', requires=['in game: the Improved Static Thrusters upgrade'],
    desc='While gliding: hold Cross to rise, Circle to sink, faster (rise 1555, sink 2555).',
    sites=[(0x0019B388, 'as if2_thrusters_flight', 'table 1555 / -2555')], translation='as if2_thrusters_flight with the other table.')
tog(id='if2_black_lightning', game='if2', name='Black Lightning', cat='visuals', kind='hook', author='L_ (copy: ' + BUNG + ')',
    src=SRC_COM2 + ':80 / ' + SRC_ZIP + ':265', desc='Cole\'s lightning is drawn black (colour patch).',
    sites=[(0x002CFA3C, 'bl 0x2BB874', 'bl wrapper: if *(*(r3+0x14)+0x11C)==0 and g=*(0xA80104)!=0 and q=func_002F96AC(g)!=0 and *(q+0x60)>0: '
            'r5=*(q+0x60), r6=*(q+0x5C), r7=g; then bl 0x2BB874')],
    translation='the call statement -> the wrapper inline: stack frame (stdu -176, LR save, r3-r9 saved at +112..+160), the tests with cr7 '
                'as the cave sets it, `func_002F96AC(ctx); DRAIN_TRAMPOLINE`, r3/r4/r8/r9 (or all of r3-r9) reloaded, '
                '`func_002BB874(ctx); DRAIN_TRAMPOLINE`, frame popped.', risk='medium: calls a game function from a new place (as the cave does)')
tog(id='if2_karma_instant', game='if2', name='Instant karma change', cat='difficulty/cheat', kind='hook', author=BUNG, src=SRC_ZIP + ':82',
    desc='Karma jumps instead of moving gradually.', sites=[(0x0012FE34, 'fadds f1,f1,f0', 'fsubs f1,f1,f0'), (0x0012FE58, 'bl 0x12D4F0', 'nop')],
    translation='fadd statement -> fsub; the call statement dropped.', risk='high: author "BETA BROKEN, can mess up progress unlocks"')
tog(id='if2_karma_frozen', game='if2', name='Karma never changes', cat='difficulty/cheat', kind='hook', author=BUNG, src=SRC_ZIP + ':93',
    desc='Nothing changes Cole\'s karma.', sites=[(0x0012FE50, 'bl 0x12F6E0', 'nop')], translation='the call statement dropped.',
    risk='medium: story karma choices stop counting')
tog(id='if2_no_harm_reaction', game='if2', name='Cole does not react to harm', cat='difficulty/cheat', kind='hook', author=BUNG, src=SRC_ZIP + ':103',
    desc='Cole ignores hits (no stagger).', requires=['if2_cole_never_dies (author: without it the screen goes black where Cole would die)'],
    sites=[(0x0017AC7C, 'stw r0,0(r28)', 'nop')], translation='the store statement dropped.', risk='medium')
tog(id='if2_enemies_never_attack', game='if2', name='Most enemies never attack', cat='difficulty/cheat', kind='hook', author=BUNG, src=SRC_ZIP + ':133',
    desc='Most enemies stop attacking.', sites=[(0x001F475C, 'bl 0x1F5AB8; nop; lis r0,0xBF80', 'b 0x1F4764 (jump); ...; lis r0,0')],
    translation='the call and the nop skipped (no LR change, as the branch), r0 = 0.', risk='high: author "BETA BROKEN CRASH"')
tog(id='if2_attacks_free', game='if2', name='Attacks cost no electricity', cat='powers', kind='hook', author=BUNG, src=SRC_ZIP + ':154',
    desc='Electric attacks and sniper zoom do not drain energy.', sites=[(0x00154DAC, 'stfs f13,0x1F68(r9)', 'nop'), (0x00155F18, 'stfs f0,0x1F68(r3)', 'nop')],
    translation='both energy stores dropped (the patch\'s "jump" to itself at 0x154DAC is overwritten by the nop that follows it in the list).')
tog(id='if2_cole_never_dies', game='if2', name='Cole never dies', cat='difficulty/cheat', kind='hook', author=BUNG, src=SRC_ZIP + ':164',
    desc='Cole\'s health is set to a huge value whenever it is checked.',
    sites=[(0x0017AC50, 'lfs f13,0x7F0(r9); clrldi r26,r27,32; fcmpu cr7,f13,f0', 'lis r0,0x7F7F; stw r0,0x7EC(r9); stw r0,0x7F0(r9)')],
    translation='3 statements -> r0 = 0x7F7F0000; store it at r9+0x7EC and r9+0x7F0 (f13, r26 and cr7 are not written, as in the patch).')
tog(id='if2_karma_evil_only', game='if2', name='Only evil karma', cat='difficulty/cheat', kind='hook', author=BUNG, src=SRC_ZIP + ':172',
    group='if2_karma_side', desc='Karma can only move towards evil.', sites=[(0x0012FE68, 'fcmpu cr7,f30,f0', 'b 0x12FF28')],
    translation='the compare -> `goto loc_0012FEA8` (0x12FF28 holds `b 0x12FEA8`; 0x12FF28 has no label).',
    risk='high: author "BETA BROKEN, can mess up progress unlocks"')
tog(id='if2_karma_good_only', game='if2', name='Only good karma', cat='difficulty/cheat', kind='hook', author=BUNG, src=SRC_ZIP + ':181',
    group='if2_karma_side', desc='Karma can only move towards good.', sites=[(0x0012FE68, 'fcmpu cr7,f30,f0', 'nop')],
    translation='the compare dropped (the next branch reads cr7 as left before).', risk='high: author "BETA BROKEN, can mess up progress unlocks"')
tog(id='if2_mod_pack_plus2', game='if2', name='Mod pack PLUS2', cat='difficulty/cheat', kind='bundle', author=BUNG, src=SRC_ZIP + ':318',
    desc='All of: no harm reaction, karma frozen, nothing can die, AI x2 speed, jump x10, free attacks, Cole never dies.',
    members=['if2_no_harm_reaction', 'if2_karma_frozen', 'if2_nothing_can_die', 'if2_ai_speed_x2', 'if2_jump_x10', 'if2_attacks_free', 'if2_cole_never_dies'],
    translation='its 10 words are exactly the words of the 7 member patches.', risk='high (sum of the members)')
tog(id='if2_ai_speed_x2', game='if2', name='AI movement speed x2', cat='difficulty/cheat', kind='hook', author=BUNG, src=SRC_ZIP + ':334',
    desc='People and enemies move twice as fast.', sites=[(0x001D99BC, 'lis r6,0x3F80 (1.0)', 'lis r6,0x4000 (2.0)')],
    translation='immediate 0x3F80 -> 0x4000.')
for x, v in ((10, 0x4120), (2, 0x4000), (5, 0x40A0)):
    tog(id='if2_jump_x%d' % x, game='if2', name='Jump height x%d' % x, cat='movement', kind='hook', author=BUNG,
        src=SRC_ZIP + ':%d' % {10: 348, 2: 358, 5: 368}[x], group='if2_jump', desc='Cole jumps %d times as high.' % x,
        sites=[(0x0022A104, 'lis r0,0x3F80 (1.0)', 'lis r0,0x%04X (%g)' % (v, u2f(v << 16)))], translation='immediate 0x3F80 -> 0x%04X.' % v,
        risk='medium (x10: long falls)' if x == 10 else 'low')
tog(id='if2_karma_fast', game='if2', name='Very fast karma gain and loss', cat='difficulty/cheat', kind='hook', author=BUNG, src=SRC_ZIP + ':381',
    desc='Karma moves very fast.', sites=[(0x00129724, 'stdu r1,-0xD0(r1)', 'nop')],
    translation='the frame push dropped: the function then saves into and pops from its caller\'s frame, exactly as on RPCS3.',
    risk='high: removes a stack frame (guest stack corruption in the original too); author "BETA BROKEN, can mess up progress unlocks"')
tog(id='if2_nothing_can_die', game='if2', name='Nothing can die', cat='difficulty/cheat', kind='hook', author=BUNG, src=SRC_ZIP + ':391',
    desc='Characters should not die (author: no effect).', sites=[(0x0034E8E4, 'stw r0,4(r31)', 'nop')], translation='the store dropped.',
    risk='low (author: "BETA NO EFFECT")')

# ============================== inFAMOUS: Festival of Blood (NPUA80657, PPU-4f5ef92b...) ==============================
tog(id='fob_skip_intro', game='fob', name='Skip intro movie', cat='misc', kind='data', author='FlexBy', src=SRC_RP + ':67607 / ' + SRC_ZIP + ':585',
    desc='The splash movies at start-up are skipped.', data=[(0x00812BA0, 4, 0), (0x00812BB0, 4, 0)],
    translation='be32 0 over the first words of "splash_fob_%s" and "splash_%s".', risk='low: same as the launcher SKIP INTRO')
tog(id='fob_no_mesh_trim', game='fob', name='Disable mesh trimming', cat='visuals', kind='data', author='Pappapatu', src=SRC_RP + ':67617',
    desc='Stops distant meshes being trimmed at resolutions above the PS3\'s.', data=[(0x008CF5F8, 4, 0x4020007F)],
    translation='be32 0x008CF5F8 = 0x4020007F (same table word as inFAMOUS 2, original 0x21000984 in both).', risk='low (visual)')
tog(id='fob_cole_never_dies', game='fob', name='Cole never dies', cat='difficulty/cheat', kind='hook', author='chidreams', src=SRC_ZIP + ':561',
    desc='Cole\'s health is set to a huge value whenever it is checked.',
    sites=[(0x0018A438, 'lfs f13,0x7F0(r9); clrldi; fcmpu', 'lis r0,0x7F7F; stw r0,0x7EC(r9); stw r0,0x7F0(r9)')], translation='as if2_cole_never_dies.')
tog(id='fob_infinite_electricity', game='fob', name='Infinite electricity', cat='powers', kind='hook', author='Hiei-YYH', src=SRC_ZIP + ':574',
    desc='Using powers adds energy instead of draining it.', sites=[(0x0015D190, 'fsubs f13,f13,f0', 'fadds f13,f13,f0')], translation='fsub statement -> fadd.')
tog(id='fob_expand_pack_buffer', game='fob', name='Expand pack buffer', cat='fix', kind='hook', author='FlexBy (L_\'s inFAMOUS 2 patch)', src=SRC_ZIP + ':732',
    desc='Bigger streaming buffer for asset packs (121 MB to 132 MB).', sites=[(0x000E2798, 'lis r26/r3/r28,0x0790', 'lis ...,0x0840')],
    evidence='the FoB block writes if2 address 0xDD900 (FoB holds lwz there); the 3 lis 0x0790 words are at FoB 0x000E2798, 9-word context identical to if2 0xDD8F0..',
    translation='as if2_expand_pack_buffer.', risk='medium: 11 MB more guest memory')
tog(id='fob_thrusters_fast', game='fob', name='Static Thrusters - Fast', cat='movement', kind='hook', author='FlexBy (' + BUNG + ' values)', src=SRC_ZIP + ':798',
    requires=['in game: the Improved Static Thrusters upgrade'], desc='Gliding with Static Thrusters is much faster (1350 to 2555).',
    sites=[(0x001AB24C, 'lfs f1,-0x7FD4(r30)', 'cave: f1 = 2555.0; b 0x1AB1F8')],
    evidence='if2 0x19B2EC -> FoB 0x1AB24C: the getter func_001AB1D4 is word-identical to if2 func_0019B274 (TOC slot 0x9EEBA0 = 1350.0 like if2 0x9A4E88)',
    translation='as if2_thrusters_fast_2555, `goto loc_001AB1F8` kept.')
tog(id='fob_thrusters_flight', game='fob', name='Static Thrusters - Flight', cat='movement', kind='hook', author='FlexBy (' + BUNG + ' values)', src=SRC_ZIP + ':744',
    requires=['in game: the Improved Static Thrusters upgrade'], desc='While gliding: hold Cross to rise, Circle to sink (1555 / 2555).',
    sites=[(0x001AB2E8, 'lwz r9,-0x7FC8(r30); lvx; vspltw', 'cave as if2, pad slot 0x009EE9D8')],
    evidence='if2 0x19B388 -> FoB 0x1AB2E8 (func_001AB2B0 word-identical); the pad slot: if2 0x009A4CC0 (-> 0xA73130) is loaded by '
             'if2 0x1967CC (lwz r9,-0x7FCC(r30), r30 = TOC-0x7D30); its FoB twin 0x1A6730 (16/17 words) loads FoB slot 0x009EE9D8 (-> 0xAC1DF0)',
    translation='as if2_thrusters_flight with slot 0x009EE9D8 and `goto loc_001AB2D4`.')
tog(id='fob_black_lightning', game='fob', name='Black Lightning', cat='visuals', kind='hook', author='FlexBy (L_\'s inFAMOUS 2 patch)', src=SRC_ZIP + ':812',
    desc='Cole\'s lightning is drawn black (colour patch).',
    sites=[(0x002E6340, 'bl 0x2D2108', 'wrapper as if2 with func_00310C10 and global 0x00ACEE74')],
    evidence='call if2 0x2CFA3C -> FoB 0x2E6340 (16/17 words); callees if2 0x2BB874 -> 0x2D2108 and 0x2F96AC -> 0x310C10 (exact); '
             'global if2 0xA80104 (slot 0x9AFB40, loaded at if2 0x49A90C) -> FoB slot 0x9FA01C (loaded at the exact twin 0x4CAD00) = 0xACEE74; '
             'the call\'s own setup reads +0x14/+0x120 at the same offsets in both games',
    translation='as if2_black_lightning; lis r11,0xAD / lwz -0x118C(r11) stands for the cave\'s lis 0xA8 / 0x104.',
    risk='medium: the object offsets +0x11C/+0x5C/+0x60 are assumed unchanged in FoB (some other offsets in this function moved by 4/16)')

# ============================== inFAMOUS (BCES00220 01.00, PPU-d0c3e2a1...) ==============================
tog(id='if1_skip_intro', game='if1', name='Skip intro movie', cat='misc', kind='data', author='FlexBy', src=SRC_RP + ':67371',
    desc='The splash movie at start-up is skipped.', data=[(0x005B5320, 4, 0)],
    translation='be32 0 over the first two UTF-16 chars of L"splash_%s".', risk='low: same as the launcher SKIP INTRO')
tog(id='if1_no_mesh_trim', game='if1', name='Disable mesh trimming', cat='visuals', kind='data', author='Yahfz', src=SRC_RP + ':67385',
    desc='Stops distant meshes being trimmed at resolutions above the PS3\'s.', data=[(0x00614220, 4, 0x35000000)],
    translation='be32 0x00614220 = 0x35000000.', risk='low (visual)')
for nm, v in (('1_4', 0x3FB33333), ('1_2', 0x3F99999A), ('1_1', 0x3F8CCCCD), ('0_9', 0x3F666666), ('0_8', 0x3F4CCCCD), ('0_6', 0x3F19999A)):
    f = u2f(v); wider = f < 1
    tog(id='if1_fov_' + nm, game='if1', name='FOV %s (%s)' % (nm.replace('_', '.'), 'wider' if wider else 'narrower'), cat='camera', kind='data',
        author='Hasster', src=SRC_RP + ':67363', group='if1_fov',
        desc='%s field of view (factor %s; 1.0 is the game\'s; lower = wider).' % ('Wider' if wider else 'Narrower', nm.replace('_', '.')),
        data=[(0x007854DC, 4, v)], translation='be32 0x007854DC = 0x%08X (one of the patch\'s "FOV" values).' % v, risk='low')
BLUR = [(0x007626c4, 0xbf8dd2f1), (0x007626cc, 0xbef30783), (0x007626d4, 0x3e222222), (0x007626dc, 0x3faaaaab), (0x007626e4, 0x3f4aaaab),
        (0x007867b8, 0xbdaaaaab), (0x007867bc, 0xbdaaaaab), (0x007867c4, 0x3daaaaab), (0x007867c8, 0xbdaaaaab), (0x007867d0, 0xbdaaaaab),
        (0x007867d4, 0x3daaaaab), (0x007867dc, 0x3daaaaab), (0x007867e0, 0x3daaaaab), (0x007867ec, 0x3daaaaab), (0x007867f0, 0x3daaaaab),
        (0x007867f8, 0xbdaaaaab), (0x007867fc, 0x3daaaaab), (0x00786804, 0x3daaaaab), (0x00786808, 0xbdaaaaab), (0x00786810, 0xbdaaaaab),
        (0x00786814, 0xbdaaaaab), (0x00786820, 0x3e2aaaab), (0x00786824, 0x3e2aaaab), (0x0078682c, 0xbe2aaaab), (0x00786830, 0x3e2aaaab),
        (0x00786838, 0x3e2aaaab), (0x0078683c, 0xbe2aaaab), (0x00786844, 0xbe2aaaab), (0x00786848, 0xbe2aaaab)]
tog(id='if1_blur_bloom_fix', game='if1', name='High-resolution blur and bloom fix', cat='visuals', kind='data', author='artofaria',
    src=SRC_RP + ':67545 (BCUS98119) / ' + SRC_ZIP + ':1137', desc='Smoother blur and bloom at higher resolutions (sample offsets cut to a third).',
    data=[(a + (0x48 if a < 0x780000 else 0x50), 4, v) for a, v in BLUR],
    evidence='written for BCUS98119; moved to BCES00220 by +0x48 (0x7626xx) / +0x50 (0x7867xx), the same shifts as the speed-limit (+0x48) '
             'and refraction (+0x50) patches that exist for both builds; all 29 originals are 3x the patch values (checked by gen_catalog.py)',
    translation='29 float words.', risk='low (visual)')
tog(id='if1_infinite_health', game='if1', name='Infinite health', cat='difficulty/cheat', kind='hook', author='Codex', src=SRC_COM1 + ':4 (NPUA80480)',
    group='if1_damage_site', desc='Cole\'s health is refilled to maximum whenever he takes damage.',
    sites=[(0x0013FCAC, 'lfs f3,-0x7FF0(r30); lfs f0,0x754(r25); fcmpu cr7,f0,f3; ble cr7,+0x2C0',
            'lfs f0,0x750(r25); stfs f0,0x754(r25); lfs f3,-0x7FF0(r30); nop')],
    evidence='written for NPUA80480 0x001405C4; the same 4 instructions are at BCES00220 0x0013FCAC (= -0x918), func_0013F994/0013F998 (2 copies)',
    translation='4 statements -> f0 = max health (+0x750); store it to current health (+0x754); f3 = the pool float; branch dropped (cr7 untouched).',
    risk='low; r25 is the damaged character: if enemies also become unkillable, it is not Cole-only (the RPCS3 patch has the same property)')
tog(id='if1_enemies_die_on_fall', game='if1', name='Enemies die after falling', cat='difficulty/cheat', kind='hook', author=BUNG, src=SRC_ZIP + ':1371 (BCUS98119)',
    group='if1_damage_site', desc='Knocked-down characters die (as published, including its typo).',
    sites=[(0x0013FCAC, 'lfs f3,-0x7FF0(r30); lfs f0,0x754(r25); fcmpu cr7,f0,f3; ble', 'lfs f0,0x750(r25); lfs f3,-0x7FF0(r30); nop; ble (kept)')],
    evidence='BCUS 0x13FE24 = BCES 0x13FCAC (-0x178, the shift proven by Circular Stick 0x152538->0x1523C0 and Cole Is Invincible 0x147760->0x1475E8 '
             'in the same range); the patch writes 0x13FE28 twice, so the published effect is: f0 = max, f3 = pool float, the compare removed, '
             'the ble reads the cr7 left by `cmpwi cr7,r0,0` at 0x13FC8C',
    translation='4 statements -> f0 = +0x750; f3 = pool float; (no compare); the original branch statement kept.',
    risk='high: an author BETA cheat whose effect depends on a stale condition register; conflicts with if1_infinite_health (same instructions)')
tog(id='if1_all_powers', game='if1', name='All powers unlocked', cat='powers', kind='hook', author='Scirvir', src=SRC_RP + ':67341',
    desc='Every power is available.', sites=[(0x002D59D8, 'beq 0x2D5D88', 'nop'), (0x002D59E4, 'ori r0,r0,1', 'ori r0,r0,0x7F (byte write 0x2D59E7)')],
    translation='the branch statement dropped; `r0 | 0x1` -> `r0 | 0x7F`.', risk='medium: the unlock bits are written into the save')
tog(id='if1_no_shadows', game='if1', name='Disable shadows', cat='visuals', kind='hook', author='FlexBy', src=SRC_RP + ':67378',
    desc='No dynamic shadows (faster).', sites=[(0x002578A8, 'beq cr7,0x2578F8', 'beq cr7,0x257998')],
    translation='`goto loc_002578F8` -> `goto loc_00257998` under the same condition.', risk='low (visual)')
tog(id='if1_disable_vfx', game='if1', name='Disable visual effects (experimental)', cat='visuals', kind='hook', author='Hasster', src=SRC_ZIP + ':867',
    desc='Some shadows and lighting off, much faster in places; may glitch other effects.', sites=[(0x00192F54, 'bl 0x21D4B0', 'nop')],
    translation='the call statement dropped.', risk='medium (author: may cause glitches)')
tog(id='if1_unstable_vfx', game='if1', name='Unstable visual effects (experimental)', cat='visuals', kind='hook', author='Hasster', src=SRC_ZIP + ':876',
    desc='Visual effects off; last resort for speed.', sites=[(0x0021FA64, 'b 0x21F6C4', 'nop')],
    translation='`goto loc_0021F6C4` dropped (falls through).', risk='medium (author: use only as the last resort)')
tog(id='if1_unstable_lighting', game='if1', name='Unstable lighting (experimental)', cat='visuals', kind='hook', author='Hasster', src=SRC_ZIP + ':885',
    desc='Faster, but fire, lightning and some lights partly break.', sites=[(0x00253F6C, 'b 0x253EEC', 'nop'), (0x00258110, 'bne cr7,0x258148', 'nop')],
    translation='both branch statements dropped.', risk='medium (author: partially breaks fire, lightning and lighting)')
tog(id='if1_cole_invincible', game='if1', name='Cole is invincible', cat='difficulty/cheat', kind='hook', author=BUNG, src=SRC_ZIP + ':1381 (BCUS98119)',
    desc='Damage is never applied to Cole.', sites=[(0x001475E8, 'bl 0x13F998 (the damage routine)', 'nop')],
    evidence='BCUS 0x147760 -> BCES 0x1475E8 (-0x178); the word there is `bl 0x13F998`, the routine Infinite Health patches',
    translation='the call statement dropped.', risk='low')
tog(id='if1_unlimited_electricity', game='if1', name='Unlimited electricity', cat='powers', kind='hook', author=BUNG, src=SRC_ZIP + ':1391 (BCUS98119)',
    desc='Energy stays full (as published).', sites=[(0x00124414, 'fsubs f11,f0,f12', 'nop')],
    evidence='BCUS 0x12458C -> BCES 0x124414 (-0x178): the energy clamp function (new = old + delta; clamp to max via fsel f11); the MOD PACK '
             'GIGA word for BCUS 0x124598 (stfs f12,8(r4)) lands on BCES 0x124420 `stfs f13,8(r4)` with the same shift',
    translation='the fsub statement dropped: the clamp then selects with the stale f11 (as on RPCS3).',
    risk='medium: works through a stale register, as the original does')
tog(id='if1_always_hero', game='if1', name='Always hero (good)', cat='difficulty/cheat', kind='hook', author=BUNG, src=SRC_ZIP + ':1401 (BCUS98119)',
    group='if1_karma_side', desc='Cole counts as good.', sites=[(0x0038B5B0, 'mr r3,r9', 'li r3,0')],
    evidence='BCUS 0x38B520 -> BCES 0x38B5B0 (+0x90, the shift of All powers 0x2D5948->0x2D59D8 and Brightness): the return-value move of '
             'the range test func_0038B568 (`mr r3,r9; extsw r3,r3; blr`)', translation='r3 = r9 -> r3 = 0.', risk='medium: every caller of this range test gets 0')
tog(id='if1_always_infamous', game='if1', name='Always infamous (evil)', cat='difficulty/cheat', kind='hook', author=BUNG, src=SRC_ZIP + ':1412 (BCUS98119)',
    group='if1_karma_side', desc='Cole counts as evil.', sites=[(0x0038B5B0, 'mr r3,r9', 'li r3,1')],
    evidence='as if1_always_hero', translation='r3 = r9 -> r3 = 1.', risk='medium: every caller of this range test gets 1 when the value is above the low end')
tog(id='if1_no_ai', game='if1', name='No enemy AI', cat='difficulty/cheat', kind='hook', author=BUNG, src=SRC_ZIP + ':1224 (BCUS98119)',
    desc='Enemies never shoot and their AI is off.', sites=[(0x002DAF1C, 'ble cr7,+8', 'b +8'), (0x002DAF48, 'stdu r1,-0x80(r1) (function entry)', 'blr')],
    evidence='BCUS 0x2DAE8C/0x2DAEB8 -> BCES 0x2DAF1C/0x2DAF48 (+0x90): a `ble +8` (the patch makes it `b +8`) and a function entry (the patch returns at once)',
    translation='`if (!gt) goto loc_002DAF24` -> `goto loc_002DAF24`; function entry -> `return;`.')
for nm, v, d in (('stand', 0x0000, 'AI stands still (speed 0)'), ('x2', 0x4000, 'AI moves twice as fast'),
                 ('back', 0xBF80, 'AI moves backwards'), ('back_x2', 0xC000, 'AI moves backwards, twice as fast')):
    tog(id='if1_ai_speed_' + nm, game='if1', name='AI speed: ' + {'stand': 'stand still', 'x2': 'x2', 'back': 'backwards', 'back_x2': 'backwards x2'}[nm],
        cat='difficulty/cheat', kind='hook', author='STALKER', src=SRC_ZIP + ':%d (BCUS98119)' % {'stand': 1176, 'x2': 1188, 'back': 1200, 'back_x2': 1212}[nm],
        group='if1_ai_speed', desc=d + '.', sites=[(0x0017E948, 'lis r0,0x3F80 (1.0)', 'lis r0,0x%04X' % v)],
        evidence='BCUS 0x17EAB0 -> BCES 0x17E948 (-0x168): the only `lis r0,0x3F80` within +-0x3000 (an object initialiser storing 1.0 at +0x2C)',
        translation='immediate 0x3F80 -> 0x%04X.' % v, risk='medium (located by its unique 1.0 constant; author BETA)')
for nm, v in (('125', 0x3FA0), ('150', 0x3FC0)):
    tog(id='if1_brightness_' + nm, game='if1', name='Brightness x%s.%s' % (nm[0], nm[1:]), cat='visuals', kind='hook', author=BUNG,
        src=SRC_ZIP + ':%d (BCUS98119)' % {'125': 1453, '150': 1464}[nm], group='if1_brightness',
        desc='Picture %s%% brighter.' % {'125': '25', '150': '50'}[nm], sites=[(0x003444B4, 'lis r11,0x3F80 (1.0)', 'lis r11,0x%04X' % v)],
        evidence='BCUS 0x344424 -> BCES 0x3444B4 (+0x90): the only `lis r11,0x3F80` within +-0x3000',
        translation='immediate 0x3F80 -> 0x%04X.' % v, risk='low (visual)')
tog(id='if1_circular_stick', game='if1', name='Circular stick mapping (2% deadzone)', cat='fix', kind='hook', author='artofaria',
    src=SRC_RP + ':67478 (BCUS98119) / ' + SRC_ZIP + ':1070', desc='Analog sticks get a round range and a small 2% deadzone.',
    sites=[(0x001523C0, 'the stick calibration function (entry)', 'replaced by a 50-instruction routine')],
    evidence='BCUS 0x152538 (function start: the patch reads its 9th/10th arguments at 116/124(r1) without a frame) -> BCES 0x1523C0 '
             '(-0x178): a function starting right after a blr with the same signature: u8 x/y in r4/r5 (clrlwi), float outputs at r6/r7/r8/r9, '
             'byte outputs r10 / arg9 (116(r1)) / arg10 (124(r1)), exactly the stores the patch makes',
    translation='at the function entry, under the flag: the patch\'s routine in C (single-precision steps as the PPC: x = (u8 r4 - 128)/127, '
                'y = (128 - u8 r5)/127, m = sqrtf(fmaf(y,y,x*x)), dz 0.02, t = min((m-0.02)/0.98, 1)), the same stores, r0/r3/r11/r12/f0-f10 '
                'and cr7 left as the PPC leaves them, then `return`. The 6 constants are C literals instead of the patch\'s table at 0x152800.',
    risk='medium: replaces the whole calibration (also the menus\'); located by signature, not by bytes')

NOT_PORTABLE = [
    ('if2', 'Ionic Charges Never Decrease XXX', BUNG, 'broken in our EBOOT: writes into bss, the ELF header and live code (author: BETA BROKEN CRASH)'),
    ('if2', 'Amp Meter Always Full XXX', BUNG, 'broken: a code cave over live code with absolute branches from another build (author: BROKEN CRASH)'),
    ('if2', 'AMP INFINITE OVERCHARGE XXX', BUNG, 'broken: 24-word cave over live code at 0x6F5B10 (author: NO EFFECT / CRASH)'),
    ('if2', 'MOD PACK FLY SUPERMAN INF2 XXX', BUNG, 'broken: 82-word cave over live code (author: NO EFFECT / CRASH)'),
    ('fob', '8 NPEA00322 (EU) entries', 'various', 'other FoB build; our NPUA80657 has its own entries (ported above)'),
    ('if1', 'Black Lightning USA XXX', BUNG, 'the inFAMOUS 2 patch pasted under the if1 key (if2 addresses 0x2CFA3C/0x75FD00/0xA80104); no if1 equivalent'),
    ('if1', 'MOD PACK PLUS GIGA XXX', BUNG, '42 words incl. 3 caves at BCUS 0x564ED0.. that compare return addresses (0x12808C) and jump back to BCUS '
                                            'absolute addresses; without the BCUS98119 EBOOT the 12 sub-sites cannot be verified one by one'),
    ('if1', 'MOD PACK FLY SUPERMAN XXX', BUNG, '109-word cave over BCUS code with absolute cross-references; cannot be verified without BCUS98119'),
    ('if1', 'Disable Shadows XXX (BCUS li r3,1000 at 0x257A48)', BUNG + ' / FlexBy', 'the BCUS shadow patch: no `li r3` site at the shifted address; '
                                                                                     'covered by if1_no_shadows (FlexBy\'s BCES version); author: BROKEN CRASH'),
    ('if1', 'Civilians Are Invincible And Can Not Decrease Karma', BUNG, 'BCUS 0x1F1D14: a nop of one instruction; the BCUS->BCES shift in '
                                                                         '0x1Fxxxx is unknown (-0x168 at 0x17E, +0x90 from 0x2D5) and no candidate is unambiguous'),
    ('if1', 'Objects Never Run Out Of Electricity', BUNG, 'BCUS 0xD800C nop: no anchor below 0x124000 to fix the shift; author: soft lock in two missions'),
    ('if1', 'Instantly Absorb All Electricity From Objects', BUNG, 'BCUS 0xD84CC nop: same, and author: NO EFFECT'),
    ('if1', 'Skip Intro USA XXX / other-build duplicates (NPUA80480, BCES v1.02, BCUS98119 copies of patches ported above)', 'various',
     'other builds; the BCES00220 01.00 version is in the catalog'),
    ('if2', 'Skip Intro for NPEA00318 / BCUS98125 / demo / UGC beta', 'FlexBy', 'other inFAMOUS 2 builds'),
]
BUILTIN = [
    ('if1', '(Experimental) Unstable audio', 'Hasster', 'already in the port: tools/patch_if1_unstable_audio.py, on by default, PS3_IF1_AUDIO_PATCH=0 turns it off'),
    ('if1', 'Disable speed limit', 'Hasster', 'already in the port: game_patches.cpp if1_rpcs3_data, PS3_IF1_RPCS3_DATA=0 turns it off'),
    ('if1', 'Disable refraction/shifting effect', 'Hasster', 'already in the port: game_patches.cpp if1_rpcs3_data (PS3_IF1_REFRACTION=1 keeps the effect)'),
]


def cstr(s):
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'


def main():
    elfs = {g: Elf(p) for g, p in ELF.items()}
    games = ('if2', 'fob', 'if1')
    ids = [t['id'] for t in T]
    assert len(ids) == len(set(ids)), 'duplicate id'
    cat = {'generated_by': 'tools/gpatch/gen_catalog.py', 'env': 'PS3_GPATCH=<id>,<id>,...', 'ini_key': 'gameplay_patches',
           'ppu_hash': PPU, 'toggles': [], 'not_portable': [], 'already_in_port': []}
    errs = []
    for g in games:
        tl = [t for t in T if t['game'] == g]
        for k, t in enumerate(tl):
            t['flag_index'] = k
            for m in t['members']:
                assert m in ids, m
            dl = []
            for ea, w, v in t['data']:
                o = elfs[g].rd(ea, w)
                dl.append((ea, w, v, o))
            t['data_full'] = dl
            if t['id'] == 'if1_blur_bloom_fix':
                for ea, w, v, o in dl:
                    if abs(u2f(o) - 3 * u2f(v)) > 1e-5 * max(1, abs(u2f(o))):
                        errs.append('blur: 0x%X holds %g, not 3 x %g' % (ea, u2f(o), u2f(v)))
        grp = {}
        for t in tl:
            if t['group']: grp.setdefault(t['group'], []).append(t['id'])
        for t in tl:
            conf = [x for x in grp.get(t['group'], []) if x != t['id']]
            if t['id'] in ('if1_infinite_health', 'if1_enemies_die_on_fall', 'if1_cole_invincible'):
                pass
            cat['toggles'].append({
                'id': t['id'], 'games': [g], 'flag_index': t['flag_index'], 'display_name': t['name'], 'description': t['desc'],
                'author': t['author'], 'source': t['src'], 'category': t['cat'], 'kind': t['kind'], 'requires': t['requires'],
                'conflicts': conf, 'conflict_group': t['group'], 'bundle_members': t['members'], 'risk': t['risk'], 'default': False,
                'sites': [{'addr': '0x%08X' % a, 'original': o, 'patched': n} for a, o, n in t['sites']],
                'data': [{'addr': '0x%08X' % ea, 'width': w, 'value': '0x%0*X' % (2 * w, v), 'original': '0x%0*X' % (2 * w, o)}
                         for ea, w, v, o in t['data_full']],
                'evidence': t['evidence'], 'translation': t['translation']})
        # ---- gpatch_<game>.inc
        L = ['/* gpatch_%s.inc -- GENERATED by tools/gpatch/gen_catalog.py from patch_catalog.json; do not edit. */' % g,
             'enum { GPK_DATA, GPK_HOOK, GPK_BUNDLE };',
             'struct gpatch_toggle_t { const char *id, *name, *author; int kind; const char *group, *members; };',
             'struct gpatch_data_t { int k; uint32_t ea; int w; uint32_t value, orig; int policy; };',
             '#define GPATCH_GAME "%s"' % g, '#define GPATCH_PPU_HASH "%s"' % PPU[g], '#define GPATCH_COUNT %d' % len(tl),
             '/* index = the flag index the patcher (gpatch_apply_%s.py) wrote into the lifted code: never reorder, only append */' % g,
             'static const gpatch_toggle_t kGpatch[GPATCH_COUNT] = {']
        for t in tl:
            L.append('    { %s, %s, %s, %s, %s, %s },   /* %d */' % (
                cstr(t['id']), cstr(t['name']), cstr(t['author']), {'data': 'GPK_DATA', 'hook': 'GPK_HOOK', 'bundle': 'GPK_BUNDLE'}[t['kind']],
                cstr(t['group']), cstr(','.join(t['members'])), t['flag_index']))
        L += ['};', '#include "gpatch_data_%s.inc"' % g, '#include "gpatch_runtime.inc"', '']
        open(os.path.join(HERE, 'gpatch_%s.inc' % g), 'w').write('\n'.join(L))
        # ---- gpatch_data_<game>.inc
        L = ['/* gpatch_data_%s.inc -- GENERATED by gen_catalog.py. { toggle index, guest address, width, value, original value in our EBOOT, policy }' % g,
             ' * policy 0: written once at boot (as RPCS3 does), 1: also watched by gpatch_tick (logged once if the game changes it) */',
             'static const gpatch_data_t kGpatchData[] = {']
        n = 0
        for t in tl:
            for ea, w, v, o in t['data_full']:
                pol = 1 if t['cat'] == 'camera' else 0
                L.append('    { %2d, 0x%08Xu, %d, 0x%08Xu, 0x%08Xu, %d },   /* %s */' % (t['flag_index'], ea, w, v, o, pol, t['id']))
                n += 1
        if not n:
            L.append('    { -1, 0, 0, 0, 0, 0 },   /* (none) */')
        L += ['};', '#define GPATCH_DATA_N (sizeof kGpatchData / sizeof kGpatchData[0])', '']
        open(os.path.join(HERE, 'gpatch_data_%s.inc' % g), 'w').write('\n'.join(L))
        # ---- gpatch_menu_<game>.inc (launcher)
        L = ['/* gpatch_menu_%s.inc -- GENERATED by gen_catalog.py: the launcher\'s GAMEPLAY PATCHES list for this game.' % g,
             ' * { ini id, name, one-line description, category, risk word, conflict group } -- all off by default.',
             ' * Needs before the include: typedef struct { const char *id, *name, *desc, *cat, *risk, *group; } gpmenu_t; */',
             'static const gpmenu_t kGpMenu_%s[] = {' % g]
        for t in tl:
            L.append('    { %s, %s, %s, %s, %s, %s },' % (cstr(t['id']), cstr(t['name'].upper()), cstr(t['desc']), cstr(t['cat'].upper()),
                                                    cstr(t['risk'].split(':')[0].split(' ')[0]), cstr(t['group'])))
        L += ['};', '']
        open(os.path.join(HERE, 'gpatch_menu_%s.inc' % g), 'w').write('\n'.join(L))
    for g, n, a, r in NOT_PORTABLE:
        cat['not_portable'].append({'game': g, 'patch': n, 'author': a, 'reason': r})
    for g, n, a, r in BUILTIN:
        cat['already_in_port'].append({'game': g, 'patch': n, 'author': a, 'note': r})
    json.dump(cat, open(os.path.join(HERE, 'patch_catalog.json'), 'w'), indent=1)
    by = {}
    for t in T:
        by.setdefault((t['game'], t['kind']), 0); by[(t['game'], t['kind'])] += 1
    print('toggles:', len(T), dict(sorted(by.items())))
    if errs:
        print('ERRORS:'); print('\n'.join(errs)); return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
