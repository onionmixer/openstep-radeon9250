#!/usr/bin/env python3
"""M1a gate A: the probe against a fake node, input by input (docs/M1A_PLAN.md 6-A).

  sim_probe.py

The first draft of that gate asked only that all nine verdicts be REACHED.  A
probe that returned them in order would have passed it -- which is the "gate
that verifies nothing" this project forbids (PLAN.md 188).  So this drives a
fake open/ioctl with a stated input and compares against a stated expected
verdict, one row at a time, and separately proves the three policies that a
table of single calls cannot reach: the cache, the one-way revocation, and the
switch that can only subtract.

The probe is compiled for 32 bits with the target's own header, against a C
harness that supplies the seam.  Nothing here imports the probe's logic: the
expected verdicts are written from docs/M1A_PLAN.md 3, not derived from the C.
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
MESA = os.path.join(PROJ, 'mesa')
TPROJ = os.path.join(PROJ, 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj')
PROBE = os.path.join(MESA, 'OSRDNMesaProbe.c')

# the nine, written out here from the plan rather than read from the header, so
# that a renumbering in one place and not the other is a failure and not a shrug
WANT = {'HARDWARE': 0, 'NO_DEVICE': 1, 'NOT_OURS': 2, 'MAGIC': 3, 'VERSION': 4,
        'NOT_READY': 5, 'NOT_RUNNING': 6, 'DISABLED': 7, 'REVOKED': 8}

# (label, fake description, expected verdict).  Every field of the fake is named
# so that the row states its own input; "ok" is the CAPS a good driver returns.
ROWS = [
    ('A1  no node (open fails)',    dict(open=-1),                          'NO_DEVICE'),
    ('A2  open ENXIO',              dict(open=-2),                          'NO_DEVICE'),
    ('A3  CAPS ENOTTY (name/major plausible)', dict(ioctl=-1),              'NOT_OURS'),
    ('A4  wrong magic',             dict(magic=0xdeadbeef),                 'MAGIC'),
    ('A5  version - 1',             dict(version=-1),                       'VERSION'),
    ('A6  version + 1',             dict(version=+1),                       'VERSION'),
    ('A7  version exact',           dict(),                                 'HARDWARE'),
    ('A8  ready 0',                 dict(ready=0),                          'NOT_READY'),
    ('A9  cpRunning 0',             dict(cpRunning=0),                      'NOT_RUNNING'),
    ('A10 switch off, rest ok',     dict(env='1'),                          'DISABLED'),
    ('A11 all good',                dict(),                                 'HARDWARE'),
]

HARNESS = r'''
int printf(const char *, ...);
void exit(int);
#include "OSRDNMesaProbe.h"
#include "osrdn_r7b.h"

/* what the fake answers; the driver of this harness sets them per case */
static int fOpen, fIoctl;
static unsigned long fMagic, fVersion, fReady, fRunning;
static const char *fEnv;
static int openCalls, ioctlCalls, closeCalls;

static int hOpen(const char *p) { (void)p; openCalls++; return fOpen; }
static void hClose(int fd) { (void)fd; closeCalls++; }
static const char *hGetenv(const char *n) { (void)n; return fEnv; }

static int hIoctl(int fd, int cmd, char *blk)
{
    osrdn_r7b_caps *c = (osrdn_r7b_caps *)blk;

    (void)fd;
    ioctlCalls++;
    if (fIoctl != 0)
        return fIoctl;
    if ((unsigned long)cmd != OSRDN_R7B_IOC_CAPS)
        return -1;
    c->magic = fMagic;
    c->version = fVersion;
    c->window = OSRDN_R7B_WINDOW_OFF;
    c->bytes = OSRDN_R7B_WINDOW_BYTES;
    c->maxWords = OSRDN_R7B_MAX_WORDS;
    c->build = 0x12345678UL;
    c->ready = fReady;
    c->cpRunning = fRunning;
    c->winStart = 0x0029e000UL;
    return 0;
}

static OSRDNMesaProbeOps ops = { hOpen, hIoctl, hClose, hGetenv };

static void good(void)
{
    fOpen = 3; fIoctl = 0; fEnv = 0;
    fMagic = OSRDN_R7B_MAGIC; fVersion = OSRDN_R7B_VERSION;
    fReady = 1UL; fRunning = 1UL;
}

int main(void)
{
    int v, w;

    OSRDNMesaProbeSetOps(&ops);

%(rows)s

    /* ---- A-cache: change the fake AFTER the first call.  A probe that asks
       again would now say NOT_READY; a cached one still says HARDWARE. */
    OSRDNMesaProbeForget();
    good();
    v = OSRDNMesaProbeRun();
    fReady = 0UL;
    w = OSRDNMesaProbeRun();
    printf("CACHE %%d %%d %%d\n", v, w, ioctlCalls);

    /* ---- A-revoke: after revoking, a fake that WOULD say HARDWARE must not. */
    OSRDNMesaProbeForget();
    good();
    v = OSRDNMesaProbeRun();
    OSRDNMesaProbeRevoke();
    good();
    w = OSRDNMesaProbeRun();
    printf("REVOKE %%d %%d\n", v, w);

    /* ---- A-switch, part 1: the switch is a PRESENCE, not a value to parse.
       Every one of these disables, "0" and "on" included -- a switch whose value
       is read is a switch that can be made to say yes. */
    {
        static const char *vals[] = { "", "0", "1", "on", "off", "no", "yes" };
        unsigned k;

        for (k = 0; k < sizeof vals / sizeof vals[0]; k++) {
            OSRDNMesaProbeForget();
            good();                 /* everything else would say HARDWARE */
            fEnv = vals[k];
            printf("SWVAL %%s %%d\n", vals[k][0] ? vals[k] : "(empty)",
                   OSRDNMesaProbeRun());
        }
    }

    /* ---- A-switch, part 2: in a state that is NOT hardware, no value may make
       it hardware.  Testing this on a good machine proves nothing: there
       HARDWARE is the right answer. */
    OSRDNMesaProbeForget();
    good();
    fRunning = 0UL;             /* not hardware, for a reason unrelated to the switch */
    fEnv = 0;
    v = OSRDNMesaProbeRun();
    OSRDNMesaProbeForget();
    fEnv = "on";                /* the most "on"-looking value there is */
    w = OSRDNMesaProbeRun();
    printf("SWITCH %%d %%d\n", v, w);

    /* ---- names: every verdict has one, and nothing outside the range does */
    for (v = -1; v <= OSRDN_PROBE_VERDICTS; v++)
        printf("NAME %%d %%s\n", v, OSRDNMesaProbeName(v));
    return 0;
}
__attribute__((force_align_arg_pointer))
void _start(void) { exit(main()); }
'''


def row_code(k, fake):
    """the C that sets one case up, runs it, and prints the verdict"""
    out = ['    OSRDNMesaProbeForget();', '    good();']
    if 'open' in fake:
        out.append('    fOpen = %d;' % fake['open'])
    if 'ioctl' in fake:
        out.append('    fIoctl = %d;' % fake['ioctl'])
    if 'magic' in fake:
        out.append('    fMagic = 0x%08xUL;' % fake['magic'])
    if 'version' in fake:
        out.append('    fVersion = OSRDN_R7B_VERSION %s %d;' %
                   ('+' if fake['version'] > 0 else '-', abs(fake['version'])))
    if 'ready' in fake:
        out.append('    fReady = %dUL;' % fake['ready'])
    if 'cpRunning' in fake:
        out.append('    fRunning = %dUL;' % fake['cpRunning'])
    if 'env' in fake:
        out.append('    fEnv = "%s";' % fake['env'])
    out.append('    printf("ROW %d %%d\\n", OSRDNMesaProbeRun());' % k)
    return '\n'.join(out)


def build_and_run(src, work):
    path = os.path.join(work, 'h.c')
    rows = '\n\n'.join(row_code(k, f) for k, (_l, f, _w) in enumerate(ROWS))
    open(path, 'w').write(HARNESS % dict(rows=rows))
    unit = os.path.join(work, 'OSRDNMesaProbe.c')
    open(unit, 'w').write(src)
    exe = os.path.join(work, 'h')
    r = subprocess.run(['gcc-12', '-m32', '-std=gnu89', '-O0', '-Wall', '-Werror',
                        '-Wno-main', '-DOSRDN_PROBE_TESTABLE',
                        '-I', MESA, '-I', TPROJ, unit, path,
                        '-nostdlib', '-nostartfiles', '/usr/lib32/libc.so.6',
                        '-Wl,-dynamic-linker,/lib/ld-linux.so.2', '-o', exe],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None, r.stderr[-900:]
    try:
        r = subprocess.run([exe], capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return None, 'the probe hangs'
    return r.stdout.splitlines(), ''


def judge(lines):
    """(problems, verdicts seen)"""
    p, seen = [], set()
    got = {}
    for l in lines:
        m = re.match(r'ROW (\d+) (-?\d+)$', l)
        if m:
            got[int(m.group(1))] = int(m.group(2))
    for k, (label, _f, want) in enumerate(ROWS):
        if k not in got:
            p.append('%s: no answer' % label)
            continue
        seen.add(got[k])
        if got[k] != WANT[want]:
            name = [n for n, v in WANT.items() if v == got[k]]
            p.append('%s: got %s, want %s' % (label, name[0] if name else got[k], want))

    m = [l for l in lines if l.startswith('CACHE ')]
    if not m:
        p.append('A-cache did not run')
    else:
        v, w, calls = (int(x) for x in m[0].split()[1:])
        seen.add(v)
        if v != WANT['HARDWARE'] or w != WANT['HARDWARE']:
            p.append('A-cache: the fake changed and the answer followed it (%d then %d)' % (v, w))
        if calls == 0:
            p.append('A-cache: the probe never asked the node at all')

    m = [l for l in lines if l.startswith('REVOKE ')]
    if not m:
        p.append('A-revoke did not run')
    else:
        v, w = (int(x) for x in m[0].split()[1:])
        seen.add(w)
        if v != WANT['HARDWARE']:
            p.append('A-revoke: the setup did not reach HARDWARE first')
        if w != WANT['REVOKED']:
            p.append('A-revoke: a later success brought it back (%d)' % w)

    vals = [(l.split()[1], int(l.split()[2])) for l in lines if l.startswith('SWVAL ')]
    if len(vals) < 7:
        p.append('A-switch part 1 did not run (%d values)' % len(vals))
    for val, got in vals:
        seen.add(got)
        if got != WANT['DISABLED']:
            p.append('A-switch: the value %r did not disable (got %d) -- the switch is being '
                     'READ, and a switch that is read can be made to say yes' % (val, got))

    m = [l for l in lines if l.startswith('SWITCH ')]
    if not m:
        p.append('A-switch part 2 did not run')
    else:
        v, w = (int(x) for x in m[0].split()[1:])
        if v != WANT['NOT_RUNNING']:
            p.append('A-switch: the non-hardware setup did not give NOT_RUNNING (%d)' % v)
        if w == WANT['HARDWARE']:
            p.append('A-switch: a value turned acceleration ON')

    names = dict((int(l.split()[1]), l.split()[2]) for l in lines if l.startswith('NAME '))
    for n, v in WANT.items():
        if names.get(v) != n:
            p.append('NAME %d is %r, want %r' % (v, names.get(v), n))
    for v in (-1, len(WANT)):
        if names.get(v) != '?':
            p.append('NAME %d is %r, want "?"' % (v, names.get(v)))

    missing = set(WANT.values()) - seen
    if missing:
        p.append('never produced: %s' % sorted(n for n, v in WANT.items() if v in missing))
    return p, seen


MUTATIONS = [
    ('the version need only be at least ours', 'blk.version != OSRDN_R7B_VERSION',
     'blk.version < OSRDN_R7B_VERSION'),
    ('identity is not taken from the ioctl', '        return OSRDN_PROBE_NOT_OURS;\n',
     '        return OSRDN_PROBE_NO_DEVICE;\n'),
    ('the verdict is not cached', '    if (probeVerdict >= 0)\n        return probeVerdict;\n', ''),
    ('revocation can be undone', '    if (probeRevoked)\n        return OSRDN_PROBE_REVOKED;\n', ''),
    ('the switch can turn it on', 'if (P_GETENV(OSRDN_PROBE_ENV) != 0)\n        return OSRDN_PROBE_DISABLED;',
     'if (P_GETENV(OSRDN_PROBE_ENV) != 0 && P_GETENV(OSRDN_PROBE_ENV)[0] != \'o\')\n        return OSRDN_PROBE_DISABLED;'),
    ('ready is not checked', '    if (blk.ready != 1UL)\n        return OSRDN_PROBE_NOT_READY;\n', ''),
    ('the CP state is not checked', '    if (blk.cpRunning != 1UL)\n        return OSRDN_PROBE_NOT_RUNNING;\n', ''),
    ('the magic is not checked', '    if (blk.magic != OSRDN_R7B_MAGIC)\n        return OSRDN_PROBE_MAGIC;\n', ''),
    ('a missing node is an error, not a verdict',
     '    if ((fd = P_OPEN(NODE)) < 0)\n        return OSRDN_PROBE_NO_DEVICE;\n',
     '    if ((fd = P_OPEN(NODE)) < 0)\n        return -1;\n'),
]


def main():
    if not os.path.exists('/usr/lib32/libc.so.6'):
        print('  --   /usr/lib32/libc.so.6 not present, skipped')
        return 0
    src = open(PROBE).read()
    work = tempfile.mkdtemp(prefix='simprobe.', dir=os.environ.get('TMPDIR'))
    atexit.register(shutil.rmtree, work, True)  # 2026-09-24: /tmp reached 35.6 GiB of our scratch
    fails = 0

    lines, err = build_and_run(src, work)
    if lines is None:
        print('  FAIL the probe does not build or run\n' + err)
        return 1
    probs, seen = judge(lines)
    for x in probs:
        print('  FAIL %s' % x)
    fails += len(probs)
    if not probs:
        print('  ok   %d input rows, each giving the verdict the plan states' % len(ROWS))
        print('  ok   the cache, the one-way revocation and the subtract-only switch')
        print('  ok   all %d verdicts produced by an input that should produce them' % len(WANT))

    for label, old, new in MUTATIONS:
        if src.count(old) != 1:
            print('  FAIL mutation %-46s anchor found %d times' % (label, src.count(old)))
            fails += 1
            continue
        w2 = tempfile.mkdtemp(prefix='simprobem.', dir=os.environ.get('TMPDIR'))
        atexit.register(shutil.rmtree, w2, True)  # 2026-09-24: /tmp reached 35.6 GiB of our scratch
        ls, e2 = build_and_run(src.replace(old, new), w2)
        if ls is None:
            caught, why = True, 'does not build'
        else:
            p2, _s = judge(ls)
            caught, why = bool(p2), (p2[0] if p2 else '')
        print('  %-4s mutation %-46s %s' % ('ok' if caught else 'FAIL', label,
                                            why if caught else 'NOT CAUGHT'))
        fails += 0 if caught else 1

    print('sim_probe: %s' % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
