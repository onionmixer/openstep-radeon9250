import sys, pickle, itertools
sys.path.insert(0,'.')
import audit as A, interp as I
from fractions import Fraction as Fr
from multiprocessing import Pool
T1=I.t.T1
GEO={'T1':T1,'T1r':[T1[0],T1[2],T1[1]],'D1':[(3,5),(29,9),(11,27)],'D2':[(6,3),(27,20),(4,24)]}   # dyadic vertices
def hits(pts,cols):
    """samples whose exact value is an integer / a half-integer (measured coverage, t16, +1/2)"""
    P,c,dx,dy,pix,smp=I.plane(pts,[Fr(v) for v in cols],'t16',(8,8))
    x0,y0=P[0]; n=h=0
    for xy in pix:
        v=c[0]+dx*(smp[xy][0]-x0)+dy*(smp[xy][1]-y0)
        n+= v.denominator==1; h+= v.denominator==2
    dyadic=all(((d.denominator & (d.denominator-1))==0) for d in (dx,dy))
    return n,h,dyadic
if __name__=='__main__':
    C=[]
    for g,pts in GEO.items():
        for cols in itertools.product((0,17,40,56,80,104,120,200,248),repeat=3):
            if len(set(cols))<2: continue
            n,h,dy=hits(pts,cols)
            if not dy and n+h>=20: C.append((n+h,g,pts,list(cols)))
    C.sort(reverse=True); C=C[:240]
    print('threshold-hitting candidates',len(C),'best',C[:3])
    added,sig=pickle.load(open('search3.pkl','rb'))
    import search3 as S3
    def score(sg):
        g={}
        for k,x in enumerate(sg): g.setdefault(x,[]).append(k)
        mixed=[v for v in g.values() if any(k<A.NG for k in v) and any(k>=A.NG for k in v)]
        return (sum(1 for v in mixed for k in v if k<A.NG), len(mixed), -len(g))
    with Pool(30) as pool: H=pool.map(A.plane_sig,[(c[2],c[3]) for c in C])
    left=dict(enumerate(C)); picked=[]
    while left:
        cur=score(sig)
        best=min(left,key=lambda i:score([a+(b,) for a,b in zip(sig,H[i])]))
        new=score([a+(b,) for a,b in zip(sig,H[best])])
        if new>=cur: break
        sig=[a+(b,) for a,b in zip(sig,H[best])]; picked.append(left.pop(best))
        print('added',picked[-1][1],picked[-1][3],'hits',picked[-1][0],'gated-in-mixed',new[0],'mixed',new[1],'classes',-new[2],flush=True)
    pickle.dump((added,picked,sig),open('exact_hits.pkl','wb'))
