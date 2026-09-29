#!/usr/bin/env python3
"""Run the R3 target scripts on a fake /private/Drivers, with teeth.

  check_target_r3.py

tools/r3/target-mode-reset.sh and target-cfgsave.sh run on the OPENSTEP
target, where a mistake costs a screen or a boot.  Here each runs under the
host's /bin/sh with R3_* pointing at a scratch tree; every refusal must leave
the table byte-identical, and the good path must change exactly one line and
keep the file's mode.  The scripts are also held to the target shell rules
(ASCII, none of printf, cut, $(...), grep -q, mkdir -p, test -e).
"""

import atexit
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
RESET = os.path.join(HERE, 'target-mode-reset.sh')
SAVE = os.path.join(HERE, 'target-cfgsave.sh')
SET = os.path.join(HERE, 'target-mode-set.sh')
# code -> (resolution index, format index) in tools/oracle/radeon_modeset.py's order
SET_CODES = {'800x600-888': (1, 0), '800x600-555': (1, 1), '800x600-256': (1, 2), '800x600-bw': (1, 3),
             '640x480-888': (0, 0), '1024x768-888': (2, 0), '1280x1024-888': (3, 0), '1600x1200-888': (4, 0)}


def _oracle():
    import importlib.util
    spec = importlib.util.spec_from_file_location('modesel_oracle_for_target', os.path.join(HERE, 'modesel_oracle.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m
TABLE = open(os.path.join(PROJ, 'OSRDNDisplay', 'Instance0.table')).read()
# G1 (2026-09-26): the shipped tables say 1024 x 768 RGB 32 (R3b-2b measured it on this machine);
# 800 x 600 was the R2b first-light mode, and every `fresh` install had been putting it back
GOOD_LINE = '"Display Mode" = "Height: 768 Width: 1024 Refresh: 60Hz ColorSpace: RGB:888/32";'
assert GOOD_LINE in TABLE, 'Instance0.table does not carry the mode this checker assumes'
OTHER = TABLE.replace(GOOD_LINE, '"Display Mode" = "Height: 600 Width: 800 Refresh: 60Hz ColorSpace: RGB:555/16";')
FORBIDDEN = [(r'\bprintf\b', 'printf'), (r'\bcut\b', 'cut'), (r'\$\(', '$('), (r'grep\s+-q', 'grep -q'),
             (r'mkdir\s+-p', 'mkdir -p'), (r'\btest\s+-e\b|\[\s+-e\b', 'test -e')]


def lint(path):
    p = []
    data = open(path, 'rb').read()
    if any(b > 0x7e or (b < 0x20 and b not in (9, 10)) for b in data):
        p.append('non-ASCII byte')
    code = '\n'.join(l for l in data.decode().split('\n') if not l.lstrip().startswith('#'))
    for rx, name in FORBIDDEN:
        if re.search(rx, code):
            p.append('uses %s' % name)
    r = subprocess.run(['sh', '-n', path], capture_output=True, text=True)
    if r.returncode != 0:
        p.append('sh -n: ' + r.stderr.strip())
    return p


def tree(root, table=OTHER, extra=(), mode=0o644):
    d = os.path.join(root, 'drv', 'OSRDNDisplay.config')
    os.makedirs(d)
    t = os.path.join(d, 'Instance0.table')
    open(t, 'w').write(table)
    os.chmod(t, mode)
    open(os.path.join(d, 'Default.table'), 'w').write(TABLE)
    for name in extra:
        open(os.path.join(d, name), 'w').write(TABLE)
    return t


def run(script, args, root):
    env = dict(os.environ, R3_DRV=os.path.join(root, 'drv'), R3_SAVE=os.path.join(root, 'save'),
               R3_TMP=root, R3_OUT=os.path.join(root, 'out', 'cfg'))
    r = subprocess.run(['sh', script] + args, capture_output=True, text=True, env=env, timeout=60)
    return r.returncode, r.stdout + r.stderr


RESET_MUTATIONS = [
    ('an Instance1 is not refused', 'if [ "$others" != "0" ]; then fail', 'if [ "$others" = "x" ]; then fail'),
    ('two Display Mode lines are not refused', 'if [ "$n" != "1" ]; then fail "Instance0.table must',
     'if [ "$n" = "x" ]; then fail "Instance0.table must'),
    ('the old table is not saved', 'cp $TABLE $SAVE/Instance0.table.$k ||', 'true ||'),
    ('the save overwrites the first copy', 'while [ -f $SAVE/Instance0.table.$k ]; do', 'while false; do'),
    ('closed=yes is not required', 'if [ "$CLOSED" != "closed=yes" ]; then', 'if false; then'),
]


def mutations(work):
    """Each defect put into target-mode-reset.sh must make one case above fail."""
    fails = 0
    text = open(RESET).read()
    for n, (label, old, new) in enumerate(RESET_MUTATIONS):
        if text.count(old) != 1:
            print('  FAIL mutation %-40s anchor found %d times' % (label, text.count(old)))
            fails += 1
            continue
        mpath = os.path.join(work, 'mut%d.sh' % n)
        open(mpath, 'w').write(text.replace(old, new))
        caught = False
        for k, (kw, args, want_rc, want) in enumerate([
                ({}, [], 2, 'usage'),
                (dict(extra=['Instance1.table']), ['closed=yes'], 1, 'other than Instance0'),
                (dict(table=OTHER + GOOD_LINE + '\n'), ['closed=yes'], 1, 'must hold exactly one')]):
            root = os.path.join(work, 'mut%d-%d' % (n, k))
            tree(root, **kw)
            rc, out = run(mpath, args, root)
            # the refusal must be the one this case is about, not a later check's
            caught = caught or rc != want_rc or want not in out
        root = os.path.join(work, 'mut%d-twice' % n)
        tree(root)
        run(mpath, ['closed=yes'], root)
        run(mpath, ['closed=yes'], root)
        saved = sorted(os.listdir(os.path.join(root, 'save'))) if os.path.isdir(os.path.join(root, 'save')) else []
        caught = caught or saved != ['Instance0.table.0', 'Instance0.table.1'] or \
            open(os.path.join(root, 'save', 'Instance0.table.0')).read() != OTHER
        print('  %-4s mutation %-40s %s' % ('ok' if caught else 'FAIL', label, 'caught' if caught else 'NOT CAUGHT'))
        fails += 0 if caught else 1
    return fails


def set_cases(work):
    """target-mode-set.sh: every code writes the oracle's string for its
    combination, and nothing else; the refusals are the reset script's."""
    oracle = _oracle()
    lines = oracle.display_modes_lines()
    fails = 0
    for code, (r, f) in sorted(SET_CODES.items()):
        root = os.path.join(work, 'set-' + code)
        t = tree(root, table=TABLE)
        before = open(t).read()
        rc, out = run(SET, ['closed=yes', code], root)
        after = open(t).read()
        want = '"Display Mode" = "%s";' % lines[r * 4 + f]
        pick = oracle.choose(lines[r * 4 + f])
        diff = [(x, y) for x, y in zip(before.split('\n'), after.split('\n')) if x != y]
        # 1024x768-888 is the table's own mode (G1): setting it changes nothing
        ok = rc == 0 and 'MODESET DONE' in out and (pick['res'], pick['fmt']) == (r, f) and \
            after.count('"Display Mode"') == 1 and want in after.split('\n') and \
            (len(diff) == 1 or (len(diff) == 0 and code == '1024x768-888')) and \
            len(before.split('\n')) == len(after.split('\n'))
        print('  %-4s set %-14s rc=%d' % ('ok' if ok else 'FAIL', code, rc))
        if not ok:
            print('       ' + out.replace('\n', '\n       ')[-400:])
        fails += 0 if ok else 1
    for label, kw, args, want_rc, want in [
            ('set: unknown code', {}, ['closed=yes', '1024x768-555'], 2, 'usage'),
            ('set: no code', {}, ['closed=yes'], 2, 'usage'),
            ('set: Configure not said closed', {}, ['1024x768-888'], 2, 'usage'),
            ('set: an Instance1 exists', dict(extra=['Instance1.table']), ['closed=yes', '1024x768-888'], 1,
             'other than Instance0'),
            ('set: two Display Mode lines', dict(table=OTHER + GOOD_LINE + '\n'), ['closed=yes', '640x480-888'], 1,
             'must hold exactly one')]:
        root = os.path.join(work, 'set-' + label.split(': ')[1].replace(' ', '-'))
        t = tree(root, **kw)
        before = open(t).read()
        rc, out = run(SET, args, root)
        ok = rc == want_rc and want in out and open(t).read() == before
        print('  %-4s %-40s rc=%d' % ('ok' if ok else 'FAIL', label, rc))
        fails += 0 if ok else 1
    return fails


def main():
    fails = 0
    for path in (RESET, SAVE, SET):
        p = lint(path)
        print('  %-4s lint %s %s' % ('FAIL' if p else 'ok', os.path.basename(path), p or ''))
        fails += 1 if p else 0

    work = tempfile.mkdtemp(prefix='r3target.', dir=os.environ.get('TMPDIR'))
    atexit.register(shutil.rmtree, work, True)  # 2026-09-24: /tmp reached 35.6 GiB of our scratch
    cases = [
        ('reset: good', {}, ['closed=yes'], 0, 'MODERESET DONE'),
        ('reset: Configure not said closed', {}, [], 2, 'usage'),
        ('reset: an Instance1 exists', dict(extra=['Instance1.table']), ['closed=yes'], 1, 'other than Instance0'),
        ('reset: two Display Mode lines', dict(table=OTHER + GOOD_LINE + '\n'), ['closed=yes'], 1, 'exactly one'),
        ('reset: the sed would touch another line', dict(table=OTHER + '"Display Mode" = x;\n'.replace('"Display Mode"', ' "Display Mode"')),
         ['closed=yes'], 0, 'MODERESET DONE'),
        ('reset: no Display Mode line', dict(table=OTHER.replace(OTHER.split('\n')[[i for i, l in enumerate(OTHER.split('\n')) if l.startswith('"Display Mode"')][0]] + '\n', '')),
         ['closed=yes'], 1, 'exactly one'),
    ]
    for n, (label, kw, args, want_rc, want) in enumerate(cases):
        root = os.path.join(work, 'r%d' % n)
        t = tree(root, **kw)
        before = open(t).read()
        rc, out = run(RESET, args, root)
        after = open(t).read()
        ok = rc == want_rc and want in out
        if want_rc == 0:
            lines_b, lines_a = before.split('\n'), after.split('\n')
            diff = [i for i, (x, y) in enumerate(zip(lines_b, lines_a)) if x != y]
            ok = ok and len(lines_b) == len(lines_a) and len(diff) == 1 and lines_a[diff[0]] == GOOD_LINE
            ok = ok and stat.S_IMODE(os.stat(t).st_mode) == 0o644
            ok = ok and open(os.path.join(root, 'save', 'Instance0.table.0')).read() == before
        else:
            ok = ok and after == before
        print('  %-4s %-40s rc=%d' % ('ok' if ok else 'FAIL', label, rc))
        if not ok:
            print('       ' + out.replace('\n', '\n       ')[-600:])
        fails += 0 if ok else 1

    # a second good reset keeps the first saved copy
    root = os.path.join(work, 'twice')
    t = tree(root)
    run(RESET, ['closed=yes'], root)
    rc, out = run(RESET, ['closed=yes'], root)
    ok = rc == 0 and os.path.exists(os.path.join(root, 'save', 'Instance0.table.1')) and \
        open(os.path.join(root, 'save', 'Instance0.table.0')).read() == OTHER
    print('  %-4s %-40s rc=%d' % ('ok' if ok else 'FAIL', 'reset: twice keeps both saved copies', rc))
    fails += 0 if ok else 1

    root = os.path.join(work, 'save1')
    tree(root, extra=['Instance1.table'])
    rc, out = run(SAVE, ['before-1024'], root)
    got = os.path.join(root, 'out', 'cfg', 'before-1024')
    sums = open(os.path.join(got, 'sums')).read().split('\n') if rc == 0 else []
    ok = rc == 0 and 'CFGSAVE DONE' in out and '3 tables' in out and \
        sorted(f for f in os.listdir(got) if f.endswith('.table')) == \
        ['Default.table', 'Instance0.table', 'Instance1.table'] and \
        len([l for l in sums if l.strip()]) == 3 and \
        [l.split()[:2] for l in sums if l.strip()] == \
        [l.split()[:2] for l in open(os.path.join(got, 'sums.copy')).read().split('\n') if l.strip()]
    print('  %-4s %-40s rc=%d' % ('ok' if ok else 'FAIL', 'cfgsave: good, every table copied', rc))
    fails += 0 if ok else 1
    for label, args, want_rc, want in [('cfgsave: the tag exists', ['before-1024'], 1, 'exists already'),
                                       ('cfgsave: a bad tag', ['../x'], 1, 'letters, digits'),
                                       ('cfgsave: no tag', [], 2, 'usage')]:
        rc, out = run(SAVE, args, root)
        ok = rc == want_rc and want in out
        print('  %-4s %-40s rc=%d' % ('ok' if ok else 'FAIL', label, rc))
        fails += 0 if ok else 1

    fails += set_cases(work)
    fails += mutations(work)
    print('check_target_r3: %s' % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
