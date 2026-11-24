#!/usr/bin/env python3
"""gen_mods_catalog.py -- the MODS page's compiled-in catalog (kModCat in launcher.c) from
   tools/gpatch/patch_catalog.json      (GAMEPLAY: every toggle; ini gameplay_patches -> PS3_GPATCH)
   tools/gpatch/cheat_table_<game>.inc  (CHEATS: every k_cheats_<game>[] entry; ini cheats -> PS3_CHEATS)
Output: the block between "/* MODS CATALOG BEGIN" and "/* MODS CATALOG END */".
  python3 -I gen_mods_catalog.py [--sample] [--out block.inc] [--splice launcher.c]
     --sample          the small development table (no JSON needed)
     --splice FILE     replace the block in FILE in place (a launcher.c with the MODS patch applied)
Rules: ids [a-z0-9_.-], < 64 chars, unique per game; at most 64 entries a game (MD_CATMAX); requires/conflicts that
name an id of the same game become links, free-text requirements ("in game: ...") become the entry's `needs` text;
entries of the two sources that write the same guest address are made to conflict (a cheat and a patch doing the
same thing). Exit 1 on any error."""
import sys, os, re, json, glob

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.dirname(HERE)
CATALOG = os.path.join(HERE, 'patch_catalog.json')
CHEATS = sorted(glob.glob(os.path.join(HERE, 'cheat_table_*.inc')))
GAMES = ('if1', 'if2', 'fob')
MAXCAT = 64
APPLY = {'CA_ONCE': 'Applied when the game starts.',
         'CA_SET': 'Written once when the game starts; a save made afterwards keeps it.',
         'CA_FREEZE': 'Held at this value all the time while you play.'}

SAMPLE = [  # (id, game, name, desc, author, category, risk, needs, requires, conflicts, cheat)
    ('if2_thrusters_flight', 'if2', 'Static Thrusters - Flight', 'While gliding: hold Cross to rise, Circle to sink.', 'L_', 'MOVEMENT', 'low', '',
     'if2_improved_thrusters', 'if2_thrusters_fast', 0),
    ('if2_thrusters_fast', 'if2', 'Static Thrusters - Fast', 'Gliding with Static Thrusters is faster (forward speed 1350 to 2000).', 'L_', 'MOVEMENT', 'low', '',
     '', 'if2_thrusters_flight', 0),
    ('if2_black_lightning', 'if2', 'Black Lightning', "Cole's lightning is drawn black (colour patch).", 'L_', 'VISUALS', 'medium', '', '', '', 0),
    ('if2_improved_thrusters', 'if2', 'Improved Static Thrusters', 'Unlocks the Improved Static Thrusters upgrade.', 'rpcs3.CT', 'CHEAT', '', '', '', '', 1),
    ('if2_cole_never_dies', 'if2', 'Cole Never Dies', "Cole's health is set to a huge value whenever it is checked.", 'bungholio', 'CHEAT', 'low', '', '', '', 1),
    ('fob_thrusters_flight', 'fob', 'Static Thrusters - Flight', 'While gliding: hold Cross to rise, Circle to sink.', 'FlexBy', 'MOVEMENT', 'low', '', '', '', 0),
    ('fob_black_lightning', 'fob', 'Black Lightning', "Cole's lightning is drawn black (colour patch).", 'FlexBy', 'VISUALS', 'medium', '', '', '', 0),
    ('if1_blur_bloom_fix', 'if1', 'High-Resolution Blur and Bloom Fix', "Blur and bloom drawn for the PS5's resolution instead of the PS3's 720p.", 'artofaria', 'VISUALS', 'low', '', '', '', 0),
    ('if1_infinite_health', 'if1', 'Infinite Health', "Cole's health never goes down.", 'bungholio', 'CHEAT', 'low', '', '', 'if1_cole_invincible', 1),
    ('if1_cole_invincible', 'if1', 'Cole Invincible', 'Nothing hurts Cole.', 'bungholio', 'CHEAT', 'high', '', '', 'if1_infinite_health', 1),
    ('if1_all_powers', 'if1', 'Unlock all powers', 'Every power and upgrade unlocked from the start.', 'bungholio', 'CHEAT', 'medium', '', '', '', 1),
]


def cstr(s):
    out = []
    for ch in s:
        if ch == '\\': out.append('\\\\')
        elif ch == '"': out.append('\\"')
        elif ch == '\n': out.append(' ')
        elif ord(ch) < 0x20: out.append(' ')
        else: out.append(ch)
    return '"' + ''.join(out) + '"'


def from_sources(errs, warn):
    E = []
    cat = json.load(open(CATALOG, encoding='utf-8'))
    writes = {}   # (game, id) -> set of guest byte addresses
    for t in cat['toggles']:
        games = t.get('games') or [t.get('game')]
        for g in games:
            if g not in GAMES: errs.append('%s: unknown game %r' % (t['id'], g)); continue
            req, needs = [], []
            for r in t.get('requires', []):
                m = re.match(r'([a-z0-9_.-]+)(\s|$)', r)
                if m and any(x['id'] == m.group(1) for x in cat['toggles']): req.append(m.group(1))
                else: needs.append(r)
            risk = t.get('risk', '') or ''
            E.append(dict(id=t['id'], game=g, name=t.get('display_name') or t['id'], desc=t.get('description', ''), author=t.get('author', ''),
                          cat=(t.get('category') or '').upper(), risk=risk, needs='; '.join(needs), req=req, conf=list(t.get('conflicts', [])), cheat=0))
            s = set()
            for d in t.get('data', []):
                a = int(d['addr'], 16); s.update(range(a, a + int(d['width'])))
            writes[(g, t['id'])] = s
    for path in CHEATS:
        src = open(path, encoding='utf-8').read()
        arrays = {}
        for m in re.finditer(r'static const cheat_write (k_\w+)\[\] = \{(.*?)\n\};', src, re.S):
            s = set()
            for w in re.finditer(r'\{\s*0x([0-9A-Fa-f]+)u?,\s*(CW_U8|CW_BE16|CW_BE32)', m.group(2)):
                a = int(w.group(1), 16); s.update(range(a, a + {'CW_U8': 1, 'CW_BE16': 2, 'CW_BE32': 4}[w.group(2)]))
            arrays[m.group(1)] = s
        for m in re.finditer(r'static const cheat_def k_cheats_(\w+)\[\] = \{(.*?)\n\};', src, re.S):
            g = m.group(1)
            if g not in GAMES: errs.append('%s: unknown game %r' % (path, g)); continue
            for e in re.finditer(r'\{\s*"([^"]*)",\s*"([^"]*)",\s*"([^"]*)",\s*(CA_\w+),\s*(\d+),\s*(\w+)\s*\}', m.group(2)):
                cid, name, credit, apply, n, arr = e.groups()
                E.append(dict(id=cid, game=g, name=name, desc=APPLY.get(apply, ''), author=credit, cat='CHEAT', risk='', needs='', req=[], conf=[], cheat=1))
                writes[(g, cid)] = arrays.get(arr, set())
                if arr not in arrays: warn.append('%s: %s: writes %s not found' % (path, cid, arr))
    # same guest bytes written by two entries of one game: they can't be on together
    for a in E:
        for b in E:
            if a is b or a['game'] != b['game'] or b['id'] in a['conf']: continue
            if writes.get((a['game'], a['id'])) and writes[(a['game'], a['id'])] & writes.get((b['game'], b['id']), set()):
                a['conf'].append(b['id'])
    return E


def main():
    args = sys.argv[1:]
    errs, warn = [], []
    if '--sample' in args:
        E = [dict(id=i, game=g, name=n, desc=d, author=a, cat=c, risk=r, needs=nd, req=[x for x in rq.split(',') if x], conf=[x for x in cf.split(',') if x], cheat=ch)
             for i, g, n, d, a, c, r, nd, rq, cf, ch in SAMPLE]
        src = 'the sample table (gen_mods_catalog.py --sample)'
    else:
        E = from_sources(errs, warn)
        src = 'tools/gpatch/patch_catalog.json + tools/gpatch/cheat_table_*.inc'
    for g in GAMES:
        ids = [e['id'] for e in E if e['game'] == g]
        if len(ids) > MAXCAT: errs.append('%s: %d entries (MD_CATMAX %d)' % (g, len(ids), MAXCAT))
        dup = {i for i in ids if ids.count(i) > 1}
        if dup: errs.append('%s: duplicate ids %s' % (g, sorted(dup)))
    for e in E:
        if not re.fullmatch(r'[a-z0-9_.-]{1,63}', e['id']): errs.append('bad id %r' % e['id'])
        for r in e['req'] + e['conf']:
            if not any(x['id'] == r and x['game'] == e['game'] for x in E): warn.append('%s: links %s (not in this game\'s catalog; ignored by the launcher)' % (e['id'], r))
    L = ['/* MODS CATALOG BEGIN -- GENERATED by tools/gpatch/gen_mods_catalog.py from %s; do not edit.' % src,
         ' * { id, game dir, name, one-line description, author, category, risk note, needs (free text), requires, conflicts',
         ' * (comma-separated ids of the same game), cheat (1: CHEATS / ini cheats / PS3_CHEATS, 0: GAMEPLAY / ini',
         ' * gameplay_patches / PS3_GPATCH) } */',
         'typedef struct { const char *id, *game, *name, *desc, *author, *cat, *risk, *needs, *requires, *conflicts; int cheat; } md_cat_t;',
         'static const md_cat_t kModCat[] = {']
    for e in E:
        L.append('    { %s },' % ', '.join([cstr(e['id']), cstr(e['game']), cstr(e['name']), cstr(e['desc']), cstr(e['author']), cstr(e['cat']),
                                           cstr(e['risk']), cstr(e['needs']), cstr(','.join(e['req'])), cstr(','.join(e['conf'])), str(e['cheat'])]))
    L += ['};', '/* MODS CATALOG END */']
    block = '\n'.join(L) + '\n'
    if '--out' in args: open(args[args.index('--out') + 1], 'w', encoding='utf-8').write(block)
    if '--splice' in args:
        p = args[args.index('--splice') + 1]
        s = open(p, encoding='utf-8').read()
        a, b = s.find('/* MODS CATALOG BEGIN'), s.find('/* MODS CATALOG END */')
        if a < 0 or b < a: errs.append('%s: no MODS CATALOG block' % p)
        else: open(p, 'w', encoding='utf-8').write(s[:a] + block + s[b + len('/* MODS CATALOG END */\n'):])
    if '--out' not in args and '--splice' not in args: sys.stdout.write(block)
    for g in GAMES:
        print('%s: %d gameplay, %d cheats' % (g, sum(1 for e in E if e['game'] == g and not e['cheat']), sum(1 for e in E if e['game'] == g and e['cheat'])), file=sys.stderr)
    for w in warn: print('warn:', w, file=sys.stderr)
    for e in errs: print('ERROR:', e, file=sys.stderr)
    return 1 if errs else 0


if __name__ == '__main__':
    sys.exit(main())
