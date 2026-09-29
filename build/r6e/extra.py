import sys,pickle; sys.path.insert(0,'.')
import interp as I, search as Sx
from multiprocessing import Pool
from collections import Counter,defaultdict
base,chosen,cur=pickle.load(open('search.pkl','rb'))
p0,c0=chosen[0]
extra=[(I.t.T1,[0,24,0]),                                  # exact halves along x: R = x - 3.5
       (I.t.T1,[0,0,24]),                                  # along y
       ([p0[1],p0[2],p0[0]],[c0[1],c0[2],c0[0]]),          # cyclic permutation: anchor
       ([(x-8,y-8) for x,y in p0] if min(v for p in p0 for v in p)>9 else [(x-1.5,y-1.5) for x,y in p0],c0)]   # translated
if __name__=='__main__':
    with Pool(8) as pool: H=pool.map(Sx.hashes,extra)
    RULES=Sx.RULES
    for k,h in enumerate(H):
        cur=[a+(b,) for a,b in zip(cur,h)]
        print('after extra',k,'classes',len(set(cur)))
    g=defaultdict(list)
    for r,s in zip(RULES,cur): g[s].append(r)
    def varies(v): return tuple(k for k,i in (('pos',0),('off',1),('arith',2),('scale',3),('F',4)) if len(set(r[i] for r in v))>1)
    print(Counter(varies(v) for v in g.values() if len(v)>1).most_common(8))
    for key in [('t16',(8,8),('exact',),'c','floor'),('t16',(8,8),('exact',),'c','round'),('t16',(8,8),('exact',),'c','even')]:
        v=[x for x in g.values() if key in x][0]; print(key,'class',len(v),v[:6])
    pickle.dump((base,chosen,extra,cur),open('search2.pkl','wb'))
