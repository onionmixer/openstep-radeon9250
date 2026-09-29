#!/usr/bin/env python3
"""The generated client-side verifier, RUN against the oracle's cases (G4-2 B0).

  sim_verify.py

mesa/OSRDNMesaVerify.c is the kernel verifier's text (gen_r7verify.py).  This compiles it on the host
with a harness that feeds it every case tools/r7/verify_oracle.py builds -- the same streams world5
stages for the kernel -- and expects the oracle's verdict for each.  Then mutations of the generated
text (a rule taken out) must be caught, so a copy that lost a rule cannot pass as the kernel's.
"""
import atexit
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
MESA = os.path.join(PROJ, 'mesa')
WIN = 0x400000                                   # the real window's start (RDN-R4 vmap); any consistent value works

_sp = importlib.util.spec_from_file_location('verify_oracle', os.path.join(PROJ, 'tools', 'r7', 'verify_oracle.py'))
VO = importlib.util.module_from_spec(_sp)
_sp.loader.exec_module(VO)

HARNESS = r'''
int printf(const char *, ...);
#include "OSRDNMesaVerify.h"
%(streams)s
int main(void)
{
    unsigned long at, word, why;
%(calls)s
    return 0;
}
'''


def all_cases():
    """the oracle's cases, plus one only this harness needs: a stream past CP_R7_BATCH_MAX (the
    oracle keeps its cases small because they are baked into the kernel's tables)"""
    cs = list(VO.cases(WIN))
    long_ = VO.stream_u1()
    pad = VO.p0(VO.RB3D_CNTL, long_[long_.index((VO.RB3D_CNTL >> 2) & 0x3fff) + 1]) if ((VO.RB3D_CNTL >> 2) & 0x3fff) in long_ else VO.p0(VO.RE_WIDTH_HEIGHT, 0x003f003f)
    while len(long_) <= VO.BATCH_MAX_WORDS:
        long_ = pad + long_
    cs.append(('LONG', long_, VO.WHY_WORDS))
    return cs


def build_and_run(work, src):
    cases = all_cases()
    streams, calls = [], []
    for k, (name, words, _why) in enumerate(cases):
        streams.append('static const unsigned long s%d[%d] = { %s };' % (k, max(1, len(words)), ', '.join('0x%08xUL' % (x & 0xffffffff) for x in words) or '0UL'))
        calls.append('    why = osrdn_r7_verify(0x%xUL, 0x%xUL, 0x%xUL, 0x%xUL, %dUL, s%d, %dUL, &at, &word); printf("C %s %%lu %%lu\\n", why, at);'
                     % (WIN, WIN + VO.WIN_BYTES, WIN + VO.PREFIX_COLOR_OFF, WIN + VO.PREFIX_DEPTH_OFF, VO.PREFIX_PITCH, k, len(words), name))
    open(os.path.join(work, 'OSRDNMesaVerify.c'), 'w').write(src)
    shutil.copy(os.path.join(MESA, 'OSRDNMesaVerify.h'), work)
    open(os.path.join(work, 'h.c'), 'w').write(HARNESS % dict(streams='\n'.join(streams), calls='\n'.join(calls)))
    exe = os.path.join(work, 'h')
    r = subprocess.run(['gcc-12', '-std=gnu89', '-Wall', '-Werror', '-O0', '-I', work,
                        os.path.join(work, 'h.c'), os.path.join(work, 'OSRDNMesaVerify.c'), '-o', exe], capture_output=True, text=True)
    if r.returncode:
        return None, r.stderr.strip().splitlines()[-1] if r.stderr.strip() else 'gcc failed'
    r = subprocess.run([exe], capture_output=True, text=True, timeout=60)
    return r.stdout.splitlines(), None


def judge(lines):
    want = dict((name, why) for name, _w, why in all_cases())
    got = {}
    for l in lines:
        p = l.split()
        if len(p) == 4 and p[0] == 'C':
            got[p[1]] = int(p[2])
    bad = []
    for name, why in want.items():
        if name not in got:
            bad.append('%s: no verdict' % name)
        elif got[name] != why:
            bad.append('%s: the unit says %s, the oracle %s' % (name, VO.WHY_NAME.get(got[name], got[name]), VO.WHY_NAME[why]))
    return bad


MUTATIONS = [
    ('the clip is no longer required before a draw', '    if (!haveWH)\n        return 0;\n', ''),
    ('K7: the draw is no longer judged where it stands',
     '        if (!cpR7SurfacesOk(c, coff, cpitch, zoff, zpitch, wh, haveWH, toff, tfmt, tfil, haveT, haveTF))\n            return CP_R7_WHY_SURFACE;\n        drew = 1;',
     '        drew = 1;'),
    ('the texture grain check goes', '(toff & CP_R7_TXO_LOW_MASK) != 0UL', '0'),
    ('an unmeasured filter field is admitted', 'if (reg == C_PP_TXFILTER_0 && (val & CP_R7_TXFILTER_UNMEASURED) != 0UL)', 'if (0)'),
    ('the vertex count check goes', 'return CP_R7_WHY_COUNT;', 'i += 0;'),
    ('the length limit goes', 'if (n > (unsigned long)CP_R7_BATCH_MAX)\n        return CP_R7_WHY_WORDS;', ''),
    ('PP_MISC takes any value', 'if (reg == C_PP_MISC && (val & ~CP_R7_PP_MISC_FIELDS) != 0UL)', 'if (0)'),
]


def main():
    if subprocess.run(['which', 'gcc-12'], capture_output=True).returncode != 0:
        print('  --   gcc-12 not present, skipped')
        return 0
    src = open(os.path.join(MESA, 'OSRDNMesaVerify.c')).read()
    work = tempfile.mkdtemp(prefix='simverify')
    atexit.register(shutil.rmtree, work, True)
    fails = 0
    out, err = build_and_run(work, src)
    if out is None:
        print('  FAIL the harness does not build: %s' % err)
        return 1
    bad = judge(out)
    for b in bad[:8]:
        print('  FAIL ' + b)
    if bad:
        fails += 1
    else:
        print('  ok   %d cases (the oracle\'s 32 and one past the length limit): the generated unit gives the kernel\'s verdict on every one' % len(all_cases()))
    for label, old, new in MUTATIONS:
        if src.count(old) != 1:
            print('  FAIL mutation %-46s anchor found %d times' % (label, src.count(old)))
            fails += 1
            continue
        o, e = build_and_run(work, src.replace(old, new, 1))
        caught = (o is None) or bool(judge(o))
        print('  %-4s mutation %-46s %s' % ('ok' if caught else 'FAIL', label, 'caught' if caught else 'NOT CAUGHT'))
        fails += 0 if caught else 1
    print('sim_verify: %s' % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
