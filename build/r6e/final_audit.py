import sys, pickle, time
sys.path.insert(0,'.')
import audit as A, interp as I
from multiprocessing import Pool
from collections import Counter
base,chosen,extra,_=pickle.load(open('search2.pkl','rb'))
T1=I.t.T1; T1r=[T1[0],T1[2],T1[1]]; X3=I.t.TRI['X3'][0][0]; T6=I.t.TRI['T6'][0][0]
G0=(0x9a,0xbc,0xde,0x3c)
E=[(T1r,[200,0,56]),(T1r,[200,80,40]),(T1r,[248,80,0]),(T1r,[248,40,200])]     # threshold hits, both error signs
R_CASES=[(p,list(c)) for p,c in base+chosen+extra]+E                            # G1-G3, S1-S8, H1, H2, P1, M1, E1-E4
RGB=R_CASES+[(T1,[v]*3) for v in G0[:3]]+[(X3,[17,201,90])]*2+[(T6,list(v)) for v in ((13,201,77),(240,5,130),(60,61,250),(240,5,130),(60,61,250),(190,30,110))]
ALPHA=R_CASES+[(T1,[G0[3]]*3),(T6,[190,30,110]),(T6,[13,201,77])]
if __name__=='__main__':
    t0=time.time()
    out={}
    for label,planes in (('RGB',RGB),('ALPHA',ALPHA)):
        uniq=list(dict.fromkeys((tuple(p),tuple(c)) for p,c in planes))
        with Pool(30) as pool: H=pool.map(A.plane_sig,[(list(p),list(c)) for p,c in uniq])
        sig=list(zip(*H)); g={}
        for k,s in enumerate(sig): g.setdefault(s,[]).append(k)
        mixed=[v for v in g.values() if any(k<A.NG for k in v) and any(k>=A.NG for k in v)]
        R=A.ALL
        def hiprec(v):          # every quantized member at q>=12, the rest exact / f32 family
            return all((R[k][2][0]!='q') or R[k][2][1]>=12 for k in v)
        print(label,'distinct planes',len(uniq),'classes',len(g),'mixed',len(mixed),'of which high-precision only',sum(1 for v in mixed if hiprec(v)),flush=True)
        for key in [('t16',(8,8),('exact',),'c','floor'),('t16',(8,8),('exact',),'c','round'),('t16',(8,8),('q',8,'trunc','v0'),'c','floor')]:
            v=[x for x in g.values() if A.ALL.index(key) in x][0]
            print('  ',key,'class size',len(v),'q values',sorted(set(R[k][2][1] for k in v if R[k][2][0]=='q')),'kinds',sorted(set(R[k][2][0] for k in v)))
        out[label]=(uniq,g)
    pickle.dump(out,open('final_audit.pkl','wb'))
    print('secs',round(time.time()-t0))
