#!/usr/bin/env python3
"""Run tools/r1c/target-r1c.sh under /bin/sh on the host, with fake target tools.

  check_target_r1c.py     lint + every case; exit 1 on any failure

The fake target:
  - cc      builds nothing: checks its arguments are exactly -O -o <exe> <src>
            and copies in rdnbios.c compiled on the host (unchanged source,
            RDN_MEM_PATH pointing at a fake memory device) -- so the script
            runs the real program, whose output the host then compares
  - sum     the BSD algorithm of tools/r1/pack_probe.py (checked there against
            a value recorded on the target)
  - ps      records that it was called and fails: the script must never run
            ps (on the target `ps ax' from a background job never returned)
  - logger  records its arguments
  - sync    does nothing
The overrides are the R1C_* variables of target-r1c.sh; nothing on the target
sets them.  The lint rules are tools/r1/check_target_scripts.py's, imported.
"""

import importlib.util
import os
import shutil
import stat
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
SCRIPT = os.path.join(HERE, 'target-r1c.sh')


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


r1scripts = _load('check_target_scripts', os.path.join(PROJ, 'tools', 'r1', 'check_target_scripts.py'))
pack = _load('pack_probe', os.path.join(PROJ, 'tools', 'r1', 'pack_probe.py'))
sim = _load('sim_r1c', os.path.join(HERE, 'sim_r1c.py'))

import re  # noqa: E402


# rules found on the real target, 2026-09-15 (R1c facts run 789463413)
TARGET_RULES = [
    (r'(^|[;&|`(\s])ps\b', 'ps (never returns from a background job on the target)',
     'n=`ps ax | grep x`'),
    (r'\$\{\w+:-[^}"]*\s[^}]*\}', 'a blank inside an unquoted ${NAME:-default} ("bad substitution")',
     'X=${Y:-/a /b}'),
]


def positional_misuse(text):
    """$1..$9 outside a function body and after the first function definition,
    or any `set --`.  The target sh does not restore the positional parameters
    after a function call (probe 2026-09-15: set -- A B; f X; echo $1 -> X), and
    the host's /bin/sh does, so only a text rule can see this."""
    bad = []
    in_function = False
    seen_function = False
    for n, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith('#'):
            continue
        code = re.sub(r"'[^']*'", "''", line)          # awk '{print $1}' is not the shell's $1
        if re.match(r'^\s*\w+\(\)\s*\{', code):
            in_function = seen_function = True
            continue
        if in_function:
            if re.match(r'^\}\s*$', code):
                in_function = False
            continue
        if re.search(r'\bset\s+--', code):
            bad.append('line %d uses set --: %s' % (n, line.strip()))
        if seen_function and re.search(r'\$[1-9]', code):
            bad.append('line %d uses a positional parameter after a function definition: %s' % (n, line.strip()))
    return bad


def lint():
    bad = []
    for pat, what, probe in TARGET_RULES:
        if not re.search(pat, probe):
            bad.append('lint rule %r does not match its own probe %r' % (what, probe))
    data = open(SCRIPT, 'rb').read()
    if any(b > 0x7e or (b < 0x20 and b not in (9, 10)) for b in data):
        bad.append('non-ASCII byte')
    for n, line in enumerate(data.decode('ascii', 'replace').splitlines(), 1):
        code = line if not line.lstrip().startswith('#') else ''
        for pat, what in r1scripts.FORBIDDEN:
            if re.search(pat, code):
                bad.append('line %d uses %s: %s' % (n, what, line.strip()))
        for pat, what, _ in TARGET_RULES:
            if re.search(pat, code):
                bad.append('line %d uses %s: %s' % (n, what, line.strip()))
    # every override the script reads is one this harness sets
    bad += positional_misuse(data.decode('ascii', 'replace'))
    names = set(re.findall(r'\$\{(R1C_\w+):-', data.decode('ascii', 'replace')))
    if names != set(ENV_NAMES):
        bad.append('override names %s != harness %s' % (sorted(names), sorted(ENV_NAMES)))
    if re.search(r'\$\{R1_\w+', data.decode('ascii', 'replace')):
        bad.append('an R1_ override name in the R1c script')
    return bad


ENV_NAMES = ['R1C_TMP', 'R1C_SRC', 'R1C_OUT', 'R1C_RANDIR', 'R1C_SUM', 'R1C_CC', 'R1C_SYSCFG',
             'R1C_MEMDEV', 'R1C_LOGGER1', 'R1C_LOGGER2', 'R1C_LOGGER3']


def write_exe(path, text):
    open(path, 'w').write(text)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)


def setup(root, drivers='"Active Drivers" = "SpaceSaver2Mouse Pro1000 EMU10K1 VGA";',
          cc_ok=True, mem='full', logger=True, randir_parent=True, out_dir=True, bad_cp=False):
    tmp = os.path.join(root, 'tmp')
    bindir = os.path.join(root, 'bin')
    out = os.path.join(root, 'out')
    me = os.path.join(root, 'me')
    for d in (tmp, bindir, me):
        os.makedirs(d, exist_ok=True)
    if out_dir:
        os.makedirs(out, exist_ok=True)
    src = os.path.join(root, 'rdnbios.c')
    shutil.copy(sim.SRC, src)
    memdev = os.path.join(root, 'fakemem')
    if mem == 'full':
        sim.fake_device(memdev, sim.pattern(0x10000), sim.BIOS_PHYS + 0x10000 + 4096)
    prebuilt = os.path.join(root, 'prebuilt-rdnbios')
    real_mem = memdev if mem != 'vanish' else os.path.join(root, 'no-such-device')
    if mem == 'vanish':
        sim.fake_device(memdev, sim.pattern(0x10000), sim.BIOS_PHYS + 0x10000 + 4096)
    sim.build(open(sim.SRC).read(), prebuilt, real_mem)
    write_exe(os.path.join(bindir, 'fakecc'), """#!/bin/sh
echo "cc $*" >> %s/cc.calls
if [ "$1" != "-O" ] || [ "$2" != "-o" ] || [ "$4" != "%s" ] || [ $# != 4 ]; then echo "fakecc: bad arguments"; exit 9; fi
%s
/bin/cp %s "$3"
""" % (root, src, '' if cc_ok else 'echo "error: something"; exit 1', prebuilt))
    write_exe(os.path.join(bindir, 'fakesum'), """#!/usr/bin/env python3
import importlib.util, sys
s = importlib.util.spec_from_file_location('p', %r); m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
print(m.bsdsum(open(sys.argv[1], 'rb').read()), sys.argv[1])
""" % pack.__file__)
    write_exe(os.path.join(bindir, 'ps'), '#!/bin/sh\necho "ps $*" >> %s/ps.calls\nexit 1\n' % root)
    write_exe(os.path.join(bindir, 'sync'), '#!/bin/sh\nexit 0\n')
    if bad_cp:
        write_exe(os.path.join(bindir, 'cp'), '#!/bin/sh\nhead -c 100 "$1" > "$2"\n')
    logger = os.path.join(bindir, 'logger')
    write_exe(logger, '#!/bin/sh\necho "$*" >> %s/logger.calls\n' % root)
    syscfg = os.path.join(root, 'Instance0.table')
    open(syscfg, 'w').write('"Boot Driver" = "x";\n%s\n' % drivers)
    env = dict(os.environ)
    env['PATH'] = bindir + ':' + env['PATH']
    env.update(R1C_TMP=tmp, R1C_SRC=src, R1C_OUT=out, R1C_RANDIR=os.path.join(me if randir_parent else root + '/gone',
                                                                              'rdn-r1c-ran.d'),
               R1C_SUM=os.path.join(bindir, 'fakesum'), R1C_CC=os.path.join(bindir, 'fakecc'),
               R1C_SYSCFG=syscfg, R1C_MEMDEV=memdev,
               R1C_LOGGER1=os.path.join(root, 'nologger1'),
               R1C_LOGGER2=(logger if logger else os.path.join(root, 'nologger2')),
               R1C_LOGGER3=os.path.join(root, 'nologger3'))
    return env, dict(tmp=tmp, out=out, src=src, root=root, me=me, memdev=memdev)


def run(env, args):
    r = subprocess.run(['/bin/sh', SCRIPT] + args, env=env, capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout + r.stderr


def main():
    failures = 0

    def check(label, ok, detail=''):
        nonlocal failures
        print('  %s %s%s' % ('ok  ' if ok else 'FAIL', label, '' if ok else ' -- ' + detail[-600:]))
        failures += not ok

    print('== lint ==')
    bad = lint()
    check('ASCII, no forbidden constructs, overrides match the harness', not bad, '; '.join(bad))
    # the two target rules must fire on the script itself with the real defect put back
    global SCRIPT
    original = SCRIPT
    text = open(original).read()
    for label, old, new, want in [
            ('ps put back', 'say "=== 3. ready ==="\n', 'say "=== 3. ready ==="\nn=`ps ax | grep nxlogd | wc -l`\n', 'ps ('),
            ('blank default put back', 'LOGGER1=${R1C_LOGGER1:-/usr/ucb/logger}',
             'LOGGER1=${R1C_LOGGER1:-/usr/ucb/logger /usr/bin/logger}', 'bad substitution'),
            ('set -- put back', "srcsum=`$SUM $SRC | awk '{print $1}'`", 'got=`$SUM $SRC`\nset -- $got\nsrcsum=$1', 'set --'),
            ('$1 after a function put back', 'LENGTH="$ARG3"', 'LENGTH="$3"', 'positional parameter')]:
        if text.count(old) != 1:
            check('lint mutation %s: anchor' % label, False, 'anchor found %d times' % text.count(old))
            continue
        with tempfile.NamedTemporaryFile('w', suffix='.sh', delete=False) as t:
            t.write(text.replace(old, new))
        SCRIPT = t.name
        try:
            hits = [h for h in lint() if want in h]
        finally:
            SCRIPT = original
            os.unlink(t.name)
        check('lint mutation %s is caught' % label, bool(hits), 'not caught')

    base = 800000000 + (os.getpid() % 90000) * 1000
    src_sum = pack.bsdsum(open(sim.SRC, 'rb').read()).split()

    def case(label, expect_rc, want, args_fn, claim=None, extra=None, **kw):
        with tempfile.TemporaryDirectory() as root:
            env, p = setup(root, **kw)
            rid = str(base + len(label))
            args = args_fn(rid)
            if extra and 'pre' in extra:
                extra['pre'](env, p, rid)
            rc, out = run(env, args)
            ok = rc == expect_rc and want in out
            detail = 'rc %d, output:\n%s' % (rc, out)
            if ok and expect_rc in (0, 1):
                tag = 'facts' if args[0] == 'facts' else args[2]
                done = os.path.join(p['tmp'], 'rdn-r1c-%s-%s.done' % (rid, tag))
                last = [l for l in out.strip().splitlines() if l.startswith('R1C')][-1:]
                if not os.path.exists(done) or [open(done).read().strip()] != last:
                    ok = False
                    detail = '.done missing or differs from the last verdict line\n' + out
            if ok and claim is not None:
                exists = os.path.isdir(os.path.join(env['R1C_RANDIR'], '%s-%s' % (rid, args[2])))
                if exists != claim:
                    ok = False
                    detail = 'claim directory exists=%s, expected %s' % (exists, claim)
            if ok and os.path.exists(os.path.join(p['root'], 'ps.calls')):
                ok = False
                detail = 'the script ran ps: ' + open(os.path.join(p['root'], 'ps.calls')).read()
            if ok and extra and 'post' in extra:
                why = extra['post'](env, p, rid, out)
                if why:
                    ok = False
                    detail = why
            for f in os.listdir('/tmp'):
                if f.startswith('rdn-bios-%s-' % rid):
                    os.unlink(os.path.join('/tmp', f))
            check(label, ok, detail)

    read = lambda length, s=src_sum: (lambda rid: ['read', rid, length, s[0], s[1]])

    def good_post(env, p, rid, out):
        cap = os.path.join(p['out'], 'rdn-bios-%s-512.bin' % rid)
        if not os.path.exists(cap) or open(cap, 'rb').read() != sim.pattern(512):
            return 'capture copy missing or wrong'
        if not os.path.exists(os.path.join(p['out'], 'rdn-r1c-%s-512.log' % rid)):
            return 'log not copied'
        calls = open(os.path.join(p['root'], 'logger.calls')).read().splitlines()
        if calls != ['RDN-R1C %s start length=512' % rid, 'RDN-R1C %s done length=512 exit=0' % rid]:
            return 'logger calls %r' % calls
        return ''

    print('== facts ==')
    case('facts', 0, 'R1CFACTS DONE', lambda rid: ['facts', rid],
         extra=dict(post=lambda env, p, rid, out: '' if 'memdev readable yes' in out and 'logger ' in out
                    and os.path.exists(os.path.join(p['out'], 'rdn-r1c-%s-facts.log' % rid)) else 'facts content'))
    print('== read ==')
    case('good read 512', 0, 'R1CREAD DONE', read('512'), claim=True, extra=dict(post=good_post))
    case('good read, no logger present', 0, 'R1CREAD DONE', read('512'), claim=True, logger=False)
    # every good case starts without rdn-r1c-ran.d, so its creation is covered above;
    # here even its parent is missing, and the claim must fail rather than proceed
    case('claim directory cannot be created', 1, 'cannot create', read('512'), claim=False, randir_parent=False)

    def pre_rerun(env, p, rid):
        os.makedirs(os.path.join(env['R1C_RANDIR'], '%s-512' % rid))
    case('same runid and length again', 1, 'already run', read('512'), claim=True, extra=dict(pre=pre_rerun))
    case('source sum differs', 1, 'differs from the host', read('512', ['12345', '9']), claim=False)
    for bad_len in ('513', '0', '70000', 'abc', '0512'):
        case('length %s' % bad_len, 1, 'R1CREAD FAIL', read(bad_len), claim=False)
    case('Matrox driver active', 1, 'names a Matrox driver', read('512'), claim=False,
         drivers='"Active Drivers" = "Pro1000 OpenStepMGAReplacementDisplay";')
    case('VGA not in Active Drivers', 1, 'does not name VGA', read('512'), claim=False,
         drivers='"Active Drivers" = "Pro1000 EMU10K1";')

    def pre_unreadable(env, p, rid):
        os.chmod(p['memdev'], 0)
    if os.geteuid() != 0:
        case('memory device unreadable', 1, 'is not readable', read('512'), claim=False,
             extra=dict(pre=pre_unreadable))
    case('cc fails (after the claim)', 1, 'cc exit 1', read('512'), claim=True, cc_ok=False)
    case('rdnbios fails (device gone)', 1, 'rdnbios exit 3', read('512'), claim=True, mem='vanish')
    case('no NFS build directory', 1, 'no build directory', read('512'), claim=True, out_dir=False)
    case('NFS copy corrupted', 1, "copy's sum", read('512'), claim=True, bad_cp=True)
    print('== usage ==')
    case('no arguments', 2, 'usage', lambda rid: [])
    case('unknown step', 2, 'usage', lambda rid: ['write', rid])
    case('runid not a number', 2, 'usage', lambda rid: ['read', 'x1', '512', '1', '1'])

    print('check_target_r1c: %s' % ('PASS' if failures == 0 else 'FAIL (%d)' % failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
