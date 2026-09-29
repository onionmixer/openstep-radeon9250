#!/usr/bin/env python3
"""M1a gate B: the probe's source rules, and a mutation for each (docs/M1A_PLAN.md 6-B).

  check_probe.py

Baseline PASS and every mutation FAIL, in the SAME run.  Seeing only that
mutations are caught says nothing about whether the real source obeys the rule;
seeing only that the baseline passes says nothing about whether the rule can
fail at all.  (PLAN.md 188, and the same lesson recorded as
check-rules-refine-not-weaken.)

The rules are the ones the plan states as policies -- P1..P7 -- expressed as
things that are true or false of the text, plus the two numbers that have to
agree with headers this project does not own.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
MESA = os.path.join(PROJ, 'mesa')
SRC = os.path.join(MESA, 'OSRDNMesaProbe.c')
HDR = os.path.join(MESA, 'OSRDNMesaProbe.h')
FCNTL = os.path.join(PROJ, '..', 'ref', 'openstep', 'headers', 'NextDeveloper',
                     'Headers', 'bsd', 'sys', 'fcntl.h')
R7B = os.path.join(PROJ, 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj', 'osrdn_r7b.h')


def uncomment(t):
    """a rule about code must not be satisfied -- or broken -- by a comment"""
    return re.sub(r'//[^\n]*', ' ', re.sub(r'/\*.*?\*/', ' ', t, flags=re.S))


def body(text, name):
    """one function's body, by brace counting from its opening line"""
    m = re.search(r'\n\w[\w \*]*\b%s\s*\([^;{]*\)\s*\n?\{' % re.escape(name), text)
    if m is None:
        return ''
    i = text.index('{', m.start())
    d, j = 0, i
    while j < len(text):
        if text[j] == '{':
            d += 1
        elif text[j] == '}':
            d -= 1
            if d == 0:
                return text[i:j + 1]
        j += 1
    return ''


def rules(src, hdr):
    r = {}
    code, hcode = uncomment(src), uncomment(hdr)

    # P7 -- plain C.  This is the reason the rung exists, so it is a rule.
    p = []
    for pat, what in ((r'#\s*import\b', '#import'), (r'\bdriverkit/', 'a driverkit header'),
                      (r'\bIODeviceMaster\b', 'IODeviceMaster'),
                      (r'@\s*(interface|implementation)\b', 'an Objective-C declaration'),
                      (r'\bobjc_\w+', 'the Objective-C runtime')):
        for label, t in (('the unit', code), ('the header', hcode)):
            if re.search(pat, t):
                p.append('%s uses %s' % (label, what))
    r['m1a-pure-c'] = p

    # the host simulator and the target build must compile the SAME text, and the
    # host has no 32-bit libc headers: so the unit includes none.
    p = []
    inc = re.findall(r'#\s*include\s*<([^>]+)>', code)
    if inc:
        p.append('the unit includes system headers: %s' % inc)
    for fn in ('getenv', 'open', 'ioctl', 'close'):
        if not re.search(r'extern\s[^;]*\b%s\s*\(' % fn, code):
            p.append('%s is used but not declared here' % fn)
    r['m1a-no-system-headers'] = p

    # nine verdicts, numbered 0..8, exactly one of which accelerates
    p = []
    nums = dict((m.group(1), int(m.group(2)))
                for m in re.finditer(r'#define\s+OSRDN_PROBE_(\w+)\s+(\d+)\b', hcode))
    count = nums.pop('VERDICTS', None)
    if count != 9:
        p.append('OSRDN_PROBE_VERDICTS is %r, want 9' % count)
    if sorted(nums.values()) != list(range(9)):
        p.append('the verdicts are not 0..8: %s' % sorted(nums.values()))
    if nums.get('HARDWARE') != 0:
        p.append('HARDWARE is %r, want 0' % nums.get('HARDWARE'))
    names = re.search(r'names\[OSRDN_PROBE_VERDICTS\]\s*=\s*\{(.*?)\}', code, re.S)
    got = re.findall(r'"(\w+)"', names.group(1)) if names else []
    want = [n for n, _v in sorted(nums.items(), key=lambda kv: kv[1])]
    if got != want:
        p.append('the name table is %s, the macros are %s' % (got, want))
    r['m1a-nine-verdicts'] = p

    # P1 -- the probe always answers: every way out of the decision is a verdict
    p = []
    ask = body(code, 'probeAsk')
    if not ask:
        p.append('probeAsk is not there')
    else:
        for m in re.finditer(r'return\s+([^;]+);', ask):
            v = m.group(1).strip()
            if not v.startswith('OSRDN_PROBE_'):
                p.append('probeAsk returns %r, which is not a verdict' % v)
    run = body(code, 'OSRDNMesaProbeRun')
    for m in re.finditer(r'return\s+([^;]+);', run):
        v = m.group(1).strip()
        if not (v.startswith('OSRDN_PROBE_') or v == 'probeVerdict'):
            p.append('Run returns %r, which is neither a verdict nor the cached one' % v)
    r['m1a-always-answers'] = p

    # P3 -- one way, and the flag is what carries it
    p = []
    rev = body(code, 'OSRDNMesaProbeRevoke')
    if 'probeRevoked = 1' not in rev:
        p.append('Revoke does not set the flag')
    if re.search(r'probeVerdict\s*=', rev):
        p.append('Revoke writes the cached verdict too, which makes the flag redundant -- '
                 'and a check that cannot be made to fail is not a check')
    i, j = run.find('probeRevoked'), run.find('probeVerdict >= 0')
    if i < 0:
        p.append('Run does not consult the revocation')
    elif j >= 0 and i > j:
        p.append('Run reads the cache before the revocation, so a cached HARDWARE wins')
    r['m1a-one-way'] = p

    # P4 -- the switch is a presence, never a value that is read
    p = []
    sw = re.search(r'P_GETENV\s*\(\s*OSRDN_PROBE_ENV\s*\)([^)]*)\)', ask or '')
    line = re.search(r'if\s*\(([^\n]*P_GETENV[^\n]*)\)', ask or '')
    if not line:
        p.append('the switch is not consulted')
    else:
        t = line.group(1)
        if '!= 0' not in t:
            p.append('the switch test is %r, not a presence test' % t.strip())
        if re.search(r'P_GETENV[^)]*\)\s*\[', t) or 'strcmp' in t or 'strlen' in t:
            p.append('the switch VALUE is read (%r) -- a switch that is read can be '
                     'made to say yes' % t.strip())
    r['m1a-switch-presence'] = p

    # P5 -- exactly the version, because it names a memory layout
    p = []
    v = re.search(r'blk\.version\s*(!=|<|>|<=|>=)\s*OSRDN_R7B_VERSION', ask or '')
    if not v:
        p.append('the version is not compared')
    elif v.group(1) != '!=':
        p.append('the version is compared with %r, not for exact equality' % v.group(1))
    r['m1a-version-exact'] = p

    # the seam must not exist in a shipped build
    p = []
    for fn in ('OSRDNMesaProbeSetOps', 'OSRDNMesaProbeForget'):
        for label, t in (('the unit', code), ('the header', hcode)):
            k = t.find(fn)
            if k < 0:
                continue
            g = t.rfind('#ifdef OSRDN_PROBE_TESTABLE', 0, k)
            e = t.rfind('#endif', 0, k)
            if g < 0 or (e > g):
                p.append('%s declares %s outside the TESTABLE guard' % (label, fn))
    r['m1a-seam-guarded'] = p

    # the two numbers that belong to headers this project does not own
    p = []
    m = re.search(r'#define\s+NODE_RDWR\s+(\d+)', code)
    want = re.search(r'#define\s+O_RDWR\s+0*(\d+)', open(FCNTL).read())
    if not m:
        p.append('NODE_RDWR is not defined')
    elif not want:
        p.append('the target fcntl.h no longer defines O_RDWR')
    elif int(m.group(1)) != int(want.group(1), 8):
        p.append('NODE_RDWR is %s, the target header says %s' % (m.group(1), want.group(1)))
    if not re.search(r'#include\s+"osrdn_r7b\.h"', code):
        p.append('the unit does not include the interface it probes')
    if not re.search(r'OSRDN_R7B_IOC_CAPS', code):
        p.append('the unit does not send CAPS')
    r['m1a-borrowed-numbers'] = p
    return r


MUTATIONS = [
    ('the unit reaches for Objective-C', 'src',
     '#include "OSRDNMesaProbe.h"', '#import <driverkit/IODeviceMaster.h>\n#include "OSRDNMesaProbe.h"',
     'm1a-pure-c'),
    ('the unit includes a system header', 'src',
     '#include "osrdn_r7b.h"', '#include <string.h>\n#include "osrdn_r7b.h"',
     'm1a-no-system-headers'),
    ('a libc call is used undeclared', 'src', 'extern char *getenv(const char *);\n', '',
     'm1a-no-system-headers'),
    ('a tenth verdict appears', 'hdr', '#define OSRDN_PROBE_VERDICTS    9',
     '#define OSRDN_PROBE_EXTRA       9\n#define OSRDN_PROBE_VERDICTS    10',
     'm1a-nine-verdicts'),
    ('the name table drifts from the macros', 'src', '"HARDWARE", "NO_DEVICE"',
     '"NO_DEVICE", "HARDWARE"', 'm1a-nine-verdicts'),
    ('the decision returns an error', 'src',
     '    if ((fd = P_OPEN(NODE)) < 0)\n        return OSRDN_PROBE_NO_DEVICE;',
     '    if ((fd = P_OPEN(NODE)) < 0)\n        return -1;', 'm1a-always-answers'),
    ('Revoke writes the cache as well', 'src', '    probeRevoked = 1;\n',
     '    probeRevoked = 1;\n    probeVerdict = OSRDN_PROBE_REVOKED;\n', 'm1a-one-way'),
    ('Run reads the cache first', 'src',
     '    if (probeRevoked)\n        return OSRDN_PROBE_REVOKED;\n    if (probeVerdict >= 0)\n        return probeVerdict;\n',
     '    if (probeVerdict >= 0)\n        return probeVerdict;\n    if (probeRevoked)\n        return OSRDN_PROBE_REVOKED;\n',
     'm1a-one-way'),
    ('the switch value is read', 'src', 'if (P_GETENV(OSRDN_PROBE_ENV) != 0)',
     "if (P_GETENV(OSRDN_PROBE_ENV) != 0 && P_GETENV(OSRDN_PROBE_ENV)[0] != 'o')",
     'm1a-switch-presence'),
    ('the version need only be at least ours', 'src', 'blk.version != OSRDN_R7B_VERSION',
     'blk.version < OSRDN_R7B_VERSION', 'm1a-version-exact'),
    ('the seam escapes the guard', 'hdr', '#ifdef OSRDN_PROBE_TESTABLE\ntypedef struct {',
     '#if 1\ntypedef struct {', 'm1a-seam-guarded'),
    ('the open flag stops matching the target header', 'src', '#define NODE_RDWR       2',
     '#define NODE_RDWR       3', 'm1a-borrowed-numbers'),
]


def main():
    src, hdr = open(SRC).read(), open(HDR).read()
    fails = 0

    r = rules(src, hdr)
    for name in sorted(r):
        for x in r[name]:
            print('    FAIL %-22s %s' % (name, x))
            fails += 1
        if not r[name]:
            print('    ok   %-22s' % name)

    for label, which, old, new, want in MUTATIONS:
        t = src if which == 'src' else hdr
        if t.count(old) != 1:
            print('    FAIL mutation %-48s anchor found %d times' % (label, t.count(old)))
            fails += 1
            continue
        m = t.replace(old, new)
        got = rules(m if which == 'src' else src, m if which == 'hdr' else hdr)
        caught = [k for k, v in got.items() if v]
        if want in caught:
            print('    ok   mutation %-48s %s' % (label, caught))
        else:
            print('    FAIL mutation %-48s caught by %s, want %s' % (label, caught, want))
            fails += 1

    print('check_probe: %s' % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
