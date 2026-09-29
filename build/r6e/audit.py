import sys, pickle, time
sys.path.insert(0,'.')
import interp as I
from multiprocessing import Pool
base,chosen,extra,_=pickle.load(open('search2.pkl','rb'))
T1=I.t.T1; X3=I.t.TRI['X3'][0][0]; T6=I.t.TRI['T6'][0][0]
G0=(0x9a,0xbc,0xde,0x3c)
G7=dict(R=(13,201,77),G=(240,5,130),B=(60,61,250),A=(190,30,110))
G7p=dict(R=(240,5,130),G=(60,61,250),B=(190,30,110),A=(13,201,77))
RGB=[(T1,[G0[0]]*3),(T1,[G0[1]]*3),(T1,[G0[2]]*3)] + [(p,list(c)) for p,c in base+chosen+extra] + \
    [(X3,[17,201,90]),(X3,[17,201,90])] + [(T6,list(G7[k])) for k in 'RGB'] + [(T6,list(G7p[k])) for k in 'RGB']
ALPHA=[(T1,[G0[3]]*3),(X3,[17,201,90]),(T6,list(G7['A'])),(T6,list(G7p['A']))]
ALL=list(I.rules())+I.diagnostic_rules()
NG=sum(1 for _ in I.rules())
def plane_sig(plane):
    pts,cols=plane
    out=[]
    for r in ALL:
        v=I.values(pts,cols,r); out.append(hash(tuple(v[k] for k in sorted(v))))
    return out
def audit(planes,label):
    with Pool(30) as pool: H=pool.map(plane_sig,planes)
    sig=list(zip(*H))
    g={}
    for k,s in enumerate(sig): g.setdefault(s,[]).append(k)
    mixed=[v for v in g.values() if any(k<NG for k in v) and any(k>=NG for k in v)]
    print(label,'planes',len(planes),'rules',len(ALL),'classes',len(g),'mixed',len(mixed),
          'gated rules in mixed classes',sum(1 for v in mixed for k in v if k<NG))
    return sig,g,mixed
if __name__=='__main__':
    t0=time.time()
    r=audit(RGB,'RGB'); a=audit(ALPHA,'ALPHA')
    pickle.dump((r,a),open('audit.pkl','wb'))
    print('secs',round(time.time()-t0))
