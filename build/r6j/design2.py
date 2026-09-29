#!/usr/bin/env python3
"""R6j design 2: the blend rule space -- how the 0..255 factor becomes a multiplier, and the
rounding constant before >> 8.  How many classes can the planned cases tell apart?"""
import math, sys
exec(open('build/r6j/design1.py').read().split("FACTORS=")[0].replace("print(","#print(",1))
FACTORS={'ZERO':lambda s,d,c: 0, 'ONE':lambda s,d,c: 255,
         'SRC_COLOR':lambda s,d,c: s[c], 'DST_COLOR':lambda s,d,c: d[c],
         'SRC_ALPHA':lambda s,d,c: s[3], 'ONE_MINUS_SRC_ALPHA':lambda s,d,c: 255-s[3],
         'DST_ALPHA':lambda s,d,c: d[3], 'ONE_MINUS_DST_ALPHA':lambda s,d,c: 255-d[3]}
CASES=[('J1','ONE','ZERO'),('J2','ZERO','ONE'),('J3','ONE','ONE'),
       ('J4','SRC_ALPHA','ONE_MINUS_SRC_ALPHA'),('J5','DST_COLOR','ZERO'),('J6','SRC_ALPHA','ONE')]
FMAP={'id': lambda x: x, 'sat256': lambda x: 256 if x==255 else x, 'expand': lambda x: x + (x>>7)}
def predict(case, fmap, r):
    _,fs,fd=case
    out=[]
    for p in range(len(dst[0])):
        d=[dst[k][p] for k in range(4)]
        for c in range(4):
            a=FMAP[fmap](FACTORS[fs](SRC,d,c)); b=FMAP[fmap](FACTORS[fd](SRC,d,c))
            out.append(min(255,(SRC[c]*a + d[c]*b + r) >> 8))
    return out
cls={}
for fmap in FMAP:
    for r in range(256):
        key=tuple(tuple(predict(c,fmap,r)) for c in CASES)
        cls.setdefault(key,[]).append((fmap,r))
print('candidates %d -> classes %d' % (3*256, len(cls)))
big=sorted(cls.values(), key=len, reverse=True)[:3]
for v in big: print('   a class with %d members, e.g. %s' % (len(v), v[:4]))
# which single case separates the factor scale?
for case in CASES:
    s={}
    for fmap in FMAP:
        s.setdefault(tuple(predict(case,fmap,128)),[]).append(fmap)
    print('   %s alone: %d distinct pictures over the three factor maps (r=128)' % (case[0], len(s)))
