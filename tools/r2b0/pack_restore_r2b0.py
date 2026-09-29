#!/usr/bin/env python3
"""Build the restore set for /me from a checked "pre" snapshot (docs/R2B0_IMPL_PLAN.md 7-2).

  pack_restore_r2b0.py <tag> [--root DIR]

Reads build/r2b0/cfg/<tag>/pre/ (it must hold PRECHECK_PASS, written by
check_cfgdiff.py precheck) and writes build/r2b0/restore/<tag>/, which must
not exist:
  set/<bundle>.config/InstanceN.table   every instance table of the snapshot
  manifest   <rel> <octal mode> <ls mode> <owner> <group> <sum> <blocks> <bytes>
  restore.sh, check.sh                  copied from tools/r2b0/me/
  SUMS       "<name> <sum> <blocks>" for manifest, restore.sh, check.sh
System.config/Default.table is not in the set: the restore never writes it
(check_cfgdiff.py stops if Configure changed it).

target-stage-restore-r2b0.sh copies this to /me/rdn-r2b0 and checks every
sum; restore.sh checks the set again before it writes.
"""

import importlib.util
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


cd = _load('check_cfgdiff_for_pack', os.path.join(HERE, 'check_cfgdiff.py'))


def octal(ls):
    """'-rw-r--r--' -> '644' (no setuid/setgid/sticky: the snapshot refuses those)."""
    if not re.fullmatch(r'-[r-][w-][x-][r-][w-][x-][r-][w-][x-]', ls):
        raise ValueError('mode %r' % ls)
    v = 0
    for i, ch in enumerate(ls[1:]):
        if ch != '-':
            v |= 1 << (8 - i)
    return '%o' % v


def pack(root, tag):
    if not re.fullmatch(r'[A-Za-z0-9-]+', tag):
        raise ValueError('tag %r' % tag)
    pre = os.path.join(root, 'build', 'r2b0', 'cfg', tag, 'pre')
    out = os.path.join(root, 'build', 'r2b0', 'restore', tag)
    if not os.path.exists(os.path.join(pre, 'PRECHECK_PASS')):
        raise ValueError('%s has no PRECHECK_PASS: run check_cfgdiff.py precheck first' % pre)
    if os.path.exists(out):
        raise ValueError('%s exists: a restore set is never rewritten' % out)
    snap = cd.load_snap(pre)
    inst = cd.instances(snap)
    if 'System.config/Instance0.table' not in inst:
        raise ValueError('the snapshot has no System.config/Instance0.table')
    os.makedirs(os.path.join(out, 'set'))
    lines = []
    for rel in sorted(inst):
        v = inst[rel]
        os.makedirs(os.path.join(out, 'set', os.path.dirname(rel)), exist_ok=True)
        open(os.path.join(out, 'set', rel), 'wb').write(v['data'])
        s = cd.pk.bsdsum(v['data']).split()
        lines.append('%s %s %s %s %s %s %s %d' % (rel, octal(v['ls']), v['ls'], v['owner'], v['group'], s[0], s[1],
                                                  len(v['data'])))
    open(os.path.join(out, 'manifest'), 'w').write('\n'.join(lines) + '\n')
    sums = []
    for name in ('restore.sh', 'check.sh'):
        shutil.copyfile(os.path.join(HERE, 'me', name), os.path.join(out, name))
    for name in ('manifest', 'restore.sh', 'check.sh'):
        data = open(os.path.join(out, name), 'rb').read()
        if any(b > 0x7e or (b < 0x20 and b not in (9, 10)) for b in data):
            raise ValueError('non-ASCII byte in %s' % name)
        sums.append('%s %s' % (name, cd.pk.bsdsum(data)))
    open(os.path.join(out, 'SUMS'), 'w').write('\n'.join(sums) + '\n')
    return out, lines, sums


def main(argv):
    args = argv[1:]
    root = PROJ
    if '--root' in args:
        i = args.index('--root')
        root = args[i + 1]
        args = args[:i] + args[i + 2:]
    if len(args) != 1:
        print(__doc__)
        return 2
    try:
        out, lines, sums = pack(root, args[0])
    except (ValueError, cd.Refused) as e:
        print('pack_restore_r2b0: FAIL %s' % e)
        return 1
    print('restore set %s' % out)
    for l in lines:
        print('  ' + l)
    for s in sums:
        print('  SUMS ' + s)
    print('on the target (telnet, root):')
    print('  sh /ndrv/openstep-radeon9250/tools/r2b0/target-stage-restore-r2b0.sh %s' % args[0])
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
