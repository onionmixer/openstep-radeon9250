import pickle, sys, math
from fractions import Fraction as Fr
sys.path.insert(0, 'tools/r6'); import depth_oracle as do
obs = pickle.load(open('build/r6f/observed_e4d44687.pkl', 'rb'))
go = do.go
name='I1_24'
pts, zs = do.triangles(name)[0]
P=[(go.pos(x,'t16'),go.pos(y,'t16')) for x,y in pts]
(x0,y0),(x1,y1),(x2,y2)=P
A=(x1-x0)*(y2-y0)-(x2-x0)*(y1-y0); z=[Fr(v) for v in zs]
def exact(x,y):
    sx,sy=Fr(2*x+1,2),Fr(2*y+1,2)
    w1=((sx-x0)*(y2-y0)-(x2-x0)*(sy-y0))/A; w2=((x1-x0)*(sy-y0)-(sx-x0)*(y1-y0))/A
    return ((1-w1-w2)*z[0]+w1*z[1]+w2*z[2])*(1<<24)
cov=sorted(go.covered(pts))
row=[(x,y) for x,y in cov if y==5]
print('x  observed    exact(2^24)      frac   diff')
for x,y in row[:14]:
    e=exact(x,y); print('%2d %9d %16.4f %8.4f %5d' % (x, obs[name][(x,y)], float(e), float(e-math.floor(e)), obs[name][(x,y)]-math.floor(e)))
d=[obs[name][q]-math.floor(exact(*q)) for q in cov]
print('diff histogram', {v: d.count(v) for v in sorted(set(d))})
# where does diff 1 happen -- by fractional part of the exact value?
import collections
b=collections.Counter()
for q in cov:
    e=exact(*q); f=float(e-math.floor(e)); b[(round(f,1), obs[name][q]-math.floor(e))]+=1
print(sorted(b.items())[:14])
