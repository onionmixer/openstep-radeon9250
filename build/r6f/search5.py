# plane form: z = c + gx*sx + gy*sy, with c (the value at the origin or a corner) also float-rounded
import pickle, sys, math
from fractions import Fraction as Fr
sys.path.insert(0,'tools/r6'); import depth_oracle as do
ns={}; exec(open('build/r6f/search3.py').read().split('CASES=')[0], ns)
obs, fq, go = ns['obs'], ns['fq'], do.go
ns4={}; exec(open('build/r6f/search4.py').read().split('\nCASES=')[0], ns4)
setup = ns4['setup']
def predict(name, mb, m, org, inv_first, cq):
    P, Z, A, nx, ny, pix, top = setup(name)
    if inv_first:
        inv = fq(Fr(1,1)/A, mb, m); qx, qy = fq(nx*inv, mb, m), fq(ny*inv, mb, m)
    else:
        qx, qy = fq(nx/A, mb, m), fq(ny/A, mb, m)
    r = min(range(3), key=lambda i: (P[i][0], P[i][1]))
    xr, yr = P[r]
    if org == 'origin':  ox, oy = Fr(0), Fr(0)
    elif org == 'bbox':  ox, oy = min(p[0] for p in P), min(p[1] for p in P)
    else:                ox, oy = xr, yr
    c = Z[r] + qx*(ox - xr) + qy*(oy - yr)
    if cq: c = fq(c, mb, m)
    return [max(0,min(top,math.floor(c + qx*(Fr(2*x+1,2)-ox) + qy*(Fr(2*y+1,2)-oy)))) for x,y in pix], pix
CASES=[n+b for n in do.IORDER for b in ('_24','_16')]
res=[]
for mb in (20,21,22,23,24):
    for m in ('floor','tz','up','even'):
        for org in ('origin','bbox','vertex'):
            for inv in (True, False):
                for cq in (True, False):
                    tot=0; per={}
                    for name in CASES:
                        got,pix=predict(name,mb,m,org,inv,cq)
                        d=sum(1 for a,p in zip(got,pix) if a!=obs[name][p]); per[name]=d; tot+=d
                    res.append((tot,mb,m,org,inv,cq,per))
res.sort()
for t in res[:6]: print('misses %5d mb=%-2d %-5s org=%-6s inv=%-5s cq=%-5s %s' % (t[0],t[1],t[2],t[3],t[4],t[5],[(k,v) for k,v in t[6].items() if v][:6]))
