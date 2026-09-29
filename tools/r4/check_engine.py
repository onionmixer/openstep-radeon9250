#!/usr/bin/env python3
"""Judge the R4 engine lines of one boot (docs/R4_ENGINE_PLAN.md 12-3, 12-5).

  check_engine.py <rdn-all.log> <build hex8>    judge the log
  check_engine.py --self-test                   the rules on built-in logs, each shown to fail

The expectations were written into docs/R4_ENGINE_PLAN.md 12-5 BEFORE any value
was seen: FIFO 64 and idle, the CP off, SURFACE_CNTL 00000100.  RB3D_CNTL was
also expected 0; the machine read 0x1800 and the operator chose to write it to
0 in each batch (docs 17), so it is now reported, not required.

Per operation (the last line of each kind wins, so a repeated call is judged
on its latest result):
  alias      "ok", the window start equals the Matrox rule for this boot's mode,
             page 8192, length 00040000
  record     rc 0 and the expectations above
  fill       rc 0, every count 0, no wait on its limit, DEFAULT_OFFSET put back
  blit 0-8   the same
  blit 9,10  the X bit deliberately wrong: mismatches mean the hardware decides
             X ("decides"); none means a row-wide source buffer ("undecidable")
             -- reported, never counted as a pass
  blit 11,12 the Y bit deliberately wrong: mismatches REQUIRED (none = anomaly)
  ublit      R4c (docs/R4C_VMAP_PLAN.md 11-2): as fill -- rc 0, every count 0
  and no line may say latched=1.
"""

import re
import sys

PAGE = 8192
WANT_SURFACE = 0x00000100


def win_start(w, h, bpp):
    v = w * h * bpp + 256 * w * bpp
    return (v + PAGE - 1) // PAGE * PAGE


BPP = {'RGB:888/32': 4, 'RGB:555/16': 2, 'RGB:256/8': 1, 'BW:8': 1}


def parse(text, boot=None):
    """{'select': (w,h,fmt), 'alias': dict, ('record'|'fill'|'blit', arg): dict} for one boot"""
    out = {}
    cur = None
    # the boot first, from the LAST select line: the driver logs its alias line
    # during init BEFORE the select line, so a one-pass reader would miss it
    if boot is None:
        sel = re.findall(r'RDN-R3 select boot=(\w+) ', text)
        boot = sel[-1] if sel else None
    for line in text.splitlines():
        m = re.search(r'RDN-R3 select boot=(\w+) res=(\d+)x(\d+) fmt=(\S+)', line)
        if m and m.group(1) == boot:
            out['select'] = (int(m.group(2)), int(m.group(3)), m.group(4))
        m = re.search(r'RDN-R4 alias boot=(\w+) win=([0-9a-f]{8}) ceiling=([0-9a-f]{8}) page=(\d+) '
                      r'len=([0-9a-f]{8}) (\S+)', line)
        if m and m.group(1) == boot:
            out['alias'] = dict(win=int(m.group(2), 16), page=int(m.group(4)), len=int(m.group(5), 16),
                                why=m.group(6))
        m = re.search(r'RDN-R4 (record|fill|blit|ublit|bad) boot=(\w+) n=(\d+) arg=([0-9a-f]{8}) rc=(-?\d+) '
                      r'why=(\d+) gv=([0-9a-f]{8}) us=(\d+) latched=(\d)', line)
        if m and m.group(2) == boot:
            key = (m.group(1), int(m.group(4), 16) if m.group(1) != 'record' else 0)
            cur = dict(rc=int(m.group(5)), why=int(m.group(6)), gv=m.group(7), us=int(m.group(8)),
                       latched=int(m.group(9)))
            out[key] = cur
            continue
        if cur is None:
            continue
        m = re.search(r'RDN-R4 rec\d ((?:\w+=[0-9a-f]{8} ?)+)', line)
        if m:
            for k, v in re.findall(r'(\w+)=([0-9a-f]{8})', m.group(1)):
                cur[k] = int(v, 16)
        m = re.search(r'RDN-R4 res in=(\d+) not=(\d+) out=(\d+) decoy=(\d+) guard=(\d+) first=(-?\d+) '
                      r'f64=(\d+) reread=(-?\d+) defsave=([0-9a-f]{8}) left=(\d)', line)
        if m:
            for k, v in zip(('in', 'not', 'out', 'decoy', 'guard', 'first', 'f64', 'reread'), m.groups()[:8]):
                cur[k] = int(v)
            cur['left'] = int(m.group(10))
        m = re.search(r'RDN-R4 wait fifo=\d+/(\d)/\d+ idle=\d+/(\d)/\d+ dc2=[0-9a-f]{8}:\d+/(\d) '
                      r'dc3=[0-9a-f]{8}:\d+/(\d) idle2=\d+/(\d) rst=\d+/(\d)', line)
        if m:
            cur['limits'] = [int(x) for x in m.groups()]
    return boot, out


def judge(text, build=None):
    """(problems, notes)"""
    p, notes = [], []
    boot, o = parse(text)
    if 'select' not in o:
        return ['no RDN-R3 select line'], notes
    w, h, fmt = o['select']
    a = o.get('alias')
    if a is None:
        p.append('no alias line for boot %s' % boot)
    else:
        if a['why'] != 'ok':
            p.append('alias refused: %s' % a['why'])
        if a['page'] != PAGE or a['len'] != 0x40000:
            p.append('alias page %d len %08x' % (a['page'], a['len']))
        want = win_start(w, h, BPP.get(fmt, 0))
        if a['win'] != want:
            p.append('alias window %08x, the Matrox rule gives %08x for %dx%d %s' % (a['win'], want, w, h, fmt))
    for key, r in o.items():
        if not isinstance(key, tuple):
            continue
        op, arg = key
        tag = '%s %s' % (op, arg if op == 'blit' else ('%08x' % arg if op in ('fill', 'ublit') else ''))
        if r['latched']:
            p.append('%s: the engine is latched' % tag)
        if r['rc'] != 0:
            p.append('%s: rc %d why %d gv %s' % (tag, r['rc'], r['why'], r['gv']))
            continue
        if op == 'record':
            if 'rb3d' not in r:
                p.append('record: no RB3D_CNTL word')
            else:
                notes.append('record: RB3D_CNTL %08x (each batch writes it to 0, docs 17)' % r['rb3d'])
            if r.get('rbbm', 0) & 0x7f != 64 or r.get('rbbm', 0) & 0x80000000:
                p.append('record: RBBM_STATUS %08x' % r.get('rbbm', 0))
            if r.get('csq', 0) & 0xf0000000:
                p.append('record: CP_CSQ_CNTL %08x' % r.get('csq', 0))
            if r.get('surf', -1) != WANT_SURFACE:
                p.append('record: SURFACE_CNTL %08x, R1 read 00000100' % r.get('surf', -1))
            continue
        need = ('in', 'out', 'decoy', 'guard', 'limits', 'left')
        if any(k not in r for k in need):
            p.append('%s: result or wait line missing' % tag)
            continue
        if any(r['limits']):
            p.append('%s: a wait ended on its limit %s' % (tag, r['limits']))
        if r['left']:
            p.append('%s: DEFAULT_OFFSET left on the decoy' % tag)
        if r['out'] or r['guard'] or r['decoy']:
            p.append('%s: out %d guard %d decoy %d' % (tag, r['out'], r['guard'], r['decoy']))
        if op == 'blit' and arg in (9, 10):
            notes.append('blit %d (X deliberately wrong): %s' % (arg, 'decides X (in %d)' % r['in']
                                                                 if r['in'] else 'X UNDECIDABLE (row buffer)'))
        elif op == 'blit' and arg in (11, 12):
            if r['in'] == 0:
                p.append('blit %d (Y deliberately wrong) matched: an anomaly, Y should always show' % arg)
            else:
                notes.append('blit %d (Y deliberately wrong): decides Y (in %d)' % (arg, r['in']))
        elif r['in']:
            p.append('%s: in %d (not %d, first %d, f64 %d, reread %d)' % (tag, r['in'], r.get('not', -1),
                                                                         r.get('first', -1), r.get('f64', -1),
                                                                         r.get('reread', -1)))
    return p, notes


# a clean boot at 1024x768x32 (window 4194304 = 00400000)
GOOD = '''\
mach: RDN-R4 alias boot=aaaa0001 win=00400000 ceiling=07c00000 page=8192 len=00040000 ok
mach: RDN-R3 select boot=aaaa0001 res=1024x768 fmt=RGB:888/32 rdflt=0 fdflt=0 pdflt=0 gray=0 gbad=0
mach: RDN-R4 record boot=aaaa0001 n=1 arg=00000000 rc=0 why=0 gv=00000000 us=100 latched=0 win=00400000
mach: RDN-R4 rec0 rbbm=00000140 csq=02010080 dc2=00000000 dc3=00000000 dcs=00000000 dc2mode=00000000 rb3d=00000000 defoff=00000000
mach: RDN-R4 rec1 defpitch=00000000 defsc=1fff1fff sctl=00000000 scbr=1fff1fff auxsc=00000000 dtype=00000000 gmc=00000000 dpcntl=00000003
mach: RDN-R4 rec2 wmask=ffffffff dstpo=00000000 srcpo=00000000 brush=00000000 surf=00000100 sclk=00007ffa sclkmore=00000000 pwrmgt=00000000
mach: RDN-R4 fill boot=aaaa0001 n=2 arg=deadbeef rc=0 why=0 gv=00000000 us=300000 latched=0 win=00400000
mach: RDN-R4 res in=0 not=0 out=0 decoy=0 guard=0 first=-1 f64=0 reread=-1 defsave=00000000 left=0 post=00000000
mach: RDN-R4 wait fifo=1/0/0 idle=3/0/20 dc2=00000000:1/0 dc3=00000000:1/0 idle2=1/0 rst=1/0
mach: RDN-R4 blit boot=aaaa0001 n=3 arg=00000009 rc=0 why=0 gv=00000000 us=300000 latched=0 win=00400000
mach: RDN-R4 res in=0 not=0 out=0 decoy=0 guard=0 first=-1 f64=0 reread=-1 defsave=00000000 left=0 post=00000000
mach: RDN-R4 wait fifo=1/0/0 idle=3/0/20 dc2=00000000:1/0 dc3=00000000:1/0 idle2=1/0 rst=1/0
mach: RDN-R4 blit boot=aaaa0001 n=4 arg=0000000b rc=0 why=0 gv=00000000 us=300000 latched=0 win=00400000
mach: RDN-R4 res in=3584 not=0 out=0 decoy=0 guard=0 first=114880 f64=0 reread=3584 defsave=00000000 left=0 post=00000000
mach: RDN-R4 wait fifo=1/0/0 idle=3/0/20 dc2=00000000:1/0 dc3=00000000:1/0 idle2=1/0 rst=1/0
mach: RDN-R4 ublit boot=aaaa0001 n=5 arg=c3010000 rc=0 why=0 gv=00000000 us=300000 latched=0 win=00400000
mach: RDN-R4 res in=0 not=0 out=0 decoy=0 guard=0 first=-1 f64=0 reread=-1 defsave=00000000 left=0 post=00000000
mach: RDN-R4 wait fifo=1/0/0 idle=3/0/20 dc2=00000000:1/0 dc3=00000000:1/0 idle2=1/0 rst=1/0
'''

BAD = [
    ('the window start is not the Matrox rule', 'win=00400000 ceiling', 'win=00402000 ceiling'),
    ('the alias was refused', 'len=00040000 ok', 'len=00040000 bridge'),
    ('SURFACE_CNTL differs from R1', 'surf=00000100', 'surf=00200100'),
    ('a fill pixel is wrong', 'res in=0 not=0 out=0 decoy=0 guard=0 first=-1 f64=0 reread=-1 defsave=00000000 left=0 post=00000000\nmach: RDN-R4 wait fifo=1/0/0 idle=3/0/20 dc2=00000000:1/0 dc3=00000000:1/0 idle2=1/0 rst=1/0\nmach: RDN-R4 blit boot=aaaa0001 n=3',
     'res in=5 not=5 out=0 decoy=0 guard=0 first=24640 f64=5 reread=5 defsave=00000000 left=0 post=00000000\nmach: RDN-R4 wait fifo=1/0/0 idle=3/0/20 dc2=00000000:1/0 dc3=00000000:1/0 idle2=1/0 rst=1/0\nmach: RDN-R4 blit boot=aaaa0001 n=3'),
    ('the decoy changed', 'decoy=0 guard=0 first=-1 f64=0 reread=-1 defsave=00000000 left=0 post=00000000\nmach: RDN-R4 wait fifo=1/0/0 idle=3/0/20 dc2=00000000:1/0 dc3=00000000:1/0 idle2=1/0 rst=1/0\nmach: RDN-R4 blit boot=aaaa0001 n=3',
     'decoy=7 guard=0 first=-1 f64=0 reread=-1 defsave=00000000 left=0 post=00000000\nmach: RDN-R4 wait fifo=1/0/0 idle=3/0/20 dc2=00000000:1/0 dc3=00000000:1/0 idle2=1/0 rst=1/0\nmach: RDN-R4 blit boot=aaaa0001 n=3'),
    ('a wait hit its limit', 'idle=3/0/20 dc2=00000000:1/0 dc3=00000000:1/0 idle2=1/0 rst=1/0\nmach: RDN-R4 blit boot=aaaa0001 n=3',
     'idle=3/1/20 dc2=00000000:1/0 dc3=00000000:1/0 idle2=1/0 rst=1/0\nmach: RDN-R4 blit boot=aaaa0001 n=3'),
    ('the engine latched', 'n=2 arg=deadbeef rc=0 why=0 gv=00000000 us=300000 latched=0', 'n=2 arg=deadbeef rc=3 why=0 gv=00000000 us=300000 latched=1'),
    ('Y deliberately wrong still matched', 'res in=3584 not=0', 'res in=0 not=0'),
    ('no alias line', 'mach: RDN-R4 alias boot=aaaa0001 win=00400000 ceiling=07c00000 page=8192 len=00040000 ok\n', ''),
    ('a line from another boot', 'RDN-R4 fill boot=aaaa0001', 'RDN-R4 fill boot=bbbb0002'),
    ('a ublit word is wrong', 'arg=c3010000 rc=0 why=0 gv=00000000 us=300000 latched=0 win=00400000\nmach: RDN-R4 res in=0 not=0',
     'arg=c3010000 rc=0 why=0 gv=00000000 us=300000 latched=0 win=00400000\nmach: RDN-R4 res in=3 not=3'),
    ('a ublit refused (the user\'s words did not read back)', 'arg=c3010000 rc=0 why=0 gv=00000000',
     'arg=c3010000 rc=1 why=16 gv=00010000'),
]


MODELOG = __import__('os').path.join(__import__('os').path.dirname(__import__('os').path.abspath(__file__)),
                                     '..', '..', 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj', 'osrdn_modelog.m')
CLASS = MODELOG.replace('osrdn_modelog.m', 'OSRDNDisplay.m')


def render(fmt, values):
    """fill a C format string with the given values in order (%08x %u %d %s only)"""
    out, k = '', 0
    for part in re.split(r'(%0?8?[xuds])', fmt):
        if re.fullmatch(r'%0?8?[xuds]', part):
            out += values[k]
            k += 1
        else:
            out += part
    return out


def driver_formats():
    """the IOLog formats of the R4 lines, as the driver writes them"""
    text = open(MODELOG).read() + open(CLASS).read()
    fm = {}
    for m in re.finditer(r'IOLog\("(RDN-R4 [^"]*)\\n"', text):
        fm[m.group(1).split(' ')[1]] = m.group(1)
    return fm


def format_check():
    """the parser reads what the driver prints (not only what this file says it prints)"""
    fm = driver_formats()
    need = ('alias', '%s', 'rec%d', 'res', 'wait')
    missing = [k for k in need if k not in fm]
    if missing:
        return ['driver formats not found: %s' % missing]
    lines = [
        render(fm['alias'], ['aaaa0001', '00400000', '07c00000', '8192', '00040000', 'ok']),
        'RDN-R3 select boot=aaaa0001 res=1024x768 fmt=RGB:888/32 rdflt=0',
        render(fm['%s'], ['fill', 'aaaa0001', '2', 'deadbeef', '0', '0', '00000000', '9', '0', '00400000']),
        render(fm['res'], ['0', '0', '0', '0', '0', '-1', '0', '-1', '00000000', '0', '00000000']),
        render(fm['wait'], ['1', '0', '0', '3', '0', '20', '00000000', '1', '0', '00000000', '1', '0', '1', '0', '1', '0']),
        render(fm['%s'], ['record', 'aaaa0001', '1', '00000000', '0', '0', '00000000', '9', '0', '00400000']),
        render(fm['rec%d'], ['0'] + [x for i in range(8) for x in ('rb3d' if i == 0 else 'surf' if i == 1 else 'x%d' % i,
                                                                    '00000000' if i != 1 else '00000100')]),
    ]
    boot, o = parse('\n'.join('mach: ' + l for l in lines))
    p = []
    if 'alias' not in o or o['alias']['win'] != 0x400000:
        p.append('the parser does not read the driver\'s alias line: %r' % lines[0])
    f = o.get(('fill', 0xdeadbeef))
    if not f or 'in' not in f or 'limits' not in f:
        p.append('the parser does not read the driver\'s fill/res/wait lines')
    r = o.get(('record', 0))
    if not r or r.get('surf') != 0x100 or r.get('rb3d') != 0:
        p.append('the parser does not read the driver\'s record lines')
    return p


def self_test():
    fails = 0
    fp = format_check()
    for x in fp:
        print('  FAIL %s' % x)
    print('  %-4s the parser reads the driver\'s own IOLog formats (osrdn_modelog.m, OSRDNDisplay.m)'
          % ('FAIL' if fp else 'ok'))
    fails += len(fp)
    p, notes = judge(GOOD)
    print('  %-4s the clean log passes%s' % ('FAIL' if p else 'ok', ('' if not p else ': %s' % p)))
    fails += 1 if p else 0
    if not any('UNDECIDABLE' in n for n in notes):
        print('  FAIL case 9 matching is not reported as undecidable')
        fails += 1
    for label, old, new in BAD:
        if GOOD.count(old) != 1:
            print('  FAIL %-40s anchor found %d times' % (label, GOOD.count(old)))
            fails += 1
            continue
        bp, _ = judge(GOOD.replace(old, new))
        # "a line from another boot" drops the fill: the judge must not see it as this boot's
        caught = bool(bp) if label != 'a line from another boot' else not any('fill' in x for x in bp)
        if label == 'a line from another boot':
            b2, o2 = parse(GOOD.replace(old, new))
            caught = ('fill', 0xdeadbeef) not in o2
        print('  %-4s %-40s %s' % ('ok' if caught else 'FAIL', label, bp[:1] if bp else ''))
        fails += 0 if caught else 1
    print('check_engine self-test: %s' % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return 1 if fails else 0


def main():
    if sys.argv[1:] == ['--self-test']:
        return self_test()
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    p, notes = judge(open(sys.argv[1], errors='replace').read(), sys.argv[2])
    for n in notes:
        print('  --   %s' % n)
    for x in p:
        print('  FAIL %s' % x)
    print('check_engine: %s' % ('PASS' if not p else 'FAIL (%d)' % len(p)))
    return 1 if p else 0


if __name__ == '__main__':
    sys.exit(main())
