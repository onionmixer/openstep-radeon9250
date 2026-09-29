#!/usr/bin/env python3
"""Run target-build.sh and target-run.sh on the host, against fake target tools.

  check_target_scripts.py      exit 1 on any failure

The target scripts gate a build and a run that cost a boot if they go wrong,
and their checks are shell text that nothing else exercises.  A check that
never fires is the failure this file exists to catch (the memory note on the
target's missing tools: a missing command turns a check into a silent pass).
So:

  lint   both scripts: ASCII only, and none of the constructs the target's sh
         and tools lack ($(...), printf, cut, grep -q, grep alternation with
         \\|, mkdir -p, test -e, dirname, [[ ]], local)
  build  pack a real tree with pack_probe.py, then run target-build.sh under
         /bin/sh with fake make/nm/sum: the good case must PASS, and each
         broken case must FAIL with its own message
  run    target-run.sh with a fake kl_util whose load runs the R1 simulator
         built from the PACKED source with the PACKED stamp and run id, so
         the whole chain pack -> build -> load -> log -> parse_r1.py is
         checked end to end; then the broken run cases

What it cannot show: the target's own sh, make, nm, strings and kl_util.
Those are exercised the first time on the target, where each script's first
failing line names what went wrong.
"""

import importlib.util
import io
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = ['target-build.sh', 'target-run.sh']


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + '.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


sim = load('sim_r1')
pr = sim.pr

FORBIDDEN = [
    (r'\$\(', '$(...)'),
    (r'(^|[;&|`\s])printf\b', 'printf'),
    (r'(^|[;&|`\s])cut\b', 'cut'),
    (r'grep\s+-q', 'grep -q'),
    (r'\\\|', 'grep alternation \\|'),
    (r'mkdir\s+-p', 'mkdir -p'),
    (r'test\s+-e|\[\s+-e\s', 'test -e'),
    (r'(^|[;&|`\s])dirname\b', 'dirname'),
    (r'\[\[', '[[ ]]'),
    (r'(^|\s)local\s', 'local'),
]


def lint():
    bad = 0
    for name in SCRIPTS:
        data = open(os.path.join(HERE, name), 'rb').read()
        if any(b > 0x7e or (b < 0x20 and b not in (9, 10)) for b in data):
            print('  FAIL %s: non-ASCII byte' % name)
            bad += 1
        for n, line in enumerate(data.decode('ascii', 'replace').splitlines(), 1):
            code = line if not line.lstrip().startswith('#') else ''
            for pat, what in FORBIDDEN:
                if re.search(pat, code):
                    print('  FAIL %s:%d uses %s: %s' % (name, n, what, line.strip()))
                    bad += 1
    # the lint must be able to fail: each forbidden construct in a probe line
    probes = ['x=$(ls)', 'printf "a"', 'a | cut -c1', 'grep -q x f', "grep 'a\\|b' f",
              'mkdir -p d', 'test -e f', 'd=`dirname f`', 'if [[ a ]]; then', 'local x']
    for p, (pat, what) in zip(probes, FORBIDDEN):
        if not re.search(pat, p):
            print('  FAIL lint rule %s does not match its own probe %r' % (what, p))
            bad += 1
    if not bad:
        print('  ok   ASCII, no forbidden constructs; each of %d rules matches its probe' % len(FORBIDDEN))
    return bad


def write_exe(path, text):
    open(path, 'w').write(text)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


KERNEL_SYMS = ['IODelay', 'IOLog', 'IOMapPhysicalIntoIOTask', 'IOSleep',
               'IOUnmapPhysicalFromIOTask', 'sprintf']


def fake_tools(bindir, work):
    os.makedirs(bindir)
    write_exe(os.path.join(bindir, 'sum'), '''#!/usr/bin/env python3
import sys
sys.path.insert(0, %r)
from pack_probe import bsdsum
print(bsdsum(open(sys.argv[1], 'rb').read()), sys.argv[1])
''' % HERE)
    # make: builds the product the way the real makefiles lay it out, with the
    # load commands as NUL-separated strings (what strings(1) will show), the
    # table with the postamble's Server Name appended, and a symbol list for
    # the fake nm.  FAKE_MAKE selects a broken product.
    write_exe(os.path.join(bindir, 'make'), r'''#!/bin/sh
mode=${FAKE_MAKE:-good}
cflags="$1"
echo "fake make $cflags"
[ "$mode" = noproduct ] && exit 0
mkdir -p RDNR1Probe.config
cp Default.table RDNR1Probe.config/Default.table
echo '"Server Name" = "RDNR1Probe";' >> RDNR1Probe.config/Default.table
[ "$mode" = othername ] && echo '"Server Name" = "Other";' >> RDNR1Probe.config/Default.table
r=RDNR1Probe.config/RDNR1Probe_reloc
{ printf '\177ELFjunk\000'; grep -v '^#' RDNR1Probe_reloc.tproj/Load_Commands.sect | tr '\n' '\000'
  [ "$mode" = advertise ] && printf 'ADVERTISE RDNR1Probe\000'
  printf '%s\000' "$cflags"; } > $r
printf 'IODelay\nIOLog\nIOMapPhysicalIntoIOTask\nIOSleep\nIOUnmapPhysicalFromIOTask\nsprintf\n' > $r.syms
[ "$mode" = missing ] && echo IOPanicNotExported >> $r.syms
[ "$mode" = nosyms ] && : > $r.syms
echo "$cflags" > $r.cflags
[ "$mode" = failafter ] && exit 2
exit 0
''')
    write_exe(os.path.join(bindir, 'nm'), r'''#!/bin/sh
if [ "$1" = "-u" ]; then sed 's/^/         /' "$2.syms"; exit 0; fi
for s in %s; do echo "00001000 T $s"; done
''' % ' '.join(KERNEL_SYMS))
    # kl_util: -l runs the simulator built from the packed source.  FAKE_KL
    # selects a broken load.
    write_exe(os.path.join(bindir, 'kl_util'), r'''#!/bin/sh
mode=${FAKE_KL:-good}
echo "kl_util $*" >> "$R1_TMP/kl_util.calls"
case "$1" in
  -a) [ "$mode" = addfail ] && exit 1; exit 0 ;;
  -l) [ "$mode" = silent ] && exit 0
      if [ "$mode" = hang ]; then touch "$R1_TMP/kl_hanging"; sleep 30; exit 0; fi
      "$FAKE_SIM" < "$FAKE_WORLD" > "$R1_TMP/sim.out" 2> "$R1_TMP/sim.err"
      if [ "$mode" = noend ]; then grep -v ' end lines=' "$R1_TMP/sim.out" >> "$R1_MSGS"
      else cat "$R1_TMP/sim.out" >> "$R1_MSGS"; fi
      exit 0 ;;
  -u) [ "$mode" = unloadfail ] && exit 1; exit 0 ;;
  *) exit 0 ;;
esac
''')
    write_exe(os.path.join(bindir, 'ps'), r'''#!/bin/sh
echo "  PID TT STAT  TIME COMMAND"
echo "    1 ?  S     0:01 /usr/etc/init"
[ "${FAKE_PS:-good}" = good ] && echo "  211 ?  S     0:00 /tmp/nxlogd /usr/adm/messages /ndrv/logs/kernel.log"
exit 0
''')


def run_sh(script, args, env, cwd):
    r = subprocess.run(['/bin/sh', os.path.join(HERE, script)] + args, env=env, cwd=cwd,
                       capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout + r.stderr


def main():
    failures = 0
    print('== lint ==')
    failures += lint()

    work = tempfile.mkdtemp(prefix='chk_target.', dir=os.environ.get('TMPDIR'))
    bindir = os.path.join(work, 'bin')
    fake_tools(bindir, work)
    runid = 424242
    pk = subprocess.run([sys.executable, os.path.join(HERE, 'pack_probe.py'), '--skip-hostcheck',
                         '--runid', str(runid), '--out-dir', os.path.join(work, 'out')],
                        capture_output=True, text=True, env=dict(os.environ, TMPDIR=work))
    if pk.returncode != 0:
        print(pk.stdout, pk.stderr)
        print('check_target_scripts: FAIL (pack)')
        return 1
    tarpath = re.search(r'packed\s+(\S+)', pk.stdout).group(1)
    stamp = re.search(r'stamp\s+(\S+)', pk.stdout).group(1)
    sumv, blocks = re.search(r'sum\s+(\d+) (\d+)', pk.stdout).groups()

    def env_for(tmp, **extra):
        e = dict(os.environ, PATH=bindir + ':' + os.environ['PATH'], R1_TMP=tmp,
                 R1_SUM=os.path.join(bindir, 'sum'), R1_KERNEL='/fake/mach_kernel',
                 R1_KLUTIL=os.path.join(bindir, 'kl_util'), R1_MSGS=os.path.join(tmp, 'messages'),
                 R1_RANDIR=os.path.join(tmp, 'ran.d'), R1_SYSCFG=os.path.join(tmp, 'Instance0.table'))
        e.update(extra)
        return e

    def fresh_tmp(label):
        t = os.path.join(work, 'tmp-' + re.sub(r'\W+', '_', label))
        os.makedirs(t)
        return t

    def broken_tar(label, edit):
        """repack the good tar with one member rewritten by edit(name, bytes)"""
        out = os.path.join(work, 'broken-%s.tar' % re.sub(r'\W+', '_', label))
        with tarfile.open(tarpath) as src, tarfile.open(out, 'w', format=tarfile.USTAR_FORMAT) as dst:
            for m in src.getmembers():
                data = src.extractfile(m).read() if m.isfile() else None
                if data is not None:
                    data = edit(m.name, data)
                    if data is None:
                        continue
                    m.size = len(data)
                dst.addfile(m, io.BytesIO(data) if data is not None else None)
            extra = edit('+', b'')
            if extra:
                name, data = extra
                ti = tarfile.TarInfo(name)
                ti.size = len(data)
                dst.addfile(ti, io.BytesIO(data))
        return out, pack_sum(out)

    def pack_sum(path):
        s = subprocess.run([os.path.join(bindir, 'sum'), path], capture_output=True, text=True).stdout.split()
        return s[0], s[1]

    def member_edit(target, fn):
        def edit(name, data):
            if name == '+':
                return None
            return fn(data) if name == target else data
        return edit

    # The packer ran with --skip-hostcheck (the real hostcheck calls this
    # file), so its MANIFEST says UNCHECKED and target-build.sh must refuse
    # it.  Every other case uses a copy with that line removed.
    unchecked_tar, unchecked_sum = tarpath, (sumv, blocks)
    tarpath, (sumv, blocks) = broken_tar('checked', member_edit(
        'RDNR1Probe/MANIFEST', lambda d: b''.join(l for l in d.splitlines(True) if not l.startswith(b'UNCHECKED'))))

    print('== target-build.sh ==')
    lc = 'RDNR1Probe/RDNR1Probe_reloc.tproj/Load_Commands.sect'
    build_cases = [
        ('good', None, {}, 0, 'R1BUILD PASS stamp=%s runid=%d' % (stamp, runid)),
        ('wrong sum', 'sum', {}, 1, 'sum differs'),
        ('no arguments', 'noargs', {}, 2, 'usage'),
        ('unstamped', member_edit('RDNR1Probe/BUILD_STAMP', lambda d: b'00000000\n'), {}, 1, 'unstamped value'),
        ('stamp malformed', member_edit('RDNR1Probe/BUILD_STAMP', lambda d: b'12ab\n'), {}, 1, 'stamp malformed'),
        ('runid malformed', member_edit('RDNR1Probe/RUNID', lambda d: b'12x\n'), {}, 1, 'runid malformed'),
        ('ADVERTISE in source', member_edit(lc, lambda d: d + b'ADVERTISE RDNR1Probe\n'), {}, 1, 'is not CALL'),
        ('CALL other run id', member_edit(lc, lambda d: d.replace(b'%d' % runid, b'1')), {}, 1, 'is not CALL'),
        ('template packed too', lambda n, d: (('RDNR1Probe/RDNR1Probe_reloc.tproj/Load_Commands.sect.in', b'x\n')
                                              if n == '+' else d), {}, 1, 'template packed'),
        ('make gives no product', None, {'FAKE_MAKE': 'noproduct'}, 1, 'no product'),
        ('make fails after a product', None, {'FAKE_MAKE': 'failafter'}, 1, 'make exited 2'),
        ('tree skipped the host gate', 'unchecked', {}, 1, 'MANIFEST says UNCHECKED'),
        ('product ADVERTISEs', None, {'FAKE_MAKE': 'advertise'}, 1, 'carries ADVERTISE'),
        ('second server name', None, {'FAKE_MAKE': 'othername'}, 1, 'does not name server'),
        ('symbol not in kernel', None, {'FAKE_MAKE': 'missing'}, 1, 'missing from the kernel'),
        ('nm lists nothing', None, {'FAKE_MAKE': 'nosyms'}, 1, 'the check saw nothing'),
    ]
    good_tmp = None
    for label, tar_edit, extra, want_rc, want in build_cases:
        tmp = fresh_tmp('build-' + label)
        if tar_edit is None:
            args = [tarpath, sumv, blocks]
        elif tar_edit == 'sum':
            args = [tarpath, '%05d' % ((int(sumv) + 1) % 65536), blocks]
        elif tar_edit == 'noargs':
            args = []
        elif tar_edit == 'unchecked':
            args = [unchecked_tar, unchecked_sum[0], unchecked_sum[1]]
        else:
            t, (s2, b2) = broken_tar(label, tar_edit)
            args = [t, s2, b2]
        rc, out = run_sh('target-build.sh', args, env_for(tmp, **extra), tmp)
        ok = rc == want_rc and want in out
        if label == 'good' and ok:
            cf = open(os.path.join(tmp, 'RDNR1Probe', 'RDNR1Probe.config', 'RDNR1Probe_reloc.cflags')).read()
            ok = cf.strip() == 'OTHER_CFLAGS=-DR1_BUILD=0x%s' % stamp
            if not ok:
                out += '\nmake was given %r' % cf
            good_tmp = tmp
        if want_rc != 0 and 'R1BUILD PASS' in out:
            ok = False
        print('  %-4s %-24s rc=%d%s' % ('ok' if ok else 'FAIL', label, rc,
                                        '' if ok else '\n' + '\n'.join('       ' + l for l in out.splitlines()[-8:])))
        failures += 0 if ok else 1

    print('== target-run.sh ==')
    # the simulator, built from the packed source with the packed stamp
    ext = os.path.join(work, 'extract')
    with tarfile.open(tarpath) as t:
        t.extractall(ext)
    simexe = os.path.join(work, 'sim-packed')
    okb, err = sim.build(os.path.join(ext, 'RDNR1Probe', 'RDNR1Probe_reloc.tproj', 'RDNR1Probe.m'),
                         simexe, int(stamp, 16))
    if not okb:
        print(err)
        print('check_target_scripts: FAIL (sim build)')
        return 1
    world = os.path.join(work, 'world.txt')
    open(world, 'w').write(sim.world(runid=runid))

    def run_tmp(label):
        tmp = fresh_tmp('run-' + label)
        shutil.copytree(os.path.join(good_tmp, 'RDNR1Probe'), os.path.join(tmp, 'RDNR1Probe'))
        open(os.path.join(tmp, 'messages'), 'w').write('Sep 15 09:59:59 old line\nRDN-R1 %d end lines=1 seq=0\n' % runid)
        open(os.path.join(tmp, 'Instance0.table'), 'w').write('"Active Drivers" = "VGA PCKeyboard PS2Mouse";\n')
        return tmp

    if good_tmp is None:
        print('  FAIL no good build to run')
        return failures + 1
    run_cases = [
        ('good, parsed end to end', {}, None, 0, 'R1RUN DONE'),
        ('run id already run', {}, 'ran', 1, 'already run'),
        ('no build pass marker', {}, 'nopass', 1, 'no R1BUILD_PASS'),
        ('pass marker for another tree', {}, 'otherpass', 1, 'does not name this tree'),
        ('reloc changed after the build', {}, 'reloc', 1, 'these reloc bytes'),
        ('nxlogd not running', {'FAKE_PS': 'none'}, None, 1, 'nxlogd is not running'),
        ('Matrox still active', {}, 'matrox', 1, 'names a Matrox driver'),
        ('no system config table', {}, 'nosyscfg', 1, 'cannot read'),
        ('unload fails', {'FAKE_KL': 'unloadfail'}, None, 1, 'may still be loaded'),
        ('kl_util -a fails', {'FAKE_KL': 'addfail'}, None, 1, 'kl_util -a failed'),
        ('probe log lacks end line', {'FAKE_KL': 'noend'}, None, 1, 'no end line'),
    ]
    for label, extra, prep, want_rc, want in run_cases:
        tmp = run_tmp(label)
        if prep == 'ran':
            os.makedirs(os.path.join(tmp, 'ran.d', str(runid)))
        elif prep == 'reloc':
            with open(os.path.join(tmp, 'RDNR1Probe', 'RDNR1Probe.config', 'RDNR1Probe_reloc'), 'ab') as f:
                f.write(b'patched')
        elif prep == 'matrox':
            open(os.path.join(tmp, 'Instance0.table'), 'w').write('"Active Drivers" = "OSMGADisplay PCKeyboard";\n')
        elif prep == 'nosyscfg':
            os.remove(os.path.join(tmp, 'Instance0.table'))
        elif prep == 'nopass':
            os.remove(os.path.join(tmp, 'RDNR1Probe', 'R1BUILD_PASS'))
        elif prep == 'otherpass':
            open(os.path.join(tmp, 'RDNR1Probe', 'R1BUILD_PASS'), 'w').write('%s 1\n' % stamp)
        env = env_for(tmp, FAKE_SIM=simexe, FAKE_WORLD=world, **extra)
        if label in ('probe log lacks end line', 'unload fails'):
            # do not wait the full 60 s: a fake sleep that returns at once
            write_exe(os.path.join(tmp, 'sleep'), '#!/bin/sh\nexit 0\n')
            env['PATH'] = tmp + ':' + env['PATH']
        rc, out = run_sh('target-run.sh', [], env, tmp)
        ok = rc == want_rc and want in out
        calls = open(os.path.join(tmp, 'kl_util.calls')).read() if os.path.exists(os.path.join(tmp, 'kl_util.calls')) else ''
        if label.startswith('good'):
            log = os.path.join(tmp, 'rdn-r1-%d.log' % runid)
            report, fail = pr.judge(open(log).read(), str(runid), stamp)
            if fail:
                ok = False
                out += '\nparse_r1: ' + '; '.join(fail)
            ran = sorted(os.listdir(os.path.join(tmp, 'ran.d')))
            if ran != [str(runid)]:
                ok = False
                out += '\nran ids %r' % ran
            if not all(('-%s RDNR1Probe' % c) in calls for c in 'lud'):
                ok = False
                out += '\nkl_util calls %r' % calls
        if label in ('probe log lacks end line', 'unload fails') and ('-u RDNR1Probe' not in calls or '-d RDNR1Probe' not in calls):
            ok = False
            out += '\nno unload after a missing end line: %r' % calls
        if want_rc != 0 and 'R1RUN DONE' in out:
            ok = False
        if (prep in ('ran', 'nopass', 'otherpass', 'reloc', 'matrox', 'nosyscfg') or
                extra.get('FAKE_PS') == 'none') and re.search(r'kl_util -[al] ', calls):
            ok = False
            out += '\nkl_util loaded something: %r' % calls
        print('  %-4s %-30s rc=%d%s' % ('ok' if ok else 'FAIL', label, rc,
                                        '' if ok else '\n' + '\n'.join('       ' + l for l in out.splitlines()[-10:])))
        failures += 0 if ok else 1

    # an interrupt while kl_util -l hangs must still unload
    import signal, time
    tmp = run_tmp('interrupted')
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
    ok = (pr_.returncode != 0 and 'R1RUN FAIL interrupted' in out and '-u RDNR1Probe' in calls
          and '-d RDNR1Probe' in calls and 'R1RUN DONE' not in out)
    print('  %-4s %-30s rc=%s%s' % ('ok' if ok else 'FAIL', 'interrupted during load', pr_.returncode,
                                    '' if ok else '\n' + out[-600:] + '\ncalls %r' % calls))
    failures += 0 if ok else 1

    shutil.rmtree(work, ignore_errors=True)
    print('check_target_scripts:', 'PASS' if failures == 0 else 'FAIL (%d)' % failures)
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
