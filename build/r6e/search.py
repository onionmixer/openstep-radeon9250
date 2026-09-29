import sys, random, pickle, time
sys.path.insert(0,'.')
import interp as I
from multiprocessing import Pool
RULES=list(I.rules())
def hashes(case):
    pts,cols=case
    s=I.sig_case(pts,cols)
    return [hash(s[r]) for r in RULES]
def area(p): return (p[1][0]-p[0][0])*(p[2][1]-p[0][1])-(p[2][0]-p[0][0])*(p[1][1]-p[0][1])
def cand(rng):
    while True:
        kind=rng.random()
        if kind<0.25:     # long shallow sliver
            x0=rng.uniform(2,6); y0=rng.uniform(2,28); pts=[(x0,y0),(rng.uniform(24,30),y0+rng.uniform(-3,3)),(rng.uniform(8,20),y0+rng.uniform(2,5))]
        else:
            pts=[(rng.uniform(2,30),rng.uniform(2,30)) for _ in range(3)]
        pts=[(round(x,3),round(y,3)) for x,y in pts]
        if all(1<=v<=30.9 for p in pts for v in p) and abs(area(pts))>60: break
    if rng.random()<0.3: cols=[rng.choice([0,255]),rng.randint(0,255),rng.randint(0,255)]
    elif rng.random()<0.5: base=rng.randint(20,200); cols=[base,base+rng.randint(1,9),base+rng.randint(1,9)]   # small gradient
    else: cols=[rng.randint(0,255) for _ in range(3)]
    rng.shuffle(cols)
    return (pts,cols)
if __name__=='__main__':
    rng=random.Random(20260919)
    base=[(I.t.T1,[0,240,0]),(I.t.T1,[0,0,240]),(I.t.TRI['X3'][0][0],[17,201,90])]
    C=[cand(rng) for _ in range(int(sys.argv[1]))]
    t0=time.time()
    with Pool(30) as pool:
        B=pool.map(hashes,base); H=pool.map(hashes,C)
    print('evaluated',len(C),'in',round(time.time()-t0),'s')
    cur=list(zip(*B))
    def ncls(sig): return len(set(sig))
    print('base classes',ncls(cur))
    chosen=[]
    left=dict(enumerate(C))
    for rnd in range(int(sys.argv[2])):
        best=max(left,key=lambda i: ncls([a+(b,) for a,b in zip(cur,H[i])]))
        cur=[a+(b,) for a,b in zip(cur,H[best])]; chosen.append(C[best]); del left[best]
        print('round',rnd,'classes',ncls(cur),C[best])
    pickle.dump((base,chosen,cur),open('search.pkl','wb'))
