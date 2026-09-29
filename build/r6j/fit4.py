"""R6j host analysis 4: the widened named space, and the class each picture falls in."""
import pickle
import sys

sys.path.insert(0, 'tools/r6')
import persp_oracle as pe
obs = pickle.load(open('build/r6j/observed_e5d4204a.pkl', 'rb'))
FM = {'id': lambda x: x, 'sat256': lambda x: 256 if x == 255 else x,
      'expand': lambda x: x + (x >> 7), 'plus1': lambda x: x + 1,
      'ceil255': lambda x: -((-x * 256) // 255)}
RULES = [(f, r) for f in sorted(FM) for r in range(256)]
DST = pe.blend_dst()
SL = (pe.BLEND_SRC[2], pe.BLEND_SRC[1], pe.BLEND_SRC[0], pe.BLEND_SRC[3])


def pic(case, rule, comb_override=None):
    fm, r = rule
    fs, fd, comb, _, _ = pe.BCASES[case]
    comb = comb_override or comb
    out = {}
    for p, d in DST.items():
        dl = (d[2], d[1], d[0], d[3])
        w = 0
        for l in range(4):
            a, b = FM[fm](pe.factor_value(fs, SL, dl, l)), FM[fm](pe.factor_value(fd, SL, dl, l))
            t, u = (SL[l] * a + r) >> 8, (dl[l] * b + r) >> 8
            v = t + u if comb.startswith('ADD') else (u - t if comb.startswith('RSUB') else t - u)
            w |= max(0, min(255, v)) << (8 * l)
        out[p] = w
    return out


GATED = ('J1', 'J3', 'J4', 'J5', 'J6')
fits = []
for rule in RULES:
    d = sum(1 for n in GATED for q, want in pic(n, rule).items() if obs[n].get(q) != want)
    fits.append((d, rule))
fits.sort(key=lambda t: (t[0], str(t[1])))
print('hardware: %d rules fit exactly: %s' % (sum(1 for d, _ in fits if d == 0),
                                              [r for d, r in fits if d == 0]))
print('  nearest misses: %s' % fits[len([1 for d, _ in fits if d == 0]):][:3])
# how big is the class if J7/J8/J9 are folded in as well?
ALL = GATED + ('J7', 'J9')
cls = [r for r in RULES if all(obs[n].get(q) == w for n in ALL for q, w in pic(n, r).items())]
print('with J7 and J9 too: %s' % cls)
# the subtract direction under the named rule
for r in cls[:1]:
    for comb in ('SUB_CLAMP', 'RSUB_CLAMP'):
        bad = sum(1 for q, w in pic('J8', r, comb).items() if obs['J8'].get(q) != w)
        print('  J8 as %-11s %d wrong' % (comb, bad))
# does the widened space still reject a moved pixel?
for n in ('J4', 'J1', 'J5'):
    m = dict(obs[n])
    k = sorted(m)[11]
    m[k] ^= 0x00010000
    ok = [r for r in RULES if all(m.get(q) == w for q, w in pic(n, r).items())]
    print('  one pixel moved in %s: %d rules still fit' % (n, len(ok)))
# and what class does each synthetic machine sit in (self-test sanity)?
for bl in (('id', 0), ('sat256', 128), ('expand', 255), ('plus1', 0)):
    syn = dict((n, pic(n, bl)) for n in GATED)
    ok = [r for r in RULES if all(syn[n].get(q) == w for n in GATED for q, w in pic(n, r).items())]
    print('  synthetic %-14s -> class %s' % (str(bl), ok if len(ok) < 8 else '%d rules' % len(ok)))
