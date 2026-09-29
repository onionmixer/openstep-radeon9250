#!/usr/bin/env python3
"""judge_g50.py -- the frame budget from one GLQuake run (docs/G5_0_PERF_MEASURE_PLAN.md 4).

  judge_g50.py <glq log> [<tstage line file>] [--ref <glq log of the same scene without the knob>]

Reads the RDN-T lines the library prints at exit (mesa/OSRDNMesaTime.c), the
`mgastats tick` lines the port prints per frame, and, when given, the kernel's
`RDN-R5 tstage` line (r5op tdump after the run).  Every RDN-T interval is
INCLUSIVE and tagged by where it happened (out / br / hook); the exclusive
partition is made here and nowhere else:

  wall      = bracket + submit[out] + upload[out] + present[out] + clear[out] + verify[out] + remainder
  bracket   = tri[br] + verify[br] + submit[br] + upload[br] + present[br] + clear[br] + bracket-other
  tri[br]   = tri-self + submit[hook] + upload[hook] + present[hook] + clear[hook]

Self-checks (each printed, any failure fails the judge):
  a. wall from RDN-T against the ticks' first-to-last span (the ticks cover the
     frames only, the wall starts at the first timed call: wall >= ticks, and
     the per-frame figure uses the tick span);
  b. no partial sum exceeds its whole;
  c. frames by present rows == frames by ticks (+-1), and clears per frame ~ 1;
  d. the calibration is 2,660 MHz +- 5 % (the target's TSC);
  e. with --ref, the instrument's cost: (ms/frame with knob) / (ms/frame without) - 1 < 5 %.
"""
import re
import sys

TSC_MHZ = 2660.0


def parse_rdnt(path, pfx='RDN-T'):
    """pfx RDN-TS reads the running totals G5-3's RDNMesaTimeSplit printed at its frame"""
    wall = None
    sites = {}
    for l in open(path, errors='replace'):
        if not l.startswith(pfx + ' '):
            continue
        l = 'RDN-T' + l[len(pfx):]
        m = re.match(r'RDN-T wall us=(\d+) cyc=([0-9a-f]{16}) gtod1000cyc=(\d+) frames_present=(\d+) frames_clear=(\d+)', l)
        if m:
            wall = dict(us=int(m.group(1)), cyc=int(m.group(2), 16), gtod=int(m.group(3)),
                        fp=int(m.group(4)), fc=int(m.group(5)))
            continue
        m = re.match(r'RDN-T site=(\w+) tag=(\w+) n=(\d+) cyc=([0-9a-f]{16}) max=(\d+) huge=(\d+) units=(\d+)', l)
        if m:
            sites[(m.group(1), m.group(2))] = dict(n=int(m.group(3)), cyc=int(m.group(4), 16), max=int(m.group(5)),
                                                    huge=int(m.group(6)), units=int(m.group(7)))
    return wall, sites


def parse_ticks(path):
    t = {}
    for l in open(path, errors='replace'):
        m = re.search(r'mgastats tick t=([\d.]+) frames=(\d+)', l)
        if m:
            t[int(m.group(2))] = float(m.group(1))
    return t


def tick_span(t, first=None):
    """(seconds, frames) from the first tick -- or from frame `first`: a `+map start` run
    spends its first ~115 frames on the console (3,000 character quads a frame, three
    textures) and the world only begins after (G5-1a 5), so the world's own figure is
    the span from frame 150 on"""
    ks = sorted(t)
    if first is not None:
        ks = [k for k in ks if k >= first]
    if len(ks) < 2:
        return None, 0
    return t[ks[-1]] - t[ks[0]], ks[-1] - ks[0]


def parse_tstage(path):
    if path is None:
        return None
    last = None
    for l in open(path, errors='replace'):
        m = re.search(r'RDN-R5 tstage boot=([0-9a-f]+) ops=(\d+) gates=(\d+) pre=(\d+) s1ring=(\d+) s1read=(\d+) '
                      r's2asm=(\d+) s2ring=(\d+) flush=(\d+) tail=(\d+) fence=(\d+) wait=(\d+) put=(\d+)', l)
        if m:
            last = dict(ops=int(m.group(2)), gates=int(m.group(3)), pre=int(m.group(4)), s1ring=int(m.group(5)),
                        s1read=int(m.group(6)), s2asm=int(m.group(7)), s2ring=int(m.group(8)), flush=int(m.group(9)),
                        tail=int(m.group(10)), fence=int(m.group(11)), wait=int(m.group(12)), put=int(m.group(13)))
    return last


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    ref = None
    if '--ref' in sys.argv:
        ref = sys.argv[sys.argv.index('--ref') + 1]
        args = [a for a in args if a != ref]
    if not args:
        print(__doc__)
        return 2
    log = args[0]
    tstage = parse_tstage(args[1]) if len(args) > 1 else None
    wall, sites = parse_rdnt(log)
    ticks = parse_ticks(log)
    bad = []
    if wall is None:
        print('judge_g50: FAIL (no RDN-T wall line in %s -- was RDNMesaTime set?)' % log)
        return 1
    span, nfr = tick_span(ticks)
    wspan, wn = tick_span(ticks, 150)
    if wspan and wn:
        print('   world frames 150-%d: %.1f ms/frame (%.1f fps) -- the budget below averages the whole run, console frames included'
              % (150 + wn, 1000.0 * wspan / wn, wn / wspan))
    cyc_per_us = wall['cyc'] / wall['us'] if wall['us'] else 0.0
    mhz = cyc_per_us
    frames = wall['fp']

    def us(site, tag):
        s = sites.get((site, tag))
        return (s['cyc'] / cyc_per_us) if (s and cyc_per_us) else 0.0

    def n(site, tag):
        s = sites.get((site, tag))
        return s['n'] if s else 0

    def units(site):
        for tag in ('out', 'br', 'hook'):       # the site's total is on each of its lines
            s = sites.get((site, tag))
            if s:
                return s['units']
        return 0

    # the partition
    # G5-3: the window-server query (G5-1c) is its own row; before this it sat in the remainder
    out_parts = {k: us(k, 'out') for k in ('submit', 'upload', 'present', 'clear', 'verify', 'tri', 'query')}
    bracket = us('bracket', 'out')
    br_parts = {k: us(k, 'br') for k in ('tri', 'verify', 'submit', 'upload', 'present', 'clear')}
    hook_parts = {k: us(k, 'hook') for k in ('submit', 'upload', 'present', 'clear')}
    bracket_other = bracket - sum(br_parts.values())
    tri_self = br_parts['tri'] + out_parts['tri'] - sum(hook_parts.values())
    remainder = wall['us'] - bracket - sum(out_parts.values())

    # a. wall against ticks
    if span is not None:
        if wall['us'] / 1e6 < span - 0.5:
            bad.append('wall %.1f s is shorter than the tick span %.1f s' % (wall['us'] / 1e6, span))
    # b. sums
    if bracket_other < -0.001 * wall['us']:
        bad.append('bracket parts exceed the bracket by %.1f ms' % (-bracket_other / 1000))
    if tri_self < -0.001 * wall['us']:
        bad.append('hook-tagged parts exceed the hook by %.1f ms' % (-tri_self / 1000))
    if remainder < -0.001 * wall['us']:
        bad.append('out-tagged parts exceed the wall by %.1f ms' % (-remainder / 1000))
    # c. frames
    if nfr and abs(frames - nfr) > 2:
        bad.append('frames by present rows %d vs by ticks %d' % (frames, nfr))
    # GLQuake clears nothing by default (gl_clear 0, gl_ztrick 1): the clear count is
    # reported, not required
    notes = []
    if frames and not (0.5 <= wall['fc'] / frames <= 1.5):
        notes.append('clears per frame %.2f (GLQuake clears nothing under gl_ztrick)' % (wall['fc'] / frames))
    # d. calibration
    if not (0.95 * TSC_MHZ <= mhz <= 1.05 * TSC_MHZ):
        bad.append('calibration %.0f MHz, want %.0f +- 5 %%' % (mhz, TSC_MHZ))

    per = (span * 1000.0 / nfr) if (span and nfr) else (wall['us'] / 1000.0 / frames if frames else 0.0)
    print('== G5-0 frame budget: %s' % log)
    print('   frames %d (present rows), %d (ticks), %d clears; tick span %.2f s -> %.1f ms/frame (%.1f fps); '
          'wall %.2f s; TSC %.0f MHz; gettimeofday %.2f us' %
          (frames, nfr, wall['fc'], span or 0.0, per, (1000.0 / per) if per else 0.0,
           wall['us'] / 1e6, mhz, (wall['gtod'] / cyc_per_us / 1000.0) if cyc_per_us else 0.0))
    F = float(frames) if frames else 1.0

    def row(name, usv, cnt=None, unit=None):
        pct = 100.0 * usv / wall['us'] if wall['us'] else 0.0
        extra = ''
        if cnt:
            extra = '  %8d calls  %7.1f us/call' % (cnt, usv / cnt)
        if unit is not None and unit:
            extra += '  %6.2f us/unit (%d units)' % (usv / unit, unit)
        print('   %-26s %8.2f ms/frame %5.1f %%%s' % (name, usv / 1000.0 / F, pct, extra))

    row('wall', wall['us'])
    row('bracket (inclusive)', bracket, n('bracket', 'out'))
    row('  tri hook (inclusive)', br_parts['tri'] + out_parts['tri'], n('tri', 'br') + n('tri', 'out'), units('tri'))
    row('    tri self', tri_self)
    row('    submit in hook', hook_parts['submit'], n('submit', 'hook'))
    row('    upload in hook', hook_parts['upload'], n('upload', 'hook'), units('upload'))
    row('  verify', br_parts['verify'] + out_parts['verify'], n('verify', 'br') + n('verify', 'out'))
    row('  submit in bracket', br_parts['submit'], n('submit', 'br'))
    row('  upload in bracket', br_parts['upload'], n('upload', 'br'))
    row('  bracket other', bracket_other)
    row('submit outside', out_parts['submit'], n('submit', 'out'))
    row('submit (all)', sum(us('submit', t) for t in ('out', 'br', 'hook')),
        sum(n('submit', t) for t in ('out', 'br', 'hook')), units('submit'))
    row('present rows', out_parts['present'] + br_parts['present'] + hook_parts['present'],
        sum(n('present', t) for t in ('out', 'br', 'hook')), units('present'))
    row('clear', out_parts['clear'] + br_parts['clear'] + hook_parts['clear'],
        sum(n('clear', t) for t in ('out', 'br', 'hook')))
    row('upload outside', out_parts['upload'], n('upload', 'out'), units('upload'))
    row('window-server query', out_parts['query'], n('query', 'out'))
    row('remainder (game + Mesa T&L)', remainder)
    if n('tri', 'out'):
        print('   NOTE %d triangle hook calls outside any bracket' % n('tri', 'out'))
    # G5-1b: present ioctls a frame, and the software paths that would draw the wrong way
    # up in present mode (the RDN-C line) must be 0
    if frames:
        print('   present ioctls a frame: %.1f' % (sum(n('present', t) for t in ('out', 'br', 'hook')) / float(frames)))
    rc_line = None
    for l in open(log, errors='replace'):
        if l.startswith('RDN-C '):
            rc_line = l.strip()
    if rc_line:
        vals = dict(re.findall(r'(\w+)=(\d+)', rc_line))
        wrong = [k for k in ('delegated', 'replayed', 'points', 'lines', 'outside', 'nosoftware',
                             'readpix', 'copypix', 'drawpix', 'bitmap') if int(vals.get(k, '0')) != 0]
        print('   ' + rc_line)
        if wrong:
            bad.append('software drew into the surface in present mode: %s' % ', '.join('%s=%s' % (k, vals[k]) for k in wrong))
    if tstage:
        ops = tstage['ops'] or 1
        keys = ('pre', 's1ring', 's1read', 's2asm', 's2ring', 'flush', 'tail', 'fence', 'wait', 'put')
        tot = sum(tstage[k] for k in keys)
        print('   kernel tstage over %d submissions: %s -- %.0f us/submission in the stages'
              % (tstage['ops'], ' '.join('%s=%.1f' % (k, tstage[k] / ops) for k in keys), tot / ops))
    if ref:
        rt = parse_ticks(ref)
        rspan, rn = tick_span(rt)
        if rspan and rn and per:
            rper = rspan * 1000.0 / rn
            cost = per / rper - 1.0
            print('   instrument cost: %.1f ms/frame with the knob vs %.1f without -> %+.1f %%' % (per, rper, 100 * cost))
            # the same scene varies 20 % between runs (46.8 / 57.2 / 38.5 ms in build/g410), so one
            # pair cannot convict the instrument; the sites' own counts bound it instead
            if cost > 0.05:
                notes.append('the knob run is %.1f %% slower than the reference -- one pair, within the scene\'s own run-to-run spread' % (100 * cost))
    # G5-3 (docs/G5_3_QUERY_CONSOLE_PLAN.md 2-3): the same partition before and after the split frame
    swall, ssites = parse_rdnt(log, 'RDN-TS')
    if swall is not None and cyc_per_us:
        def diff(a, b):
            out = {}
            for k in set(a) | set(b):
                x, y = a.get(k, dict(n=0, cyc=0)), b.get(k, dict(n=0, cyc=0))
                out[k] = dict(n=x['n'] - y['n'], cyc=x['cyc'] - y['cyc'])
            return out
        for title, w_us, fr, ss in (('frames 1-%d (console, loading)' % swall['fp'], swall['us'], swall['fp'], ssites),
                                    ('frames %d-%d (world)' % (swall['fp'], frames), wall['us'] - swall['us'],
                                     frames - swall['fp'], diff(sites, ssites))):
            if fr <= 0 or w_us <= 0:
                bad.append('the split at frame %d leaves an empty part' % swall['fp'])
                continue
            u = lambda site, tags=('out', 'br', 'hook'): sum(ss.get((site, t), dict(cyc=0))['cyc'] for t in tags) / cyc_per_us
            br = u('bracket', ('out',))
            hk = sum(u(k, ('hook',)) for k in ('submit', 'upload', 'present', 'clear'))
            parts = [('submit (all)', u('submit')), ('tri self', u('tri') - hk), ('upload', u('upload')),
                     ('verify', u('verify')), ('present', u('present')), ('query', u('query')),
                     ('bracket other', br - sum(u(k, ('br',)) for k in ('tri', 'verify', 'submit', 'upload', 'present', 'clear')))]
            outs = sum(u(k, ('out',)) for k in ('submit', 'upload', 'present', 'clear', 'verify', 'tri', 'query'))
            parts.append(('remainder (game + T&L)', w_us - br - outs))
            tris = sum(ss.get(('tri', t), dict(n=0))['n'] for t in ('out', 'br'))
            print('   -- %s: %.1f ms/frame, %d triangles/frame' % (title, w_us / 1000.0 / fr, tris // fr))
            print('      ' + '  '.join('%s %.2f' % (nm, v / 1000.0 / fr) for nm, v in parts))
    for nt in notes:
        print('   NOTE ' + nt)
    for b in bad:
        print('   FAIL ' + b)
    print('judge_g50: %s' % ('PASS' if not bad else 'FAIL (%d)' % len(bad)))
    return 0 if not bad else 1


if __name__ == '__main__':
    sys.exit(main())
