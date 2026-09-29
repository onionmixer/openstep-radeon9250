#!/usr/bin/env python3
"""Run tools/r1c/rdnbios.c on the host against a fake memory device, under strace.

  sim_r1c.py        every world and every mutation; exit 1 on any failure

The source is built unchanged with the host compiler.  The only differences
from the target build are the include shim tools/r1c/hostsim/libc.h (glibc
stands in for NeXT's libc.h) and -DRDN_MEM_PATH=<fake device file>.

Each run is traced (strace -f) and judged on what actually happened to the
fake device's file descriptors, including duplicates of them:
  - the device path is opened exactly once, O_RDONLY, and only after the
    output file was created
  - exactly one lseek on it, to 786432 (0xC0000) with SEEK_SET
  - on it only read and close: no write, pwrite, ioctl, mmap
A text rule cannot decide which variable holds the device descriptor
(Q10 B4); the trace can.

What this cannot show: the character-device semantics of the target's
/dev/mem (one physical page per kernel mapping, EFAULT at mem_size).  Those
were settled by reading the decompiled kernel (docs/R1C_R2A_IMPL_PLAN.md
section 1-1), not by this fake, which is a regular file.
"""

import os
import re
import resource
import signal
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'rdnbios.c')
SHIM = os.path.join(HERE, 'hostsim')
BIOS_PHYS = 0xC0000
STRACE = '/usr/bin/strace'


def build(source_text, exe, mem_path):
    src = exe + '.c'
    open(src, 'w').write(source_text)
    cmd = ['gcc-12', '-std=gnu89', '-O0', '-Wno-deprecated', '-I', SHIM,
           '-DRDN_MEM_PATH="%s"' % mem_path, '-o', exe, src]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError('build failed: %s' % r.stderr[-800:])


def fake_device(path, content_at_phys, file_size):
    data = bytearray(file_size)
    data[BIOS_PHYS:BIOS_PHYS + len(content_at_phys)] = content_at_phys[:max(0, file_size - BIOS_PHYS)]
    open(path, 'wb').write(bytes(data))


def pattern(n):
    # 55 AA, then a position-dependent byte, so a misplaced read shows
    b = bytearray((i * 7 + 3) & 0xff for i in range(n))
    b[0:2] = b'\x55\xaa'
    return bytes(b)


def run(exe, args, trace, fsize_limit=None):
    def pre():
        if fsize_limit is not None:
            signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
            resource.setrlimit(resource.RLIMIT_FSIZE, (fsize_limit, fsize_limit))
    cmd = [STRACE, '-f', '-o', trace, '-e',
           'trace=open,openat,creat,lseek,_llseek,read,pread64,readv,write,pwrite64,writev,'
           'mmap,mmap2,ioctl,close,dup,dup2,dup3,fcntl', exe] + args
    r = subprocess.run(cmd, capture_output=True, text=True, preexec_fn=pre, timeout=60)
    return r.returncode, r.stdout


def judge_trace(trace, mem_path, out_path):
    """Return a list of rule violations found in the trace."""
    bad = []
    dev_fds = set()
    out_created = False
    opens = opened = lseeks = 0
    for line in open(trace):
        line = line.strip()
        m = re.match(r'(?:\d+\s+)?(\w+)\((.*)\)\s+=\s+(-?\d+)', line)
        if not m:
            continue
        call, args, ret = m.group(1), m.group(2), int(m.group(3))
        if call in ('open', 'openat', 'creat'):
            if '"%s"' % out_path in args and ret >= 0:
                out_created = True
            if '"%s"' % mem_path in args:
                opens += 1
                flags = re.findall(r'O_[A-Z]+', args)
                if [f for f in flags if f not in ('O_RDONLY', 'O_LARGEFILE')] or 'O_RDONLY' not in flags:
                    bad.append('device opened with %s' % '|'.join(flags))
                if not out_created:
                    bad.append('device opened before the output file was created')
                if ret >= 0:
                    opened += 1
                    dev_fds.add(ret)
            continue
        fd = re.match(r'(\d+)', args)
        fd = int(fd.group(1)) if fd else None
        if call in ('dup', 'dup2', 'dup3') and fd in dev_fds and ret >= 0:
            dev_fds.add(ret)
            continue
        if call == 'fcntl' and fd in dev_fds and 'F_DUPFD' in args and ret >= 0:
            dev_fds.add(ret)
            continue
        if fd not in dev_fds:
            if call == 'close' and fd is not None:
                dev_fds.discard(fd)
            continue
        if call in ('lseek', '_llseek'):
            lseeks += 1
            if not re.match(r'\d+, 786432, SEEK_SET$', args):
                bad.append('device lseek %s' % args)
        elif call in ('read', 'pread64', 'readv'):
            if call != 'read':
                bad.append('device %s' % call)
        elif call == 'close':
            dev_fds.discard(fd)
        else:
            bad.append('device %s(%s)' % (call, args[:40]))
    if opens > 1:
        bad.append('device opened %d times' % opens)
    if opened == 1 and lseeks != 1:
        bad.append('device lseek called %d times' % lseeks)
    return bad, opens


MUTATIONS = [
    ('offset taken from the length argument',
     '(off_t)BIOS_PHYS, SEEK_SET', '(off_t)length, SEEK_SET'),
    ('device opened O_RDWR',
     'open(RDN_MEM_PATH, O_RDONLY)', 'open(RDN_MEM_PATH, O_RDWR)'),
    ('a write through a duplicate of the device descriptor',
     '    got = 0;\n    while', '    { int twin = dup(dfd); if (write(twin, image, 1) < 0) got = 0; }\n    got = 0;\n    while'),
    ('short read ignored',
     '    if (got != (int)length)\n        finish(runid, length, got, 4);\n', ''),
    ('O_EXCL removed',
     'O_WRONLY | O_CREAT | O_EXCL', 'O_WRONLY | O_CREAT | O_TRUNC'),
    ('write return ignored',
     '    if (write(ofd, image, (int)length) != (int)length)\n        finish(runid, length, got, 6);\n',
     '    write(ofd, image, (int)length);\n'),
    ('device opened before the output file',
     '    ofd = open(path, O_WRONLY | O_CREAT | O_EXCL, 0644);\n    if (ofd < 0)\n        finish(runid, length, 0, 2);\n\n    dfd = open(RDN_MEM_PATH, O_RDONLY);\n',
     '    dfd = open(RDN_MEM_PATH, O_RDONLY);\n    ofd = open(path, O_WRONLY | O_CREAT | O_EXCL, 0644);\n    if (ofd < 0)\n        finish(runid, length, 0, 2);\n\n'),
    ('two lseeks',
     '    where = lseek(dfd, (off_t)BIOS_PHYS, SEEK_SET);\n',
     '    where = lseek(dfd, (off_t)BIOS_PHYS, SEEK_SET);\n    where = lseek(dfd, (off_t)BIOS_PHYS, SEEK_SET);\n'),
]


def worlds(tmp):
    mem = os.path.join(tmp, 'fakemem')
    base = 900000000 + (os.getpid() % 90000) * 1000
    w = []
    # (label, device content setup, args, expected exit, extra checks)
    w.append(dict(label='good 512', dev=('full',), args=[str(base + 1), '512'], code=0, compare=512))
    w.append(dict(label='good 65536', dev=('full',), args=[str(base + 2), '65536'], code=0, compare=65536))
    w.append(dict(label='device shorter than 0xC0000 + length', dev=('short', 100), args=[str(base + 3), '512'],
                  code=4))
    w.append(dict(label='device missing', dev=('missing',), args=[str(base + 4), '512'], code=3))
    for bad_len in ('0', '511', '513', '65537', '-512', 'x', '1024x'):
        w.append(dict(label='length %r' % bad_len, dev=('full',), args=[str(base + 5), bad_len], code=2,
                      no_device=True))
    for bad_id in ('0', 'abc', '1000000000'):
        w.append(dict(label='runid %r' % bad_id, dev=('full',), args=[bad_id, '512'], code=2, no_device=True))
    w.append(dict(label='wrong argument count', dev=('full',), args=['1'], code=2, no_device=True))
    w.append(dict(label='output file already exists', dev=('full',), args=[str(base + 6), '512'], code=2,
                  precreate=True, no_device=True))
    w.append(dict(label='output write limited (short write)', dev=('full',), args=[str(base + 7), '65536'], code=6,
                  fsize=4096))
    return mem, w


def run_world(exe, mem, w, tmp):
    kind = w['dev'][0]
    if os.path.exists(mem):
        os.unlink(mem)
    if kind == 'full':
        fake_device(mem, pattern(0x10000), BIOS_PHYS + 0x10000 + 4096)
    elif kind == 'short':
        fake_device(mem, pattern(w['dev'][1]), BIOS_PHYS + w['dev'][1])
    args = w['args']
    out_path = None
    if len(args) == 2:
        out_path = '/tmp/rdn-bios-%s-%s.bin' % (args[0], args[1])
        if os.path.exists(out_path):
            os.unlink(out_path)
        if w.get('precreate'):
            open(out_path, 'wb').write(b'keep')
    trace = os.path.join(tmp, 'trace')
    code, stdout = run(exe, args, trace, w.get('fsize'))
    problems = []
    if code != w['code']:
        problems.append('exit %d, expected %d (%s)' % (code, w['code'], stdout.strip()))
    bad, opens = judge_trace(trace, mem, out_path or '')
    problems += bad
    if w.get('no_device') and opens:
        problems.append('device opened although the arguments or output were refused')
    if w.get('precreate') and open(out_path, 'rb').read() != b'keep':
        problems.append('existing output file was overwritten')
    if 'compare' in w and code == 0:
        got = open(out_path, 'rb').read()
        if got != pattern(0x10000)[:w['compare']]:
            problems.append('capture differs from the bytes at 0xC0000')
        if not re.search(r'^RDNBIOS runid=%s offset=000c0000 length=%d got=%d first=55aa exit=0$'
                         % (args[0], w['compare'], w['compare']), stdout.strip()):
            problems.append('unexpected report line: %r' % stdout.strip())
    if out_path and os.path.exists(out_path):
        os.unlink(out_path)
    return problems


def main():
    if not os.path.exists(STRACE):
        print('  FAIL %s not found: the dynamic rules cannot run' % STRACE)
        print('sim_r1c: FAIL')
        return 1
    source = open(SRC).read()
    failures = 0
    with tempfile.TemporaryDirectory() as tmp:
        mem, ws = worlds(tmp)
        exe = os.path.join(tmp, 'rdnbios')
        build(source, exe, mem)
        print('== worlds (unchanged source) ==')
        for w in ws:
            problems = run_world(exe, mem, w, tmp)
            print('  %s %s%s' % ('ok  ' if not problems else 'FAIL', w['label'],
                                '' if not problems else ': ' + '; '.join(problems)))
            failures += bool(problems)
        print('== mutations (each must be caught) ==')
        for label, old, new in MUTATIONS:
            if source.count(old) != 1:
                print('  FAIL mutation %r: anchor found %d times' % (label, source.count(old)))
                failures += 1
                continue
            mexe = os.path.join(tmp, 'mutant')
            try:
                build(source.replace(old, new), mexe, mem)
            except RuntimeError as e:
                print('  FAIL mutation %r does not build: %s' % (label, e))
                failures += 1
                continue
            caught = []
            for w in ws:
                if run_world(mexe, mem, w, tmp):
                    caught.append(w['label'])
            print('  %s %s%s' % ('ok  ' if caught else 'FAIL', label,
                                ' -- caught by: ' + ', '.join(caught[:3]) if caught else ' -- NOT caught'))
            failures += not caught
    print('sim_r1c: %s' % ('PASS' if failures == 0 else 'FAIL (%d)' % failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
