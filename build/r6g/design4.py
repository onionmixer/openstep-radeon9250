import sys, math
from fractions import Fraction as Fr
sys.path.insert(0,'tools/r6'); import depth_oracle as do
go=do.go
T=do.GEOM['T1z']; pix=sorted(go.covered(T)); n=len(pix)
pat=do.pattern_block()
vals=[do.read_depth(pat,x,y,16) for x,y in pix]
print('pattern depth at the covered pixels: min %d max %d median %d' % (min(vals), max(vals), sorted(vals)[n//2]))
print('distribution:', {k: sum(1 for v in vals if v>>12 == k) for k in sorted(set(v>>12 for v in vals))})
def zi(v): return math.floor(Fr(v)*65536)
print('\nchoose draw1 z (stored) and draw2 z: want draw2 vs stored -> 0 pass, draw2 vs pattern -> many')
for z1 in (0.9, 0.95, 0.99):
    for z2 in (0.3, 0.5, 0.7, 0.8):
        s, d = zi(z1), zi(z2)
        if d >= s: continue
        print('  draw1 %.2f (%5d) draw2 %.2f (%5d): vs stored passes %3d, vs pattern would pass %3d'
              % (z1, s, z2, d, sum(1 for _ in pix if d < s) * 0 + (n if d < s else 0), sum(1 for v in vals if d < v)))
