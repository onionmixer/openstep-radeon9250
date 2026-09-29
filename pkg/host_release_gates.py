#!/usr/bin/env python3
"""The host's half of a release build (docs/REL1_PACKAGING_PLAN.md 11-1, 12).

  host_release_gates.py --lib <runid>      judge build/m1b/<runid> with
        tools/mesa/judge_m1b.py (gates B3 and F); on PASS write
        build/m1b/<runid>/M1B_PASS holding "<sum> <blocks>" of libGL_radeon.a
        -- the BSD sum the target's /usr/bin/sum prints, from the same
        function tools/r2b0/check_reloc_r2b0.py uses for R2B0RELOC_PASS
  host_release_gates.py --driver <runid>   require build/r2b0/<runid>/BUILD_PASS
        and R2B0RELOC_PASS, and that the latter names the reloc sum the
        former records (fields 3 and 4) -- the same test
        tools/r2b0/target-install-r2b0.sh makes
  host_release_gates.py --self-test

The package builders on the target (pkg/build-accel-pkg.sh,
pkg/build-demos-overlay.sh, pkg/build-driver-pkg.sh) refuse bytes these
markers do not name.  Nothing here runs anything on the target.
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


pk = _load('pack_probe_for_rel1', os.path.join(PROJ, 'tools', 'r1', 'pack_probe.py'))
jm = _load('judge_m1b_for_rel1', os.path.join(PROJ, 'tools', 'mesa', 'judge_m1b.py'))


def gate_lib(runid, root=PROJ):
    d = os.path.join(root, 'build', 'm1b', runid)
    lib = os.path.join(d, 'libGL_radeon.a')
    if not os.path.isfile(lib):
        return False, ['no %s' % lib]
    marker = os.path.join(d, 'M1B_PASS')
    if os.path.exists(marker):
        os.remove(marker)               # a stale PASS must not survive a FAIL
    ok, bad = jm.judge(d)
    for x in ok:
        print('  ok   %s' % x)
    for x in bad:
        print('  FAIL %s' % x)
    if bad:
        return False, bad
    got = pk.bsdsum(open(lib, 'rb').read())
    open(marker, 'w').write(got + '\n')
    print('  marker %s: %s' % (marker, got))
    return True, []


def gate_driver(runid, root=PROJ):
    d = os.path.join(root, 'build', 'r2b0', runid)
    bp = os.path.join(d, 'BUILD_PASS')
    rp = os.path.join(d, 'R2B0RELOC_PASS')
    bad = []
    if not os.path.isfile(bp):
        bad.append('no %s -- run tools/r2b0/target-build-r2b0.sh' % bp)
    if not os.path.isfile(rp):
        bad.append('no %s -- run tools/r2b0/check_reloc_r2b0.py with --marker' % rp)
    if bad:
        return False, bad
    f = open(bp).read().split()
    want = ' '.join(f[2:4]) if len(f) >= 4 else ''
    have = ' '.join(open(rp).read().split())
    if not want or want != have:
        return False, ['R2B0RELOC_PASS names "%s", BUILD_PASS records "%s"' % (have, want)]
    print('  ok   driver runid %s: reloc %s judged' % (runid, have))
    return True, []


def self_test():
    import tempfile
    import shutil
    fails = 0
    t = tempfile.mkdtemp(prefix='rel1gates.')
    try:
        # driver: agreeing and disagreeing markers
        d = os.path.join(t, 'build', 'r2b0', '1')
        os.makedirs(d)
        open(os.path.join(d, 'BUILD_PASS'), 'w').write('abcd1234 1 01234 56 00001 1\n')
        open(os.path.join(d, 'R2B0RELOC_PASS'), 'w').write('01234 56\n')
        ok, _ = gate_driver('1', t)
        fails += 0 if ok else 1
        open(os.path.join(d, 'R2B0RELOC_PASS'), 'w').write('01235 56\n')
        ok, _ = gate_driver('1', t)
        fails += 1 if ok else 0          # a mismatch must fail
        os.remove(os.path.join(d, 'R2B0RELOC_PASS'))
        ok, _ = gate_driver('1', t)
        fails += 1 if ok else 0          # no judge, no pass
        # lib: a failing judge removes a stale marker and writes none
        l = os.path.join(t, 'build', 'm1b', '2')
        os.makedirs(l)
        open(os.path.join(l, 'libGL_radeon.a'), 'wb').write(b'!<arch>\n')
        open(os.path.join(l, 'M1B_PASS'), 'w').write('stale\n')
        ok, _ = gate_lib('2', t)
        fails += 1 if ok else 0
        fails += 1 if os.path.exists(os.path.join(l, 'M1B_PASS')) else 0
        # the sum is the one the target prints (recorded pair in pack_probe)
        fails += 0 if pk.bsdsum(b'test\n') == '41076 1' else 1
    finally:
        shutil.rmtree(t)
    print('host_release_gates self-test: %s' % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return fails == 0


def main(argv):
    a = argv[1:]
    if a == ['--self-test']:
        return 0 if self_test() else 1
    if len(a) != 2 or a[0] not in ('--lib', '--driver') or not a[1].isdigit():
        print(__doc__)
        return 2
    ok, bad = (gate_lib if a[0] == '--lib' else gate_driver)(a[1])
    for x in bad:
        print('FAIL ' + x)
    print('host_release_gates %s %s: %s' % (a[0], a[1], 'PASS' if ok else 'FAIL'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
