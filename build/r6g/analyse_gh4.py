import re, sys, pickle
sys.path.insert(0,'tools/r6'); import depth_oracle as do
exec(open('build/r6g/analyse_gi.py').read().split('gi = vals')[0])
gh4 = vals(do.GCASE_NUM['GH4'])
pix = do.go.covered(do.GEOM[do.GEOM_G])
c, d = do.g_predict('GH4')
d1, d2 = do.g_drawn('GH4', 1), do.g_drawn('GH4', 2)
r6f = pickle.load(open('build/r6f/observed_e4d44687.pkl','rb'))['I1_16']
won2 = [p for p in pix if c[p] == do.to.pixel(do.C2)]
won1 = [p for p in pix if c[p] == do.to.pixel(do.C1)]
print('GH4: draw2 won %d, draw1 won %d (colour matched the prediction)' % (len(won2), len(won1)))
print('  where draw1 won, depth = exact draw1 in %d of %d; = the R6f measurement in %d'
      % (sum(1 for p in won1 if gh4[p] == d1[p]), len(won1), sum(1 for p in won1 if gh4[p] == r6f[p])))
print('  where draw2 won, depth = exact draw2 in %d of %d (the reversed slope was never measured)'
      % (sum(1 for p in won2 if gh4[p] == d2[p]), len(won2)))
diffs = [gh4[p] - (d2[p] if p in won2 else d1[p]) for p in pix]
print('  deviation from exact: %s' % {v: diffs.count(v) for v in sorted(set(diffs))})
