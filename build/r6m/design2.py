#!/usr/bin/env python3
"""R6m design 2: choose the boot's tail so that cpR6Submit's PADDING path actually runs (task #30).

The R6l boot wrapped, but it wrapped by landing EXACTLY on the ring end (wptr 2800 -> 0), which is
the pad == 0 branch.  The padding branch -- length > RING - p, so the submission skips to 0 and
leaves pad PACKET2 words behind -- has still never executed on the hardware.

The model is read off the R6l boot log (build/r6/boot-e6661063.full.log), not guessed: every ZCLEAR
advances the write pointer by 32 (the prefix submission) plus the draw rounded up to 16, each
submission padding to the ring end when it does not fit.  Checked here against that log first.
"""
import importlib.util
import os
import sys

RING, MASK = 4096, 0xfff
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..', '..')


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ru = _load('reuse_oracle', os.path.join(ROOT, 'tools', 'r6', 'reuse_oracle.py'))
ba, te = ru.ba, ru.te
PREFIX = 32                                     # the prefix submission, rounded to 16


def submit(p, n):
    """cpR6Submit: (the new write pointer, the words of padding it left behind)"""
    length = (n + 15) & ~15
    pad = RING - p if length > RING - p else 0
    return (p + pad + length) & MASK, pad


def case_words(name):
    if name in ru.SCASES:
        return ru.words_needed(name)
    if name in ba.SCASES:
        return ba.words_needed(name)
    return te.words_needed(name)


def run(start, names):
    """[(case, wptr after, padding words)] -- the prefix and the draw are separate submissions"""
    p, out = start, []
    for n in names:
        p, pa = submit(p, 12 * 2)               # eleven register pairs and the marker: 22 -> 32
        p, pb = submit(p, case_words(n))
        out.append((n, p, pa + pb))
    return out


def check_against_r6l():
    """the same model, run over the R6l boot, must reproduce its logged pointers"""
    log = os.path.join(ROOT, 'build', 'r6', 'boot-e6661063.full.log')
    if not os.path.exists(log):
        print('  (the R6l boot log is not here -- the model is unchecked)')
        return 0
    import re
    want = []
    for chunk in open(log, errors='replace').read().split('RDN-R5 begin ')[1:]:
        chunk = chunk.split('RDN-R5 begin ')[0]
        c = re.search(r'RDN-R6 zclear case=(\d+) stage=3', chunk)
        w = re.search(r'wptr=(\d+)', chunk)
        if c and w and 'boot=e6661063' in chunk:
            want.append((int(c.group(1)), int(w.group(1))))
    names = [{6: 'F'}.get(c) or ru.ba.ORDER[c - ba.FIRST] for c, _ in want]
    got = run(16, ['F' if n is None else n for n in names])
    bad = [(a, b) for (a, (_n, b, _p)) in zip(want, got) if a[1] != b]
    print('  the model reproduces the R6l boot: %s (%d operations%s)' %
          ('yes' if not bad else 'NO', len(want), '' if not bad else ', %s' % bad[:3]))
    return 0 if not bad else 1


def main():
    # 'F' is the first case of every R6 boot; it draws zclear_oracle's case F
    globals()['case_words'] = lambda n, f=case_words: 65 if n == 'F' else f(n)
    bad = check_against_r6l()
    head = ['F'] + ru.BOOT
    print('  the R6m cases:')
    p = 16
    for n, p2, pad in run(p, head):
        print('    %-3s wptr %4d -> %4d  padding %d' % (n, p, p2, pad))
        p = p2
    # now pick a tail of R6l cases that makes a submission PAD (not land exactly on the end)
    best = None
    for tail in (['BA', 'BA', 'BC', 'BB'], ['BA', 'BA', 'BB'], ['BA', 'BB', 'BB'], ['BB', 'BB'],
                 ['BA', 'BA', 'BA', 'BB'], ['BB', 'BA', 'BB'], ['BA', 'BB', 'BA', 'BB']):
        q, pads = p, []
        for n, q2, pad in run(q, tail):
            pads.append((n, q2, pad))
            q = q2
        if any(pad > 0 for _n, _q, pad in pads):
            best = (tail, pads)
            break
    if best is None:
        print('  FAIL: none of the candidate tails pads')
        return 1
    tail, pads = best
    print('  the tail that burns the padding path: %s' % ' '.join(tail))
    for n, q2, pad in pads:
        print('    %-3s wptr -> %4d  padding %d %s' % (n, q2, pad, '<-- the pad path' if pad else ''))
    print('design2: %s' % ('PASS' if not bad else 'FAIL'))
    return bad


if __name__ == '__main__':
    sys.exit(main())
