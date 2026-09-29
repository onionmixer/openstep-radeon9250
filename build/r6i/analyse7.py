"""R6i: with the sample point at pixel + o, how big is the residual and what quantum fits?"""
import pickle, sys, math
import numpy as np
from fractions import Fraction as Fr
sys.path.insert(0,'tools/r6'); import persp_oracle as pe
obs=pickle.load(open('build/r6i/observed_ff78c18a.pkl','rb'))
OFFS=[Fr(0),Fr(1,8),Fr(1,4),Fr(5,16),Fr(3,8),Fr(7,16),Fr(1,2)]
for case in ('LD','LF','LC'):
    w,h,_,pat=pe.tex_of(case); st,tt=pe.st_of(case)
    print('== %s' % case)
    for o in OFFS:
        s=pe.coord(case,st,'A',o); t=pe.coord(case,tt,'A',o)
        err=[]
        for p,v in obs[case].items():
            u=s[p]*w-Fr(1,2); i=math.floor(u); fu=float(u-i)
            R=(v>>16)&0xff
            wex = fu if i%2==0 else 1-fu
            err.append(R - wex*255)
        e=np.array(err)
        print('   o=%-5s  mean %+6.2f  max |e| %5.2f  rms %5.2f LSB' % (o, e.mean(), abs(e).max(), e.std()))
