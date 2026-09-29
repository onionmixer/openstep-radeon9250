#!/usr/bin/env python3
"""Every build/r6*/plan_ops.txt must be exactly the procedure its judge expects.

  check_plan_ops.py [--self-test]

WHY THIS EXISTS.  The first R6m boot (00ef86d4, 2026-09-21) was run with the operation list in
build/r6m/plan_ops.txt, which left out the leading F control because the earlier rungs ran F by
hand.  Every case still ran and every R6m gate passed, but the missing submission moved the ring
112 words and the wrap that task #30 needed never happened -- one boot spent, and the CP is one
LOAD..STOP cycle per boot, so it could not be retried without another reboot.

The plan file and the judge's ORDERS entry are two statements of the same thing, and nothing
compared them.  Now something does: a plan file that names its procedure in a "# procedure <name>"
line is expanded to the full operation list (the fixed preamble, the file's cases with their
planes, the fixed tail) and compared with ORDERS[<name>], element for element.  A file with no such
line is history and is listed as unchecked.
"""

import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE) if os.path.basename(HERE) != 'r6' else os.path.dirname(os.path.dirname(HERE))
PRE = ['record', 'rec3d', 'load', 'map', 'reset', 'start', 'rec3d']
TAIL = ['rec3d', 'stop', 'record']
# G4-7 (docs/G4_7_TRIPERF_PLAN.md 4): a plan file that says "# tail nostop" leaves the CP running -- it is one
# LOAD..STOP cycle per boot, and the GLQuake run that the boot is for comes after the judged operations
TAIL_NOSTOP = ['rec3d', 'record']


def _load():
    spec = importlib.util.spec_from_file_location('check_r6a', os.path.join(HERE, 'check_r6a.py'))
    mod = importlib.util.module_from_spec(spec)
    sys.modules['check_r6a'] = mod
    spec.loader.exec_module(mod)
    return mod


def expand(text):
    """(procedure or None, the operations the runner will perform, the case numbers)"""
    proc, ops, cases, tail = None, list(PRE), [], TAIL
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('#'):
            if line[1:].split()[:1] == ['procedure']:
                proc = line.split()[2]
            if line[1:].split()[:2] == ['tail', 'nostop']:
                tail = TAIL_NOSTOP
            continue
        if not line:
            continue
        line = line.split('#')[0].strip()   # the plan files name each case after it
        if not line:
            continue
        f = line.split()
        if f[0] == 'stage':
            continue            # R7a: staging touches no hardware; it is not a CP operation
        if f[0] != 'case':
            continue
        ops += ['zprep', 'zclear'] + ['plane'] * (len(f) - 2)
        cases.append(int(f[1]))
    return proc, ops + tail, cases


def check(paths=None):
    ck = _load()
    if paths is None:
        base = os.path.join(PROJ, 'build')
        paths = sorted(os.path.join(base, d, 'plan_ops.txt') for d in os.listdir(base)
                       if os.path.exists(os.path.join(base, d, 'plan_ops.txt')))
    bad, checked = 0, 0
    for p in paths:
        rel = os.path.relpath(p, PROJ)
        proc, ops, cases = expand(open(p).read())
        if proc is None:
            print('  --   %s names no procedure (not checked)' % rel)
            continue
        if proc not in ck.ORDERS:
            print('  FAIL %s names procedure %r, which the judge does not have' % (rel, proc))
            bad += 1
            continue
        wops, wcases = ck.ORDERS[proc]
        checked += 1
        if ops != wops:
            k = next((i for i in range(max(len(ops), len(wops)))
                      if ops[i:i + 1] != wops[i:i + 1]), 0)
            print('  FAIL %s: operation %d is %r, the %s procedure wants %r (%d vs %d operations)' %
                  (rel, k, ops[k:k + 1], proc, wops[k:k + 1], len(ops), len(wops)))
            bad += 1
        elif cases != wcases:
            print('  FAIL %s: the cases are %s, the %s procedure wants %s' % (rel, cases, proc, wcases))
            bad += 1
        else:
            print('  ok   %s is exactly the %s procedure (%d operations, %d cases)' %
                  (rel, proc, len(ops), len(cases)))
    print('check_plan_ops: %s (%d checked)' % ('PASS' if not bad else 'FAIL (%d)' % bad, checked))
    return bad


def self_test():
    """the check must fail on the very mistake that made it: a missing leading case"""
    ck = _load()
    fails = 0

    def ok(cond, what):
        nonlocal fails
        fails += 0 if cond else 1
        print('  %-4s %s' % ('ok' if cond else 'FAIL', what))

    good = open(os.path.join(PROJ, 'build', 'r6m', 'plan_ops.txt')).read()
    proc, ops, cases = expand(good)
    ok(proc == 'r6m', 'the R6m plan file names its procedure (%s)' % proc)
    ok((ops, cases) == ck.ORDERS['r6m'], 'and expands to exactly the r6m procedure')
    # the mistake of boot 00ef86d4: the F control dropped from the front
    lost = '\n'.join(l for l in good.splitlines() if l.strip() != 'case 6')
    _p, ops2, cases2 = expand(lost)
    ok((ops2, cases2) != ck.ORDERS['r6m'], 'dropping the leading F control is caught')
    # a plane count that does not match the case
    fewer = good.replace(' 0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15\n', ' 0 1 2 3\n', 1)
    _p, ops3, _c = expand(fewer)
    ok(ops3 != ck.ORDERS['r6m'][0], 'a short plane list is caught')
    # a case in the wrong order
    swapped = good.replace('case 170\ncase 166', 'case 166\ncase 170', 1)
    _p, _o, cases4 = expand(swapped)
    ok(cases4 != ck.ORDERS['r6m'][1], 'a case out of order is caught')
    ok(expand('case 6\n')[0] is None, 'a file with no procedure line is not checked')
    print('check_plan_ops self-test: %s' % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return fails


if __name__ == '__main__':
    sys.exit(1 if (self_test() if '--self-test' in sys.argv else check()) else 0)
