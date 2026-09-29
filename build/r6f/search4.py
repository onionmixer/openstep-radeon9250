# gradients via a float reciprocal: inv = fl(1/A), g = fl(num * inv); reference value and accumulation exact
import pickle, sys, math
from fractions import Fraction as Fr
sys.path.insert(0,'tools/r6'); import depth_oracle as do
ns={}; exec(open('build/r6f/search3.py').read().split('CASES=')[0], ns)
obs, fq, go = ns['obs'], ns['fq'], do.go
def setup(name):
    pts, zs = do.triangles(name)[0]
    P=[(go.pos(x,'t16'),go.pos(y,'t16')) for x,y in pts]
    (x0,y0),(x1,y1),(x2,y2)=P
    A=(x1-x0)*(y2-y0)-(x2-x0)*(y1-y0)
    bits=do.fmt_bits(name); S=1<<bits
    Z=[Fr(v)*S for v in zs]
    nx=(Z[1]-Z[0])*(y2-y0)-(Z[2]-Z[0])*(y1-y0)
    ny=(Z[2]-Z[0])*(x1-x0)-(Z[1]-Z[0])*(x2-x0)
    return P, Z, A, nx, ny, sorted(go.covered(pts)), S-1
def predict(name, mb, m, ref, inv_first):
    P, Z, A, nx, ny, pix, top = setup(name)
    if inv_first:
        inv = fq(Fr(1, 1) / A, mb, m)
        qx, qy = fq(nx * inv, mb, m), fq(ny * inv, mb, m)
    else:
        qx, qy = fq(nx / A, mb, m), fq(ny / A, mb, m)
    r = {'v0':0,'left':min(range(3),key=lambda i:(P[i][0],P[i][1])),'top':min(range(3),key=lambda i:(P[i][1],P[i][0]))}[ref]
    zr, (xr, yr) = Z[r], P[r]
    return [max(0,min(top,math.floor(zr + qx*(Fr(2*x+1,2)-xr) + qy*(Fr(2*y+1,2)-yr)))) for x,y in pix], pix
CASES=[n+b for n in do.IORDER for b in ('_24','_16')]
res=[]
for mb in range(18, 25):
    for m in ('floor','tz','up','even'):
        for ref in ('v0','left','top'):
            for inv in (True, False):
                tot=0; per={}
                for name in CASES:
                    got,pix=predict(name,mb,m,ref,inv)
                    d=sum(1 for a,p in zip(got,pix) if a!=obs[name][p]); per[name]=d; tot+=d
                res.append((tot,mb,m,ref,inv,per))
res.sort()
for t in res[:6]: print('misses %5d mb=%-2d %-5s ref=%-4s inv=%-5s %s' % (t[0],t[1],t[2],t[3],t[4],[(k,v) for k,v in t[5].items() if v][:6]))
