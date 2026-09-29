import pickle, sys, math
from fractions import Fraction as Fr
sys.path.insert(0,'tools/r6'); import depth_oracle as do
ns={}; exec(open('build/r6f/search3.py').read().split('CASES=')[0], ns)
obs, predict, setup = ns['obs'], ns['predict'], ns['setup']
for name in ('I4_24','I3_24','I7_24','I6_24'):
    got, pix = predict(name, 22, 'floor', 'left', 'exact')
    d = {p: g - obs[name][p] for g, p in zip(got, pix)}
    print(name, 'diffs', {v: list(d.values()).count(v) for v in sorted(set(d.values()))})
    ys = sorted(set(y for x, y in pix))
    for y in ys[:4] + ys[-2:]:
        row = [x for x, yy in pix if yy == y]
        print('  y=%2d x %2d..%2d  %s' % (y, row[0], row[-1], ''.join('.' if d[(x,y)]==0 else ('+' if d[(x,y)]>0 else '-') for x in row)))
