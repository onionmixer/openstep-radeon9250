#!/usr/bin/env python3
"""Pack the R1 probe for a target build, with a build stamp and a run id.

  pack_probe.py [--runid N]      write build/r1/RDNR1Probe-<stamp>-<runid>.tar

Steps, and why each is here:

  1. tools/r1/hostcheck.sh must PASS first -- a tree that fails the host gate
     is never packed.
  2. The probe tree is copied to a stage and Load_Commands.sect is generated
     from Load_Commands.sect.in with the run id (a positive decimal below
     2**31, since the probe takes it as an int).  The template itself is not
     packed, so there is exactly one load-command file in the tar.
  3. The stamp is the first 32 bits of SHA-256 over the staged tree (each
     file's relative path and bytes, in sorted order), excluding the two
     metadata files below.  The target build passes it as -DR1_BUILD=0x<stamp>
     and the probe prints it on its first line, so the log names the tree it
     came from (PLAN section 4 provenance chain: source -> build -> log).
  4. BUILD_STAMP and RUNID are written into the tar root for the target
     scripts; MANIFEST lists every file's SHA-256.
  5. The tar's BSD `sum' (the algorithm of the target's /usr/bin/sum, checked
     here against the value recorded on the target for a known file) is
     printed; target-build.sh refuses a tar whose sum differs.

The run id defaults to the current Unix time modulo 10**9: distinct per pack,
so a stale run's lines in the same syslog cannot be read as this run's.
"""

import argparse
import hashlib
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
WS = os.path.dirname(PROJ)
PROBE_DIR = os.path.join(PROJ, 'probe', 'RDNR1Probe')
OUT_DIR = os.path.join(PROJ, 'build', 'r1')
META = ('BUILD_STAMP', 'RUNID', 'MANIFEST')
PACK_MTIME = 946684800              # 2000-01-01 00:00:00 UTC


def bsdsum(data):
    """BSD sum: 16-bit rotating checksum, 1024-byte blocks."""
    s = 0
    for b in data:
        s = (s >> 1) + ((s & 1) << 15)
        s = (s + b) & 0xffff
    return '%05d %d' % (s, (len(data) + 1023) // 1024)


def bsdsum_self_check():
    # recorded on the target: MatroxMGA_reloc 104788 bytes, `sum' = 45628 103
    # (openstep-matrox-remade/docs/R2_ORIGINAL_BINARY_CONFIGURATION_AUDIT.md:14)
    ref = os.path.join(WS, 'openstep-matrox-remade', 'reference', 'original-binaries',
                       'MatroxMGA_reloc.R0-20260818')
    assert bsdsum(b'test\n') == '41076 1'
    if os.path.exists(ref):
        got = bsdsum(open(ref, 'rb').read())
        if got != '45628 103':
            sys.exit('bsdsum disagrees with the target record: %s' % got)


def tree_files(root):
    out = []
    for d, dirs, files in os.walk(root):
        dirs.sort()
        for f in sorted(files):
            rel = os.path.relpath(os.path.join(d, f), root)
            if rel not in META:
                out.append(rel)
    return sorted(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--runid', type=int, default=int(time.time()) % 10**9)
    ap.add_argument('--out-dir', default=OUT_DIR)
    ap.add_argument('--skip-hostcheck', action='store_true',
                    help='for testing this script only; the tar is marked UNCHECKED')
    a = ap.parse_args()
    if not 0 < a.runid < 2**31:
        sys.exit('runid must be in 1..2**31-1')
    bsdsum_self_check()

    if not a.skip_hostcheck:
        r = subprocess.run(['sh', os.path.join(HERE, 'hostcheck.sh')], capture_output=True, text=True)
        if r.returncode != 0 or 'hostcheck: PASS' not in r.stdout:
            sys.stdout.write(r.stdout[-3000:])
            sys.exit('hostcheck did not pass: nothing packed')
        print('hostcheck: PASS')

    stage = tempfile.mkdtemp(prefix='pack_r1.', dir=os.environ.get('TMPDIR'))
    top = os.path.join(stage, 'RDNR1Probe')
    shutil.copytree(PROBE_DIR, top, ignore=shutil.ignore_patterns(
        '*.config', 'i386_obj', 'sym', '*.o', '*.d', '.DS_Store'))
    reloc = os.path.join(top, 'RDNR1Probe_reloc.tproj')
    tmpl = os.path.join(reloc, 'Load_Commands.sect.in')
    text = open(tmpl).read()
    if text.count('@RUNID@') != 1 or text.count('\nCALL radeonR1Entry @RUNID@\n') != 1:
        sys.exit('Load_Commands.sect.in must hold the placeholder once, in the CALL line')
    open(os.path.join(reloc, 'Load_Commands.sect'), 'w').write(text.replace('@RUNID@', str(a.runid)))
    os.remove(tmpl)

    # every packed file must be ASCII: the target's tools choke on high bytes
    files = tree_files(top)
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
    name = 'RDNR1Probe-%s-%d.tar' % (stamp, a.runid)
    buf = io.BytesIO()
    # old-style ustar, short paths: the target's tar is old (100-char names)
    # every directory gets its own entry ahead of its files: an old tar may
    # not create intermediate directories
    with tarfile.open(fileobj=buf, mode='w', format=tarfile.USTAR_FORMAT) as t:
        rels = sorted(tree_files(top) + list(META))
        dirs = sorted({os.path.dirname(os.path.join('RDNR1Probe', r)) for r in rels} |
                      {'RDNR1Probe'})
        for path in dirs + [os.path.join('RDNR1Probe', r) for r in rels]:
            if len(path) >= 100:
                sys.exit('path too long for the target tar: %s' % path)
            src = os.path.join(stage, path)
            info = t.gettarinfo(src, arcname=path)
            info.uid = info.gid = 0
            info.uname = info.gname = ''
            # a fixed, nonzero, past time: the target's make treats a zero
            # mtime as "file does not exist" ("Don't know how to make
            # RDNR1Probe.m", first target build 2026-09-15), and the target
            # clock is years behind the host, so the pack time would be future
            info.mtime = PACK_MTIME
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
    print('on the target (sh):')
    rel = os.path.relpath(out, PROJ)
    where = ('/ndrv/openstep-radeon9250/' + rel) if not rel.startswith('..') else '<target copy of %s>' % name
    print('  sh /ndrv/openstep-radeon9250/tools/r1/target-build.sh %s %s %s' % (where, s.split()[0], s.split()[1]))
    print('  sh /ndrv/openstep-radeon9250/tools/r1/target-run.sh')
    print('then on the host:')
    print('  python3 tools/r1/parse_r1.py <fetched log> %d %s' % (a.runid, stamp))
    return 0


if __name__ == '__main__':
    sys.exit(main())
