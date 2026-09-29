"""R6j host analysis 3: name the product map, then check the whole blend on every case."""
import pickle
import sys

sys.path.insert(0, 'tools/r6')
import persp_oracle as pe
obs = pickle.load(open('build/r6j/observed_e5d4204a.pkl', 'rb'))
dst = pe.blend_dst()
SL = (pe.BLEND_SRC[2], pe.BLEND_SRC[1], pe.BLEND_SRC[0], pe.BLEND_SRC[3])
DL = dict((p, (d[2], d[1], d[0], d[3])) for p, d in dst.items())
L = dict((n, dict((p, [(w >> (8 * l)) & 0xff for l in range(4)]) for p, w in obs[n].items()))
         for n in obs if n != 'PZ')

# the two-point set the earlier fit recovered, restated independently
pts = [(155, 55, 33), (42, 55, 9), (193, 55, 42), (55, 55, 12)]
psa = dict((l, dict((a, g) for a, b, g in pts)[SL[l]]) for l in range(4))
for p in DL:
    for l in range(4):
        if L['J4'][p][l] != 255:
            pts.append((DL[p][l], 200, L['J4'][p][l] - psa[l]))
FAM = {'Eb=b+(b>>7)': lambda a, b: (a * (b + (b >> 7))) >> 8,
       'Eb=b+1': lambda a, b: (a * (b + 1)) >> 8,
       'Eb=b+1,ex0': lambda a, b: (a * (b + 1)) >> 8 if b else 0,
       'ceil(ab/255)': lambda a, b: -((-a * b) // 255),
       '(ab+a)>>8': lambda a, b: (a * b + a) >> 8}
for n, f in sorted(FAM.items(), key=lambda t: sum(t[1](a, b) != g for a, b, g in pts)):
    print('%-14s %4d of %d wrong' % (n, sum(f(a, b) != g for a, b, g in pts), len(pts)))


def P(a, b):
    return (a * (b + 1)) >> 8


FV = {'ZERO': lambda s, d, l: 0, 'ONE': lambda s, d, l: 255,
      'SRC_COLOR': lambda s, d, l: s[l], 'DST_COLOR': lambda s, d, l: d[l],
      'SRC_ALPHA': lambda s, d, l: s[3], 'ONE_MINUS_SRC_ALPHA': lambda s, d, l: 255 - s[3]}
CA = {'J1': ('ONE', 'ZERO', 'ADD'), 'J2': ('ZERO', 'ONE', 'ADD'), 'J3': ('ONE', 'ONE', 'ADD'),
      'J4': ('SRC_ALPHA', 'ONE_MINUS_SRC_ALPHA', 'ADD'), 'J5': ('DST_COLOR', 'ZERO', 'ADD'),
      'J6': ('SRC_ALPHA', 'ONE', 'ADD'), 'J7': ('SRC_ALPHA', 'ONE_MINUS_SRC_ALPHA', 'ADD'),
      'J8': ('ONE', 'ONE', 'SUB'), 'J9': ('SRC_ALPHA', 'ONE_MINUS_SRC_ALPHA', 'ADD')}
print('--- the whole blend with P(a,b) = (a*(b+1))>>8, clamped to 0..255')
for n in sorted(CA):
    fs, fd, comb = CA[n]
    bad = []
    for p in DL:
        for l in range(4):
            s, d = SL, DL[p]
            t, u = P(s[l], FV[fs](s, d, l)), P(d[l], FV[fd](s, d, l))
            v = max(0, min(255, t + u if comb == 'ADD' else t - u))
            if v != L[n][p][l]:
                bad.append((p, l, v, L[n][p][l]))
    print('%-3s %4d of %d lanes wrong %s' % (n, len(bad), 4 * len(DL), bad[:3]))
