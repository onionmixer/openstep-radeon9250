#!/usr/bin/env python3
"""Run tools/r2a/target-build.sh and target-run.sh on the host, against fake target tools.

  check_target_r2a.py      lint + every case; exit 1 on any failure

As tools/r1/check_target_scripts.py (whose fake-tool pattern this follows),
with R2a's names and additions:

  lint   R1's forbidden constructs, R1c's target rules (no ps, no blank in an
         unquoted default), no set -- and no $1..$9 after the first function
         (the target sh does not restore them), ASCII; each rule and each
         real-target defect proven to fire by a mutation of the script text;
         the R2A_* override names equal the harness's
  build  a tree packed by tools/r2a/pack_probe.py: good (reloc copied to the
         fake NFS directory, copy sum equal, reloc.sum written, the NFS
         parent created when missing), and each broken case
  run    kl_util -l runs the R2a simulator built from the PACKED source with
         the PACKED stamp and run id; the log copied to NFS is judged by
         parse_r2a.py against an R1 log R1's simulator wrote for the same
         world -- pack -> build -> reloc marker -> load -> log -> parse, end to
         end; run.done must hold the final line on DONE and on every FAIL
         after the run id is known; the broken run cases

The fake `ps' records a call and fails: neither script may run it.  The fake
`cp' corrupts a copy into the NFS directory when FAKE_CP=corrupt.

What it cannot show: the target's own sh, make, nm, strings, kl_util and NFS.
"""

import importlib.util
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
SCRIPTS = ['target-build.sh', 'target-run.sh']


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


r1scripts = _load('check_target_scripts', os.path.join(PROJ, 'tools', 'r1', 'check_target_scripts.py'))
r1c = _load('check_target_r1c', os.path.join(PROJ, 'tools', 'r1c', 'check_target_r1c.py'))
sim = _load('sim_r2a', os.path.join(HERE, 'sim_r2a.py'))
p2 = sim.p2
s1 = sim.s1

ENV_NAMES = {
    'target-build.sh': ['R2A_TMP', 'R2A_SUM', 'R2A_KERNEL', 'R2A_NFSOUT'],
    'target-run.sh': ['R2A_TMP', 'R2A_KLUTIL', 'R2A_MSGS', 'R2A_RANDIR', 'R2A_SUM', 'R2A_SYSCFG', 'R2A_NFSOUT'],
}


def lint_text(name, text):
    bad = []
    data = text.encode('latin-1', 'replace')
    if any(b > 0x7e or (b < 0x20 and b not in (9, 10)) for b in data):
        bad.append('non-ASCII byte')
    for n, line in enumerate(text.splitlines(), 1):
        code = line if not line.lstrip().startswith('#') else ''
        for pat, what in r1scripts.FORBIDDEN:
            if re.search(pat, code):
                bad.append('line %d uses %s: %s' % (n, what, line.strip()))
        for pat, what, _ in r1c.TARGET_RULES:
            if re.search(pat, code):
                bad.append('line %d uses %s: %s' % (n, what, line.strip()))
    bad += r1c.positional_misuse(text)
    names = set(re.findall(r'\$\{(R2A_\w+):-', text))
    if names != set(ENV_NAMES[name]):
        bad.append('override names %s != harness %s' % (sorted(names), sorted(ENV_NAMES[name])))
    if re.search(r'\$\{R1C?_\w+', text):
        bad.append('an R1 override name in an R2a script')
    return bad


def lint():
    failures = 0
    texts = dict((n, open(os.path.join(HERE, n)).read()) for n in SCRIPTS)
    for n in SCRIPTS:
        bad = lint_text(n, texts[n])
        for b in bad:
            print('  FAIL %s: %s' % (n, b))
        failures += len(bad)
    if not failures:
        print('  ok   both scripts: ASCII, no forbidden construct, no ps, no set --, overrides as the harness')
    muts = [
        ('target-run.sh', 'ps put back', 'echo "=== 1. ready to load ==="\n',
         'echo "=== 1. ready to load ==="\nn=`ps ax | grep nxlogd | wc -l`\n', 'ps ('),
        ('target-run.sh', 'blank in a default', 'KLUTIL=${R2A_KLUTIL:-/usr/etc/kl_util}',
         'KLUTIL=${R2A_KLUTIL:-/usr/etc/kl_util /etc/kl_util}', 'bad substitution'),
        ('target-build.sh', 'set -- put back', 'GOTSUM=`$SUM "$TAR" | awk \'{print $1}\'`',
         'got=`$SUM "$TAR"`\nset -- $got\nGOTSUM=$1', 'set --'),
        ('target-run.sh', '$1 after a function', 'RS1=`$SUM $RELOC | awk \'{print $1}\'`',
         'RS1=`$SUM $RELOC`\nRS1="$1"', 'positional parameter'),
        ('target-build.sh', '$(...)', 'STAMP=`cat $TOP/BUILD_STAMP`', 'STAMP=$(cat $TOP/BUILD_STAMP)', '$(...)'),
        ('target-run.sh', 'unlisted override', 'NFSOUT=${R2A_NFSOUT:-/ndrv/openstep-radeon9250/build/r2a}',
         'NFSOUT=${R2A_NFS:-/ndrv/openstep-radeon9250/build/r2a}', 'override names'),
    ]
    for name, label, old, new, want in muts:
        if texts[name].count(old) != 1:
            print('  FAIL lint mutation %r: anchor found %d times' % (label, texts[name].count(old)))
            failures += 1
            continue
        bad = lint_text(name, texts[name].replace(old, new))
        ok = any(want in b for b in bad)
        print('  %-4s lint mutation %-22s %s' % ('ok' if ok else 'FAIL', label, bad[:1] if ok else 'not caught'))
        failures += 0 if ok else 1
    return failures


def write_exe(path, text):
    open(path, 'w').write(text)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


KERNEL_SYMS = ['IODelay', 'IOLog', 'IOMapPhysicalIntoIOTask', 'IOSleep', 'IOUnmapPhysicalFromIOTask', 'sprintf',
               'splhigh', 'splx']


def fake_tools(bindir):
    os.makedirs(bindir)
    write_exe(os.path.join(bindir, 'sum'), '''#!/usr/bin/env python3
import sys
sys.path.insert(0, %r)
from pack_probe import bsdsum
print(bsdsum(open(sys.argv[1], 'rb').read()), sys.argv[1])
''' % os.path.join(PROJ, 'tools', 'r1'))
    write_exe(os.path.join(bindir, 'make'), r'''#!/bin/sh
mode=${FAKE_MAKE:-good}
cflags="$1"
echo "fake make $cflags"
[ "$mode" = noproduct ] && exit 0
mkdir -p RDNR2aProbe.config
/bin/cp Default.table RDNR2aProbe.config/Default.table
echo '"Server Name" = "RDNR2aProbe";' >> RDNR2aProbe.config/Default.table
r=RDNR2aProbe.config/RDNR2aProbe_reloc
{ printf '\376\355\372\316junk\000'; grep -v '^#' RDNR2aProbe_reloc.tproj/Load_Commands.sect | tr '\n' '\000'
  [ "$mode" = advertise ] && printf 'ADVERTISE RDNR2aProbe\000'
  printf '%s\000' "$cflags"; } > $r
printf 'IODelay\nIOLog\nIOMapPhysicalIntoIOTask\nIOSleep\nIOUnmapPhysicalFromIOTask\nsprintf\nsplhigh\nsplx\n' > $r.syms
[ "$mode" = missing ] && echo IOPanicNotExported >> $r.syms
echo "$cflags" > $r.cflags
exit 0
''')
    write_exe(os.path.join(bindir, 'nm'), r'''#!/bin/sh
if [ "$1" = "-u" ]; then sed 's/^/         /' "$2.syms"; exit 0; fi
for s in %s; do echo "00001000 T $s"; done
''' % ' '.join(KERNEL_SYMS))
    write_exe(os.path.join(bindir, 'kl_util'), r'''#!/bin/sh
mode=${FAKE_KL:-good}
echo "kl_util $*" >> "$R2A_TMP/kl_util.calls"
case "$1" in
  -a) [ "$mode" = addfail ] && exit 1; exit 0 ;;
  -l) if [ "$mode" = hang ]; then touch "$R2A_TMP/kl_hanging"; sleep 30; exit 0; fi
      "$FAKE_SIM" < "$FAKE_WORLD" > "$R2A_TMP/sim.out" 2> "$R2A_TMP/sim.err"
      if [ "$mode" = noend ]; then grep -v ' end lines=' "$R2A_TMP/sim.out" >> "$R2A_MSGS"
      else cat "$R2A_TMP/sim.out" >> "$R2A_MSGS"; fi
      exit 0 ;;
  -u) [ "$mode" = unloadfail ] && exit 1; exit 0 ;;
  *) exit 0 ;;
esac
''')
    write_exe(os.path.join(bindir, 'ps'), '#!/bin/sh\necho "ps $*" >> "$R2A_TMP/ps.calls"\nexit 1\n')
    write_exe(os.path.join(bindir, 'cp'), r'''#!/bin/sh
/bin/cp "$@" || exit $?
if [ "${FAKE_CP:-good}" = corrupt ]; then
  for last; do :; done
  case "$last" in *nfs*) echo junk >> "$last" ;; esac
fi
exit 0
''')


def run_sh(script, args, env, cwd, timeout=120):
    r = subprocess.run(['/bin/sh', os.path.join(HERE, script)] + args, env=env, cwd=cwd,
                       capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout + r.stderr


def main():
    failures = 0
    print('== lint ==')
    failures += lint()

    work = tempfile.mkdtemp(prefix='chk_target_r2a.', dir=os.environ.get('TMPDIR'))
    bindir = os.path.join(work, 'bin')
    fake_tools(bindir)
    runid = 434343
    pk = subprocess.run([sys.executable, os.path.join(HERE, 'pack_probe.py'), '--skip-hostcheck',
                         '--runid', str(runid), '--out-dir', os.path.join(work, 'out')],
                        capture_output=True, text=True, env=dict(os.environ, TMPDIR=work))
    if pk.returncode != 0:
        print(pk.stdout, pk.stderr)
        print('check_target_r2a: FAIL (pack)')
        return 1
    tarpath = re.search(r'packed\s+(\S+)', pk.stdout).group(1)
    stamp = re.search(r'stamp\s+(\S+)', pk.stdout).group(1)
    unchecked = (tarpath,) + tuple(re.search(r'sum\s+(\d+) (\d+)', pk.stdout).groups())

    def pack_sum(path):
        s = subprocess.run([os.path.join(bindir, 'sum'), path], capture_output=True, text=True).stdout.split()
        return s[0], s[1]

    # a copy without the UNCHECKED line for every case but the one that tests it
    checked = os.path.join(work, 'checked.tar')
    with tarfile.open(tarpath) as src, tarfile.open(checked, 'w', format=tarfile.USTAR_FORMAT) as dst:
        for m in src.getmembers():
            data = src.extractfile(m).read() if m.isfile() else None
            if m.name == 'RDNR2aProbe/MANIFEST':
                data = b''.join(l for l in data.splitlines(True) if not l.startswith(b'UNCHECKED'))
                m.size = len(data)
            import io
            dst.addfile(m, io.BytesIO(data) if data is not None else None)
    sumv, blocks = pack_sum(checked)

    def env_for(tmp, **extra):
        e = dict(os.environ, PATH=bindir + ':' + os.environ['PATH'], R2A_TMP=tmp,
                 R2A_SUM=os.path.join(bindir, 'sum'), R2A_KERNEL='/fake/mach_kernel',
                 R2A_KLUTIL=os.path.join(bindir, 'kl_util'), R2A_MSGS=os.path.join(tmp, 'messages'),
                 R2A_RANDIR=os.path.join(tmp, 'ran.d'), R2A_SYSCFG=os.path.join(tmp, 'Instance0.table'),
                 R2A_NFSOUT=os.path.join(tmp, 'nfs', 'build', 'r2a'))
        e.update(extra)
        return e

    def fresh_tmp(label):
        t = os.path.join(work, 'tmp-' + re.sub(r'\W+', '_', label))
        os.makedirs(os.path.join(t, 'nfs', 'build'))
        return t

    print('== target-build.sh ==')
    build_cases = [
        ('good', {}, None, 0, 'R2ABUILD PASS stamp=%s runid=%d' % (stamp, runid)),
        ('good, NFS r2a directory exists', {}, 'nfsdir', 0, 'R2ABUILD PASS'),
        ('wrong sum', {}, 'sum', 1, 'sum differs'),
        ('no arguments', {}, 'noargs', 2, 'usage'),
        ('tree skipped the host gate', {}, 'unchecked', 1, 'MANIFEST says UNCHECKED'),
        ('make gives no product', {'FAKE_MAKE': 'noproduct'}, None, 1, 'no product'),
        ('product ADVERTISEs', {'FAKE_MAKE': 'advertise'}, None, 1, 'carries ADVERTISE'),
        ('symbol not in kernel', {'FAKE_MAKE': 'missing'}, None, 1, 'missing from the kernel'),
        ('NFS copy corrupted', {'FAKE_CP': 'corrupt'}, None, 1, 'differs from the reloc'),
        ('NFS parent missing', {}, 'noparent', 1, 'cannot create'),
    ]
    good_tmp = None
    for label, extra, prep, want_rc, want in build_cases:
        tmp = fresh_tmp('build-' + label)
        args = [checked, sumv, blocks]
        if prep == 'sum':
            args = [checked, '%05d' % ((int(sumv) + 1) % 65536), blocks]
        elif prep == 'noargs':
            args = []
        elif prep == 'unchecked':
            args = list(unchecked)
        elif prep == 'nfsdir':
            os.makedirs(os.path.join(tmp, 'nfs', 'build', 'r2a', str(runid)))
        elif prep == 'noparent':
            shutil.rmtree(os.path.join(tmp, 'nfs'))
        rc, out = run_sh('target-build.sh', args, env_for(tmp, **extra), tmp)
        ok = rc == want_rc and want in out
        nfs = os.path.join(tmp, 'nfs', 'build', 'r2a', str(runid))
        if want_rc == 0 and ok:
            reloc = os.path.join(tmp, 'RDNR2aProbe', 'RDNR2aProbe.config', 'RDNR2aProbe_reloc')
            cf = open(reloc + '.cflags').read().strip()
            rsum = ' '.join(pack_sum(reloc))
            copy_ok = (os.path.exists(os.path.join(nfs, 'RDNR2aProbe_reloc')) and
                       open(os.path.join(nfs, 'RDNR2aProbe_reloc'), 'rb').read() == open(reloc, 'rb').read() and
                       open(os.path.join(nfs, 'reloc.sum')).read().strip() == rsum)
            passline = open(os.path.join(tmp, 'RDNR2aProbe', 'R2ABUILD_PASS')).read().strip()
            ok = cf == 'OTHER_CFLAGS=-DR2A_BUILD=0x%s' % stamp and copy_ok and passline == '%s %d %s' % (stamp, runid, rsum)
            if not ok:
                out += '\ncflags %r copy_ok %s pass %r' % (cf, copy_ok, passline)
            if label == 'good':
                good_tmp = tmp
        if want_rc != 0 and 'R2ABUILD PASS' in out:
            ok = False
        if want_rc != 0 and os.path.exists(os.path.join(nfs, 'reloc.sum')):
            ok = False
            out += '\nreloc.sum written by a failing build'
        if os.path.exists(os.path.join(tmp, 'ps.calls')):
            ok = False
            out += '\nps was called'
        print('  %-4s %-32s rc=%d%s' % ('ok' if ok else 'FAIL', label, rc,
                                        '' if ok else '\n' + '\n'.join('       ' + l for l in out.splitlines()[-8:])))
        failures += 0 if ok else 1
    if good_tmp is None:
        print('check_target_r2a: FAIL (no good build)')
        return 1

    print('== target-run.sh ==')
    ext = os.path.join(work, 'extract')
    with tarfile.open(checked) as t:
        t.extractall(ext)
    simexe = os.path.join(work, 'sim-packed')
    tproj = os.path.join(ext, 'RDNR2aProbe', 'RDNR2aProbe_reloc.tproj')
    okb, err = sim.build(os.path.join(tproj, 'RDNR2aProbe.m'), simexe, int(stamp, 16), tproj)
    r1exe = os.path.join(work, 'sim-r1')
    okb1, err1 = s1.build(s1.PROBE, r1exe)
    if not okb or not okb1:
        print(err, err1)
        print('check_target_r2a: FAIL (sim build)')
        return 1
    world_text = sim.world(runid=runid)
    world = os.path.join(work, 'world.txt')
    open(world, 'w').write(world_text)
    r1log = subprocess.run([r1exe], input=sim.r1_world(world_text).replace('runid %d' % runid, 'runid 4241'),
                           capture_output=True, text=True).stdout

    def run_tmp(label):
        tmp = fresh_tmp('run-' + label)
        shutil.copytree(os.path.join(good_tmp, 'RDNR2aProbe'), os.path.join(tmp, 'RDNR2aProbe'))
        shutil.copytree(os.path.join(good_tmp, 'nfs', 'build', 'r2a'), os.path.join(tmp, 'nfs', 'build', 'r2a'))
        nfs = os.path.join(tmp, 'nfs', 'build', 'r2a', str(runid))
        open(os.path.join(nfs, 'R2ARELOC_PASS'), 'w').write(open(os.path.join(nfs, 'reloc.sum')).read())
        open(os.path.join(tmp, 'messages'), 'w').write('Sep 15 09:59:59 old line\nRDN-R2A %d end lines=1 seq=0\n' % runid)
        open(os.path.join(tmp, 'Instance0.table'), 'w').write('"Active Drivers" = "VGA PCKeyboard PS2Mouse";\n')
        return tmp, nfs

    run_cases = [
        ('good, parsed end to end', {}, None, 0, 'R2ARUN DONE'),
        ('run id already run', {}, 'ran', 1, 'already run'),
        ('no build pass marker', {}, 'nopass', 1, 'no R2ABUILD_PASS'),
        ('reloc changed after the build', {}, 'reloc', 1, 'these reloc bytes'),
        ('no reloc disassembly marker', {}, 'nomarker', 1, 'no R2ARELOC_PASS'),
        ('reloc marker for other bytes', {}, 'othermarker', 1, 'R2ARELOC_PASS does not name'),
        ('no NFS run directory', {}, 'nonfs', 1, 'did not copy the reloc'),
        ('Matrox still active', {}, 'matrox', 1, 'names a Matrox driver'),
        ('no VGA driver active', {}, 'novga', 1, 'names no VGA driver'),
        ('no system config table', {}, 'nosyscfg', 1, 'cannot read'),
        ('unload fails', {'FAKE_KL': 'unloadfail'}, None, 1, 'may still be loaded'),
        ('kl_util -a fails', {'FAKE_KL': 'addfail'}, None, 1, 'kl_util -a failed'),
        ('probe log lacks end line', {'FAKE_KL': 'noend'}, None, 1, 'no end line'),
    ]
    refuse = ('ran', 'nopass', 'reloc', 'nomarker', 'othermarker', 'nonfs', 'matrox', 'novga', 'nosyscfg')
    for label, extra, prep, want_rc, want in run_cases:
        tmp, nfs = run_tmp(label)
        if prep == 'ran':
            os.makedirs(os.path.join(tmp, 'ran.d', str(runid)))
        elif prep == 'reloc':
            with open(os.path.join(tmp, 'RDNR2aProbe', 'RDNR2aProbe.config', 'RDNR2aProbe_reloc'), 'ab') as f:
                f.write(b'patched')
        elif prep == 'nomarker':
            os.remove(os.path.join(nfs, 'R2ARELOC_PASS'))
        elif prep == 'othermarker':
            open(os.path.join(nfs, 'R2ARELOC_PASS'), 'w').write('12345 1\n')
        elif prep == 'nonfs':
            shutil.rmtree(nfs)
        elif prep == 'matrox':
            open(os.path.join(tmp, 'Instance0.table'), 'w').write('"Active Drivers" = "VGA OSMGADisplay PCKeyboard";\n')
        elif prep == 'novga':
            open(os.path.join(tmp, 'Instance0.table'), 'w').write('"Active Drivers" = "PCKeyboard PS2Mouse";\n')
        elif prep == 'nosyscfg':
            os.remove(os.path.join(tmp, 'Instance0.table'))
        elif prep == 'nopass':
            os.remove(os.path.join(tmp, 'RDNR2aProbe', 'R2ABUILD_PASS'))
        env = env_for(tmp, FAKE_SIM=simexe, FAKE_WORLD=world, **extra)
        if label in ('probe log lacks end line',):
            write_exe(os.path.join(tmp, 'sleep'), '#!/bin/sh\nexit 0\n')
            env['PATH'] = tmp + ':' + env['PATH']
        rc, out = run_sh('target-run.sh', [], env, tmp)
        ok = rc == want_rc and want in out
        calls = open(os.path.join(tmp, 'kl_util.calls')).read() if os.path.exists(os.path.join(tmp, 'kl_util.calls')) else ''
        done = os.path.join(nfs, 'run.done')
        if prep == 'nopass':
            # before the run id is read: no done marker is possible
            pass
        elif prep == 'nonfs':
            if os.path.exists(done):
                ok = False
                out += '\nrun.done without an NFS run directory'
        else:
            want_done = 'R2ARUN DONE' if want_rc == 0 else 'R2ARUN FAIL'
            got_done = open(done).read() if os.path.exists(done) else ''
            if not got_done.startswith(want_done) or (want_rc != 0 and want not in got_done):
                ok = False
                out += '\nrun.done %r' % got_done
        if label.startswith('good'):
            copied = os.path.join(nfs, 'rdn-r2a-%d.log' % runid)
            report, fail, replan, rec = p2.judge(open(copied).read() if os.path.exists(copied) else '',
                                                 str(runid), stamp, r1log, '4241')
            if fail or replan:
                ok = False
                out += '\nparse_r2a: ' + '; '.join((fail or replan)[:3])
            if sorted(os.listdir(os.path.join(tmp, 'ran.d'))) != [str(runid)]:
                ok = False
            if not all(('-%s RDNR2aProbe' % c) in calls for c in 'lud'):
                ok = False
                out += '\nkl_util calls %r' % calls
        if label in ('probe log lacks end line', 'unload fails') and ('-u RDNR2aProbe' not in calls or '-d RDNR2aProbe' not in calls):
            ok = False
            out += '\nno unload: %r' % calls
        if want_rc != 0 and 'R2ARUN DONE' in out:
            ok = False
        if prep in refuse and re.search(r'kl_util -[al] ', calls):
            ok = False
            out += '\nkl_util loaded something: %r' % calls
        if os.path.exists(os.path.join(tmp, 'ps.calls')):
            ok = False
            out += '\nps was called'
        print('  %-4s %-32s rc=%d%s' % ('ok' if ok else 'FAIL', label, rc,
                                        '' if ok else '\n' + '\n'.join('       ' + l for l in out.splitlines()[-10:])))
        failures += 0 if ok else 1

    # an interrupt while kl_util -l hangs must still unload and write run.done
    tmp, nfs = run_tmp('interrupted')
    env = env_for(tmp, FAKE_SIM=simexe, FAKE_WORLD=world, FAKE_KL='hang')
    pr_ = subprocess.Popen(['/bin/sh', os.path.join(HERE, 'target-run.sh')], env=env, cwd=tmp,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    t0 = time.time()
    while not os.path.exists(os.path.join(tmp, 'kl_hanging')) and time.time() - t0 < 20:
        time.sleep(0.1)
    pr_.send_signal(signal.SIGTERM)
    try:
        out, _ = pr_.communicate(timeout=60)
    except subprocess.TimeoutExpired:
        pr_.kill()
        out, _ = pr_.communicate()
    calls = open(os.path.join(tmp, 'kl_util.calls')).read()
    done = open(os.path.join(nfs, 'run.done')).read() if os.path.exists(os.path.join(nfs, 'run.done')) else ''
    ok = (pr_.returncode != 0 and 'R2ARUN FAIL interrupted' in out and '-u RDNR2aProbe' in calls
          and '-d RDNR2aProbe' in calls and 'R2ARUN DONE' not in out and done.startswith('R2ARUN FAIL interrupted'))
    print('  %-4s %-32s rc=%s%s' % ('ok' if ok else 'FAIL', 'interrupted during load', pr_.returncode,
                                    '' if ok else '\n' + out[-600:] + '\ncalls %r done %r' % (calls, done)))
    failures += 0 if ok else 1

    shutil.rmtree(work, ignore_errors=True)
    print('check_target_r2a:', 'PASS' if failures == 0 else 'FAIL (%d)' % failures)
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
