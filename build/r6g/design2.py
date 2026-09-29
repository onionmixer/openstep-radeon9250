import sys
sys.path.insert(0,'tools/r6'); import depth_oracle as do
go=do.go
T=do.GEOM['T1z']; pix=sorted(go.covered(T)); Zc=32768
best=[]
for B in (256, 512, 1024):
    for C in (0, 256, 512, 1024):
        for ax in range(5, 25):
            for ay in (4, 8, 12, 16):
                A = Zc - B*ax - C*ay
                st = {p: A + B*p[0] + C*p[1] for p in pix}
                if min(st.values()) < 0 or max(st.values()) > 65535: continue
                lt = sum(1 for p in pix if Zc < st[p]); eq = sum(1 for p in pix if Zc == st[p]); gt = len(pix)-lt-eq
                if eq >= 8 and min(lt, gt) >= 80:
                    best.append((min(lt,gt), eq, B, C, ax, ay, lt, gt))
best.sort(reverse=True)
for b in best[:6]: print('min side %3d equal %3d  B=%4d C=%4d anchor (%2d,%2d)  less %3d greater %3d' % b)
