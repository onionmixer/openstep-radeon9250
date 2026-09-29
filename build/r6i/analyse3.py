"""R6i: where exactly do the bilinear levels change?  (boundaries modulo the quantum)"""
import pickle, sys, math
from fractions import Fraction as Fr
sys.path.insert(0,'tools/r6'); import persp_oracle as pe
obs=pickle.load(open('build/r6i/observed_ff78c18a.pkl','rb'))
for case in ('LF','LD'):
    w,h,_,_=pe.tex_of(case); st,tt=pe.st_of(case)
    s=pe.coord(case,st,'A',Fr(0)); t=pe.coord(case,tt,'A',Fr(0))
    rows=[]
    for p,v in obs[case].items():
        u=s[p]*w-Fr(1,2); i=math.floor(u); f=u-i
        wodd = f if i%2==0 else 1-f
        rows.append((wodd, (v>>16)&0xff, p))
    rows.sort(key=lambda r: r[0])
    # the byte as a function of the weight: level -> [min w, max w]
    lv={}
    for f,b,p in rows: lv.setdefault(b,[f,f]); lv[b][0]=min(lv[b][0],f); lv[b][1]=max(lv[b][1],f)
    print('== %s: %d levels' % (case, len(lv)))
    ks=[]
    for b in sorted(lv):
        lo,hi=lv[b]
        ks.append((b, float(lo)*64, float(hi)*64))
    for b,lo,hi in ks[:8]:
        print('   byte %3d  w*64 in [%7.3f, %7.3f]' % (b, lo, hi))
    # boundary estimate: between the top of one level and the bottom of the next
    bs=[]
    for (b0,lo0,hi0),(b1,lo1,hi1) in zip(ks,ks[1:]):
        if b1>b0: bs.append(((hi0+lo1)/2, b0, b1))
    frac=[x[0]-math.floor(x[0]) for x in bs]
    print('   boundaries (w*64) fractional part: min %.3f max %.3f mean %.3f  n=%d' %
          (min(frac), max(frac), sum(frac)/len(frac), len(frac)))
    # byte value against k = round(w*64)
    print('   byte vs k: %s' % [(b, round((lo+hi)/2)) for b,lo,hi in ks[:6]])
