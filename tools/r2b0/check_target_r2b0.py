#!/usr/bin/env python3
"""Run the R2b-0 target scripts on the host against fake target tools (docs/R2B0_IMPL_PLAN.md 6-5, 7, 8).

  check_target_r2b0.py      lint + every case; exit 1 on any failure

Scripts: target-build-r2b0.sh, target-install-r2b0.sh, target-cfgsnap-r2b0.sh,
target-stage-restore-r2b0.sh, target-run-r2b0.sh, me/check.sh, me/restore.sh.

lint     R1's forbidden constructs, R1c's target rules (no ps, no blank in an
         unquoted default), no set -- and no $1..$9 after the first function,
         no while-read loop, no set -e, no grep -c exit status used, ASCII;
         the R2B0_* override names of each script equal the harness's; every
         rule proven to fire by a mutation
build    a tree packed by pack_r2b0.py --skip-hostcheck (UNCHECKED line
         removed for the cases that need it): good, and each broken case
install  first install and an upgrade that keeps the machine's instance
         tables byte for byte; each refusal
restore  the whole R-1 path on a fake /private/Drivers/i386 made of the
         tables captured on the target (build/r2b0/emu10k1): cfgsnap pre ->
         check_cfgdiff precheck -> pack_restore -> stage -> check.sh ->
         a Configure-like activation (reordered keys, VGA instance deleted,
         OSRDNDisplay instance made from Default.table) -> cfgsnap post ->
         check_cfgdiff activate -> restore.sh -> cfgsnap post3 ->
         check_cfgdiff restored; and the restore refusals (a corrupted set
         writes nothing, a missing bundle directory, owner repaired)
run      target-run-r2b0.sh with a fake rdnr2b0 that runs the R2b-0
         simulator and appends its lines to the fake syslog; the captured log
         is judged by parse_r2b0.py end to end; each refusal

Fake tools: sum (BSD, tools/r1/pack_probe.py), ls -lg in the target's format
with owner/group from a small database (chown writes it, keyed by inode, so
mv keeps and cp resets to root.wheel), find with -user root/-group wheel
mapped to the host user, make, nm, cc, logger (appends to the fake syslog),
kl_util -s, and ps (records a call and fails).

What it cannot show: the target's sh, make, cc, nm, find, NFS and Configure.
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
PROJ = os.path.dirname(os.path.dirname(HERE))
SCRIPTS = ['target-build-r2b0.sh', 'target-install-r2b0.sh', 'target-cfgsnap-r2b0.sh',
           'target-stage-restore-r2b0.sh', 'target-park-extra-r2b0.sh', 'target-run-r2b0.sh',
           'me/check.sh', 'me/restore.sh']
ENV_NAMES = {
    'target-build-r2b0.sh': ['R2B0_TMP', 'R2B0_SUM', 'R2B0_KERNEL', 'R2B0_CC', 'R2B0_NFSOUT'],
    'target-install-r2b0.sh': ['R2B0_TMP', 'R2B0_SUM', 'R2B0_DRV', 'R2B0_NFSOUT'],
    'target-cfgsnap-r2b0.sh': ['R2B0_DRV', 'R2B0_SUM', 'R2B0_LS', 'R2B0_NFSOUT', 'R2B0_TMP'],
    'target-stage-restore-r2b0.sh': ['R2B0_ME', 'R2B0_SUM', 'R2B0_NFSOUT'],
    'target-park-extra-r2b0.sh': ['R2B0_TMP', 'R2B0_DRV', 'R2B0_ME', 'R2B0_SUM', 'R2B0_NFSOUT'],
    'target-run-r2b0.sh': ['R2B0_TMP', 'R2B0_SUM', 'R2B0_DRV', 'R2B0_ME', 'R2B0_RANDIR', 'R2B0_MSGS',
                           'R2B0_KLUTIL', 'R2B0_NFSOUT'],
    'me/check.sh': ['R2B0_ME', 'R2B0_DRV', 'R2B0_SUM', 'R2B0_LS'],
    'me/restore.sh': ['R2B0_ME', 'R2B0_DRV', 'R2B0_SUM', 'R2B0_LS'],
}


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


r1scripts = _load('check_target_scripts_r2b0', os.path.join(PROJ, 'tools', 'r1', 'check_target_scripts.py'))
r1c = _load('check_target_r1c_r2b0', os.path.join(PROJ, 'tools', 'r1c', 'check_target_r1c.py'))
pk = _load('pack_r1_for_target_r2b0', os.path.join(PROJ, 'tools', 'r1', 'pack_probe.py'))
cd = _load('check_cfgdiff_for_target', os.path.join(HERE, 'check_cfgdiff.py'))
pr = _load('pack_restore_for_target', os.path.join(HERE, 'pack_restore_r2b0.py'))
sim = _load('sim_r2b0_for_target', os.path.join(HERE, 'sim_r2b0.py'))
pb = sim.pb

EXTRA_RULES = [
    (r'\bwhile\s+read\b', 'while read (a redirected loop is a subshell on the target)', 'while read a; do :; done < f'),
    (r'\bset\s+-e\b', 'set -e (kills the script silently on the target)', 'set -e'),
    (r'\bif\s+grep\s+-c\b', 'grep -c exit status used as a test', 'if grep -c x f; then :; fi'),
]


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
        for pat, what, _ in r1c.TARGET_RULES + EXTRA_RULES:
            if re.search(pat, code):
                bad.append('line %d uses %s: %s' % (n, what, line.strip()))
    bad += r1c.positional_misuse(text)
    names = set(re.findall(r'\$\{(R2B0_\w+):-', text))
    if names != set(ENV_NAMES[name]):
        bad.append('override names %s != harness %s' % (sorted(names), sorted(ENV_NAMES[name])))
    if re.search(r'\$\{R(1C?|2A)_\w+', text):
        bad.append('an R1/R2a override name in an R2b-0 script')
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
        print('  ok   %d scripts: ASCII, no forbidden construct, overrides as the harness' % len(SCRIPTS))
    for pat, what, probe in EXTRA_RULES:
        if not re.search(pat, probe):
            print('  FAIL extra lint rule %r does not match its probe' % what)
            failures += 1
    muts = [
        ('me/restore.sh', 'ps put back', 'echo "=== 4. verify ==="\n', 'echo "=== 4. verify ==="\nn=`ps ax | wc -l`\n', 'ps ('),
        ('me/restore.sh', 'while read loop', 'RELS=`awk \'{ print $1 }\' $MAN`\n',
         'RELS=`awk \'{ print $1 }\' $MAN`\nwhile read rel; do :; done < $MAN\n', 'while read'),
        ('target-run-r2b0.sh', '$1 after a function', 'STAMP=`awk \'{ print $1 }\' $NFSOUT/$RUNID/BUILD_PASS`',
         'STAMP="$1"', 'positional parameter'),
        ('target-cfgsnap-r2b0.sh', 'set -e', 'MODE="$1"\n', 'set -e\nMODE="$1"\n', 'set -e'),
        ('target-stage-restore-r2b0.sh', 'blank in a default', 'ME=${R2B0_ME:-/me/rdn-r2b0}',
         'ME=${R2B0_ME:-/me/rdn-r2b0 /tmp}', 'bad substitution'),
        ('target-install-r2b0.sh', 'unlisted override', 'SUM=${R2B0_SUM:-/usr/bin/sum}', 'SUM=${R2B0_SUMX:-/usr/bin/sum}',
         'override names'),
        ('target-build-r2b0.sh', 'grep -c as a test', 'n=`grep -c \'^UNCHECKED\' $TOP/MANIFEST`\n',
         'if grep -c \'^UNCHECKED\' $TOP/MANIFEST; then fail x; fi\n', 'grep -c exit'),
        ('target-park-extra-r2b0.sh', 'park: $(...) substitution', 'TAG=`cat $ME/CURRENT`',
         'TAG=$(cat $ME/CURRENT)', '$('),
        ('target-park-extra-r2b0.sh', 'park: mkdir -p', 'mkdir $PARK || fail', 'mkdir -p $PARK || fail', 'mkdir -p'),
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


def fake_tools(bindir, owners):
    os.makedirs(bindir)
    os.makedirs(owners)
    write_exe(os.path.join(bindir, 'sum'), '''#!/usr/bin/env python3
import sys
sys.path.insert(0, %r)
from pack_probe import bsdsum
print(bsdsum(open(sys.argv[1], 'rb').read()), sys.argv[1])
''' % os.path.join(PROJ, 'tools', 'r1'))
    write_exe(os.path.join(bindir, 'ls'), '''#!/usr/bin/env python3
import os, stat, sys
db = %r
paths = [a for a in sys.argv[1:] if not a.startswith('-')]
for p in paths:
    st = os.stat(p)
    o = open(os.path.join(db, str(st.st_ino))).read().split() if os.path.exists(os.path.join(db, str(st.st_ino))) else ['root', 'wheel']
    print('%%s  1 %%-8s %%-8s %%8d Sep 16 10:00 %%s' %% (stat.filemode(st.st_mode), o[0], o[1], st.st_size, p))
''' % owners)
    write_exe(os.path.join(bindir, 'chown'), '''#!/usr/bin/env python3
import os, sys
db = %r
args = [a for a in sys.argv[1:] if a != '-R']
rec = '-R' in sys.argv[1:]
spec = args[0].replace(':', '.').split('.')
if os.environ.get('FAKE_CHOWN') == 'fail':
    sys.exit(1)
def put(p):
    f = os.path.join(db, str(os.stat(p).st_ino))
    cur = open(f).read().split() if os.path.exists(f) else ['root', 'wheel']
    owner = spec[0]
    group = spec[1] if len(spec) > 1 else cur[1]
    open(f, 'w').write('%%s %%s\\n' %% (owner, group))
for p in args[1:]:
    put(p)
    if rec and os.path.isdir(p):
        for d, dirs, files in os.walk(p):
            for x in dirs + files:
                put(os.path.join(d, x))
''' % owners)
    write_exe(os.path.join(bindir, 'find'), '''#!/bin/sh
u=`id -un`
g=`id -gn`
out=""
for a in "$@"; do
  case "$a" in root) a=$u ;; wheel) a=$g ;; esac
  out="$out '$a'"
done
eval /usr/bin/find $out
''')
    write_exe(os.path.join(bindir, 'make'), r'''#!/bin/sh
mode=${FAKE_MAKE:-good}
cflags="$1"
echo "fake make $cflags"
[ "$mode" = fail ] && exit 2
[ "$mode" = noproduct ] && exit 0
mkdir -p OSRDNDisplay.config/English.lproj
/bin/cp Default.table OSRDNDisplay.config/Default.table
/bin/cp Instance0.table OSRDNDisplay.config/Instance0.table
[ "$mode" != nomodes ] && /bin/cp Display.modes OSRDNDisplay.config/Display.modes
/bin/cp English.lproj/Localizable.strings OSRDNDisplay.config/English.lproj/
echo "cc -static -O -I./compat -DOSRDN_BUILD -c OSRDNDisplayInspector.m"
echo "cc -static -O -I./compat -DOSRDN_BUILD -c osrdn_mode.m"
# the Configure inspector (docs/R3_MULTIMODE_PLAN.md 26-5): nib and executable
mkdir -p OSRDNDisplay.config/English.lproj/DisplayInspector.nib
/bin/cp English.lproj/DisplayInspector.nib/* OSRDNDisplay.config/English.lproj/DisplayInspector.nib/
[ "$mode" = nonib ] && rm OSRDNDisplay.config/English.lproj/DisplayInspector.nib/data.nib
[ "$mode" = emptynib ] && : > OSRDNDisplay.config/English.lproj/DisplayInspector.nib/data.classes
e=OSRDNDisplay.config/OSRDNDisplay
if [ "$mode" != noexe ]; then
  echo "fake bundle executable" > $e
  [ "$mode" != noclass ] && echo "00000000 A .objc_class_name_OSRDNDisplayInspector" > $e.syms
  echo "         U .objc_class_name_IODisplayInspector" >> $e.syms
fi
for t in OSRDNDisplay.config/Default.table OSRDNDisplay.config/Instance0.table; do
  echo '"Server Name" = "OSRDNDisplay";' >> $t          # Makefile.bundle_postamble, every table
  [ "$mode" = twoservers ] && echo '"Server Name" = "OSRDNDisplay";' >> $t
  [ "$mode" = otherserver ] && echo '"Server Name" = "VGA";' >> $t
done
[ "$mode" = nokey ] && sed -i '/RDN R2B0 Record/d' OSRDNDisplay.config/Instance0.table
[ "$mode" = twomodes ] && grep '^"Display Mode"' Instance0.table >> OSRDNDisplay.config/Instance0.table
[ "$mode" = nomode ] && sed -i '/^"Display Mode"/d' OSRDNDisplay.config/Default.table
r=OSRDNDisplay.config/OSRDNDisplay_reloc
{ printf '\376\355\372\316junk\000'; grep -v '^#' OSRDNDisplay_reloc.tproj/Load_Commands.sect | tr '\n' '\000'
  [ "$mode" = advertise ] && printf 'ADVERTISE OSRDNDisplay\000'
  printf '%s\000' "$cflags"; } > $r
printf '_IODelay\n_IOLog\n_IOSleep\n_IOGetTimestamp\n_sprintf\n_splhigh\n_splx\n' > $r.syms
[ "$mode" != nobcm ] && echo _basicConsoleMode >> $r.syms
[ "$mode" = missing ] && echo _IOPanicNotExported >> $r.syms
exit 0
''')
    write_exe(os.path.join(bindir, 'nm'), r'''#!/bin/sh
if [ "$1" = "-u" ]; then sed 's/^/         /' "$2.syms"; exit 0; fi
if [ -f "$1.syms" ]; then cat "$1.syms"; exit 0; fi      # the bundle executable
for s in _IODelay _IOLog _IOSleep _IOGetTimestamp _sprintf _splhigh _splx _basicConsoleMode; do echo "00001000 T $s"; done
''')
    write_exe(os.path.join(bindir, 'cc'), r'''#!/bin/sh
[ "${FAKE_CC:-good}" = fail ] && { echo "rdnr2b0.m:1: error"; exit 1; }
if [ "${FAKE_CC:-good}" = fail4 ]; then case "$*" in *rdnr4map.m*) echo "rdnr4map.m:1: error"; exit 1 ;; esac; fi
if [ "${FAKE_CC:-good}" = fail5 ]; then case "$*" in *rdnr5cp.m*) echo "rdnr5cp.m:1: error"; exit 1 ;; esac; fi
out=""
while [ $# -gt 0 ]; do [ "$1" = "-o" ] && { shift; out="$1"; }; shift; done
echo "fake tool" > "$out"
exit 0
''')
    write_exe(os.path.join(bindir, 'logger'), r'''#!/bin/sh
[ "${FAKE_LOGGER:-good}" = drop ] && exit 0
echo "Sep 16 10:00:00 nextonion root: $*" >> "$R2B0_MSGS"
''')
    write_exe(os.path.join(bindir, 'kl_util'), '#!/bin/sh\necho "kl_util $*"\n')
    write_exe(os.path.join(bindir, 'sleep'), '#!/bin/sh\nexit 0\n')
    write_exe(os.path.join(bindir, 'ps'), '#!/bin/sh\necho "ps $*" >> "$FAKE_PS_CALLS"\nexit 1\n')
    write_exe(os.path.join(bindir, 'cp'), r'''#!/bin/sh
/bin/cp "$@" || exit $?
if [ "${FAKE_CP:-good}" = corrupt ]; then
  for last; do :; done
  case "$last" in *nfs*) [ -f "$last" ] && echo junk >> "$last" ;; esac
fi
exit 0
''')


def main():
    failures = 0
    os.umask(0o022)             # root's umask on the target; the host user's 002 would make tables group-writable
    print('== lint ==')
    failures += lint()

    work = tempfile.mkdtemp(prefix='chk_target_r2b0.', dir=os.environ.get('TMPDIR'))
    bindir = os.path.join(work, 'bin')
    owners = os.path.join(work, 'owners')
    fake_tools(bindir, owners)
    ps_calls = os.path.join(work, 'ps.calls')

    def env_for(tmp, **extra):
        e = dict(os.environ, PATH=bindir + ':' + os.environ['PATH'], R2B0_TMP=tmp,
                 R2B0_SUM=os.path.join(bindir, 'sum'), R2B0_KERNEL='/fake/mach_kernel', R2B0_CC=os.path.join(bindir, 'cc'),
                 R2B0_NFSOUT=os.path.join(tmp, 'nfs', 'build', 'r2b0'), R2B0_DRV=os.path.join(tmp, 'drv'),
                 R2B0_LS=os.path.join(bindir, 'ls'), R2B0_ME=os.path.join(tmp, 'me', 'rdn-r2b0'),
                 R2B0_RANDIR=os.path.join(tmp, 'me', 'rdn-r2b0-ran.d'), R2B0_MSGS=os.path.join(tmp, 'messages'),
                 R2B0_LOGGER=os.path.join(bindir, 'logger'), R2B0_KLUTIL=os.path.join(bindir, 'kl_util'),
                 FAKE_PS_CALLS=ps_calls)
        e.update(extra)
        return e

    def run_sh(script, args, env, cwd):
        r = subprocess.run(['/bin/sh', os.path.join(HERE, script)] + args, env=env, cwd=cwd,
                           capture_output=True, text=True, timeout=300)
        return r.returncode, r.stdout + r.stderr

    def fresh(label):
        t = os.path.join(work, re.sub(r'\W+', '_', label))
        os.makedirs(os.path.join(t, 'nfs', 'build', 'r2b0'))
        os.makedirs(os.path.join(t, 'drv'))
        os.makedirs(os.path.join(t, 'me'))
        return t

    def report(label, ok, rc, out, n=10):
        nonlocal failures
        if os.path.exists(ps_calls):
            ok = False
            out += '\nps was called'
            os.remove(ps_calls)
        print('  %-4s %-48s rc=%s%s' % ('ok' if ok else 'FAIL', label, rc,
                                        '' if ok else '\n' + '\n'.join('       ' + l for l in out.splitlines()[-n:])))
        failures += 0 if ok else 1

    # ---- build ----
    runid = 515151
    pk_ = subprocess.run([sys.executable, os.path.join(HERE, 'pack_r2b0.py'), '--skip-hostcheck', '--runid', str(runid),
                          '--out-dir', os.path.join(work, 'out')], capture_output=True, text=True,
                         env=dict(os.environ, TMPDIR=work))
    if pk_.returncode != 0:
        print(pk_.stdout, pk_.stderr)
        print('check_target_r2b0: FAIL (pack)')
        return 1
    tarpath = re.search(r'packed\s+(\S+)', pk_.stdout).group(1)
    stamp = re.search(r'stamp\s+(\S+)', pk_.stdout).group(1)
    unchecked = (tarpath,) + tuple(re.search(r'sum\s+(\d+) (\d+)', pk_.stdout).groups())
    checked = os.path.join(work, 'checked.tar')
    with tarfile.open(tarpath) as src, tarfile.open(checked, 'w', format=tarfile.USTAR_FORMAT) as dst:
        for m in src.getmembers():
            data = src.extractfile(m).read() if m.isfile() else None
            if m.name.endswith('/MANIFEST'):
                data = b''.join(l for l in data.splitlines(True) if not l.startswith(b'UNCHECKED'))
                m.size = len(data)
            dst.addfile(m, io.BytesIO(data) if data is not None else None)
    s = pk.bsdsum(open(checked, 'rb').read()).split()
    # the same tree with the postamble's key already in a source table
    srcserver = os.path.join(work, 'srcserver.tar')
    with tarfile.open(checked) as src, tarfile.open(srcserver, 'w', format=tarfile.USTAR_FORMAT) as dst:
        for m in src.getmembers():
            data = src.extractfile(m).read() if m.isfile() else None
            if m.name.endswith('OSRDNDisplay/Default.table'):
                data = data + b'"Server Name" = "OSRDNDisplay";\n'
                m.size = len(data)
            dst.addfile(m, io.BytesIO(data) if data is not None else None)
    ss = pk.bsdsum(open(srcserver, 'rb').read()).split()

    print('== target-build-r2b0.sh ==')
    build_cases = [
        ('good', {}, None, 0, 'OSRDNBUILD PASS stamp=%s runid=%d' % (stamp, runid)),
        ('wrong sum', {}, 'sum', 1, 'sum differs'),
        ('no arguments', {}, 'noargs', 2, 'usage'),
        ('tree skipped the host gate', {}, 'unchecked', 1, 'UNCHECKED'),
        ('make fails', {'FAKE_MAKE': 'fail'}, None, 1, 'make exited'),
        ('make gives no product', {'FAKE_MAKE': 'noproduct'}, None, 1, 'no product'),
        ('product ADVERTISEs', {'FAKE_MAKE': 'advertise'}, None, 1, 'not WIRE alone'),
        ('built Instance0 lacks the key', {'FAKE_MAKE': 'nokey'}, None, 1, 'RDN R2B0 Record'),
        ('built bundle has no Display.modes', {'FAKE_MAKE': 'nomodes'}, None, 1, 'no Display.modes'),
        ('built table says Display Mode twice', {'FAKE_MAKE': 'twomodes'}, None, 1, 'exactly one "Display Mode"'),
        ('built table has no Display Mode', {'FAKE_MAKE': 'nomode'}, None, 1, 'exactly one "Display Mode"'),
        ('built table names the server twice', {'FAKE_MAKE': 'twoservers'}, None, 1, 'exactly one "Server Name"'),
        ('built table names another server too', {'FAKE_MAKE': 'otherserver'}, None, 1, 'exactly one "Server Name"'),
        ('built bundle has no inspector nib', {'FAKE_MAKE': 'nonib'}, None, 1, 'DisplayInspector.nib/data.nib'),
        ('built inspector data.classes is empty', {'FAKE_MAKE': 'emptynib'}, None, 1, 'DisplayInspector.nib/data.classes'),
        ('built bundle has no executable', {'FAKE_MAKE': 'noexe'}, None, 1, 'has no executable'),
        ('executable does not define the inspector', {'FAKE_MAKE': 'noclass'}, None, 1, 'does not define OSRDNDisplayInspector'),
        ('source table names the server itself', {}, 'srcserver', 1, 'postamble appends that line'),
        ('symbol not in kernel', {'FAKE_MAKE': 'missing'}, None, 1, 'missing from the kernel'),
        ('no _basicConsoleMode reference', {'FAKE_MAKE': 'nobcm'}, None, 1, '_basicConsoleMode'),
        ('tool does not compile', {'FAKE_CC': 'fail'}, None, 1, 'cc exited'),
        ('the mapping tool does not compile (R4c)', {'FAKE_CC': 'fail4'}, None, 1, 'cc rdnr4map exited'),
        ('the CP tool does not compile (R5)', {'FAKE_CC': 'fail5'}, None, 1, 'cc rdnr5cp exited'),
        ('NFS copy corrupted', {'FAKE_CP': 'corrupt'}, None, 1, 'copy on'),
        ('run id built before', {}, 'nfsdir', 1, 'was built before'),
    ]
    good_tmp = None
    for label, extra, prep, want_rc, want in build_cases:
        tmp = fresh('build-' + label)
        args = [checked, s[0], s[1]]
        if prep == 'sum':
            args = [checked, '%05d' % ((int(s[0]) + 1) % 65536), s[1]]
        elif prep == 'noargs':
            args = []
        elif prep == 'unchecked':
            args = list(unchecked)
        elif prep == 'srcserver':
            args = [srcserver, ss[0], ss[1]]
        elif prep == 'nfsdir':
            os.makedirs(os.path.join(tmp, 'nfs', 'build', 'r2b0', str(runid)))
        rc, out = run_sh('target-build-r2b0.sh', args, env_for(tmp, **extra), tmp)
        ok = rc == want_rc and want in out
        nfs = os.path.join(tmp, 'nfs', 'build', 'r2b0', str(runid))
        if want_rc == 0 and ok:
            bp = open(os.path.join(nfs, 'BUILD_PASS')).read().split()
            reloc = os.path.join(tmp, 'OSRDNDisplay-r2b0', 'OSRDNDisplay', 'OSRDNDisplay.config', 'OSRDNDisplay_reloc')
            ok = (bp[:2] == [stamp, str(runid)] and ' '.join(bp[2:4]) == pk.bsdsum(open(reloc, 'rb').read()) and
                  b'OTHER_CFLAGS=-DOSRDN_BUILD=0x' + stamp.encode() in open(reloc, 'rb').read() and
                  os.path.exists(os.path.join(nfs, 'rdnr2b0')) and
                  os.path.exists(os.path.join(nfs, 'rdnr4map')) and
                  os.path.exists(os.path.join(nfs, 'rdnr5cp')) and
                  open(os.path.join(nfs, 'rdnr4map.sum')).read().split() ==
                  pk.bsdsum(open(os.path.join(nfs, 'rdnr4map'), 'rb').read()).split() and
                  'OSRDNDisplayInspector.m' in open(os.path.join(nfs, 'make-cc.txt')).read())
            good_tmp = tmp
        if want_rc != 0 and os.path.exists(os.path.join(nfs, 'BUILD_PASS')):
            ok = False
            out += '\nBUILD_PASS written by a failing build'
        report(label, ok, rc, out)
    if good_tmp is None:
        print('check_target_r2b0: FAIL (no good build)')
        return 1

    # ---- install ----
    print('== target-install-r2b0.sh ==')
    ev = os.path.join(PROJ, 'build', 'r2b0', 'emu10k1')
    SYSTEM = open(os.path.join(ev, 'System.Instance0.after-configure-1456'), 'rb').read()
    EMU = open(os.path.join(ev, 'EMU10K1.Instance0.after-configure-1456'), 'rb').read()
    VGA = open(os.path.join(ev, 'VGA.Instance0.after-configure-1456'), 'rb').read()
    SYSDEF = b'"Active Drivers" = "PS2Mouse BusMouse SerialPointingDevice ParallelPort VGA";\n"Boot Drivers" = "PS2Keyboard";\n'

    def machine(tmp, system=SYSTEM):
        drv = os.path.join(tmp, 'drv')
        for rel, data in (('System.config/Instance0.table', system), ('System.config/Default.table', SYSDEF),
                          ('EMU10K1.config/Instance0.table', EMU), ('VGA.config/Instance0.table', VGA)):
            os.makedirs(os.path.join(drv, os.path.dirname(rel)), exist_ok=True)
            open(os.path.join(drv, rel), 'wb').write(data)
            os.chmod(os.path.join(drv, rel), 0o644)
        return drv

    def install_tmp(label, marker=True):
        tmp = fresh('install-' + label)
        shutil.copytree(os.path.join(good_tmp, 'OSRDNDisplay-r2b0'), os.path.join(tmp, 'OSRDNDisplay-r2b0'))
        shutil.copytree(os.path.join(good_tmp, 'nfs', 'build', 'r2b0', str(runid)),
                        os.path.join(tmp, 'nfs', 'build', 'r2b0', str(runid)))
        nfs = os.path.join(tmp, 'nfs', 'build', 'r2b0', str(runid))
        if marker:
            open(os.path.join(nfs, 'R2B0RELOC_PASS'), 'w').write(open(os.path.join(nfs, 'reloc.sum')).read())
        machine(tmp)
        return tmp, nfs

    install_cases = [
        ('first install', None, 0, 'INSTALL DONE'),
        ('upgrade keeps the machine instance table', 'upgrade', 0, 'kept the machine'),
        ('upgrade over a table with the server named twice stops', 'dupserver', 1, 'needs \'fresh\''),
        ('fresh installs the build\'s table over it', 'fresh', 0, 'fresh: the build'),
        ('a second argument that is not fresh', 'badfresh', 2, 'usage'),
        ('no closed=yes', 'noclosed', 2, 'usage'),
        ('no reloc marker', 'nomarker', 1, 'no R2B0RELOC_PASS'),
        ('reloc marker for other bytes', 'othermarker', 1, 'does not name these reloc bytes'),
        ('Active Drivers names OSRDNDisplay', 'active', 1, 'Active Drivers names OSRDNDisplay'),
        ('live installs under the active driver', 'activelive', 0, 'live: replacing the bundle'),
        ('live is recorded in the INSTALLED marker', 'activelive', 0, 'INSTALL DONE'),
        ('build marker differs from NFS', 'buildpass', 1, 'differ'),
        ('owner not root (chown fails)', 'chownfail', 1, 'chown failed'),
        ('built bundle lost its inspector nib', 'nonib', 1, 'missing or empty member: English.lproj/DisplayInspector.nib/data.nib'),
        ('built bundle lost its executable', 'noexe', 1, 'missing or empty member: OSRDNDisplay'),
    ]
    for label, prep, want_rc, want in install_cases:
        tmp, nfs = install_tmp(label, marker=prep != 'nomarker')
        args = ['closed=yes']
        extra = {}
        dst = os.path.join(tmp, 'drv', 'OSRDNDisplay.config')
        machine_table = '"Title" = "machine";\n"RDN R2B0 Record" = "Yes";\n"Server Name" = "OSRDNDisplay";\n'
        if prep in ('upgrade', 'dupserver', 'fresh'):
            os.makedirs(dst)
            t = machine_table
            if prep in ('dupserver', 'fresh'):
                t = t + '"Server Name" = "OSRDNDisplay";\n'     # what the 2026-09-16 build left installed
            open(os.path.join(dst, 'Instance0.table'), 'w').write(t)
            open(os.path.join(dst, 'OSRDNDisplay_reloc'), 'w').write('old')
            if prep == 'fresh':
                args = ['closed=yes', 'fresh']
        elif prep == 'badfresh':
            args = ['closed=yes', 'stale']
        elif prep == 'noclosed':
            args = []
        elif prep == 'othermarker':
            open(os.path.join(nfs, 'R2B0RELOC_PASS'), 'w').write('12345 1\n')
        elif prep == 'active':
            open(os.path.join(tmp, 'drv', 'System.config', 'Instance0.table'), 'wb').write(SYSTEM.replace(b' VGA"', b' OSRDNDisplay"'))
        elif prep == 'activelive':
            # the same machine state as 'active', but the operator asked for it:
            # gate 2 refuses without "live" (the case above) and proceeds with it
            open(os.path.join(tmp, 'drv', 'System.config', 'Instance0.table'), 'wb').write(SYSTEM.replace(b' VGA"', b' OSRDNDisplay"'))
            args = ['closed=yes', 'fresh', 'live']
        elif prep == 'buildpass':
            open(os.path.join(tmp, 'OSRDNDisplay-r2b0', 'OSRDNBUILD_PASS'), 'w').write('x\n')
        elif prep == 'chownfail':
            extra['FAKE_CHOWN'] = 'fail'
        elif prep in ('nonib', 'noexe'):
            # the build's gate 5 would refuse these; this is the install's own
            # MEMBERS check catching a bundle damaged after the build
            built = os.path.join(tmp, 'OSRDNDisplay-r2b0', 'OSRDNDisplay', 'OSRDNDisplay.config')
            os.remove(os.path.join(built, 'English.lproj/DisplayInspector.nib/data.nib' if prep == 'nonib'
                                   else 'OSRDNDisplay'))
        rc, out = run_sh('target-install-r2b0.sh', args, env_for(tmp, **extra), tmp)
        ok = rc == want_rc and want in out
        if want_rc == 0 and ok:
            inst = open(os.path.join(dst, 'Instance0.table')).read()
            ok = open(os.path.join(dst, 'OSRDNDisplay_reloc'), 'rb').read() == \
                open(os.path.join(tmp, 'OSRDNDisplay-r2b0', 'OSRDNDisplay', 'OSRDNDisplay.config', 'OSRDNDisplay_reloc'), 'rb').read()
            if prep == 'upgrade':
                ok = ok and inst.startswith('"Title" = "machine"') and os.path.exists(dst + '.prev')
            elif prep == 'fresh':
                # the build's table is installed and the machine's, duplicate
                # line and all, is still in .prev
                ok = (ok and '"RDN R2B0 Record" = "Yes";' in inst and 'machine' not in inst and
                      inst.count('"Server Name"') == 1 and
                      open(os.path.join(dst + '.prev', 'Instance0.table')).read().count('"Server Name"') == 2)
            else:
                ok = ok and '"RDN R2B0 Record" = "Yes";' in inst
            ok = ok and os.path.exists(os.path.join(nfs, 'INSTALLED')) and not os.path.exists(dst + '.new')
        elif want_rc != 0 and os.path.exists(os.path.join(dst, 'OSRDNDisplay_reloc')) and \
                prep not in ('upgrade', 'dupserver', 'fresh'):
            ok = False
            out += '\ninstalled by a failing run'
        report(label, ok, rc, out)

    # ---- restore path (R-1) ----
    print('== R-1 on a fake machine: snapshot, restore set, Configure, restore ==')
    tmp = fresh('restore')
    drv = machine(tmp)
    env = env_for(tmp)
    nfsroot = os.path.join(tmp, 'nfs')           # stands for the project root on NFS
    snaps = os.path.join(nfsroot, 'build', 'r2b0', 'cfg', 'R1')
    pcils = os.path.join(PROJ, 'logs-pcils-20260915.txt')

    def step(label, script, args, want_rc, want, e=env):
        rc, out = run_sh(script, args, e, tmp)
        report(label, rc == want_rc and want in out, rc, out)
        return rc, out

    def host(label, argv, want_rc):
        rc, out = cd.run(['check_cfgdiff.py'] + argv)
        report(label, rc == want_rc, rc, '\n'.join(out))
        return rc, out

    step('cfgsnap pre', 'target-cfgsnap-r2b0.sh', ['pre', 'R1', 'closed=yes'], 0, 'CFGSNAP DONE pre R1 tables=4')
    step('cfgsnap refuses to overwrite', 'target-cfgsnap-r2b0.sh', ['pre', 'R1', 'closed=yes'], 1, 'never overwritten')
    step('cfgsnap refuses without closed=yes', 'target-cfgsnap-r2b0.sh', ['post', 'R1'], 1, 'closed=yes')
    host('check_cfgdiff precheck', ['precheck', os.path.join(snaps, 'pre'), '--pcils', pcils], 0)
    try:
        out_dir, _, _ = pr.pack(nfsroot, 'R1')
        report('pack_restore_r2b0', os.path.exists(os.path.join(out_dir, 'SUMS')), 0, '')
    except Exception as e:
        report('pack_restore_r2b0', False, 1, str(e))
    try:
        pr.pack(nfsroot, 'R1')
        report('pack_restore refuses to rewrite a set', False, 0, 'packed twice')
    except ValueError as e:
        report('pack_restore refuses to rewrite a set', 'never rewritten' in str(e), 1, str(e))
    step('stage', 'target-stage-restore-r2b0.sh', ['R1'], 0, 'STAGE DONE R1 tables=3')
    me = os.path.join(tmp, 'me', 'rdn-r2b0')
    step('stage refuses a second time', 'target-stage-restore-r2b0.sh', ['R1'], 1, 'never overwritten')
    step('check.sh right after staging: no difference', 'me/check.sh', [], 0, 'differ=0 extra=0')
    # Configure-like activation
    # Configure makes the instance from the INSTALLED Default.table, which is
    # the source table plus what the bundle postamble appended
    kv = cd.expected_driver_kv(open(os.path.join(PROJ, 'OSRDNDisplay', 'Default.table'), 'rb').read(), 'shipped')
    made = ''.join('"%s" = "%s";\n' % (k, kv[k]) for k in reversed(list(kv))) + '"Default Table" = "Default";\n'
    ad = cd.parse_table(SYSTEM, 's')['Active Drivers']
    sysl = [l for l in SYSTEM.decode().splitlines()]
    sysl = [l.replace(ad, ad.replace('VGA', 'OSRDNDisplay')) for l in reversed(sysl)]
    open(os.path.join(drv, 'System.config', 'Instance0.table'), 'w').write('\n'.join(sysl) + '\n')
    emul = EMU.decode().splitlines()
    open(os.path.join(drv, 'EMU10K1.config', 'Instance0.table'), 'w').write('\n'.join(emul[1:] + emul[:1]) + '\n')
    os.remove(os.path.join(drv, 'VGA.config', 'Instance0.table'))
    os.makedirs(os.path.join(drv, 'OSRDNDisplay.config'))
    open(os.path.join(drv, 'OSRDNDisplay.config', 'Instance0.table'), 'w').write(made)
    # Configure also ADDS a second instance with the real slot (measured 2026-09-16),
    # and the installed bundle carries Default.table (postamble line included)
    shipped = open(os.path.join(PROJ, 'OSRDNDisplay', 'Default.table'), 'rb').read()
    installed_def = shipped + b'"Server Name" = "OSRDNDisplay";\n'
    open(os.path.join(drv, 'OSRDNDisplay.config', 'Default.table'), 'wb').write(installed_def)
    made1 = made.replace('"Instance" = "0";', '"Instance" = "1";').replace(
        '"Location" = "";', '"Location" = "Dev:11 Func:0 Bus:3";')
    inst1 = os.path.join(drv, 'OSRDNDisplay.config', 'Instance1.table')
    open(inst1, 'w').write(made1)

    print('== target-park-extra-r2b0.sh ==')
    step('park refuses before the postraw snapshot exists', 'target-park-extra-r2b0.sh', ['closed=yes'], 2, 'postraw/LIST')
    step('cfgsnap postraw', 'target-cfgsnap-r2b0.sh', ['postraw', 'R1', 'closed=yes'], 0, 'tables=5')
    step('park refuses without closed=yes', 'target-park-extra-r2b0.sh', [], 2, 'usage')
    stranger = os.path.join(drv, 'EMU10K1.config', 'Instance1.table')
    open(stranger, 'w').write(open(os.path.join(drv, 'EMU10K1.config', 'Instance0.table')).read())
    step('park refuses while a stranger table is there', 'target-park-extra-r2b0.sh', ['closed=yes'], 3, 'nobody expected')
    os.remove(stranger)
    bad = os.path.join(drv, 'OSRDNDisplay.config', 'Instance9x.table')
    open(bad, 'w').write(made1)
    step('park refuses an odd instance file name', 'target-park-extra-r2b0.sh', ['closed=yes'], 3, 'unexpected instance table name')
    os.remove(bad)
    saved0 = open(os.path.join(drv, 'OSRDNDisplay.config', 'Instance0.table')).read()
    os.remove(os.path.join(drv, 'OSRDNDisplay.config', 'Instance0.table'))
    step('park refuses when Instance0 is the missing one', 'target-park-extra-r2b0.sh', ['closed=yes'], 3, 'a person has to look')
    open(os.path.join(drv, 'OSRDNDisplay.config', 'Instance0.table'), 'w').write(
        saved0.replace('"Auto Detect IDs" = "0x59601002";', '"Auto Detect IDs" = "0x00000000";'))
    step('park refuses when Instance0 is not the installed Default.table',
         'target-park-extra-r2b0.sh', ['closed=yes'], 3, 'not the installed Default.table')
    open(os.path.join(drv, 'OSRDNDisplay.config', 'Instance0.table'), 'w').write(saved0)
    rc, out = step('park', 'target-park-extra-r2b0.sh', ['closed=yes'], 0, 'PARK DONE tag=R1 parked=1')
    me_park = os.path.join(tmp, 'me', 'rdn-r2b0', 'parked-activate.R1', 'OSRDNDisplay.config', 'Instance1.table')
    report('the surplus instance is parked in /me and gone from the bundle',
           os.path.exists(me_park) and not os.path.exists(inst1) and
           os.path.exists(os.path.join(drv, 'OSRDNDisplay.config', 'Instance0.table')), rc, out)
    step('park refuses to overwrite a park', 'target-park-extra-r2b0.sh', ['closed=yes'], 3, 'never overwritten')

    step('cfgsnap post', 'target-cfgsnap-r2b0.sh', ['post', 'R1', 'closed=yes'], 0, 'tables=4')
    host('check_cfgdiff activate', ['activate', os.path.join(snaps, 'pre'), os.path.join(snaps, 'post')], 0)
    step('check.sh on the activated tables: differences and one extra', 'me/check.sh', [], 0, 'differ=3 extra=1')
    # a table owned by someone else is put right by the restore
    vga_dir_owner = os.path.join(owners, str(os.stat(os.path.join(drv, 'EMU10K1.config', 'Instance0.table')).st_ino))
    open(vga_dir_owner, 'w').write('me wheel\n')
    step('restore.sh', 'me/restore.sh', [], 0, 'RESTORE DONE set=R1 tables=3 wrote=3 parked=1')
    report('the parked driver table is kept in /me', os.path.exists(os.path.join(me, 'parked.R1', 'OSRDNDisplay.config',
                                                                               'Instance0.table')), 0, '')
    step('cfgsnap post3', 'target-cfgsnap-r2b0.sh', ['post3', 'R1', 'closed=yes'], 0, 'tables=4')
    host('check_cfgdiff restored', ['restored', os.path.join(snaps, 'pre'), os.path.join(snaps, 'post3')], 0)
    step('restore.sh again: nothing to write', 'me/restore.sh', [], 0, 'wrote=0 parked=0')

    # refusals
    before = dict((r, open(os.path.join(drv, r), 'rb').read()) for r in
                  ('System.config/Instance0.table', 'EMU10K1.config/Instance0.table', 'VGA.config/Instance0.table'))
    open(os.path.join(drv, 'VGA.config', 'Instance0.table'), 'ab').write(b'"X" = "1";\n')
    setf = os.path.join(me, 'set.R1', 'EMU10K1.config', 'Instance0.table')
    good_set = open(setf, 'rb').read()
    open(setf, 'ab').write(b'\n')
    rc, out = run_sh('me/restore.sh', [], env, tmp)
    report('restore.sh with a corrupted set writes nothing (exit 2)',
           rc == 2 and 'sums' in out and open(os.path.join(drv, 'VGA.config', 'Instance0.table'), 'rb').read().endswith(b'"X" = "1";\n'),
           rc, out)
    rc, out = run_sh('me/check.sh', [], env, tmp)
    report('check.sh with a corrupted set exits 2', rc == 2 and 'CHECK FAIL' in out, rc, out)
    open(setf, 'wb').write(good_set)
    shutil.rmtree(os.path.join(drv, 'EMU10K1.config'))
    rc, out = run_sh('me/restore.sh', [], env, tmp)
    report('restore.sh with a bundle directory gone: exit 4, no directory made',
           rc == 4 and 'not creating one' in out and not os.path.exists(os.path.join(drv, 'EMU10K1.config')), rc, out)
    rc, out = run_sh('me/restore.sh', [], dict(env, R2B0_ME=os.path.join(tmp, 'nome')), tmp)
    report('restore.sh with no CURRENT: exit 2', rc == 2, rc, out)
    del before

    # ---- run ----
    print('== target-run-r2b0.sh ==')
    rid = 4343                                          # the simulator world's run id
    simexe = os.path.join(work, 'sim')
    okb, err = sim.build(sim.RECORD, sim.PLLSRC, simexe)
    if not okb:
        print(err)
        print('check_target_r2b0: FAIL (sim build)')
        return 1
    world = os.path.join(work, 'world.txt')
    open(world, 'w').write(sim.world())
    toolsrc = r'''#!/bin/sh
mode=${FAKE_TOOL:-good}
[ "$mode" = exit4 ] && { echo "RDNR2B0 exit=4 why=display-info"; exit 4; }
if [ "$3" = state ]; then
  # the driver logs one line when the tool reads State; nothing touches hardware
  [ "${FAKE_STATE:-good}" = drop ] || echo "Sep 16 10:00:00 nextonion mach: RDN-R2B0 state boot=2a05f200 build=1234abcd records=0 last=0 flags=03580101 cmode=1 loc=03:0b.0" >> "$R2B0_MSGS"
  echo "RDNR2B0 state when=before nonce=2a05f200 build=1234abcd enter=1 revert=1 records=0 lastrunid=0 lastresult=0 lastlines=0 flags=03580101 key=1 latched=0 busy=0 cmode=1 loc=358"
  echo "RDNR2B0 exit=0 state-only"
  exit 0
fi
"%s" < "%s" > "$R2B0_TMP/sim.out" 2> "$R2B0_TMP/sim.err"
grep 'RDN-R2B0 ' "$R2B0_TMP/sim.out" | grep -v 'RDN-R2B0-MARK' | grep -v 'RDN-R2B0 probe' | grep -v 'RDN-R2B0 init' > "$R2B0_TMP/sim.lines"
if [ "$mode" = noend ]; then grep -v ' end lines=' "$R2B0_TMP/sim.lines" >> "$R2B0_MSGS"; else cat "$R2B0_TMP/sim.lines" >> "$R2B0_MSGS"; fi
grep '^RDNR2B0 state' "$R2B0_TMP/sim.out"
echo "RDNR2B0 exit=0"
exit 0
''' % (simexe, world)

    def run_tmp(label):
        t = fresh('run-' + label)
        d = machine(t, system=SYSTEM.replace(b' VGA"', b' OSRDNDisplay"'))
        os.remove(os.path.join(d, 'VGA.config', 'Instance0.table'))
        os.makedirs(os.path.join(d, 'OSRDNDisplay.config'))
        reloc = os.path.join(d, 'OSRDNDisplay.config', 'OSRDNDisplay_reloc')
        open(reloc, 'wb').write(b'reloc bytes')
        nfs = os.path.join(t, 'nfs', 'build', 'r2b0', str(rid))
        os.makedirs(nfs)
        write_exe(os.path.join(nfs, 'rdnr2b0'), toolsrc)
        rsum = pk.bsdsum(open(reloc, 'rb').read())
        tsum = pk.bsdsum(open(os.path.join(nfs, 'rdnr2b0'), 'rb').read())
        open(os.path.join(nfs, 'BUILD_PASS'), 'w').write('1234abcd %d %s %s\n' % (rid, rsum, tsum))
        open(os.path.join(nfs, 'R2B0RELOC_PASS'), 'w').write(rsum + '\n')
        open(os.path.join(nfs, 'INSTALLED'), 'w').write('%d %s closed=yes date\n' % (rid, rsum))
        shutil.copytree(me, os.path.join(t, 'me', 'rdn-r2b0'))
        open(os.path.join(t, 'messages'), 'w').write('Sep 16 09:00:00 old line\n')
        return t, nfs

    # want_done: 'DONE', 'FAIL', or None when the step that fails runs before
    # the run id is claimed (nothing may be written to run.done then)
    run_cases = [
        ('good, parsed end to end', None, {}, 0, 'R2B0RUN DONE', 'DONE'),
        ('run id already run', 'ran', {}, 1, 'already run', None),
        ('tool bytes differ', 'tool', {}, 1, 'tool copy', None),
        ('installed reloc differs', 'reloc', {}, 1, 'installed reloc', None),
        ('not the activation boot', 'vga', {}, 1, 'does not name OSRDNDisplay', None),
        ('restore set not staged', 'nome', {}, 1, 'never staged', None),
        ('the state line never reaches syslog', None, {'FAKE_STATE': 'drop'}, 1, 'state line did not reach', None),
        ('tool exits 4 at the State read (before the run id is claimed)', None, {'FAKE_TOOL': 'exit4'}, 1,
         'State read failed (exit 4)', None),
        ('record end line missing', None, {'FAKE_TOOL': 'noend'}, 1, 'no end line', 'FAIL'),
    ]
    for label, prep, extra, want_rc, want, want_done in run_cases:
        t, nfs = run_tmp(label)
        if prep == 'ran':
            os.makedirs(os.path.join(t, 'me', 'rdn-r2b0-ran.d', str(rid)))
            open(os.path.join(nfs, 'run.done'), 'w').write('R2B0RUN DONE earlier run\n')
        elif prep == 'tool':
            open(os.path.join(nfs, 'rdnr2b0'), 'a').write('# changed\n')
        elif prep == 'reloc':
            open(os.path.join(t, 'drv', 'OSRDNDisplay.config', 'OSRDNDisplay_reloc'), 'ab').write(b'x')
        elif prep == 'vga':
            open(os.path.join(t, 'drv', 'System.config', 'Instance0.table'), 'wb').write(SYSTEM)
        elif prep == 'nome':
            shutil.rmtree(os.path.join(t, 'me', 'rdn-r2b0'))
        rc, out = run_sh('target-run-r2b0.sh', [str(rid)], env_for(t, **extra), t)
        ok = rc == want_rc and want in out
        done = os.path.join(nfs, 'run.done')
        got_done = open(done).read() if os.path.exists(done) else ''
        if want_done is None:
            if prep == 'ran':
                if got_done != 'R2B0RUN DONE earlier run\n':
                    ok = False
                    out += '\nthe earlier run.done was overwritten: %r' % got_done
            elif got_done:
                ok = False
                out += '\nrun.done written before the run id was claimed: %r' % got_done
        elif not got_done.startswith('R2B0RUN ' + want_done):
            ok = False
            out += '\nrun.done %r' % got_done
        if want_rc == 0 and ok:
            log = open(os.path.join(nfs, 'rdn-r2b0-%d.log' % rid)).read()
            tool = open(os.path.join(nfs, 'rdnr2b0.out')).read()
            rep, fail, rec, klass = pb.judge(log, str(rid), '1234abcd', tool)
            if klass != 'PASS-ENTER':
                ok = False
                out += '\nparse_r2b0 %s: %s' % (klass, fail[:3])
        report(label, ok, rc, out)

    shutil.rmtree(work, ignore_errors=True)
    print('check_target_r2b0:', 'PASS' if failures == 0 else 'FAIL (%d)' % failures)
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
