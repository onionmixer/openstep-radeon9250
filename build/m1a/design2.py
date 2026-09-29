#!/usr/bin/env python3
"""M1a design: the probe's verdicts, derived from what can actually go wrong.

  python3 build/m1a/design2.py

The gate comes before the hooks (openstep-matrox-remade/docs/M1_3_GATING_PLAN.md 1:
filling the hooks first leaves the revert path untested, and the revert path is the
one MOST users run).  A gate is only worth having if its verdicts are the real
failure modes, so this enumerates them from the interface R7b already built --
osrdn_r7b.h and the driver's d_ioctl -- rather than from a list someone invented.

Every verdict but one must mean SOFTWARE.  That is the property the precedent
insists on, and it is checked here by counting.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
TPROJ = os.path.join(PROJ, 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj')
HDR = os.path.join(TPROJ, 'osrdn_r7b.h')
DISP = os.path.join(TPROJ, 'OSRDNDisplay.m')

# Each verdict names a step of the probe that can fail, and what the client does.
# "hardware" is the only one that accelerates.
VERDICTS = [
    ('HARDWARE',    'every check passed',                                 'accelerate'),
    ('NO_DEVICE',   'the node is absent, or open() refused',              'software'),
    ('NOT_OURS',    'the node answers, but not this driver (ENOTTY)',     'software'),
    ('MAGIC',       'CAPS returned, but the magic word is not ours',      'software'),
    ('VERSION',     'the interface version is not the one we compiled to','software'),
    ('NOT_READY',   'no batch page or no batch window (caps.ready == 0)', 'software'),
    ('NOT_RUNNING', 'the CP is not running (caps.cpRunning == 0)',        'software'),
    ('DISABLED',    'the environment switch turned acceleration off',     'software'),
    ('REVOKED',     'something went wrong earlier and we gave it up',     'software'),
]


def main():
    hdr, disp = open(HDR).read(), open(DISP).read()
    bad = 0

    print('1. the verdicts')
    for name, why, what in VERDICTS:
        print('   %-12s %-52s -> %s' % (name, why, what))
    hw = [v for v in VERDICTS if v[2] == 'accelerate']
    sw = [v for v in VERDICTS if v[2] == 'software']
    print('   %d verdicts: %d accelerate, %d mean software' % (len(VERDICTS), len(hw), len(sw)))
    if len(hw) != 1:
        print('   FAIL: exactly one verdict may accelerate')
        bad += 1
    if len(sw) != len(VERDICTS) - 1:
        print('   FAIL: every other verdict must mean software')
        bad += 1

    print('2. each verdict is reachable through the interface R7b built')
    # the field or behaviour that produces it, checked to exist rather than assumed
    need = {'MAGIC': r'OSRDN_R7B_MAGIC', 'VERSION': r'OSRDN_R7B_VERSION',
            'NOT_READY': r'unsigned long ready;', 'NOT_RUNNING': r'unsigned long cpRunning;'}
    for v, pat in need.items():
        if re.search(pat, hdr):
            print('   %-12s <- osrdn_r7b.h has %s' % (v, pat.strip()))
        else:
            print('   FAIL %s: osrdn_r7b.h has no %s' % (v, pat))
            bad += 1
    if re.search(r'return ENOTTY;', disp):
        print('   %-12s <- the driver answers an unknown command with ENOTTY' % 'NOT_OURS')
    else:
        print('   FAIL NOT_OURS: the driver does not return ENOTTY')
        bad += 1
    if re.search(r'return ENXIO;', disp):
        print('   %-12s <- d_open/d_ioctl refuse with ENXIO' % 'NO_DEVICE')
    else:
        print('   FAIL NO_DEVICE: nothing refuses with ENXIO')
        bad += 1

    print('3. the policies the precedent fixes, stated as testable rules')
    rules = [
        ('P1', 'a failure is a VERDICT, not an error: the probe always answers'),
        ('P2', 'the answer is cached and must be the same on every later call'),
        ('P3', 'revocation is ONE-WAY: REVOKED never goes back to HARDWARE'),
        ('P4', 'the environment switch can only turn acceleration OFF, never on'),
        ('P5', 'the version must match EXACTLY -- it names a shared memory layout'),
        ('P6', 'identity comes from the ioctl itself; a foreign driver says ENOTTY'),
        ('P7', 'the client links WITHOUT -lDriver: plain C, or libGL cannot carry it'),
    ]
    for k, s in rules:
        print('   %s %s' % (k, s))

    print('4. what M1a does NOT do')
    for s in ('no hook site is added to osmesa.c (that tree is not touched)',
              'no accelerated libGL is built',
              'nothing is drawn, on hardware or otherwise',
              'the driver is not changed, so this rung costs no reboot'):
        print('   - %s' % s)

    print('design2: %s' % ('PASS' if not bad else 'FAIL (%d)' % bad))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
