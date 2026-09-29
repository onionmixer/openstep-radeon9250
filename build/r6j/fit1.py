"""R6j host analysis 1: recover the per-term product map P(v, f) from the measured pixels.

  J6 = (SRC_ALPHA, ONE):  result = P(src, 0x37) + dst          -> P(src, 0x37), one value per lane
  J4 = (SRC_ALPHA, 1-SA): result = P(src, 0x37) + P(dst, 0xc8) -> P(dst, 0xc8) for every dst seen
  J5 = (DST_COLOR, ZERO): result = P(dst, dst)
  J3 = (ONE, ONE):        result = src + dst (clamped?)
  J1 = (ONE, ZERO):       result = src
Nothing is assumed about the arithmetic: the maps are printed as measured.
"""
import pickle
import sys

sys.path.insert(0, 'tools/r6')
sys.path.insert(0, 'build/r6j')
import persp_oracle as pe

N = sys.argv[1] if len(sys.argv) > 1 else 'e5d4204a'
obs = pickle.load(open('build/r6j/observed_%s.pkl' % N, 'rb'))
dst = pe.blend_dst()                                   # {(x,y): (r,g,b,a)} by measured rule B
SL = (pe.BLEND_SRC[2], pe.BLEND_SRC[1], pe.BLEND_SRC[0], pe.BLEND_SRC[3])   # lanes b,g,r,a


def lanes(case):
    return dict((p, [(w >> (8 * l)) & 0xff for l in range(4)]) for p, w in obs[case].items())


J = dict((n, lanes(n)) for n in ('J1', 'J3', 'J4', 'J5', 'J6', 'J2', 'J0'))
DL = dict((p, (d[2], d[1], d[0], d[3])) for p, d in dst.items())

print('src lanes (b,g,r,a) = %s' % (SL,))
print('J1 distinct words: %s' % sorted(set(obs['J1'].values()))[:4])
print('J0 distinct words: %s' % sorted(set(obs['J0'].values()))[:4])
# ---- P(src, 0x37) from J6, one number per lane
psa = {}
for l in range(4):
    vals = set()
    for p in DL:
        vals.add(J['J6'][p][l] - DL[p][l])
    psa[l] = sorted(vals)
    print('J6 lane %d: src=%3d  result-dst = %s' % (l, SL[l], psa[l]))
