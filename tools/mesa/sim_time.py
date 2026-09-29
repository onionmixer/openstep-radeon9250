#!/usr/bin/env python3
"""sim_time.py -- the frame-budget instrument (mesa/OSRDNMesaTime.c) run on the host.

G5-0 (docs/G5_0_PERF_MEASURE_PLAN.md 2).  The unit has no system headers and
formats its own report, so it links against the host libc as it is (the rdtsc
opcode and the two-word arithmetic are the same on x86-64; `unsigned long` is
64 bits here, which only makes the borrow case easier to construct).  A driver
program exercises every entry point, then python reads the RDN-T lines back
and checks:

  1. the knob: nothing is reported when RDNMesaTime is unset;
  2. one interval per site lands in the bin the flags name (out / br / hook);
  3. the 64-bit subtraction borrows (a start stamp whose low word is above the
     end's), and the carry into `hi` on accumulation;
  4. `huge` counts an interval of 2^32 cycles or more and leaves `max` alone;
  5. the frame boundary from present rows going back up the screen;
  6. the calibration: cycles from the report divided by the wall microseconds
     agrees with the driver's own two clocks within 5 %;
  7. every mutation below is caught;
  8. G5-3 (docs/G5_3_QUERY_CONSOLE_PLAN.md 2): with RDNMesaTimeSplit=2 the running totals are
     printed ONCE as RDN-TS when the second frame is counted -- frames 2, only the sites added
     before that frame, every count at most the final one -- and never without the knob.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.normpath(os.path.join(HERE, '..', '..'))
SRC = os.path.join(PROJ, 'mesa', 'OSRDNMesaTime.c')
INC = os.path.join(PROJ, 'mesa')

DRIVER = r'''
#include "OSRDNMesaTime.h"
#include <stdio.h>
#include <stdlib.h>
#include <sys/time.h>
extern unsigned long osrdn_time_calls(int);
static unsigned long tsc(void) { unsigned long lo, hi; __asm__ __volatile__(".byte 0x0f, 0x31" : "=a"(lo), "=d"(hi)); return (hi << 32) | lo; }
int main(void)
{
    osrdn_time_stamp t;
    struct timeval a, b;
    unsigned long c0, c1, k;
    volatile unsigned long sink = 0;
    if (!osrdn_time_on()) { printf("DRV off\n"); return 0; }
    gettimeofday(&a, 0); c0 = tsc();
    /* 1: out */
    osrdn_time_now(&t); for (k = 0; k < 100000; k++) sink += k; osrdn_time_add(OSRDN_TIME_SUBMIT, &t); osrdn_time_count(OSRDN_TIME_SUBMIT, 4068);
    /* 2: br */
    osrdn_time_in_render = 1;
    osrdn_time_now(&t); for (k = 0; k < 100000; k++) sink += k; osrdn_time_add(OSRDN_TIME_VERIFY, &t);
    /* 3: hook (in_hook wins over in_render) */
    osrdn_time_in_hook = 1;
    osrdn_time_now(&t); for (k = 0; k < 100000; k++) sink += k; osrdn_time_add(OSRDN_TIME_UPLOAD, &t); osrdn_time_count(OSRDN_TIME_UPLOAD, 65536);
    osrdn_time_in_hook = 0; osrdn_time_in_render = 0;
    /* 4: the borrow -- a start whose low word is 2^31 above the end's, one hi below: the
          difference is 2^31 plus what the clock moved, under a word.  The clock must be in
          the lower half of its low word for the sum not to wrap, so wait for that. */
    do { osrdn_time_now(&t); } while (t.lo >= 0x7ff00000UL);
    t.lo += 0x80000000UL; t.hi -= 1UL; osrdn_time_add(OSRDN_TIME_CLEAR, &t);
    /* 5: huge -- a start two hi words below: 2^33 and more */
    osrdn_time_now(&t); t.hi -= 2UL; osrdn_time_add(OSRDN_TIME_PRESENT, &t);
    /* 6: frames: rows go 479, 478, ... then back to 479 */
    osrdn_time_frame_present(479); osrdn_time_frame_present(478); osrdn_time_frame_present(477);
    osrdn_time_frame_present(479); osrdn_time_frame_present(478);
    osrdn_time_frame_present(300);
    /* G5-1b: two coalesced frames land at the same dstY -- both count */
    osrdn_time_frame_present(0); osrdn_time_frame_present(0);
    osrdn_time_frame_clear(); osrdn_time_frame_clear(); osrdn_time_frame_clear();
    /* 7: the carry on accumulation: two intervals of 2^31 and a little, whose low words sum past 2^32 */
    do { osrdn_time_now(&t); } while (t.lo >= 0x7ff00000UL);
    t.lo += 0x80000000UL; t.hi -= 1UL; osrdn_time_add(OSRDN_TIME_TRI, &t);
    do { osrdn_time_now(&t); } while (t.lo >= 0x7ff00000UL);
    t.lo += 0x80000000UL; t.hi -= 1UL; osrdn_time_add(OSRDN_TIME_TRI, &t);
    for (k = 0; k < 2000000; k++) sink += k;
    gettimeofday(&b, 0); c1 = tsc();
    printf("DRV us=%lu cyc=%lu calls_submit=%lu us_submit=%lu units_submit=%lu\n",
           (unsigned long)((b.tv_sec - a.tv_sec) * 1000000L + (b.tv_usec - a.tv_usec)), c1 - c0,
           osrdn_time_calls(OSRDN_TIME_SUBMIT), osrdn_time_us(OSRDN_TIME_SUBMIT), osrdn_time_units(OSRDN_TIME_SUBMIT));
    osrdn_time_report();
    osrdn_time_report();            /* a second call must print nothing */
    /* G5-6: a line longer than the buffer ends in a newline and is followed by RDN-CUT */
    osrdn_time_line_begin("RDN-LONG");
    for (k = 0; k < 40; k++) osrdn_time_line_put("field_name", k);
    osrdn_time_line_end();
    osrdn_time_line_begin("RDN-SHORT");
    osrdn_time_line_put("a", 1UL);
    osrdn_time_line_end();
    return (int)(sink & 0UL);
}
'''

MUTATIONS = [
    ('the borrow is dropped',
     "*dhi = (b->hi - a->hi - ((b->lo < a->lo) ? 1UL : 0UL)) & TIME_WORD;", "*dhi = (b->hi - a->hi) & TIME_WORD;"),
    ('the carry into hi is dropped',
     "    if (a->lo < dlo)\n        a->hi++;\n", ""),
    ('the low word is not masked (a 64-bit host would hide the wrap)',
     "    a->lo = (a->lo + dlo) & TIME_WORD;", "    a->lo = a->lo + dlo;"),
    ('huge intervals go into max',
     "    if (dhi != 0UL)\n        a->huge++;\n    else if (dlo > a->max)", "    if (dlo > a->max)"),
    ('the hook flag no longer wins',
     "tag = osrdn_time_in_hook ? OSRDN_TIME_HOOK : (osrdn_time_in_render ? OSRDN_TIME_BR : OSRDN_TIME_OUT);",
     "tag = osrdn_time_in_render ? OSRDN_TIME_BR : (osrdn_time_in_hook ? OSRDN_TIME_HOOK : OSRDN_TIME_OUT);"),
    ('a frame is counted on every row',
     "if (framesPresent == 0UL || dstY >= lastDstY)", "if (1)"),
    ('a coalesced frame (same dstY each frame) is not counted',
     "if (framesPresent == 0UL || dstY >= lastDstY)", "if (framesPresent == 0UL || dstY > lastDstY)"),
    ('the knob is ignored',
     'timeOn = (getenv("RDNMesaTime") != 0) ? 1 : 0;', 'timeOn = 1;'),
    ('G5-3: the split prints at every later frame',
     "        splitDone = 1;\n", ""),
    ('G5-3: the split knob is never read',
     "            splitAt = splitAt * 10UL + (unsigned long)(*e - '0');", "            splitAt = 0UL;"),
    ('G5-3: the split prints one frame late',
     "framesPresent == splitAt) {", "framesPresent == splitAt + 1UL) {"),
    ('G5-6: a cut line is not flagged',
     "        lineCut = 1;                    /* G5-6", "        (void) 0;                    /* G5-6"),
    ('G5-6: a full buffer loses its newline',
     "        lineBuf[lineLen - 1U] = '\\n';", "        ;"),
    ('the report repeats',
     "    if (timeOn != 1 || reported)\n        return;\n    reported = 1;\n", "    if (timeOn != 1)\n        return;\n"),
]


def build(src_text, tmp):
    src = os.path.join(tmp, 'OSRDNMesaTime.c')
    drv = os.path.join(tmp, 'drv.c')
    exe = os.path.join(tmp, 'drv')
    open(src, 'w').write(src_text)
    open(drv, 'w').write(DRIVER)
    r = subprocess.run(['gcc', '-O1', '-w', '-I', INC, '-o', exe, drv, src],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None, r.stderr
    return exe, ''


def run(exe, knob, split='2'):
    env = dict(os.environ)
    env.pop('RDNMesaTime', None)
    env.pop('RDNMesaTimeSplit', None)
    if knob:
        env['RDNMesaTime'] = '1'
    if split is not None:
        env['RDNMesaTimeSplit'] = split
    r = subprocess.run([exe], capture_output=True, text=True, env=env)
    return r.stdout, r.stderr


def parse(err):
    lines = {}
    wall = None
    ends = 0
    for l in err.split('\n'):
        m = re.match(r'RDN-T wall us=(\d+) cyc=([0-9a-f]{16}) gtod1000cyc=(\d+) frames_present=(\d+) frames_clear=(\d+)', l)
        if m:
            wall = dict(us=int(m.group(1)), cyc=int(m.group(2), 16), gtod=int(m.group(3)),
                        fp=int(m.group(4)), fc=int(m.group(5)))
            continue
        m = re.match(r'RDN-T site=(\w+) tag=(\w+) n=(\d+) cyc=([0-9a-f]{16}) max=(\d+) huge=(\d+) units=(\d+)', l)
        if m:
            lines[(m.group(1), m.group(2))] = dict(n=int(m.group(3)), cyc=int(m.group(4), 16), max=int(m.group(5)),
                                                    huge=int(m.group(6)), units=int(m.group(7)))
            continue
        if l.strip() == 'RDN-T end':
            ends += 1
    return wall, lines, ends


def split_check(err):
    """G5-3: the RDN-TS block of a run with RDNMesaTimeSplit=2"""
    p = []
    ts = '\n'.join(l[len('RDN-TS'):].join(['RDN-T', '']) for l in err.split('\n') if l.startswith('RDN-TS'))
    tw, tl, te = parse(ts)
    fw, fl, _ = parse(err)
    if te != 1 or tw is None:
        return ['RDN-TS printed %d times (want once, at frame 2)' % te]
    if tw['fp'] != 2:
        p.append('RDN-TS at frame %d, want 2' % tw['fp'])
    # frame 2 comes after the submit/verify/upload/clear/present intervals and before the two tri ones
    if set(tl) != {('submit', 'out'), ('verify', 'br'), ('upload', 'hook'), ('clear', 'out'), ('present', 'out')}:
        p.append('RDN-TS bins %s' % sorted(tl))
    for k, v in tl.items():
        if k not in fl or v['n'] > fl[k]['n'] or v['cyc'] > fl[k]['cyc']:
            p.append('RDN-TS %s is past the final totals' % (k,))
    if fw and tw['us'] > fw['us']:
        p.append('RDN-TS wall past the final wall')
    return p


def cut_check(err):
    """G5-6: the over-long line is ended and flagged; the short one after it is whole and unflagged"""
    ls = err.split('\n')
    i = next((k for k, l in enumerate(ls) if l.startswith('RDN-LONG')), None)
    if i is None or i + 2 >= len(ls):
        return ['no RDN-LONG line']
    p = []
    if not ls[i + 1].startswith('RDN-CUT'):
        p.append('the over-long line is not followed by RDN-CUT')
    if ls[i + 2] != 'RDN-SHORT a=1':
        p.append('the line after the cut is %r' % ls[i + 2])
    return p


def judge(out, err):
    """[] when the run is right; else the complaints"""
    p = split_check(err) + cut_check(err)
    wall, lines, ends = parse(err)
    if wall is None:
        return ['no RDN-T wall line']
    if ends != 1:
        p.append('RDN-T end printed %d times, want 1' % ends)
    want_bins = {('submit', 'out'), ('verify', 'br'), ('upload', 'hook'), ('clear', 'out'),
                 ('present', 'out'), ('tri', 'out')}
    if set(lines) != want_bins:
        p.append('bins %s, want %s' % (sorted(lines), sorted(want_bins)))
        return p
    for k in want_bins:
        if lines[k]['n'] != (2 if k[0] == 'tri' else 1):
            p.append('%s n=%d' % (k, lines[k]['n']))
    if lines[('submit', 'out')]['units'] != 4068 or lines[('upload', 'hook')]['units'] != 65536:
        p.append('units: submit %d (want 4068), upload/hook %d (want 65536: the site total on every line)'
                 % (lines[('submit', 'out')]['units'], lines[('upload', 'hook')]['units']))
    # 3: the borrow: 2^31 plus the clock's own movement (well under 2^20), under a word, huge = 0
    c = lines[('clear', 'out')]
    if not ((1 << 31) <= c['cyc'] < (1 << 31) + (1 << 20)) or c['huge'] != 0 or c['max'] != c['cyc']:
        p.append('borrow: clear cyc=%d max=%d huge=%d' % (c['cyc'], c['max'], c['huge']))
    # 4: huge: two hi words -> >= 2^33, huge = 1, max untouched (0)
    h = lines[('present', 'out')]
    if h['cyc'] < (1 << 33) or h['huge'] != 1 or h['max'] != 0:
        p.append('huge: present cyc=%d max=%d huge=%d' % (h['cyc'], h['max'], h['huge']))
    # 7: the carry: two intervals of 2^31 and a little sum past 2^32 -- hi must be 1
    t = lines[('tri', 'out')]
    if not ((1 << 32) <= t['cyc'] < (1 << 32) + (1 << 21)) or t['huge'] != 0:
        p.append('carry: tri cyc=%d huge=%d' % (t['cyc'], t['huge']))
    # 5: frames: 479 478 477 | 479 478 | 300 | 0 | 0 -> 3 starts by present: 479, 479 again, and
    #    the second 0 (300 and the first 0 still descend; a coalesced frame repeats its dstY), 3 clears
    if wall['fp'] != 3 or wall['fc'] != 3:
        p.append('frames present=%d (want 3) clear=%d (want 3)' % (wall['fp'], wall['fc']))
    # 6: calibration against the driver's own clocks
    m = re.search(r'DRV us=(\d+) cyc=(\d+) calls_submit=(\d+) us_submit=(\d+) units_submit=(\d+)', out)
    if not m:
        p.append('no DRV line')
    else:
        dus, dcyc = int(m.group(1)), int(m.group(2))
        if dus > 0 and wall['us'] > 0:
            r1 = wall['cyc'] / wall['us']
            r2 = dcyc / dus
            if abs(r1 - r2) > 0.05 * r2:
                p.append('calibration %.1f vs the driver %.1f cycles/us' % (r1, r2))
        if int(m.group(3)) != 1 or int(m.group(5)) != 4068:
            p.append('shim accessors: calls %s units %s' % (m.group(3), m.group(5)))
        if int(m.group(4)) == 0:
            p.append('osrdn_time_us(submit) is 0')
    if wall['gtod'] == 0:
        p.append('gettimeofday cost not measured')
    return p


def main():
    src = open(SRC).read()
    bad = 0
    with tempfile.TemporaryDirectory() as tmp:
        exe, e = build(src, tmp)
        if exe is None:
            print('sim_time: FAIL (the unit does not build on the host)\n' + e)
            return 1
        out, err = run(exe, False)
        if 'RDN-T' in err or 'DRV off' not in out:
            print('  FAIL the knob off still reports')
            bad += 1
        else:
            print('  ok   nothing is reported without RDNMesaTime')
        out, err = run(exe, True, None)
        if 'RDN-TS' in err:
            print('  FAIL the split prints without RDNMesaTimeSplit')
            bad += 1
        else:
            print('  ok   no RDN-TS without RDNMesaTimeSplit')
        out, err = run(exe, True)
        p = judge(out, err)
        if p:
            bad += 1
            print('  FAIL the instrument: ' + '; '.join(p))
        else:
            print('  ok   every entry point, bin, borrow, carry, huge, frame count and calibration')
        for name, a, b in MUTATIONS:
            if src.count(a) != 1:
                print('  FAIL mutation %-40s anchor found %d times' % (name, src.count(a)))
                bad += 1
                continue
            m = src.replace(a, b)
            with tempfile.TemporaryDirectory() as t2:
                exe2, e2 = build(m, t2)
                if exe2 is None:
                    print('  ok   mutation %-40s does not build' % name)
                    continue
                o2, r2 = run(exe2, True)
                caught = bool(judge(o2, r2))
                if name == 'the knob is ignored':
                    o3, r3 = run(exe2, False)
                    caught = 'RDN-T' in r3
                print('  %s mutation %-40s %s' % ('ok  ' if caught else 'FAIL', name, 'caught' if caught else 'NOT caught'))
                bad += 0 if caught else 1
    print('sim_time: %s' % ('PASS' if bad == 0 else 'FAIL (%d)' % bad))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
