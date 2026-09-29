"""R6i: the staircase of LF -- observed R against the exact fraction, level by level."""
import pickle, sys, math
from fractions import Fraction as Fr
sys.path.insert(0,'tools/r6'); import persp_oracle as pe
obs=pickle.load(open('build/r6i/observed_%s.pkl'%sys.argv[1],'rb'))
for case in ('LF','LD'):
    w,h,_,_=pe.tex_of(case); st,tt=pe.st_of(case)
    for o in (Fr(0), Fr(1,2)):
        s=pe.coord(case,st,'A',o)
        rows=[]
        for p,v in obs[case].items():
            u=s[p]*w-Fr(1,2); i=math.floor(u); f=u-i
            wodd = f if i%2==0 else 1-f
            rows.append((float(wodd), (v>>16)&0xff))
        rows.sort()
        levels=sorted(set(r[1] for r in rows))
        print('%s o=%s: %d pixels, %d distinct R, levels %s' % (case, o, len(rows), len(levels), levels[:12]))
        # transitions: where does the level change as the fraction grows?
        tr=[]
        for (f0,v0),(f1,v1) in zip(rows,rows[1:]):
            if v1!=v0: tr.append(((f0+f1)/2, v0, v1))
        print('   %d transitions; first six: %s' % (len(tr), [('%.4f'%t[0], t[1], t[2]) for t in tr[:6]]))
        if len(levels)>2:
            d=[levels[k+1]-levels[k] for k in range(len(levels)-1)]
            print('   level steps: %s' % sorted(set(d)))
        break
