#!/usr/bin/env python3
"""Judge one R4c boot: the kernel's lines and rdnr4map's output against the
gates of docs/R4C_VMAP_PLAN.md 11-5.

  check_vmap_log.py <rdn-all.log> <rdnr4map.out> <build hex8>
  check_vmap_log.py --self-test

  G1  the vmap line: ok, fix 0, self-test 0 wrong, allowed pages = (end-start)/page,
      start = the Matrox rule for this boot's mode, end 07c00000, page 8192, shift
      13, bar0 = R1's e0000000, mem = aper = R1's 08000000, pfn0 and pfnN
      recomputed here, the major equal to the tool's; the tool saw no other node
  G2  the ten boundaries as the plan's 4 step 4 list says (read from the
      document), minor 1 refused with ENXIO (6)
  G3  the round trip: bad 0
  G4  UBLIT: the kernel's line rc 0 and every count 0; the tool's block ok 65536,
      stale = mark = other = 0
  G5  FILL: the same, and the warm read-back 0
  G6  aliasing: lo unchanged, hi read back, both pages put back
  G7  the tool ended exit=0; this boot's open lines are one ok and one refused;
      a later RDNR2bCycle is live with verdict 0 and bad = vga = palette = 0

What the verdict cannot say (plan 11-5): whether the mapping is uncached or
write-combining -- the tool's write/read timings are printed for the record.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
DOC = os.path.join(PROJ, 'docs', 'R4C_VMAP_PLAN.md')
DISP = os.path.join(PROJ, 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj', 'OSRDNDisplay.m')
sys.path.insert(0, HERE)
from check_engine import parse as engine_parse, win_start, BPP  # noqa: E402

PAGE = 8192
CEIL = 0x07C00000
BAR0 = 0xE0000000           # docs/R1_RESULT.md 25
VRAM = 0x08000000           # docs/R1_RESULT.md 35
MAJOR = 38                  # the tables' "Character Major" (docs/R4C_VMAP_PLAN.md 14)
BLOCK_WORDS = 0x40000 // 4


def plan_bounds():
    doc = open(DOC, encoding='utf-8').read()
    sec = doc.split('### 11-4.', 1)[0].split('## 4.', 1)[1].split('## 5.', 1)[0]
    m = re.search(r'4\. \*\*경계\*\*[^:]*:(.*?)\n\s*\d+\.', sec, re.S)
    return [('✓' in x) for x in m.group(1).split('·')] if m else []


def judge(log, out, build, bounds=None):
    p, notes = [], []
    bounds = plan_bounds() if bounds is None else bounds
    boot, eng = engine_parse(log)
    if boot is None or 'select' not in eng:
        return ['no RDN-R3 select line'], notes
    w, h, fmt = eng['select']

    # ---- G1
    vm = None
    for line in log.splitlines():
        m = re.search(r'RDN-R4 vmap boot=(\w+) start=([0-9a-f]{8}) end=([0-9a-f]{8}) page=(\d+) shift=(\d+) '
                      r'bar0=([0-9a-f]{8}) pfn0=([0-9a-f]{8}) pfnN=([0-9a-f]{8}) mem=([0-9a-f]{8}) aper=([0-9a-f]{8}) '
                      r'fix=(-?\d+) self=(\d+)/(\d+) allowed=(\d+) major=(-?\d+) '
                      r'batch=(-?\d+) bphys=([0-9a-f]{8}) (\S+)', line)
        if m and m.group(1) == boot:
            g = m.groups()
            vm = dict(start=int(g[1], 16), end=int(g[2], 16), page=int(g[3]), shift=int(g[4]), bar0=int(g[5], 16),
                      pfn0=int(g[6], 16), pfnN=int(g[7], 16), mem=int(g[8], 16), aper=int(g[9], 16), fix=int(g[10]),
                      cases=int(g[11]), bad=int(g[12]), allowed=int(g[13]), major=int(g[14]),
                      batch=int(g[15]), bphys=int(g[16], 16), why=g[17])
    if vm is None:
        p.append('G1: no vmap line for boot %s' % boot)
    else:
        want_start = win_start(w, h, BPP.get(fmt, 0))
        checks = [('why', 'ok'), ('fix', 0), ('bad', 0), ('start', want_start), ('end', CEIL), ('page', PAGE),
                  ('shift', 13), ('bar0', BAR0), ('mem', VRAM), ('aper', VRAM),
                  ('allowed', (CEIL - want_start) // PAGE), ('pfn0', (BAR0 + want_start) >> 13),
                  ('pfnN', (BAR0 + CEIL - PAGE) >> 13)]
        for k, v in checks:
            if vm[k] != v:
                p.append('G1: vmap %s = %s, want %s' % (k, vm[k] if isinstance(vm[k], str) else hex(vm[k]),
                                                      v if isinstance(v, str) else hex(v)))
        if vm['major'] != MAJOR:
            p.append('G1: the major is %d, the tables fix %d' % (vm['major'], MAJOR))
        if vm['cases'] < (CEIL // PAGE):
            p.append('G1: the self-test asked only %d cases' % vm['cases'])
        # R7b: the batch window is offered on the same line and by the same gate.
        # 0 is OSRDN_VMAP_OK; anything else is a refusal code, and an accepted
        # window at address zero is not a window.
        if vm['batch'] != 0:
            p.append('G1: the batch window was refused, code %d' % vm['batch'])
        elif vm['bphys'] == 0:
            p.append('G1: the batch window is accepted but fixed at zero')
        elif vm['bphys'] % PAGE:
            p.append('G1: the batch window is at %#x, which does not start a page' % vm['bphys'])
        if 'must NOT be unloaded' not in log:
            p.append('G1: the "must NOT be unloaded" line is missing')
    tm = re.search(r'RDNR4M step=major r=0 major=(\d+) driver=(-?\d+)', out)
    if not tm or vm is None or int(tm.group(1)) != vm['major'] or int(tm.group(2)) != vm['major']:
        p.append('G1: the tool\'s major %s is not the driver\'s %s' % (tm.groups() if tm else None,
                                                                       vm and vm['major']))
    nodes = re.findall(r'RDNR4M devscan node=(\S+)', out)
    if any(n not in ('/dev/rdnvram0', '/dev/rdnvram1') for n in nodes):
        p.append('G1: other nodes reach the major: %s' % nodes)
    if not re.search(r'RDNR4M begin runid=\d+ build=%s' % build.lower(), out):
        p.append('G1: the tool output is not for build %s' % build)

    # ---- G2
    got = re.findall(r'RDNR4M bound k=(\d+) what=(\S+) off=[0-9a-f]{8} pages=\d+ prot=\d+ want=(ok|refused) '
                     r'got=(ok|refused) errno=(-?\d+)', out)
    if len(got) != 10 or len(bounds) != 10:
        p.append('G2: %d boundary lines, the plan lists %d' % (len(got), len(bounds)))
    else:
        for (k, what, want, g, err), plan in zip(got, bounds):
            if (want == 'ok') != plan or (g == 'ok') != plan:
                p.append('G2: bound %s %s wanted %s got %s, the plan says %s' % (k, what, want, g,
                                                                               'ok' if plan else 'refused'))
            if g == 'refused' and err != '22':
                notes.append('G2: bound %s %s refused with errno %s (EINVAL is 22)' % (k, what, err))
    if not re.search(r'RDNR4M step=minor1 fd=-1 errno=6\b', out):
        p.append('G2: minor 1 was not refused with ENXIO')

    # ---- G3
    m = re.search(r'RDNR4M self bad=(\d+) write_us=(\d+) read_us=(\d+) bytes=(\d+)', out)
    if not m or int(m.group(1)) != 0:
        p.append('G3: the round trip %s' % (m.group(0) if m else 'is missing'))
    else:
        b = int(m.group(4))
        for what, us in (('write', int(m.group(2))), ('read', int(m.group(3)))):
            notes.append('%s %d bytes in %d us (%.1f MB/s) -- for the record, it cannot decide UC from WC'
                         % (what, b, us, b / us if us else 0.0))

    # ---- G4, G5
    for op, key in (('ublit', 'G4'), ('fill', 'G5')):
        m = re.search(r'RDNR4M %s ok=(\d+) stale=(\d+) mark=(\d+) other=(\d+) first=(-?\d+)' % op, out)
        if not m or (int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))) != (BLOCK_WORDS, 0, 0, 0):
            p.append('%s: the tool read %s' % (key, m.group(0) if m else 'nothing'))
            if m and int(m.group(2)) and not int(m.group(4)):
                notes.append('%s: stale words with a clean kernel judge mean the two mappings differ (plan 11-5)' % key)
        # the kernel's result for THIS tool's argument (other fills may share the boot)
        bm = re.search(r'RDNR4M begin runid=\d+ build=\w+ seedA=([0-9a-f]{8}) seedB=[0-9a-f]{8} colour=([0-9a-f]{8})', out)
        arg = int(bm.group(1 if op == 'ublit' else 2), 16) if bm else None
        r = eng.get((op, arg))
        if r is None:
            p.append('%s: no kernel %s result for the tool\'s argument %s' % (key, op, '%08x' % arg if bm else '?'))
            continue
        if r['rc'] != 0 or r['latched'] or any(r.get(x, 1) for x in ('in', 'out', 'decoy', 'guard', 'left')) \
                or any(r.get('limits', [1])):
            p.append('%s: the kernel judged rc %d why %d in %s out %s decoy %s guard %s' % (
                key, r['rc'], r['why'], r.get('in'), r.get('out'), r.get('decoy'), r.get('guard')))
    m = re.search(r'RDNR4M warm bad=(\d+)', out)
    if not m or int(m.group(1)):
        p.append('G5: the warm read-back %s' % (m.group(0) if m else 'is missing'))

    # ---- G6
    m = re.search(r'RDNR4M alias lo_changed=(\d+) hi_wrong=(\d+) stride=04000000', out)
    if not m or m.group(1) != '0' or m.group(2) != '0':
        p.append('G6: %s' % (m.group(0) if m else 'no aliasing line'))
    m = re.search(r'RDNR4M restore bad=(\d+)', out)
    if not m or m.group(1) != '0':
        p.append('G6: the pages were not put back: %s' % (m.group(0) if m else 'no restore line'))

    # ---- G7
    if not re.search(r'RDNR4M exit=0\s*$', out.strip() + '\n'):
        p.append('G7: the tool did not end exit=0')
    opens = re.findall(r'RDN-R4 open boot=%s dev=\w+ minor=(\d+) (ok|refused)' % re.escape(boot), log)
    if sorted(opens) != [('0', 'ok'), ('1', 'refused')]:
        p.append('G7: open lines %s, want minor 0 ok and minor 1 refused' % opens)
    closes = re.findall(r'RDN-R4 close boot=%s' % re.escape(boot), log)
    notes.append('G7: %d close line(s) (the last close only; an observation)' % len(closes))
    lines = log.splitlines()
    cyc = [k for k, l in enumerate(lines) if re.search(r'RDN-R2B cycled boot=%s live=1' % re.escape(boot), l)]
    verdict = None
    if cyc:
        for l in lines[cyc[-1] + 1:]:
            m = re.search(r'RDN-R2B cycle n=\d+ why=-?\d+ checked=(\d+) cwhy=-?\d+ bad=(\d+) vga=(\d+) palette=(\d+) '
                          r'kernel=\d+ verdict=(-?\d+)', l)
            if m:
                verdict = m.groups()
                break
    if verdict != ('1', '0', '0', '0', '0'):
        p.append('G7: the cycle after the tool: %s' % (verdict,))
    return p, notes


GOOD_LOG = '''\
mach: RDN-R4 alias boot=aaaa0001 win=0029e000 ceiling=07c00000 page=8192 len=00040000 ok
mach: RDN-R3 select boot=aaaa0001 res=800x600 fmt=RGB:888/32 rdflt=0 fdflt=0 pdflt=0 gray=256 gbad=0
mach: RDN-R4 vmap boot=aaaa0001 start=0029e000 end=07c00000 page=8192 shift=13 bar0=e0000000 pfn0=0007014f pfnN=00073dff mem=08000000 aper=08000000 fix=0 self=15900/0 allowed=15537 major=38 batch=0 bphys=00050000 ok
mach: RDN-R4 vmap boot=aaaa0001 the driver must NOT be unloaded: the mappings and the slot outlive it
mach: RDN-R4 open boot=aaaa0001 dev=2601 minor=1 refused opens=0 refused=1 closes=0
mach: RDN-R4 open boot=aaaa0001 dev=2600 minor=0 ok opens=1 refused=1 closes=0
mach: RDN-R4 ublit boot=aaaa0001 n=1 arg=c3070000 rc=0 why=0 gv=00000000 us=300000 latched=0 win=0029e000
mach: RDN-R4 res in=0 not=0 out=0 decoy=0 guard=0 first=-1 f64=0 reread=-1 defsave=00000000 left=0 post=00000000
mach: RDN-R4 wait fifo=1/0/0 idle=3/0/20 dc2=00000000:1/0 dc3=00000000:1/0 idle2=1/0 rst=1/0
mach: RDN-R4 fill boot=aaaa0001 n=2 arg=96000007 rc=0 why=0 gv=00000000 us=300000 latched=0 win=0029e000
mach: RDN-R4 res in=0 not=0 out=0 decoy=0 guard=0 first=-1 f64=0 reread=-1 defsave=00000000 left=0 post=00000000
mach: RDN-R4 wait fifo=1/0/0 idle=3/0/20 dc2=00000000:1/0 dc3=00000000:1/0 idle2=1/0 rst=1/0
mach: RDN-R4 close boot=aaaa0001 dev=2600 minor=0 opens=1 refused=1 closes=1
mach: RDN-R2B cycled boot=aaaa0001 live=1
mach: RDN-R2B cycle n=1 why=0 checked=1 cwhy=0 bad=0 vga=0 palette=0 kernel=0 verdict=0
'''

GOOD_OUT = '''\
RDNR4M begin runid=7 build=937ebd28 seedA=c3070000 seedB=3c070000 colour=96000007
RDNR4M step=state r=0 build=937ebd28 flags=00000001
RDNR4M step=vmap r=0 magic=52344d30 state=1 start=0029e000 end=07c00000 page=8192 major=38 engine=0029e000
RDNR4M step=major r=0 major=38 driver=38
RDNR4M step=minor1 fd=-1 errno=6
RDNR4M bound k=0 what=start off=0029e000 pages=1 prot=3 want=ok got=ok errno=0
RDNR4M bound k=1 what=last off=07bfe000 pages=1 prot=3 want=ok got=ok errno=0
RDNR4M bound k=2 what=last+next off=07bfe000 pages=2 prot=3 want=refused got=refused errno=22
RDNR4M bound k=3 what=end off=07c00000 pages=1 prot=3 want=refused got=refused errno=22
RDNR4M bound k=4 what=before off=0029c000 pages=1 prot=3 want=refused got=refused errno=22
RDNR4M bound k=5 what=zero off=00000000 pages=1 prot=3 want=refused got=refused errno=22
RDNR4M bound k=6 what=unaligned off=0029e004 pages=1 prot=3 want=refused got=refused errno=22
RDNR4M bound k=7 what=readonly off=0029e000 pages=1 prot=1 want=refused got=refused errno=22
RDNR4M bound k=8 what=exec off=0029e000 pages=1 prot=7 want=refused got=refused errno=22
RDNR4M bound k=9 what=negative off=80000000 pages=1 prot=3 want=refused got=refused errno=22
RDNR4M step=block off=0029e000 pages=32 got=ok errno=0
RDNR4M step=fresh already=0
RDNR4M self bad=0 write_us=2000 read_us=9000 bytes=262144
RDNR4M engine op=4 arg=c3070000 r=0
RDNR4M ublit ok=65536 stale=0 mark=0 other=0 first=-1
RDNR4M warm bad=0
RDNR4M engine op=2 arg=96000007 r=0
RDNR4M fill ok=65536 stale=0 mark=0 other=0 first=-1
RDNR4M step=aliasmap lo=03bfe000 hi=07bfe000 got=ok errno=0
RDNR4M alias lo_changed=0 hi_wrong=0 stride=04000000
RDNR4M restore bad=0
RDNR4M done runid=7
RDNR4M exit=0
'''

BAD = [
    ('L', 'the self-test found a wrong answer', 'self=15900/0', 'self=15900/1'),
    ('L', 'the window does not start where the mode puts it', 'start=0029e000 end', 'start=002a0000 end'),
    ('L', 'bar0 is not R1\'s', 'bar0=e0000000', 'bar0=d0000000'),
    ('L', 'MEMSIZE is not 128 MiB', 'mem=08000000', 'mem=04000000'),
    ('L', 'the last PFN is off by one', 'pfnN=00073dff', 'pfnN=00073e00'),
    ('L', 'registration refused', 'major=38 batch=0', 'major=-1 cdevsw batch=0'),
    ('L', 'the automatic major', 'allowed=15537 major=38 batch=', 'allowed=15537 major=1 batch='),
    ('L', 'the batch window was refused', 'batch=0 bphys=', 'batch=13 bphys='),
    ('L', 'the batch window is fixed at zero', 'bphys=00050000', 'bphys=00000000'),
    ('L', 'no "must not unload" line', 'the driver must NOT be unloaded', 'the driver is here'),
    ('O', 'the tool\'s major differs', 'major=38 driver=38', 'major=20 driver=38'),
    ('O', 'another node reaches the major', 'RDNR4M step=minor1', 'RDNR4M devscan node=/dev/osmgavram dev=2600\nRDNR4M step=minor1'),
    ('O', 'the end page was accepted', 'what=end off=07c00000 pages=1 prot=3 want=refused got=refused',
     'what=end off=07c00000 pages=1 prot=3 want=refused got=ok'),
    ('O', 'minor 1 opened', 'fd=-1 errno=6', 'fd=4 errno=0'),
    ('O', 'the round trip is wrong', 'self bad=0', 'self bad=3'),
    ('O', 'stale words after UBLIT', 'ublit ok=65536 stale=0', 'ublit ok=65530 stale=6'),
    ('O', 'marker in the fill rectangle', 'fill ok=65536 stale=0 mark=0', 'fill ok=65000 stale=0 mark=536'),
    ('L', 'the kernel judged the UBLIT wrong', 'arg=c3070000 rc=0 why=0 gv=00000000 us=300000 latched=0 win=0029e000\nmach: RDN-R4 res in=0',
     'arg=c3070000 rc=0 why=0 gv=00000000 us=300000 latched=0 win=0029e000\nmach: RDN-R4 res in=4'),
    ('L', 'the UBLIT was refused', 'arg=c3070000 rc=0 why=0', 'arg=c3070000 rc=1 why=16'),
    ('O', 'aliasing', 'lo_changed=0', 'lo_changed=2048'),
    ('O', 'a page was not put back', 'restore bad=0', 'restore bad=1'),
    ('O', 'the tool did not finish', 'RDNR4M exit=0', 'RDNR4M exit=17'),
    ('L', 'two successful opens', 'minor=1 refused opens=0', 'minor=0 ok opens=0'),
    ('L', 'the cycle after the tool failed', 'palette=0 kernel=0 verdict=0', 'palette=3 kernel=0 verdict=1'),
    ('O', 'another build', 'build=937ebd28 seedA', 'build=11111111 seedA'),
    ('L', 'the kernel\'s UBLIT used another seed', 'ublit boot=aaaa0001 n=1 arg=c3070000', 'ublit boot=aaaa0001 n=1 arg=c3080000'),
]


def driver_format_check():
    """the parser reads the vmap/open lines as the driver writes them"""
    text = open(DISP).read()
    fm = {}
    for m in re.finditer(r'IOLog\(((?:"[^"]*"\s*)+)', text):
        s = ''.join(re.findall(r'"([^"]*)"', m.group(1)))
        if s.startswith('RDN-R4 vmap boot=%08x start'):
            fm['vmap'] = s
        elif s.startswith('RDN-R4 open') and ' ok ' in s:
            fm['open'] = s
    p = []
    if set(fm) != {'vmap', 'open'}:
        return ['driver formats not found: %s' % sorted(fm)]
    vals = iter(['aaaa0001', '0029e000', '07c00000', '8192', '13', 'e0000000', '0007014f', '00073dff', '08000000',
                 '08000000', '0', '15900', '0', '15537', '38', '0', '00050000', 'ok'])
    line = re.sub(r'%0?8?[xuds]', lambda _: next(vals), fm['vmap']).replace('\\n', '')
    if line not in GOOD_LOG:
        p.append('the driver\'s vmap line renders as %r, which the good log does not contain' % line)
    vals = iter(['aaaa0001', '1300', '0', '1', '1', '0'])
    line = re.sub(r'%0?4?8?[xuds]', lambda _: next(vals), fm['open']).replace('\\n', '')
    if not re.search(r'RDN-R4 open boot=aaaa0001 dev=\w+ minor=0 ok', line):
        p.append('the driver\'s open line renders as %r' % line)
    return p


def self_test():
    fails = 0
    fp = driver_format_check()
    for x in fp:
        print('  FAIL %s' % x)
    print('  %-4s the parser reads the driver\'s own vmap and open formats' % ('FAIL' if fp else 'ok'))
    fails += len(fp)
    pb = plan_bounds()
    ok = pb == [True, True] + [False] * 8
    print('  %-4s the plan\'s boundary list reads as 2 accepted then 8 refused (%s)' % ('ok' if ok else 'FAIL', pb))
    fails += 0 if ok else 1
    p, notes = judge(GOOD_LOG, GOOD_OUT, '937ebd28')
    print('  %-4s the clean boot passes%s' % ('FAIL' if p else 'ok', '' if not p else ': %s' % p))
    fails += 1 if p else 0
    for which, label, old, new in BAD:
        base = GOOD_LOG if which == 'L' else GOOD_OUT
        if base.count(old) != 1:
            print('  FAIL %-46s anchor found %d times' % (label, base.count(old)))
            fails += 1
            continue
        lg, ot = (base.replace(old, new), GOOD_OUT) if which == 'L' else (GOOD_LOG, base.replace(old, new))
        bp, _ = judge(lg, ot, '937ebd28')
        print('  %-4s %-46s %s' % ('ok' if bp else 'FAIL', label, bp[:1] if bp else 'NOT CAUGHT'))
        fails += 0 if bp else 1
    print('check_vmap_log self-test: %s' % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return 1 if fails else 0


def main():
    if sys.argv[1:] == ['--self-test']:
        return self_test()
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    p, notes = judge(open(sys.argv[1], errors='replace').read(), open(sys.argv[2], errors='replace').read(),
                     sys.argv[3])
    for n in notes:
        print('  --   %s' % n)
    for x in p:
        print('  FAIL %s' % x)
    print('check_vmap_log: %s' % ('PASS' if not p else 'FAIL (%d)' % len(p)))
    return 1 if p else 0


if __name__ == '__main__':
    sys.exit(main())
