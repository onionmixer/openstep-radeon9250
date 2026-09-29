#!/usr/bin/env python3
"""Pack the R2a probe for a target build, with a build stamp and a run id.

  pack_probe.py [--runid N]      write build/r2a/RDNR2aProbe-<stamp>-<runid>.tar

The steps and their reasons are tools/r1/pack_probe.py's, whose functions
(bsdsum and its target check, tree_files, the fixed member time) are imported
unchanged; only the names differ: probe/RDNR2aProbe, CALL radeonR2aEntry,
tools/r2a/hostcheck.sh as the gate, build/r2a as the output.
"""

import argparse
import hashlib
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
PROBE_DIR = os.path.join(PROJ, 'probe', 'RDNR2aProbe')
OUT_DIR = os.path.join(PROJ, 'build', 'r2a')
NAME = 'RDNR2aProbe'
ENTRY = 'radeonR2aEntry'


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


r1 = _load('pack_r1', os.path.join(PROJ, 'tools', 'r1', 'pack_probe.py'))
bsdsum = r1.bsdsum
META = r1.META


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--runid', type=int, default=int(time.time()) % 10**9)
    ap.add_argument('--out-dir', default=OUT_DIR)
    ap.add_argument('--skip-hostcheck', action='store_true',
                    help='for testing this script only; the tar is marked UNCHECKED')
    a = ap.parse_args()
    if not 0 < a.runid < 2**31:
        sys.exit('runid must be in 1..2**31-1')
    r1.bsdsum_self_check()

    if not a.skip_hostcheck:
        r = subprocess.run(['sh', os.path.join(HERE, 'hostcheck.sh')], capture_output=True, text=True)
        if r.returncode != 0 or '\nhostcheck-r2a: PASS\n' not in r.stdout:
            sys.stdout.write(r.stdout[-3000:])
            sys.exit('hostcheck did not pass: nothing packed')
        print('hostcheck-r2a: PASS')

    stage = tempfile.mkdtemp(prefix='pack_r2a.', dir=os.environ.get('TMPDIR'))
    top = os.path.join(stage, NAME)
    shutil.copytree(PROBE_DIR, top, ignore=shutil.ignore_patterns(
        '*.config', 'i386_obj', 'sym', '*.o', '*.d', '.DS_Store'))
    reloc = os.path.join(top, NAME + '_reloc.tproj')
    tmpl = os.path.join(reloc, 'Load_Commands.sect.in')
    text = open(tmpl).read()
    if text.count('@RUNID@') != 1 or text.count('\nCALL %s @RUNID@\n' % ENTRY) != 1:
        sys.exit('Load_Commands.sect.in must hold the placeholder once, in the CALL line')
    open(os.path.join(reloc, 'Load_Commands.sect'), 'w').write(text.replace('@RUNID@', str(a.runid)))
    os.remove(tmpl)

    files = r1.tree_files(top)
    for rel in files:
        data = open(os.path.join(top, rel), 'rb').read()
        if any(b > 0x7e or (b < 0x20 and b not in (9, 10)) for b in data):
            sys.exit('non-ASCII byte in %s' % rel)

    h = hashlib.sha256()
    manifest = []
    for rel in files:
        data = open(os.path.join(top, rel), 'rb').read()
        h.update(rel.encode() + b'\0' + len(data).to_bytes(8, 'little') + data)
        manifest.append('%s  %s' % (hashlib.sha256(data).hexdigest(), rel))
    stamp = h.hexdigest()[:8]
    if stamp == '00000000':
        sys.exit('stamp collides with the unstamped value; change a comment and repack')
    if a.skip_hostcheck:
        manifest.insert(0, 'UNCHECKED: packed with --skip-hostcheck')
    open(os.path.join(top, 'BUILD_STAMP'), 'w').write(stamp + '\n')
    open(os.path.join(top, 'RUNID'), 'w').write('%d\n' % a.runid)
    open(os.path.join(top, 'MANIFEST'), 'w').write('\n'.join(manifest) + '\n')

    os.makedirs(a.out_dir, exist_ok=True)
    name = '%s-%s-%d.tar' % (NAME, stamp, a.runid)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w', format=tarfile.USTAR_FORMAT) as t:
        rels = sorted(r1.tree_files(top) + list(META))
        dirs = sorted({os.path.dirname(os.path.join(NAME, r)) for r in rels} | {NAME})
        for path in dirs + [os.path.join(NAME, r) for r in rels]:
            if len(path) >= 100:
                sys.exit('path too long for the target tar: %s' % path)
            src = os.path.join(stage, path)
            info = t.gettarinfo(src, arcname=path)
            info.uid = info.gid = 0
            info.uname = info.gname = ''
            info.mtime = r1.PACK_MTIME
            if info.isdir():
                info.mode = 0o755
                t.addfile(info)
            else:
                info.mode = 0o644
                t.addfile(info, open(src, 'rb'))
    data = buf.getvalue()
    with tarfile.open(fileobj=io.BytesIO(data)) as t:
        zero = [m.name for m in t.getmembers() if m.mtime <= 0]
    if zero:
        sys.exit('tar members with a zero mtime (the target make cannot build them): %s' % zero)
    out = os.path.join(a.out_dir, name)
    open(out, 'wb').write(data)
    shutil.rmtree(stage)

    s = bsdsum(data)
    print('packed   %s' % out)
    print('stamp    %s' % stamp)
    print('runid    %d' % a.runid)
    print('sum      %s' % s)
    print()
    rel = os.path.relpath(out, PROJ)
    where = ('/ndrv/openstep-radeon9250/' + rel) if not rel.startswith('..') else '<target copy of %s>' % name
    print('on the target (sh, detached):')
    print('  sh /ndrv/openstep-radeon9250/tools/r2a/target-build.sh %s %s %s' % (where, s.split()[0], s.split()[1]))
    print('then on the host:')
    print('  python3 tools/r2a/check_reloc.py build/r2a/%d/RDNR2aProbe_reloc <sum> <blocks> --marker build/r2a/%d'
          % (a.runid, a.runid))
    print('then on the target (after tools/nx-logcatch.sh status on the host):')
    print('  nohup sh /ndrv/openstep-radeon9250/tools/r2a/target-run.sh < /dev/null > /tmp/rdn-r2a-run.out 2>&1 &')
    print('then on the host:')
    print('  python3 tools/r2a/parse_r2a.py build/r2a/%d/rdn-r2a-%d.log %d %s build/r1/rdn-r1-789453017.log 789453017'
          ' --out build/r2a/%d' % (a.runid, a.runid, a.runid, stamp, a.runid))
    return 0


if __name__ == '__main__':
    sys.exit(main())
