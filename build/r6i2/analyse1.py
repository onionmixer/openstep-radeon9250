"""R6i-2: the observed weight against the exact fraction, for the dyadic sweep (no setup rounding)."""
import pickle, sys, math
from fractions import Fraction as Fr
sys.path.insert(0,'tools/r6'); import persp_oracle as pe
obs=pickle.load(open('build/r6i2/observed_ff6dab1c.pkl','rb'))
for case in ('Q1','Q5','Q2','Q3'):
    w,h,_,_=pe.tex_of(case); st,tt=pe.st_of(case)
    s=pe.coord(case,st,'A',pe.MEASURED_OFF); t=pe.coord(case,tt,'A',pe.MEASURED_OFF)
    rows=[]
    for p,v in obs[case].items():
        u=s[p]*w-Fr(1,2); vv=t[p]*h-Fr(1,2)
        i0,j0=math.floor(u),math.floor(vv); fu,fv=u-i0,vv-j0
        R=(v>>16)&0xff; G=(v>>8)&0xff
        rows.append((fu,fv,i0,j0,R,G))
    fus=sorted(set(r[0] for r in rows)); fvs=sorted(set(r[1] for r in rows))
    print('== %s: %d pixels, fu %d distinct (den lcm %s), fv %s' %
          (case, len(rows), len(fus), max(f.denominator for f in fus), [str(x) for x in fvs[:3]]))
    # the R byte as a function of fu (the odd-column weight)
    tab={}
    for fu,fv,i0,j0,R,G in rows:
        wodd = fu if i0%2==0 else 1-fu
        tab.setdefault(wodd, set()).add(R)
    multi=[k for k,v in tab.items() if len(v)>1]
    ks=sorted(tab)
    print('   R depends only on the horizontal weight: %s (%d weights map to >1 byte)' % (not multi, len(multi)))
    print('   first: %s' % [(str(k), sorted(tab[k])) for k in ks[:6]])
    print('   last:  %s' % [(str(k), sorted(tab[k])) for k in ks[-3:]])
