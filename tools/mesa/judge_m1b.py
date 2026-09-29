#!/usr/bin/env python3
"""M1b gates B3 and F, judged on the host (docs/M1B_PLAN.md 6).

  judge_m1b.py <build dir>          e.g. build/m1b/790027122
  judge_m1b.py --self-test

B3 -- the undefined symbols of our accelerated object.  This is the gate that
carries the rung's central claim, because the one the plan first relied on
cannot: identical pixels are what a library that drew the same thing would also
produce.  What cannot be argued with is that a hook which drew would have to
reach SOMETHING to do it, and nothing it could reach is in this object.

F -- the provenance chain.  The accelerated archive must be the stock one with
exactly one member replaced and exactly one added, and the source we compile
must be the source the stock archive was built from.

The archives are read here directly: `ar` format is a text header and a blob,
and parsing it is how the host can compare member for member without needing a
toolchain for the target's architecture.
"""

import shutil
import atexit
import os
import re
import sys

# Every symbol our accelerated object is allowed to leave undefined, and why.
# Nothing here can write into a caller's buffer:
#   open/close/ioctl  the probe asks CAPS and nothing else; without mmap there
#                     is no mapped page, so the submission path cannot be reached
#   getenv            the acceleration switch
#   dyld_stub_...     the linker's own
ALLOW = {
    '_open': 'the probe opens the node, and the surface opens it to map',
    '_close': 'and closes it',
    '_ioctl': 'CAPS, and from M1d SUBMIT.  This justification used to say the '
              'batch window was never mapped; that stopped being true when the '
              'triangle unit mapped it, and the claim is now the narrower one '
              'that every submission is logged by the driver and counted here',
    '_getenv': 'the acceleration switch',
    'dyld_stub_binding_helper': "the linker's own",
    # M1c: the rung maps ONE window, so the claim changed from "cannot draw"
    # to "can reach the one window it mapped" (docs/M1C_PLAN.md 4).
    '_mmap': 'the one offscreen window, at the offset CAPS gave',
    '_vm_allocate': 'the place that mmap maps over -- 4.2BSD has no MAP_FIXED',
    '_task_self': 'vm_allocate needs it',
    # M1d: the only way to have a software fallback at all.  Mesa keeps our
    # pointer once it is set (src/triangle.c 1532), so it never chooses one --
    # we call the chooser ourselves and keep what it picked.
    '_gl_set_triangle_function': 'to learn the software triangle function we '
                                 'fall back to',
    # G3: the present unit keys its owner on the current context -- a read of
    # which context is current, nothing written (OSRDNMesaPresent.c).
    '_OSMesaGetCurrentContext': 'the present owner key (docs/G3_PRESENT_PLAN.md)',
    # G4-1b: the residency record of a texture image lives on OUR heap through
    # Mesa's MALLOC/FREE (OSRDNMesaHook.c osrdnTexResident/osrdnTexDrop).  A
    # heap of our own is not a caller's buffer; the one window stays the only
    # place a pixel can go.
    '_malloc': 'the per-image residency record (G4-1b)',
    '_free': 'and its release',
    # G4-2 B1: the point and line functions are wrapped the way the triangle
    # function is (flush the batch, then call what Mesa chose), and for the
    # same reason the choosers are called here: Mesa keeps a non-null pointer
    # (points.c 1333-1346, lines.c 1071-1084) and would never choose one.
    '_gl_set_point_function': 'to learn the software point function the wrapper calls',
    '_gl_set_line_function': 'to learn the software line function the wrapper calls',
    # G4-6: the submission trace -- write/fsync/lseek to the two files RDNMesaTrace and
    # RDNMesaTraceLast name, and only from triTrace (check_hook m1b-no-drawing carries the
    # narrowing); a freeze leaves no kernel log, so the stream has to reach the NFS host first
    '_write': 'the submission trace (triTrace), to the files the environment names',
    '_fsync': 'and its flush to the NFS host before the ioctl',
    '_lseek': 'the last-stream file is rewritten from offset 0',
    '_ftruncate': 'G5-4: and cut to the stream just written (a shorter one left an old tail)',
    # G5-0: the frame-budget instrument (OSRDNMesaTime.c) -- its wall clock for the
    # calibration, and its report at exit; the report itself goes through _write
    '_gettimeofday': 'the instrument\'s calibration clock (docs/G5_0_PERF_MEASURE_PLAN.md 2-1)',
    '_atexit': 'the instrument\'s report at exit',
    # G5-1c: the window query (OSRDNMesaWindow.c) binds AppKit, the ObjC runtime and the
    # DPS operator at RUN time through the dynamic linker, so nothing else is undefined
    # and a program without AppKit simply has no window query
    '_NSIsSymbolNameDefined': 'G5-1c: is AppKit here (docs/G5_1C_PRESENT_SERVER_POSITION_PLAN.md 1-1)',
    '_NSLookupAndBindSymbol': 'G5-1c: bind NSApp, objc_msgSend, sel_getUid, PScurrentwindowbounds',
    '_NSAddressOfSymbol': 'G5-1c: and take their addresses',
}

# M1b said mmap must be absent; M1c may not say that any more.  What it says
# instead is that mmap is reachable and NOTHING ELSE that writes is.
FORBIDDEN_AFTER_M1C = ('memcpy', 'bcopy', 'memset', 'bzero', 'strcpy', 'sprintf',
                       'vm_write', 'vm_copy')

# Anything of these would mean a hook could put bytes somewhere.
FORBIDDEN_HINTS = ('mmap', 'memcpy', 'bcopy', 'memset', 'bzero', 'write',
                   'vm_allocate', 'vm_write', 'strcpy', 'sprintf')


def ar_members(path):
    """[(name, bytes)] of a Unix ar archive, without a toolchain"""
    with open(path, 'rb') as f:
        if f.read(8) != b'!<arch>\n':
            raise ValueError('%s is not an ar archive' % path)
        out = []
        while True:
            hdr = f.read(60)
            if len(hdr) < 60:
                break
            name = hdr[0:16].decode('ascii', 'replace').rstrip()
            size = int(hdr[48:58].decode('ascii', 'replace').strip())
            body = f.read(size)
            if size % 2:
                f.read(1)
            # BSD long names: "#1/<len>" puts the name in front of the body
            m = re.match(r'#1/(\d+)$', name)
            if m:
                n = int(m.group(1))
                name = body[:n].split(b'\0')[0].decode('ascii', 'replace')
                body = body[n:]
            out.append((name.rstrip('/'), body))
        return out


def syms(text):
    """(global defined, undefined, local defined) from an nm listing.

    The three are kept apart because only two of them say anything about the
    SOURCE.  A lowercase kind is a file-local symbol, and whether a static
    function leaves one behind depends on the optimisation level -- our build
    emits `t _choose_triangle_function` and the installed object does not,
    which is a flags difference and not a different osmesa.c.  Comparing locals
    would fail a correct provenance chain; comparing globals is what the chain
    can actually be evidenced by at this level.
    """
    g, u, loc = set(), set(), set()
    for line in text.splitlines():
        m = re.match(r'^\s*([0-9a-fA-F]*)\s*([A-Za-z])\s+(\S+)\s*$', line)
        if not m:
            m2 = re.match(r'^\s+U\s+(\S+)\s*$', line)
            if m2:
                u.add(m2.group(1))
            continue
        kind, name = m.group(2), m.group(3)
        if kind.upper() == 'U':
            u.add(name)
        elif kind.islower():
            loc.add(name)
        else:
            g.add(name)
    return g, u, loc


def judge(d):
    ok, bad = [], []

    # ---- B3
    p = os.path.join(d, 'nm-undef.txt')
    if not os.path.exists(p):
        bad.append('B3: no nm-undef.txt in the build')
    else:
        undef = set(x.strip() for x in open(p).read().split() if x.strip())
        extra = sorted(undef - set(ALLOW))
        if extra:
            bad.append('B3: the accel object leaves %s undefined, which is not on the list'
                       % extra)
        else:
            ok.append('B3: %d undefined symbols, every one on the list (%s)'
                      % (len(undef), ', '.join(sorted(undef))))
        for hint in FORBIDDEN_AFTER_M1C:
            if any(hint in u for u in undef):
                bad.append('B3: %r is reachable -- a hook could write with it' % hint)
        if not undef:
            bad.append('B3: no undefined symbols at all, which means nm read nothing')

    # ---- F1, F2
    a = os.path.join(d, 'libGL_radeon.a')
    b = os.path.join(d, 'libGL-stock.a')
    if not (os.path.exists(a) and os.path.exists(b)):
        bad.append('F: the two archives are not both in the build')
    else:
        acc = dict(ar_members(a))
        stock = dict(ar_members(b))
        # the ranlib table is a member on some systems; ignore it either side
        for k in list(acc):
            if k.startswith('__.SYMDEF'):
                del acc[k]
        for k in list(stock):
            if k.startswith('__.SYMDEF'):
                del stock[k]
        added = sorted(set(acc) - set(stock))
        lost = sorted(set(stock) - set(acc))
        if lost:
            bad.append('F1: the accelerated archive LOST %s' % lost)
        if len(added) != 1:
            bad.append('F1: it adds %s, want exactly one member' % (added or 'nothing'))
        else:
            ok.append('F1: %d stock members kept, exactly one added (%s)'
                      % (len(stock), added[0]))
        changed = sorted(k for k in stock if k in acc and acc[k] != stock[k])
        if changed != ['osmesa.o']:
            bad.append('F2: the members that differ are %s, want only osmesa.o' % changed)
        else:
            ok.append('F2: every stock member is byte-identical except osmesa.o')

    # ---- F3
    s1 = os.path.join(d, 'nm-osmesa-stock.txt')
    s2 = os.path.join(d, 'nm-osmesa-installed.txt')
    if not (os.path.exists(s1) and os.path.exists(s2)):
        bad.append('F3: the two nm listings are not both in the build')
    else:
        g1, u1, l1 = syms(open(s1).read())
        g2, u2, l2 = syms(open(s2).read())
        if not g1 or not g2:
            bad.append('F3: one of the listings has no global symbols')
        elif g1 != g2 or u1 != u2:
            bad.append('F3: our tree defines globals %s and leaves %s undefined that the '
                       'installed member does not (and the other way, %s / %s)'
                       % (sorted(g1 - g2)[:4], sorted(u1 - u2)[:4],
                          sorted(g2 - g1)[:4], sorted(u2 - u1)[:4]))
        else:
            ok.append('F3: our tree compiles to the same %d global and %d undefined '
                      'symbols as the installed osmesa.o' % (len(g1), len(u1)))
            if l1 != l2:
                ok.append('F3: the file-local symbols differ by %d, which is an '
                          'optimisation-level difference and not a source one '
                          '(e.g. %s)' % (len(l1 ^ l2), sorted(l1 ^ l2)[:2]))
    return ok, bad


GOOD_UNDEF = ('_close\n_getenv\n_ioctl\n_open\n_mmap\n_vm_allocate\n'
              '_task_self\ndyld_stub_binding_helper\n')


def self_test():
    """the judge must fail on each way the build could be wrong"""
    fails = 0

    def one(label, undef, expect_bad):
        nonlocal fails
        got = set(x.strip() for x in undef.split() if x.strip())
        extra = sorted(got - set(ALLOW))
        hit = bool(extra) or any(h in u for h in FORBIDDEN_AFTER_M1C for u in got)
        okk = hit == expect_bad
        fails += 0 if okk else 1
        print('  %-4s %s' % ('ok' if okk else 'FAIL', label))

    one('the real undefined set passes', GOOD_UNDEF, False)
    one('memset is caught', GOOD_UNDEF + '_memset\n', True)
    one('memcpy is caught', GOOD_UNDEF + '_memcpy\n', True)
    one('an unexplained symbol is caught', GOOD_UNDEF + '_frobnicate\n', True)

    # the ar parser, on an archive built here
    import io
    blob = b'!<arch>\n'
    for name, body in (('a.o', b'AAAA'), ('bb.o', b'BBBBBB')):
        blob += ('%-16s%-12s%-6s%-6s%-8s%-10d`\n' % (name, '0', '0', '0', '0', len(body))).encode()
        blob += body + (b'\n' if len(body) % 2 else b'')
    import tempfile
    t = tempfile.mkdtemp()
    atexit.register(shutil.rmtree, t, True)  # 2026-09-24: /tmp reached 35.6 GiB of our scratch
    p = os.path.join(t, 'x.a')
    open(p, 'wb').write(blob)
    got = ar_members(p)
    okk = [n for n, _b in got] == ['a.o', 'bb.o'] and got[0][1] == b'AAAA'
    fails += 0 if okk else 1
    print('  %-4s the ar parser reads members and bodies' % ('ok' if okk else 'FAIL'))

    g, u, loc = syms('00001000 T _foo\n         U _bar\n00002000 D _baz\n'
                     '00003000 t _local\n')
    okk = g == {'_foo', '_baz'} and u == {'_bar'} and loc == {'_local'}
    fails += 0 if okk else 1
    print('  %-4s the nm reader keeps global, undefined and local apart'
          % ('ok' if okk else 'FAIL'))

    print('judge_m1b self-test: %s' % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return fails


def main():
    if '--self-test' in sys.argv:
        return 1 if self_test() else 0
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    ok, bad = judge(sys.argv[1])
    for x in ok:
        print('  ok   %s' % x)
    for x in bad:
        print('  FAIL %s' % x)
    print('judge_m1b: %s' % ('PASS' if not bad else 'FAIL (%d)' % len(bad)))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
