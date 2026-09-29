# how well do the cases separate the candidate rules, counting only pixels far from a texel boundary?
import sys, math
from fractions import Fraction as Fr
sys.path.insert(0,'tools/r6'); import depth_oracle as do
exec(open('build/r6h/design1.py').read().split('def texel')[0])
DELTA = Fr(1, 1024)          # a generous bound on the interpolation's error in texel units
def tex_of(v, w, off, mode):
    f = v * w + off
    t = math.floor(f)
    safe = min(f - t, t + 1 - f) > DELTA
    if mode == 'clamp': t = max(0, min(w - 1, t))
    else: t = t % w
    return t, safe
RULES = [(off, mode) for off in (0, Fr(-1,2), Fr(1,2)) for mode in ('clamp', 'wrap')]
CASES = {
 'XA': (8,8,(0,1,0),(0,0,1)), 'XB': (8,8,(Fr(1,16),Fr(17,16),Fr(1,16)),(Fr(1,16),Fr(1,16),Fr(17,16))),
 'XC': (8,8,(0,2,0),(0,0,2)), 'XD': (8,8,(Fr(-1,4),Fr(5,4),Fr(-1,4)),(Fr(-1,4),Fr(-1,4),Fr(5,4))),
 'XF': (4,4,(0,1,0),(0,0,1)), 'XG': (8,8,(0,1,0),(Fr(17,32),)*3),   # t*8 = 4.25: off a texel boundary
}
sep = {}
for n,(w,h,st,tt) in CASES.items():
    s=interp(st); t=interp(tt)
    maps={}
    for off,mode in RULES:
        m={}
        for p in pix:
            u,su = tex_of(s[p], w, off, mode); v,sv = tex_of(t[p], h, off, mode)
            m[p]=((u,v), su and sv)
        maps[(off,mode)]=m
    for i,a in enumerate(RULES):
        for b in RULES[i+1:]:
            d=sum(1 for p in pix if maps[a][p][1] and maps[b][p][1] and maps[a][p][0]!=maps[b][p][0])
            sep[(a,b)]=sep.get((a,b),0)+d
    safe=sum(1 for p in pix if all(maps[r][p][1] for r in RULES))
    print('%-3s safe under every rule: %3d of %d' % (n, safe, len(pix)))
print()
worst=sorted(sep.items(), key=lambda kv: kv[1])[:5]
for (a,b),d in worst:
    print('rules %-18s vs %-18s differ on %4d safe pixels (all cases)' % (str(a), str(b), d))
