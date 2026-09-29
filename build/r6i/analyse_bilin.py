"""R6i host analysis: the bilinear weight curve, read straight off the alternating texture.

  python3 build/r6i/analyse_bilin.py <boot nonce>

With pattern 2 (R = 255 when u is odd, G = 255 when v is odd, B = 0x55, A = 0xff) the R byte of a
bilinear sample is 255 x (the weight of the odd column) and G is the same for the odd row, so each
pixel gives one point of the one-dimensional weight curve per axis -- independent of the other axis.

For each named texel offset a and screen sample offset o it prints:
  - how the observed weight compares with the exact fraction (max and mean error in LSBs)
  - the staircase: the distinct (fraction, observed weight) pairs, and which quantum explains them
"""
import math
import pickle
import sys
from fractions import Fraction as Fr

sys.path.insert(0, 'tools/r6')
import persp_oracle as pe                        # noqa: E402

nonce = sys.argv[1]
obs = pickle.load(open('build/r6i/observed_%s.pkl' % nonce, 'rb'))
CASES = [n for n in ('LD', 'LF', 'PL') if n in obs]
QUANTA = [None, 8, 16, 32, 64, 128, 256, 512]


def fractions(case, a, o, model='A'):
    """{(x, y): (fu, fv)} -- the exact texel-space fractions this reading gives"""
    w, h, _, _ = pe.tex_of(case)
    st, tt = pe.st_of(case)
    s, t = pe.coord(case, st, model, o), pe.coord(case, tt, model, o)
    out = {}
    for p in s:
        fs, ft = s[p] * w + a, t[p] * h + a
        out[p] = (fs - math.floor(fs), ft - math.floor(ft), math.floor(fs), math.floor(ft))
    return out


def observed_weights(case):
    """{(x, y): (w_odd_column, w_odd_row)} in 1/255 units, from R and G"""
    return dict((p, (((v >> 16) & 0xff) / 255.0, ((v >> 8) & 0xff) / 255.0)) for p, v in obs[case].items())


for case in CASES:
    print('== %s ==' % case)
    model = 'Pq' if pe.recntl_of(case) & 8 else 'A'
    for a in (Fr(0), Fr(-1, 2)):
        for o in (Fr(0), Fr(1, 2)):
            fr = fractions(case, a, o, model)
            ow = observed_weights(case)
            err = []
            pts = []
            for p, (fu, fv, iu, iv) in fr.items():
                wu = fu if iu % 2 == 0 else 1 - fu          # the weight of the ODD column
                wv = fv if iv % 2 == 0 else 1 - fv
                err.append(abs(ow[p][0] * 255 - float(wu) * 255))
                err.append(abs(ow[p][1] * 255 - float(wv) * 255))
                pts.append((float(wu), round(ow[p][0] * 255)))
            print('  a=%-5s o=%-3s  exact-weight error: max %5.1f  mean %5.2f LSB' %
                  (a, o, max(err), sum(err) / len(err)))
            if max(err) < 8:
                best = []
                for q in QUANTA:
                    for rmode in ('floor', 'round', 'even'):
                        d = 0
                        for wu, got in pts:
                            z = Fr(wu).limit_denominator(10 ** 6)
                            k = pe.quantise(z, q, rmode)
                            d = max(d, abs(round(float(k) * 255) - got))
                        best.append((d, q, rmode))
                best.sort(key=lambda t: (t[0], t[1] or 0, t[2]))
                print('     quantum candidates (max LSB off): %s' % best[:4])
