"""R6i: split the deviation by tap parity -- a screen offset keeps its sign, a byte-map bias flips it."""
import pickle, sys, math
import numpy as np
from fractions import Fraction as Fr
sys.path.insert(0,'tools/r6'); import persp_oracle as pe
obs=pickle.load(open('build/r6i/observed_ff78c18a.pkl','rb'))
for case in ('LD','LF','LC'):
    w,h,_,pat=pe.tex_of(case); st,tt=pe.st_of(case)
    s=pe.coord(case,st,'A',Fr(0)); t=pe.coord(case,tt,'A',Fr(0))
    grad = float(pe.st_of(case)[0][1]-pe.st_of(case)[0][0])*w/24.0     # texels per pixel in x
    by={0:[],1:[]}
    for p,v in obs[case].items():
        u=s[p]*w-Fr(1,2); vv=t[p]*h-Fr(1,2)
        i,j=math.floor(u),math.floor(vv); fu=float(u-i)
        R=(v>>16)&0xff
        wobs=R/255.0
        by[i%2].append((fu, wobs, p))
    print('== %s (gradient %.4f texel/px)' % (case, grad))
    for par in (0,1):
        if not by[par]: continue
        d=np.array([ (wo-fu) if par==0 else (wo-(1-fu)) for fu,wo,p in by[par] ])
        print('   i %s: n=%3d  mean weight error %+.5f  (min %+.5f max %+.5f)' %
              ('even' if par==0 else 'odd ', len(d), d.mean(), d.min(), d.max()))
    # a screen offset o shifts fu by o*grad with the SAME sign for both parities
    if by[0] and by[1]:
        d0=np.array([wo-fu for fu,wo,p in by[0]]).mean()
        d1=np.array([wo-(1-fu) for fu,wo,p in by[1]]).mean()
        print('   -> byte-map bias (same sign) %+.5f ; screen offset %+.4f px (from the difference)' %
              ((d0+d1)/2, (d0-d1)/2/grad))
