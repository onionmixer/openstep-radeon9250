# conv_space + codex Q3 families (docs/R6F_PLAN.md 8): reduced-precision float / fixed intermediate,
# 16->24 expansion, reserved all-ones code
import math
from fractions import Fraction as Fr
from conv_space import hyps as hyps1, f32, rnd
def e_of(z):
    e = 0
    while Fr(2) ** e > z: e -= 1
    while Fr(2) ** (e + 1) <= z: e += 1
    return e
def fq(z, mb, m):
    z = Fr(z)
    if z == 0: return z
    s = Fr(2) ** (mb - e_of(z)); return Fr(rnd(z * s, m)) / s
def hyps(bits):
    out = dict(hyps1(bits)); top = (1 << bits) - 1
    for mb in (10, 12, 14, 16, 18, 20, 22):
        for qm in ('floor', 'even'):
            for sc in ('m1', 'p2'):
                for m in ('floor', 'up', 'even'):
                    out[('fp', mb, qm, sc, m)] = (lambda z, mb=mb, qm=qm, sc=sc, m=m:
                        max(0, min(top, rnd(fq(z, mb, qm) * (top if sc == 'm1' else (1 << bits)), m))))
    for q in (8, 10, 12, 14):
        for qm in ('floor', 'up', 'even'):
            for m in ('floor', 'up', 'even'):
                out[('fx', q, qm, m)] = (lambda z, q=q, qm=qm, m=m:
                    max(0, min(top, rnd(Fr(rnd(Fr(z) * (1 << q), qm), 1 << q) * top, m))))
    for m in ('floor', 'up', 'even'):
        out[('res1', m)] = lambda z, m=m: max(0, min(top, rnd(Fr(z) * (top - 1), m)))
    if bits == 24:
        for m1 in ('floor', 'even'):
            for m2 in ('floor', 'even'):
                out[('u16to24', m1, m2)] = (lambda z, m1=m1, m2=m2:
                    max(0, min(top, rnd(Fr(rnd(Fr(z) * 65535, m1)) * top / 65535, m2))))
    return out
