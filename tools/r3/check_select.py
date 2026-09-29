#!/usr/bin/env python3
"""Judge one R3b-2 boot: did the driver drive what Configure asked for?

  check_select.py <log> <cfg dir> <build>     judge
  check_select.py --self-test

<log> is ONE boot's driver lines (from its RDN-R2B0 init line on), <cfg dir>
a copy of that boot's OSRDNDisplay.config tables (tools/r3/target-cfgsave.sh),
<build> the stamp the boot must carry.  docs/R3_MULTIMODE_PLAN.md 23-5, 23-9 X2.

Every expected value comes from tools/r3/modesel_oracle.py and
tools/oracle/radeon_modeset.py, never from the driver's generated header:
  * the table holds exactly one Instance table and one "Display Mode";
  * the select line names the combination the oracle picks for that string;
  * the entry was live, and its read-back equals the oracle: the four CRTC
    words and the pitch, the CRTC_GEN_CNTL format field with EXT_DISP and
    CRTC_EN, the FIFO fields, the DAC bits, PPLL_DIV_3 for the boot's refdiv,
    and a clean LUT line.
"""

import glob
import importlib.util
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


oracle = _load('modesel_oracle_for_select', os.path.join(HERE, 'modesel_oracle.py'))
rm = oracle.rm
KEY = re.compile(r'^"Display Mode"\s*=\s*"([^"]*)";')


def table_gray(cfg_dir):
    """(levels, refused) for the table's "Gray Levels" (absent: 256)."""
    keys = [m.group(1) for m in (re.match(r'^"Gray Levels"\s*=\s*"([^"]*)";', l)
                                 for l in open(os.path.join(cfg_dir, 'Instance0.table')).read().split('\n')) if m]
    return oracle.gray(keys[0] if keys else None)


def table_mode(cfg_dir):
    """(the Display Mode string, problems)."""
    p = []
    tables = sorted(os.path.basename(f) for f in glob.glob(os.path.join(cfg_dir, 'Instance*.table')))
    if tables != ['Instance0.table']:
        p.append('instance tables %s: exactly Instance0.table is needed (driverLoader configures every one)'
                 % tables)
        return None, p
    keys = [m.group(1) for m in (KEY.match(l) for l in open(os.path.join(cfg_dir, 'Instance0.table')).read().split('\n')) if m]
    if len(keys) != 1:
        p.append('Instance0.table holds %d "Display Mode" lines' % len(keys))
        return None, p
    return keys[0], p


def judge(log_text, mode_string, build, gray=None):
    """Problems, one string each, and a one-line summary.  gray: (levels,
    refused) the table asks for; None skips that check (an R3b-2a boot)."""
    p = []
    lines = [l for l in log_text.split('\n') if 'RDN-' in l]
    inits = [re.search(r'RDN-R2B0 init boot=([0-9a-f]{8}) build=([0-9a-f]{8}) .* ok$', l) for l in lines]
    inits = [m for m in inits if m]
    if len(inits) != 1:
        return ['%d init lines: one boot, starting at its init line, is needed' % len(inits)], ''
    boot = inits[0].group(1)
    if inits[0].group(2) != build:
        p.append('the boot ran build %s, not %s' % (inits[0].group(2), build))

    want = oracle.choose(mode_string)
    res, fmt = rm.MODES[want['res']], rm.FORMATS[want['fmt']]
    sel = [re.search(r'RDN-R3 select boot=(\w+) res=(\d+)x(\d+) fmt=(\S+) rdflt=(\d) fdflt=(\d) pdflt=(\d)', l)
           for l in lines]
    sel = [m for m in sel if m]
    if len(sel) != 1:
        return p + ['%d select lines' % len(sel)], ''
    s = sel[0]
    got = (s.group(1), int(s.group(2)), int(s.group(3)), s.group(4), int(s.group(5)), int(s.group(6)), int(s.group(7)))
    exp = (boot, res['hdisp'], res['vdisp'], fmt['token'], want['resDefault'], want['fmtDefault'], want['pairDefault'])
    if got != exp:
        p.append('select line %s, the oracle says %s for %r' % (got, exp, mode_string))
    if gray is not None:
        g = re.search(r'RDN-R3 select boot=\w+ .* gray=(\d+) gbad=(\d)', [l for l in lines if 'RDN-R3 select' in l][0])
        if g is None or (int(g.group(1)), int(g.group(2))) != tuple(gray):
            p.append('select line Gray Levels %s, the table asks for %s' % (g.groups() if g else None, gray))

    enters = [i for i, l in enumerate(lines) if re.search(r'RDN-R2B enter boot=%s n=\d+ live=' % boot, l)]
    if len(enters) != 1:
        return p + ['%d enter lines (this judge wants exactly one entry)' % len(enters)], ''
    i = enters[0]
    if not lines[i].endswith('live=1'):
        p.append('the entry was not live: %s' % lines[i].split('mach: ')[-1])
    block = lines[i + 1:]
    stop = [k for k, l in enumerate(block) if 'RDN-R2B revert ' in l]
    block = block[:stop[0]] if stop else block
    reg = dict(re.findall(r'RDN-R2B reg (\w+) snap=[0-9a-f]{8} got=([0-9a-f]{8})', '\n'.join(block)))
    pll = dict(re.findall(r'RDN-R2B pll (\w+) snap=[0-9a-f]{8} got=([0-9a-f]{8})', '\n'.join(block)))
    reg = dict((k, int(v, 16)) for k, v in reg.items())
    pll = dict((k, int(v, 16)) for k, v in pll.items())
    mline = [re.search(r'RDN-R2B mode why=(\d+) step=(\d+) refdiv=(\d+) div3=([0-9a-f]{8}) bad=(\d+)', l) for l in block]
    mline = [m for m in mline if m]
    if len(reg) != 13 or len(pll) != 5 or len(mline) != 1:
        return p + ['the entry block has %d reg, %d pll, %d mode lines' % (len(reg), len(pll), len(mline))], ''
    why, step, refdiv, div3, bad = (int(mline[0].group(1)), int(mline[0].group(2)), int(mline[0].group(3)),
                                    int(mline[0].group(4), 16), int(mline[0].group(5)))
    if (why, step, bad) != (0, 14, 0):
        p.append('mode line why=%d step=%d bad=%d, want 0 14 0' % (why, step, bad))

    words = rm.rfb_crtc_words(res)
    for name, w in zip(('CRTC_H_TOTAL_DISP', 'CRTC_H_SYNC_STRT_WID', 'CRTC_V_TOTAL_DISP', 'CRTC_V_SYNC_STRT_WID'), words):
        if reg[name] != w:
            p.append('%s %08x, the oracle says %08x' % (name, reg[name], w))
    if reg['CRTC_PITCH'] != rm.crtc_pitch(res, fmt['bpp']):
        p.append('CRTC_PITCH %08x, the oracle says %08x' % (reg['CRTC_PITCH'], rm.crtc_pitch(res, fmt['bpp'])))
    g = reg['CRTC_GEN_CNTL']
    if (g >> 8) & 0xf != fmt['crtc_format'] or not g & 0x01000000 or not g & 0x02000000:
        p.append('CRTC_GEN_CNTL %08x: format %d, EXT_DISP and CRTC_EN wanted' % (g, fmt['crtc_format']))
    fifo = rm.fifo(res, fmt['bytes'])
    if reg['GRPH_BUFFER_CNTL'] & fifo['clear_bits'] != fifo['set_bits']:
        p.append('GRPH_BUFFER_CNTL %08x, the oracle sets %08x' % (reg['GRPH_BUFFER_CNTL'], fifo['set_bits']))
    if reg['DAC_CNTL'] & 0xff000100 != 0xff000100:
        p.append('DAC_CNTL %08x: DAC_MASK_ALL and DAC_8BIT_EN wanted' % reg['DAC_CNTL'])
    table = rm.pll_table(res)
    if refdiv not in table:
        p.append('refdiv %d has no row for %s' % (refdiv, res['name']))
    else:
        w = table[refdiv]['word']
        if div3 != w or pll['PPLL_DIV_3'] & 0x000707ff != w or pll['PPLL_REF_DIV'] & 0x3ff != refdiv:
            p.append('PPLL_DIV_3 %08x (line %08x), the oracle says %08x for refdiv %d'
                     % (pll['PPLL_DIV_3'], div3, w, refdiv))
    if pll['HTOTAL_CNTL'] != res['htotal'] & 7:
        p.append('HTOTAL_CNTL %08x' % pll['HTOTAL_CNTL'])

    v = [re.search(r'RDN-R3 verify res=(\d+)x(\d+) fmt=(\S+) sel=1 want=(\d+) got=(\d+)', l) for l in block]
    v = [m for m in v if m]
    lut = [re.search(r'RDN-R3 verifylut bad=(-?\d+) k=(-?\d+)', l) for l in block]
    lut = [m for m in lut if m]
    if len(v) != 1 or len(lut) != 1:
        p.append('%d verify and %d verifylut lines' % (len(v), len(lut)))
    else:
        if (int(v[0].group(1)), int(v[0].group(2)), v[0].group(3), int(v[0].group(4)), int(v[0].group(5))) != \
                (res['hdisp'], res['vdisp'], fmt['token'], fmt['crtc_format'], fmt['crtc_format']):
            p.append('verify line %s' % (v[0].groups(),))
        if (int(lut[0].group(1)), int(lut[0].group(2))) != (0, -1):
            p.append('the LUT read-back found %s wrong entries, first %s' % lut[0].groups())
    # R3b-2b: every transfer table and brightness call that reached the card
    # read back clean (docs/R3_MULTIMODE_PLAN.md 24-4, 24-9 A4)
    xfers = [re.search(r'RDN-R3 xfer n=(\d+) count=(-?\d+) result=(\d) applied=\d+ deferred=\d+ stored=\d+ '
                       r'lutbad=(-?\d+) k=(-?\d+)', l) for l in lines]
    xfers = [m for m in xfers if m]
    brights = [re.search(r'RDN-R3 bright n=(\d+) level=(\d+) result=(\d) applied=\d+ deferred=\d+ lutbad=(-?\d+)', l)
               for l in lines]
    brights = [m for m in brights if m]
    want_count = 32 if fmt['bpp'] == 16 else 256
    for m in xfers:
        if int(m.group(2)) != want_count:
            p.append('a transfer table of %s entries at %s (the kernel sends %d)' % (m.group(2), fmt['token'], want_count))
        if m.group(3) == '1' and int(m.group(4)) != 0:
            p.append('transfer table %s read back %s wrong entries' % (m.group(1), m.group(4)))
        if m.group(3) not in '123':
            p.append('transfer table %s result %s' % (m.group(1), m.group(3)))
    applies = [re.search(r'RDN-R3 lutapply applied=(\d+) deferred=\d+ bad=(-?\d+)', l) for l in block]
    applies = [m for m in applies if m]
    if gray is not None and len(applies) != 1:
        p.append('%d lutapply lines in the entry block' % len(applies))
    for m in applies:
        if int(m.group(1)) > 0 and int(m.group(2)) != 0:
            p.append('a table applied as the entry let go read back %s wrong entries' % m.group(2))
    for m in brights:
        if m.group(3) == '1' and int(m.group(4)) != 0:
            p.append('brightness call %s read back %s wrong entries' % (m.group(1), m.group(4)))
    summary = '%s %s refdiv %d div3 %08x, %d tables, %d brightness lines' % (
        res['name'], fmt['token'], refdiv, div3, len(xfers), len(brights))
    return p, summary


XF = 'RDN-R3 xfer n=1 count=%d result=%d applied=1 deferred=0 stored=0 lutbad=%d k=-1'


def self_test():
    """A real R3b-1 boot is an 800x600 32 bpp boot with no select or verify
    lines: synthesise those from the oracle and the judge must pass it, and
    each corruption must fail it."""
    base = open(os.path.join(PROJ, 'build', 'r3b1', 'dfc37c33', 'rdn-all.log')).read().rstrip('\n').split('\n')
    mode = 'Height: 600 Width: 800 Refresh: 60Hz ColorSpace: RGB:888/32'
    init = [k for k, l in enumerate(base) if 'RDN-R2B0 init' in l][0]
    enter = [k for k, l in enumerate(base) if 'RDN-R2B enter' in l][0]
    pre = 'Sep 12 15:21:29 nextonion mach: '
    good = (base[:init + 1] + [pre + 'RDN-R3 select boot=dfc37c33 res=800x600 fmt=RGB:888/32 rdflt=0 fdflt=0 pdflt=0'] +
            base[init + 1:] +
            [pre + 'RDN-R3 verify res=800x600 fmt=RGB:888/32 sel=1 want=6 got=6 fifo=20005c5c dac=ff000102',
             pre + 'RDN-R3 verifylut bad=0 k=-1 got=00000000 want=00000000'])
    good = '\n'.join(good)
    good2b = good.replace('pdflt=0', 'pdflt=0 gray=0 gbad=0') + '\n' + pre + \
        'RDN-R3 lutapply applied=0 deferred=0 bad=0 k=0'
    cases = [
        ('good', good, mode, '04ff2b68', 0),
        ('another build', good, mode, '388767be', 1),
        ('Configure asked for 1024x768', good, mode.replace('600 Width: 800', '768 Width: 1024'), '04ff2b68', 1),
        ('Configure asked for 555', good, mode.replace('888/32', '555/16'), '04ff2b68', 1),
        ('a wrong pitch', good.replace('CRTC_PITCH snap=00000028 got=00640064', 'CRTC_PITCH snap=00000028 got=00320032'),
         mode, '04ff2b68', 1),
        ('a wrong divider', good.replace('div3=0003008e bad=0 written=1', 'div3=0003008f bad=0 written=1'), mode, '04ff2b68', 1),
        ('LUT not clean', good.replace('verifylut bad=0 k=-1', 'verifylut bad=3 k=7'), mode, '04ff2b68', 1),
        ('the entry was refused', good.replace('n=1 live=1', 'n=1 live=0'), mode, '04ff2b68', 1),
        ('two boots mixed', good + '\n' + good, mode, '04ff2b68', 1),
        ('no select line', good.replace('RDN-R3 select', 'RDN-R3 xselect'), mode, '04ff2b68', 1),
        ('a clean table', good + '\n' + pre + XF % (256, 1, 0), mode, '04ff2b68', 0),
        ('2b: clean, Gray Levels 256', good2b, mode, 'x', 0, (0, 0)),
        ('2b: the table asks for 4 greys', good2b, mode, 'x', 1, (4, 0)),
        ('2b: a refused Gray Levels', good2b.replace('gbad=0', 'gbad=1'), mode, 'x', 1, (0, 0)),
        ('2b: a deferred apply read back wrong', good2b.replace('lutapply applied=0 deferred=0 bad=0',
                                                                'lutapply applied=1 deferred=1 bad=2'),
         mode, 'x', 1, (0, 0)),
        ('2b: no lutapply line', good2b.replace('RDN-R3 lutapply', 'RDN-R3 xlutapply'), mode, 'x', 1, (0, 0)),
        ('a table that read back wrong', good + '\n' + pre + XF % (256, 1, 3), mode, '04ff2b68', 1),
        ('a table of the wrong length', good + '\n' + pre + XF % (32, 1, 0), mode, '04ff2b68', 1),
        ('a stored table (no read-back)', good + '\n' + pre + XF % (256, 2, -1), mode, '04ff2b68', 0),
        ('a brightness that read back wrong', good + '\n' + pre +
         'RDN-R3 bright n=1 level=16 result=1 applied=2 deferred=0 lutbad=5', mode, '04ff2b68', 1),
    ]
    fails = 0
    for case in cases:
        label, text, m, build, nwant = case[:5]
        if build == 'x':
            text = text.replace('build=04ff2b68', 'build=0000beef')
            build = '0000beef'
        prob, _ = judge(text, m, build, case[5] if len(case) > 5 else None)
        ok = (not prob) if nwant == 0 else bool(prob)
        print('  %-4s self-test: %-32s %s' % ('ok' if ok else 'FAIL', label, prob[:1] if not ok else ''))
        fails += 0 if ok else 1
    print('check_select self-test: %s' % ('PASS' if not fails else 'FAIL'))
    return 1 if fails else 0


def main(argv):
    if argv[1:] == ['--self-test']:
        return self_test()
    if len(argv) != 4:
        print(__doc__)
        return 2
    mode, p = table_mode(argv[2])
    if mode is not None:
        more, summary = judge(open(argv[1], errors='replace').read(), mode, argv[3],
                              None if argv[3] == '0562410c' else table_gray(argv[2]))
        p += more
    for x in p:
        print('  FAIL %s' % x)
    print('R3 select: %s%s' % ('PASS ' + summary if not p else 'FAIL', '' if p else ' for %r' % mode))
    return 1 if p else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
