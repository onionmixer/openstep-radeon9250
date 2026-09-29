#!/usr/bin/env python3
"""Pack OSRDNDisplay (R2b, the first mode set) and its user tool for a target build.

  pack_r2b0.py [--runid N] [--out-dir DIR] [--skip-hostcheck]
        write build/r2b0/OSRDNDisplay-<stamp>-<runid>.tar

The tar holds OSRDNDisplay/ (the bundle project), rdnr2b0.m, PROVENANCE,
BUILD_STAMP, RUNID and MANIFEST under the top directory OSRDNDisplay-r2b0/.
The stamp is the first 32 bits of a SHA-256 over every packed file,
PROVENANCE included -- which names the R2b-0, R2a and R1 runs and R1c's
capture (docs/R2B_IMPL_PLAN.md, docs/R2B0_IMPL_PLAN.md 3, R2 plan 6), so a
stamp also says which measurements the build was reviewed against.  The
target-side names stay r2b0: this is the same pipeline (build, install,
reloc gate, run, restore), carrying a build that now sets the mode.  The run id is the one the
record will run under.

Steps and reasons as tools/r2a/pack_probe.py (whose R1 helpers are imported):
hostcheck-r2b0 must pass first, members get a fixed non-zero mtime, paths
stay under 100 characters, every file is ASCII.
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
BUNDLE = os.path.join(PROJ, 'OSRDNDisplay')
TOOL = os.path.join(HERE, 'rdnr2b0.m')
R4TOOLS = [os.path.join(os.path.dirname(HERE), 'r4', n) for n in ('rdnr4map.m', 'r4map_want.c')]   # R4c
R4TOOLS += [os.path.join(os.path.dirname(HERE), 'r5', 'rdnr5cp.m')]                                  # R5
R4TOOLS += [os.path.join(os.path.dirname(HERE), 'r7', 'rdnr7sub.m')]                                 # R7a
R4TOOLS += [os.path.join(os.path.dirname(HERE), 'r7', 'rdnr7dev.c')]                                 # R7b
# M1a: the acceleration gate and the two C-only clients that exercise it.  The
# probe unit itself ships in the library later; it is packed now because the
# target test programs compile it (docs/M1A_PLAN.md 5).
R4TOOLS += [os.path.join(PROJ, 'mesa', n) for n in ('OSRDNMesaProbe.c', 'OSRDNMesaProbe.h')]
R4TOOLS += [os.path.join(PROJ, 'test', n)
            for n in ('osrdn-mesa-probe-test.c', 'osrdn-caps-client.c')]
OUT_DIR = os.path.join(PROJ, 'build', 'r2b0')
TOP = 'OSRDNDisplay-r2b0'
PROVENANCE = """R2b-0 run 789526262 log sha256 132e60c24471010e (build/r2b0/789526262/rdn-r2b0-789526262.log)
R2a run 789467668 log sha256 e97c433f28e14a5e (build/r2a/789467668/rdn-r2a-789467668.log)
R1 run 789453017 log sha256 3ede696609722b72 (build/r1/rdn-r1-789453017.log)
R1c capture sha256 7124ae93f71ea1497b4bc01b8623ae41a4916f4033aa4cf108f466a5ce7ada8c (docs/R1C_RESULT.md 50)
plan docs/R2B_IMPL_PLAN.md (first mode set); it carries docs/R2B0_IMPL_PLAN.md revision 2
mode osrdn_mode_expect.h from tools/oracle/radeon_modeset.py via tools/r2b/gen_expect_r2b.py
verdict docs/review/Q13_verdict.md
R3b-2c docs/R3_MULTIMODE_PLAN.md 24-14/24-15 (the FIFO request fields keep only multiples of 4, measured boot fa2dcdbd)
R3d docs/R3_MULTIMODE_PLAN.md 25/26 (Configure inspector; nib derived from Configure.app's own, stock sha256 380bb6ed)
R4 docs/R4_ENGINE_PLAN.md 12-15 (2D engine fill/blit over MMIO, alias at the Matrox window start, MMIO map 0x4000)
R4c docs/R4C_VMAP_PLAN.md 11-12 (character device d_mmap over the Matrox window to 124 MiB, UBLIT, tool rdnr4map)
R5 docs/R5_PLAN.md 8-9 (CP microcode, PCI GART ring in an IOMallocLow block, engine reset, markers; tool rdnr5cp)
"""

# The one member that is not ASCII: the inspector's archived nib
# (docs/R3_MULTIMODE_PLAN.md 26-5).  One path, not a pattern; it is hashed
# into the stamp and MANIFEST like every other file, and a listed path that
# is missing fails the pack, so the list cannot go stale.
BINARY_MEMBERS = ('OSRDNDisplay/English.lproj/DisplayInspector.nib/data.nib',)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


r1 = _load('pack_r1_for_r2b0', os.path.join(PROJ, 'tools', 'r1', 'pack_probe.py'))


def check_provenance():
    """The log hashes in PROVENANCE are the files' own."""
    for rel, want in (('build/r2b0/789526262/rdn-r2b0-789526262.log', '132e60c24471010e'),
                      ('build/r2a/789467668/rdn-r2a-789467668.log', 'e97c433f28e14a5e'),
                      ('build/r1/rdn-r1-789453017.log', '3ede696609722b72')):
        got = hashlib.sha256(open(os.path.join(PROJ, rel), 'rb').read()).hexdigest()[:16]
        if got != want:
            sys.exit('PROVENANCE names %s as %s, the file is %s' % (rel, want, got))


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
    check_provenance()

    if not a.skip_hostcheck:
        r = subprocess.run(['sh', os.path.join(HERE, 'hostcheck.sh')], capture_output=True, text=True)
        if r.returncode != 0 or '\nhostcheck-r2b0: PASS\n' not in r.stdout:
            sys.stdout.write(r.stdout[-3000:])
            sys.exit('hostcheck-r2b0 did not pass: nothing packed')
        print('hostcheck-r2b0: PASS')

    stage = tempfile.mkdtemp(prefix='pack_r2b0.', dir=os.environ.get('TMPDIR'))
    top = os.path.join(stage, TOP)
    os.makedirs(top)
    shutil.copytree(BUNDLE, os.path.join(top, 'OSRDNDisplay'), ignore=shutil.ignore_patterns(
        '*.config', 'i386_obj', 'sym', '*.o', '*.d', '.DS_Store', '.lastBuildTime',
        '__pycache__', '*.pyc'))
    shutil.copyfile(TOOL, os.path.join(top, 'rdnr2b0.m'))
    for f in R4TOOLS:
        shutil.copyfile(f, os.path.join(top, os.path.basename(f)))
    open(os.path.join(top, 'PROVENANCE'), 'w').write(PROVENANCE)

    files = r1.tree_files(top)
    for rel in BINARY_MEMBERS:
        if rel not in files:
            sys.exit('%s is listed as the binary member but is not packed' % rel)
    for rel in files:
        if rel in BINARY_MEMBERS:
            continue
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
    name = 'OSRDNDisplay-%s-%d.tar' % (stamp, a.runid)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w', format=tarfile.USTAR_FORMAT) as t:
        rels = sorted(r1.tree_files(top) + list(r1.META))
        dirs = sorted({os.path.dirname(os.path.join(TOP, r)) for r in rels} | {TOP})
        dirs = sorted(set(d for x in dirs for d in [os.path.join(*x.split('/')[:k + 1]) for k in range(len(x.split('/')))]))
        for path in dirs + [os.path.join(TOP, r) for r in rels]:
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

    s = r1.bsdsum(data)
    print('packed   %s' % out)
    print('stamp    %s' % stamp)
    print('runid    %d' % a.runid)
    print('sum      %s' % s)
    print()
    rel = os.path.relpath(out, PROJ)
    where = ('/ndrv/openstep-radeon9250/' + rel) if not rel.startswith('..') else '<target copy of %s>' % name
    print('on the target (sh):')
    print('  sh /ndrv/openstep-radeon9250/tools/r2b0/target-build-r2b0.sh %s %s %s' % (where, s.split()[0], s.split()[1]))
    print('then on the host:')
    print('  python3 tools/r2b0/check_reloc_r2b0.py build/r2b0/%d/OSRDNDisplay_reloc <sum> <blocks> --marker build/r2b0/%d'
          % (a.runid, a.runid))
    print('then docs/R2B0_IMPL_PLAN.md section 9 steps 3 onward')
    return 0


if __name__ == '__main__':
    sys.exit(main())
