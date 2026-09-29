#!/usr/bin/env python3
"""R6i design 4: how finely do LD and LF sample the horizontal weight curve, and are the taps safe?"""
import importlib.util, os, math, struct
from fractions import Fraction as Fr
def load(n):
    sp=importlib.util.spec_from_file_location(n, os.path.join('tools/r6',n+'.py'))
    m=importlib.util.module_from_spec(sp); sp.loader.exec_module(m); return m
to_=load('tex_oracle')
def f32(x):
    return Fr(struct.unpack('<f', struct.pack('<f', float(x)))[0])
DELTA=Fr(1,1024)
CASES={
 'LD': ((Fr(1,8),Fr(2,8),Fr(1,8)), (Fr(1,8),Fr(1,8),Fr(2,8))),
 'LF': ((Fr(1,8),Fr(2,8),Fr(1,8)+Fr(3,512)), (Fr(5,32),)*3),
}
for name,(st,tt) in CASES.items():
    st=tuple(f32(v) for v in st); tt=tuple(f32(v) for v in tt)
    for a in (Fr(0), Fr(-1,2)):
        s=to_.interp(st, Fr(0)); t=to_.interp(tt, Fr(0))
        fr=[]; unsafe=0
        for p in s:
            uf=s[p]*8+a; vf=t[p]*8+a
            fu=uf-math.floor(uf); fv=vf-math.floor(vf)
            if min(fu,1-fu)<=DELTA or min(fv,1-fv)<=DELTA: unsafe+=1; continue
            fr.append(fu)
        fr=sorted(set(fr))
        gaps=[b-a2 for a2,b in zip(fr,fr[1:])]
        print(f"{name} a={a}: n={len(s)} unsafe={unsafe} distinct fu={len(fr)} "
              f"min={float(min(fr)):.4f} max={float(max(fr)):.4f} largest gap={float(max(gaps)):.5f} ({float(max(gaps))*255:.1f} LSB)")
