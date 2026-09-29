#!/usr/bin/env python3
"""Hold the R4c user tool (tools/r4/rdnr4map.m, r4map_want.c) to the driver and
to the plan (docs/R4C_VMAP_PLAN.md 6-4, 10-2 B7 B12 B13, 11-4, 11-7).

  check_tool_r4map.py        every rule on the real files, then every mutation

  t-consts     every number the tool copies equals the driver's own: the block
               layout, the marker, the fill rectangle, case 0, the parameter
               names, magics, op numbers, the ON state, the seed and colour top
               bytes against the kernel's seed rule; PROT_* and MAP_SHARED are
               the header's (plan 1 F10)
  t-bounds     the ten boundary cases, in order, want exactly what the plan's
               4 step 4 list says (read from the document)
  t-pages      no mapping is longer than 32 pages (plan 1 F4)
  t-order      no boundary mapping is dereferenced; nothing near the ceiling is
               touched before the block has read back clean; the aliasing step
               writes lo, writes hi, reads lo, reads hi, then puts both back
  t-cleanup    after the nodes are made every exit goes through finish(), which
               unlinks both; a drain follows every write loop
  t-want       r4map_want.c against what the driver and the fake engine leave in
               VRAM, every word (tools/r4/sim/world4.c), with its own mutations
"""

import shutil
import atexit
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
TPROJ = os.path.join(PROJ, 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj')
DOC = os.path.join(PROJ, 'docs', 'R4C_VMAP_PLAN.md')
MMAN = os.path.join(os.path.dirname(PROJ), 'ref', 'openstep', 'headers', 'NextDeveloper', 'Headers', 'bsd', 'sys',
                    'mman.h')
INC = os.path.join(PROJ, 'tools', 'r2b', 'sim', 'include')
LIBC32 = '/usr/lib32/libc.so.6'
LD32 = '/lib/ld-linux.so.2'


def defs(text):
    out = {}
    for m in re.finditer(r'^#define\s+(\w+)\s+\(?(0x[0-9a-fA-F]+|\d+)U?L?\b', text, re.M):
        out[m.group(1)] = int(m.group(2), 0)
    return out


def sdefs(text):
    return dict(re.findall(r'^#define\s+(\w+)\s+"([^"]*)"', text, re.M))


def main_body(tool):
    k = tool.find('\nmain(int argc')
    return tool[k:] if k >= 0 else ''


def rules(src):
    r = {}
    tool, want, eh, em, disp, doc, mman = (src['rdnr4map.m'], src['r4map_want.c'], src['osrdn_engine.h'],
                                           src['osrdn_engine.m'], src['OSRDNDisplay.m'], src['doc'], src['mman.h'])
    dw, de, dd, dt, dm = defs(want), defs(eh), defs(disp), defs(tool), defs(mman)

    p = []
    pairs = [('R4M_BLOCK', 'ENG_ALIAS_BYTES'), ('R4M_S0_OFF', 'ENG_S0_OFF'), ('R4M_S0_H', 'ENG_S0_H'),
             ('R4M_S1_OFF', 'ENG_S1_OFF'), ('R4M_S1_H', 'ENG_S1_H'), ('R4M_S2_OFF', 'ENG_S2_OFF'),
             ('R4M_S2_H', 'ENG_S2_H'), ('R4M_MARK', 'ENG_MARK'), ('R4M_FILL_X', 'ENG_FILL_X'),
             ('R4M_FILL_Y', 'ENG_FILL_Y'), ('R4M_FILL_W', 'ENG_FILL_W'), ('R4M_FILL_H', 'ENG_FILL_H')]
    for a, b in pairs:
        if dw.get(a) is None or dw.get(a) != de.get(b):
            p.append('%s = %s, the driver\'s %s = %s' % (a, dw.get(a), b, de.get(b)))
    for a, w in (('R4M_S0_PITCH', 'ENG_S0_W'), ('R4M_S1_PITCH', 'ENG_S1_W'), ('R4M_S2_PITCH', 'ENG_S2_W')):
        if dw.get(a) != 4 * de.get(w, -1):
            p.append('%s = %s, the driver\'s pitch is 4 x %s' % (a, dw.get(a), de.get(w)))
    m = re.search(r'engCases\[ENG_BLIT_CASES\] = \{\s*\{([^}]*)\}', em)
    row = [x.strip() for x in m.group(1).split(',')] if m else []
    if len(row) != 12:
        p.append('engCases[0] not found in osrdn_engine.m')
    else:
        want_row = {'R4M_C0_SX': row[2], 'R4M_C0_SY': row[3], 'R4M_C0_DX': row[7], 'R4M_C0_DY': row[8],
                    'R4M_C0_W': row[9], 'R4M_C0_H': row[10]}
        for k, v in want_row.items():
            if str(dw.get(k)) != v:
                p.append('%s = %s, engCases[0] has %s' % (k, dw.get(k), v))
        if row[0] != 'ENG_S1_OFF' or row[4] != 'ENG_S2_OFF':
            p.append('engCases[0] is no longer S1 onto S2: %s' % row[:5])
    ts, ds = sdefs(tool), sdefs(disp)
    for a, b in (('VMAP_PARAM', 'OSRDN_VMAP_PARAM'), ('ENGINE_PARAM', 'OSRDN_ENGINE_PARAM')):
        if ts.get(a) is None or ts.get(a) != ds.get(b):
            p.append('%s = %r, the driver\'s %s = %r' % (a, ts.get(a), b, ds.get(b)))
    for a, b, d in (('VMAP_MAGIC', 'OSRDN_VMAP_MAGIC', dd), ('VMAP_COUNT', 'OSRDN_VMAP_COUNT', dd),
                    ('VMAP_ON', 'OSRDN_VMAP_ON', dd), ('ENGINE_MAGIC', 'ENG_MAGIC', de),
                    ('OP_FILL', 'ENG_OP_FILL', de), ('OP_UBLIT', 'ENG_OP_UBLIT', de)):
        if dt.get(a) is None or dt.get(a) != d.get(b):
            p.append('%s = %s, the driver\'s %s = %s' % (a, dt.get(a), b, d.get(b)))
    tops = {}
    for name in ('seedA', 'seedB', 'colour'):
        mm = re.search(r'\b%s = (0x[0-9A-Fa-f]+)UL' % name, tool)
        tops[name] = int(mm.group(1), 16) >> 24 if mm else None
    bad = {de.get('ENG_SEED_BAD_TOP_1'), de.get('ENG_SEED_BAD_TOP_2'), de.get('ENG_SEED_BAD_TOP_3')}
    if None in tops.values() or tops['seedA'] in bad or tops['seedB'] in bad or tops['seedA'] == tops['seedB']:
        p.append('the seeds\' top bytes %s break the kernel\'s rule %s' % (tops, sorted(x for x in bad if x)))
    if tops.get('colour') != de.get('ENG_SEED_BAD_TOP_3') or tops.get('colour') == (de.get('ENG_MARK', 0) >> 24):
        p.append('the fill colour\'s top byte %s is not the one the kernel keeps out of seeds' % tops.get('colour'))
    if (dm.get('PROT_READ'), dm.get('PROT_WRITE'), dm.get('PROT_EXEC'), dm.get('MAP_SHARED')) != (1, 2, 4, 1):
        p.append('mman.h: PROT_READ/WRITE/EXEC, MAP_SHARED = %s' % [dm.get(k) for k in
                                                                     ('PROT_READ', 'PROT_WRITE', 'PROT_EXEC', 'MAP_SHARED')])
    r['t-consts'] = p

    p = []
    sec = doc.split('### 11-4.', 1)[0].split('## 4.', 1)
    sec = sec[1].split('## 5.', 1)[0] if len(sec) == 2 else ''
    m = re.search(r'4\. \*\*경계\*\*[^:]*:(.*?)\n\s*\d+\.', sec, re.S)
    plan = [('✓' in x) for x in m.group(1).split('·')] if m else []
    rows = re.findall(r'\{ "([^"]+)",\s*(\d), (-?\d+)L,\s*(\d+)UL, ([^,]+),\s*(\d) \}', tool)
    if len(plan) != 10:
        p.append('the plan\'s boundary list was not found (%d items)' % len(plan))
    elif [bool(int(x[5])) for x in rows] != plan:
        p.append('the tool\'s boundary wants %s, the plan says %s' % ([int(x[5]) for x in rows], [int(x) for x in plan]))
    r['t-bounds'] = p

    p = []
    if dt.get('MAX_PAGES') is None or dt['MAX_PAGES'] > 32:
        p.append('MAX_PAGES is %s' % dt.get('MAX_PAGES'))
    mp = re.search(r'static volatile unsigned long \*\nmapAt\([^)]*\)\n\{(.*?)\n\}', tool, re.S)
    if not mp or 'pages > MAX_PAGES' not in mp.group(1):
        p.append('mapAt does not refuse more than MAX_PAGES')
    for mm in re.finditer(r'\bmapAt\(fd, [^,]+, ([^,]+),', tool):
        if mm.group(1).strip() not in ('1UL', 'b->pages', 'R4M_BLOCK / page'):
            p.append('a mapping of %s pages' % mm.group(1))
    if any(int(x[3]) > 2 for x in rows):
        p.append('a boundary case maps more than 2 pages')
    r['t-pages'] = p

    p = []
    body = main_body(tool)
    # uses, not the declaration "volatile unsigned long *m, *blk"
    if re.search(r'\bm\s*\[|\bm\s*->|[=(!,+?:-]\s*\*\s*m\b(?!\s*,\s*\*blk)', body):
        p.append('a boundary mapping is dereferenced')
    und = body.find('alias UNDECIDED')
    first_hi = min([x for x in (body.find('pl['), body.find('ph[')) if x >= 0] or [-1])
    if und < 0 or first_hi < 0 or first_hi < und or body.find('judgeBlock("fill"') > und:
        p.append('the aliasing pages are touched before the block read back clean')
    seq = ['pl[i] = 0xA1', 'ph[i] = 0xB2', '(pl[i] != (0xA1', '(ph[i] != (0xB2', 'pl[i] = saveLo[i]',
           'ph[i] = saveHi[i]', '(pl[i] != saveLo[i])']
    pos = [body.find(s) for s in seq]
    if any(x < 0 for x in pos) or pos != sorted(pos):
        p.append('the aliasing order is not write lo, write hi, read lo, read hi, restore: %s' % pos)
    if 'hi = end - page;' not in body or 'lo = hi - ALIAS_STRIDE;' not in body or dt.get('ALIAS_STRIDE') != 0x4000000:
        p.append('hi/lo are not end - page and 64 MiB below it')
    r['t-order'] = p

    p = []
    k = body.find('nodesMade = 1;')
    rets = re.findall(r'\breturn ([^;]*);', body[k:]) if k >= 0 else ['?']
    if k < 0 or any(not x.startswith('finish(') for x in rets):
        p.append('an exit after the nodes are made does not go through finish(): %s'
                 % [x for x in rets if not x.startswith('finish(')])
    fin = re.search(r'\nfinish\(int code\)\n\{(.*?)\n\}', tool, re.S)
    if not fin or 'unlink(NODE0)' not in fin.group(1) or 'unlink(NODE1)' not in fin.group(1):
        p.append('finish() does not unlink both nodes')
    loops = len(re.findall(r'\n\s*(?:blk|pl|ph)\[[^\]]*\] = [^;]*;\n\s*drain\(\);', body))
    writes = len(re.findall(r'\n\s*(?:blk|pl|ph)\[[^\]]*\] = ', body))
    if loops != writes:
        p.append('%d write loops, %d followed by drain()' % (writes, loops))
    r['t-cleanup'] = p
    return r


T, W = 'rdnr4map.m', 'r4map_want.c'
MUTATIONS = [
    (W, 'the tool\'s S2 pitch is wrong', '#define R4M_S2_PITCH    512UL', '#define R4M_S2_PITCH    256UL', ['t-consts']),
    (W, 'the tool\'s marker is not the driver\'s', '#define R4M_MARK        0x5a5a5a5aUL',
     '#define R4M_MARK        0x5a5a5a5bUL', ['t-consts']),
    (W, 'case 0 source moved', '#define R4M_C0_SX       32UL', '#define R4M_C0_SX       24UL', ['t-consts']),
    (T, 'the engine magic drifted', '#define ENGINE_MAGIC    0x52344530U', '#define ENGINE_MAGIC    0x52344531U',
     ['t-consts']),
    (T, 'the vmap parameter name drifted', '#define VMAP_PARAM      "RDNR4Vmap"', '#define VMAP_PARAM      "RDNR4VMap"',
     ['t-consts']),
    (T, 'seed A takes the marker\'s top byte', 'seedA = 0xC3000000UL', 'seedA = 0x5A000000UL', ['t-consts']),
    (T, 'the colour is not the byte the kernel keeps out', 'colour = 0x96000000UL', 'colour = 0x97000000UL',
     ['t-consts']),
    (T, 'a refused boundary is wanted', '{ "end",            1, 0L,      1UL, PROT_RW,                0 }',
     '{ "end",            1, 0L,      1UL, PROT_RW,                1 }', ['t-bounds']),
    (T, 'a boundary case is dropped', '    { "zero",           2, 0L,      1UL, PROT_RW,                0 },\n', '',
     ['t-bounds']),
    (T, 'the page cap is raised', '#define MAX_PAGES       32UL', '#define MAX_PAGES       64UL', ['t-pages']),
    (T, 'mapAt forgets the cap', '    if (pages == 0UL || pages > MAX_PAGES)\n        return 0;\n',
     '    if (pages == 0UL)\n        return 0;\n', ['t-pages']),
    (T, 'the whole window is mapped at once', 'blk = mapAt(fd, start, R4M_BLOCK / page, page',
     'blk = mapAt(fd, start, (end - start) / page, page', ['t-pages']),
    (T, 'an accepted boundary mapping is read', '        if (m == 0 && b->want)\n            return finish(11);\n',
     '        if (m == 0 && b->want)\n            return finish(11);\n        if (m != 0)\n            (void)m[0];\n',
     ['t-order']),
    (T, 'an accepted boundary mapping is read through *m',
     '        if (m == 0 && b->want)\n            return finish(11);\n',
     '        if (m == 0 && b->want)\n            return finish(11);\n        i = (m != 0) ? *m : 0UL;\n', ['t-order']),
    (T, 'hi is read before the block check', '    /* 5. the block, and freshness',
     '    if (0)\n        (void)ph[0];\n    /* 5. the block, and freshness', ['t-order']),
    (T, 'hi is written before lo', '    for (i = 0UL; i < page / 4UL; i++)\n        pl[i] = 0xA1000000UL',
     '    for (i = 0UL; i < page / 4UL; i++)\n        ph[i] = 0xB2000000UL | (runid & 0xffUL) << 16 | i;\n'
     '    for (i = 0UL; i < page / 4UL; i++)\n        pl[i] = 0xA1000000UL', ['t-order']),
    (T, 'the stride is 32 MiB', '#define ALIAS_STRIDE    0x4000000UL', '#define ALIAS_STRIDE    0x2000000UL',
     ['t-order']),
    (T, 'an exit leaves the nodes behind', '        return finish(12);', '        return 12;', ['t-cleanup']),
    (T, 'finish forgets one node', '        (void)unlink(NODE1);\n', '', ['t-cleanup']),
    (T, 'a write loop is not drained', '        blk[off / 4UL] = r4mUser(seedB, off);\n    drain();\n',
     '        blk[off / 4UL] = r4mUser(seedB, off);\n', ['t-cleanup']),
]

# r4map_want.c mutants that only the fake world can see (t-want)
WANT_MUTATIONS = [
    ('the copy\'s source row is off by one', '(R4M_C0_SY + (y - R4M_C0_DY)) * R4M_S1_PITCH',
     '(R4M_C0_SY + 1UL + (y - R4M_C0_DY)) * R4M_S1_PITCH'),
    ('the destination rectangle is one pixel wide too many', 'x >= R4M_C0_DX + R4M_C0_W', 'x > R4M_C0_DX + R4M_C0_W'),
    ('S1 is expected to hold the marker after UBLIT', '    if (r4mIn(off, R4M_S1_OFF, R4M_S1_PITCH, R4M_S1_H, &x, &y))\n'
     '        return r4mUser(seed, off);\n', ''),
    ('the fill rectangle ends a row late', 'y < R4M_FILL_Y + R4M_FILL_H', 'y <= R4M_FILL_Y + R4M_FILL_H'),
    ('a stale word counts as other', '    if (got == old)\n        return R4M_STALE;\n', ''),
    ('the marker counts as marked outside the result', '    if (spot && got == R4M_MARK)', '    if (got == R4M_MARK)'),
]


def world(want_path, work):
    exe = os.path.join(work, 'w4')
    cmd = ['gcc-12', '-m32', '-std=gnu89', '-O0', '-Wall', '-Wno-deprecated', '-nostdinc', '-I', INC, '-I', TPROJ,
           '-DR4MAP_WANT="%s"' % want_path, '-x', 'c', os.path.join(TPROJ, 'osrdn_engine.m'),
           os.path.join(TPROJ, 'osrdn_snap.m'), os.path.join(HERE, 'sim', 'world4.c'), '-x', 'none', '-nostdlib',
           '-nostartfiles', LIBC32, '-Wl,-dynamic-linker,' + LD32, '-o', exe]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return None, r.stderr[-400:]
    r = subprocess.run([exe], capture_output=True, text=True, timeout=120)
    return r.stdout, ''


def main():
    src = {'rdnr4map.m': open(os.path.join(HERE, 'rdnr4map.m')).read(),
           'r4map_want.c': open(os.path.join(HERE, 'r4map_want.c')).read(),
           'osrdn_engine.h': open(os.path.join(TPROJ, 'osrdn_engine.h')).read(),
           'osrdn_engine.m': open(os.path.join(TPROJ, 'osrdn_engine.m')).read(),
           'OSRDNDisplay.m': open(os.path.join(TPROJ, 'OSRDNDisplay.m')).read(),
           'doc': open(DOC, encoding='utf-8').read(),
           'mman.h': open(MMAN, errors='replace').read()}
    fails = 0
    print('  == rules on the real files ==')
    base = rules(src)
    for n in sorted(base):
        for why in base[n]:
            print('    FAIL %-10s %s' % (n, why))
        fails += len(base[n])
    if not fails:
        print('    ok   %d rules' % len(base))
    print('  == mutations (each caught by the rule it targets) ==')
    for path, label, old, new, want in MUTATIONS:
        if src[path].count(old) != 1:
            print('    FAIL %-56s anchor found %d times' % (label, src[path].count(old)))
            fails += 1
            continue
        got = rules(dict(src, **{path: src[path].replace(old, new)}))
        caught = sorted(n for n in got if got[n])
        ok = all(w in caught for w in want)
        print('    %-4s %-56s %s' % ('ok' if ok else 'FAIL', label, caught if ok else 'caught by %s' % caught))
        fails += 0 if ok else 1
    print('  == t-want: r4map_want.c against the fake world ==')
    if not os.path.exists(LIBC32):
        print('    --   %s not present, skipped' % LIBC32)
    else:
        work = tempfile.mkdtemp(prefix='chkr4map.', dir=os.environ.get('TMPDIR'))
        atexit.register(shutil.rmtree, work, True)  # 2026-09-24: /tmp reached 35.6 GiB of our scratch
        out, err = world(os.path.join(HERE, 'r4map_want.c'), work)
        ok = out is not None and 'world4: PASS' in out and "the tool's expectations equal VRAM" in out
        print('    %-4s the real file: the world agrees with it word for word' % ('ok' if ok else 'FAIL'))
        if not ok:
            print(out or err)
        fails += 0 if ok else 1
        for label, old, new in WANT_MUTATIONS:
            if src['r4map_want.c'].count(old) != 1:
                print('    FAIL %-56s anchor found %d times' % (label, src['r4map_want.c'].count(old)))
                fails += 1
                continue
            mdir = tempfile.mkdtemp(prefix='chkr4mapm.', dir=os.environ.get('TMPDIR'))
            atexit.register(shutil.rmtree, mdir, True)  # 2026-09-24: /tmp reached 35.6 GiB of our scratch
            path = os.path.join(mdir, 'r4map_want.c')
            open(path, 'w').write(src['r4map_want.c'].replace(old, new))
            out, err = world(path, mdir)
            caught = out is None or 'world4: FAIL' in out
            first = [l.strip() for l in (out or '').splitlines() if l.strip().startswith('FAIL')]
            print('    %-4s %-56s %s' % ('ok' if caught else 'FAIL', label,
                                         (first[0][:60] if first else 'does not build') if caught else 'NOT CAUGHT'))
            fails += 0 if caught else 1
    print('check_tool_r4map: %s' % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
