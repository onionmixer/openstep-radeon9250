import sys, random, pickle, time
sys.path.insert(0,'.')
import audit as A, search as Sx
from multiprocessing import Pool
def mixed_count(sig):
    g={}
    for k,s in enumerate(sig): g.setdefault(s,[]).append(k)
    return sum(1 for v in g.values() if any(k<A.NG for k in v) and any(k>=A.NG for k in v)), len(g)
if __name__=='__main__':
    (sig,g,mixed),_=pickle.load(open('audit.pkl','rb'))
    rng=random.Random(int(sys.argv[3]) if len(sys.argv)>3 else 7)
    added=[]
    for batch in range(int(sys.argv[1])):
        C=[Sx.cand(rng) for _ in range(int(sys.argv[2]))]
        t0=time.time()
        with Pool(30) as pool: H=pool.map(A.plane_sig,C)
        left=dict(enumerate(C))
        while True:
            cur=mixed_count(sig)
            best=min(left,key=lambda i: mixed_count([a+(b,) for a,b in zip(sig,H[i])]))
            new=mixed_count([a+(b,) for a,b in zip(sig,H[best])])
            if new[0]>=cur[0]: break
            sig=[a+(b,) for a,b in zip(sig,H[best])]; added.append(C[best]); del left[best]
            print('batch',batch,'added',C[best],'mixed',new[0],'classes',new[1],flush=True)
            if new[0]==0: break
        print('batch',batch,'secs',round(time.time()-t0),'mixed now',mixed_count(sig),flush=True)
        if mixed_count(sig)[0]==0: break
    pickle.dump((added,sig),open('search3.pkl','wb'))
