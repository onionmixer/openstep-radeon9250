import pickle, sys, math
from fractions import Fraction as Fr
sys.path.insert(0, 'tools/r6'); import depth_oracle as do
obs = pickle.load(open('build/r6f/observed_e4d44687.pkl','rb')); go=do.go
def model(name):
    pts, zs = do.triangles(name)[0]
    P=[(go.pos(x,'t16'),go.pos(y,'t16')) for x,y in pts]
    (x0,y0),(x1,y1),(x2,y2)=P
    A=(x1-x0)*(y2-y0)-(x2-x0)*(y1-y0); z=[Fr(v) for v in zs]
    def exact(x,y):
        sx,sy=Fr(2*x+1,2),Fr(2*y+1,2)
        w1=((sx-x0)*(y2-y0)-(x2-x0)*(sy-y0))/A; w2=((x1-x0)*(sy-y0)-(sx-x0)*(y1-y0))/A
        return ((1-w1-w2)*z[0]+w1*z[1]+w2*z[2])*(1<<24)
    return exact, sorted(go.covered(pts))
for name in ['I1_24']:
    exact, cov = model(name)
    odd=[(x,y,float(exact(x,y)-math.floor(exact(x,y)))) for x,y in cov
         if obs[name][(x,y)]-math.floor(exact(x,y))==-1 and abs(float(exact(x,y)-math.floor(exact(x,y)))-1/3)<0.01]
    print(name,'diff -1 with frac 1/3:',[(x,y) for x,y,_ in odd])
    ys=sorted(set(y for x,y in cov))
    for y in ys[:6]:
        r=[(x, obs[name][(x,y)]-math.floor(exact(x,y))) for x,y in cov if _==_ and (x,y) in obs[name] and y==y]
    # per-row: first covered x and the deficit pattern
    for y in ys[:8]:
        row=[x for x,yy in cov if yy==y]
        pat=''.join('.' if obs[name][(x,y)]-math.floor(exact(x,y))==0 else '-' for x in row)
        print(' y=%2d x0=%2d %s' % (y,row[0],pat))
