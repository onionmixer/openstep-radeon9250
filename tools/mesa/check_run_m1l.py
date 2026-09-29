#!/usr/bin/env python3
"""Check build/m1l/run_m1l.sh: every arm states its own knobs, and `knobs` works.

  python3 tools/mesa/check_run_m1l.py            check the real script
  python3 tools/mesa/check_run_m1l.py --self-test   mutate it and prove the rules fire

WHY THIS EXISTS.  A judge pair's whole claim is "these two arms differ in ONE
knob".  Until M2e that claim rested on the ORDER of the arms: the baseline arm
t-stage stated neither of its two knobs and inherited both.  Moving an arm, or
adding one, broke the claim with nothing to say so -- and when M2e flipped the
WBINVD default, every inherited value changed meaning at once.

WHAT IS CHECKED BY TEXT, AND WHAT BY RUNNING IT.  Three of the four rules are
about the shape of the file (is there a `knobs` call between this arm and the
one before it?  is the helper defined above its first use?  does the run end at
the shipped default?) and text is the right tool for those.  The fourth -- does
`knobs` actually issue the two operations, in order, and complain when one is
refused -- is about behaviour, so the function is EXTRACTED AND RUN under a stub
shell (docs/M2E_PLAN.md 2-2; the lesson is
memory:build-script-checks-should-run-the-script).
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
SCRIPT = os.path.join(PROJ, 'build', 'm1l', 'run_m1l.sh')

# What each arm's two knobs must be.  This table is the SECOND copy of that
# intent -- the script is the first -- so a value changed in one place and not
# the other is a failure and not a silent drift.
#
#   nowb 0 = do the WBINVD (the pre-M2e behaviour)
#   nowb 1 = skip it (the M2e default)
#   time 1 = the stage instrument on
WANT = {
    't-stock': (0, 1), 't-accel': (0, 1), 't-nobatch': (0, 1), 't-hold': (0, 1),
    't-poison': (0, 1), 't-quiet': (0, 1), 't-qhold': (0, 1),
    't-nosent': (0, 1), 't-nullsend': (0, 1),
    't-inline': (0, 1), 't-nullinl': (0, 1), 't-group': (0, 1),
    't-stage': (0, 1),          # the baseline: both knobs as they were before M2e
    't-nowb': (1, 1),           # M2a's arm: the WBINVD skipped
    't-spin': (0, 1),           # M2b's arm: the spin is a third knob, set separately
    't-notime': (0, 0),         # M2c's arm: the instrument off
    't-bothoff': (1, 0),        # M2d's fourth cell
    't-accel2': (0, 1),         # the log-on drift arm: must match t-accel
    't-stage2': (0, 1),         # the quiet drift bar: must match t-stage
}

# M2g: which arms pay the driver's submit log.  The log is OFF by default now,
# so these must ASK for it with `loud N` in their own lines -- five of them
# used to pay it only because the default did, and flipping the default would
# have made them quiet with nothing to say so (docs/M2G_PLAN.md 4-2, 4-3).
# Everything not named here must run quiet.  t-stock and t-poison submit
# nothing, so their log state is not checked.
LOUD = {'t-accel', 't-nobatch', 't-hold', 't-accel2', 't-ab1', 't-ab4', 't-grid'}
NOLOG = {'t-stock', 't-poison'}
LOUD_RE = re.compile(r'^\s*(?:bash "\$OP" )?loud (\d+)\b')
ABBA_RE = re.compile(r'^\s*abba (ab\d) \d+ (\d+)\b')

ARM_RE = re.compile(r'> \$N/(t-[a-z0-9-]+)\.out')
KNOBS_RE = re.compile(r'^\s*knobs (\d) (\d)\b')


def check(text):
    """[complaint]"""
    bad = []
    lines = text.split('\n')

    # ---- 1. the helper is defined above its first use
    defn = use = None
    for i, l in enumerate(lines):
        if defn is None and l.startswith('knobs() {'):
            defn = i
        if use is None and KNOBS_RE.match(l):
            use = i
    if defn is None:
        bad.append('there is no knobs() helper')
    elif use is None:
        bad.append('nothing calls knobs')
    elif defn > use:
        bad.append('knobs() is defined at line %d but first called at line %d -- sh '
                   'reads the file as it runs, so that call is "command not found" '
                   'and the arm runs with whatever state it inherited'
                   % (defn + 1, use + 1))

    # ---- 2. every arm has a knobs call of its own, after the previous arm
    last_arm = -1
    seen = []
    for i, l in enumerate(lines):
        m = ARM_RE.search(l)
        if not m:
            continue
        arm = m.group(1)
        seen.append(arm)
        window = lines[last_arm + 1:i]
        calls = [KNOBS_RE.match(w) for w in window]
        calls = [c for c in calls if c]
        if not calls:
            bad.append('%s runs with no knobs call of its own: it inherits whatever '
                       'the arm before it left, and a judge pair that uses it is '
                       'claiming a one-knob difference it cannot show' % arm)
        else:
            got = (int(calls[-1].group(1)), int(calls[-1].group(2)))
            want = WANT.get(arm)
            if want is None:
                bad.append('%s is an arm this checker has no entry for: add it to '
                           'WANT, or the run can change its meaning unseen' % arm)
            elif got != want:
                bad.append('%s says knobs %d %d, the table says %d %d'
                           % (arm, got[0], got[1], want[0], want[1]))
        last_arm = i
    for arm in WANT:
        if arm not in seen:
            bad.append('the table names %s but the script never runs it' % arm)

    # ---- 3. the run ends at the shipped default
    tail = [l for l in lines if KNOBS_RE.match(l)]
    if not tail:
        pass                                    # already complained
    elif KNOBS_RE.match(tail[-1]).groups() != ('1', '0'):
        bad.append('the last knobs call is `%s`, not `knobs 1 0` -- a run must end '
                   'where a fresh boot starts (WBINVD skipped, instrument off), or '
                   'anything done by hand afterwards gets a machine nobody described'
                   % tail[-1].strip())

    # ---- 4. M2g: every arm's submit log is what the table says, and a loud arm
    #         asked for it itself
    state, since = 0, False         # the boot default: quiet
    last_loud = None
    for i, l in enumerate(lines):
        st = l.strip()
        if st.startswith('#'):
            continue
        if re.match(r'^\s*(?:bash "\$OP" )?quiet 0\b', l):
            bad.append('line %d still says `quiet 0` -- it meant "log back on", '
                       'and after M2g it silences' % (i + 1))
        m = LOUD_RE.match(l)
        if m:
            state = int(m.group(1)); since = state > 0; last_loud = m.group(1)
            continue
        arm = None
        m = ABBA_RE.match(l)
        if m:
            arm, state, since = 't-' + m.group(1), int(m.group(2)), int(m.group(2)) > 0
        elif 't-grid-$gl-$gn.out' in l:
            arm = 't-grid'
        else:
            m = ARM_RE.search(l)
            if m:
                arm = m.group(1)
        if arm is None or arm in NOLOG:
            continue
        loud = state > 0
        if arm in LOUD and not loud:
            bad.append('%s must pay the submit log but runs quiet -- its price '
                       'would come out as a quiet arm\'s' % arm)
        elif arm not in LOUD and loud:
            bad.append('%s must run quiet but a loud lease is live when it starts'
                       % arm)
        elif arm in LOUD and not since and arm != 't-grid':
            bad.append('%s is loud only because an earlier arm left it so -- it must '
                       'ask with its own `loud N`' % arm)
        if arm != 't-grid':
            since = False
    if last_loud != '0':
        bad.append('the last loud call is `loud %s`, not `loud 0` -- a run must end '
                   'quiet, the shipped default' % last_loud)
    return bad


def run_the_helper():
    """[complaint] -- extract knobs() and RUN it against a stub $OP"""
    bad = []
    text = open(SCRIPT, errors='replace').read()
    lines = text.split('\n')
    try:
        i = next(k for k, l in enumerate(lines) if l.startswith('knobs() {'))
        j = next(k for k in range(i, len(lines)) if lines[k] == '}')
    except StopIteration:
        return ['knobs() could not be extracted to run it']
    body = '\n'.join(lines[i:j + 1])

    d = tempfile.mkdtemp()
    atexit.register(shutil.rmtree, d, True)  # 2026-09-24: /tmp reached 35.6 GiB of our scratch
    op = os.path.join(d, 'op.sh')
    for case, extra in (('ok', ''), ('refused', '')):
        with open(op, 'w') as f:
            f.write('#!/bin/sh\n'
                    'echo "$@" >> %s/calls\n' % d)
            if case == 'ok':
                f.write('echo "mach: op=$1 r=0"\n')
            else:
                f.write('if [ "$1" = time ]; then echo "mach: op=$1 r=-714";'
                        ' else echo "mach: op=$1 r=0"; fi\n')
        os.chmod(op, 0o755)
        calls = os.path.join(d, 'calls')
        os.path.exists(calls) and os.unlink(calls)
        prog = ('OP=%s\nsay() { echo "== $*"; }\n%s\nknobs 1 0\n' % (op, body))
        r = subprocess.run(['sh', '-c', prog], capture_output=True, text=True)
        got = open(calls).read().split('\n') if os.path.exists(calls) else []
        got = [g for g in got if g]
        if got != ['nowb 1', 'time 0']:
            bad.append('running knobs 1 0 issued %r, want [\'nowb 1\', \'time 0\'] '
                       '(%s stub)' % (got, case))
        if 'knobs nowb=1' not in r.stdout:
            bad.append('knobs printed no line naming its state (%s stub): %r'
                       % (case, r.stdout))
        if case == 'refused' and 'a knob was refused' not in r.stdout:
            bad.append('a refused knob produced no complaint: %r' % r.stdout)
        if case == 'ok' and 'a knob was refused' in r.stdout:
            bad.append('a knob that was accepted still complained: %r' % r.stdout)
    return bad


def self_test():
    text = open(SCRIPT, errors='replace').read()
    ok = True

    def one(name, cond):
        nonlocal ok
        print('  %-4s %s' % ('ok' if cond else 'FAIL', name))
        if not cond:
            ok = False

    one('the script as it stands passes', not check(text))
    one('and the helper does what it says when run', not run_the_helper())

    # an arm that loses its knobs call
    cut = text.replace('knobs 0 1              # M2e: this arm says its own state\n', '', 1)
    one('an arm that inherits its knobs is a FAILURE',
        any('no knobs call of its own' in b for b in check(cut)))
    # a knob set to the wrong value
    wrong = text.replace('knobs 1 1              # M2e', 'knobs 0 1              # M2e', 1)
    one('a knob that disagrees with the table is a FAILURE',
        any('the table says' in b for b in check(wrong)))
    # the helper below its first use
    lines = text.split('\n')
    i = next(k for k, l in enumerate(lines) if l.startswith('knobs() {'))
    j = next(k for k in range(i, len(lines)) if lines[k] == '}')
    moved = lines[:i] + lines[j + 1:] + lines[i:j + 1]
    one('the helper defined below its first use is a FAILURE',
        any('command not found' in b for b in check('\n'.join(moved))))
    # a run that does not end at the shipped default
    end = text.rstrip().rsplit('knobs 1 0', 1)
    one('a run that does not end at the shipped default is a FAILURE',
        len(end) == 2 and any('must end where a fresh boot starts' in b
                              for b in check(end[0] + 'knobs 0 1' + end[1])))
    # an arm the table does not know
    # M2g: the submit log
    cut = text.replace('zprep\nloud 5000\nknobs 0 1', 'zprep\nknobs 0 1', 1)
    one('M2g: a log-on arm that does not ask for the log is a FAILURE',
        any('must pay the submit log but runs quiet' in x or 'loud only because' in x
            for x in check(cut)))
    cut = text.replace('RDNMesaHold=1 $B/rdntri-accel ${R}h flat p > $N/t-hold.out 2>&1; sync; echo RC=\\$?" | tail -1\nloud 0\n',
                       'RDNMesaHold=1 $B/rdntri-accel ${R}h flat p > $N/t-hold.out 2>&1; sync; echo RC=\\$?" | tail -1\n', 1)
    one('M2g: a loud lease left live into a quiet arm is a FAILURE',
        cut != text and any('must run quiet but a loud lease is live' in x for x in check(cut)))
    cut = text.replace('abba ab2 42000 0', 'abba ab2 42000 5000', 1)
    one('M2g: an ABBA "off" arm that is loud is a FAILURE',
        any('t-ab2 must run quiet' in x for x in check(cut)))
    cut = text.replace('abba ab4 44000 5000', 'abba ab4 44000 0', 1)
    one('M2g: an ABBA "on" arm that is quiet is a FAILURE',
        any('t-ab4 must pay the submit log' in x for x in check(cut)))
    cut = text.rstrip('\n') + '\nbash "$OP" quiet 0\n'
    one('M2g: `quiet 0` anywhere is a FAILURE -- its meaning changed',
        any('still says `quiet 0`' in x for x in check(cut)))

    extra = text.replace('> $N/t-stock.out', '> $N/t-newarm.out', 1)
    one('an arm the table has no entry for is a FAILURE',
        any('no entry for' in b for b in check(extra)))
    print('check_run_m1l self-test: %s' % ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


def main():
    if '--self-test' in sys.argv:
        return self_test()
    bad = check(open(SCRIPT, errors='replace').read()) + run_the_helper()
    for b in bad:
        print('  FAIL %s' % b)
    print('check_run_m1l: %s' % ('PASS' if not bad else 'FAIL (%d)' % len(bad)))
    return 0 if not bad else 1


if __name__ == '__main__':
    sys.exit(main())
