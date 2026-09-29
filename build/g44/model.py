#!/usr/bin/env python3
"""G4-4 (boot 9) numbers: K8 copyin chunks and the batch that follows, K5 mip chains and the probe's
squares (docs/G4_4_KERNEL_PLAN.md 2-3, 4).  Every number in the plan comes from here."""
import math, re, os
P = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
h = open(os.path.join(P, 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj', 'osrdn_cp.h')).read()
r = open(os.path.join(P, 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj', 'osrdn_r7b.h')).read()
t = open(os.path.join(P, 'mesa', 'OSRDNMesaTriTable.h')).read()
d = lambda txt, n: int(re.search(r'#define\s+%s\s+(\d+)' % n, txt).group(1))
APPEND, MAXW = d(h, 'CP_R7_APPEND_MAX'), d(r, 'OSRDN_R7B_MAX_WORDS')
PAGE = d(r, 'OSRDN_R7B_WINDOW_BYTES') // 4
TPRO, TVW = d(t, 'OSRDN_TEX_PROLOGUE_WORDS'), d(t, 'OSRDN_TEX_VERTEX_WORDS')
print('K8: %d words = %d append chunks of %d (last %d), one copyin <= %d B; page holds %d words' %
      (MAXW, math.ceil(MAXW / APPEND), APPEND, MAXW - (math.ceil(MAXW / APPEND) - 1) * APPEND, APPEND * 4, PAGE))
for bound, tag in ((PAGE, 'today (page)'), (MAXW, 'after K8')):
    per = (bound - TPRO - 2) // (3 * TVW)
    print('   %-14s textured triangles a batch %3d -> GHOST_MANY 300 = %d batches' % (tag, per, math.ceil(300 / per)))

def chain(w, h, minside=1):
    """bytes of an ARGB8888 mip chain in the r200 layout (r200_texstate.c 272, 282: rows rounded to
    32 B, levels 32 B aligned, contiguous) down to `minside`; == cpR7TextureBytes / texture_bytes"""
    total, levels = 0, 0
    while True:
        total = ((total + 31) & ~31) + ((w * 4 + 31) & ~31) * h
        levels += 1
        if w <= minside and h <= minside:
            return total, levels
        w, h = max(1, w // 2), max(1, h // 2)

for s in (128, 256, 512):
    b, l = chain(s, s)
    print('K5: %dx%d chain to 1x1: %d levels, %d B = %.4f x base (MAX_MIP_LEVEL %d)' % (s, s, l, b, b / (s * s * 4), l - 1))
b8, l8 = chain(128, 128, 8)
print('K5: 128x128 chain cut at 8x8: %d levels, %d B (MAX_MIP_LEVEL %d)' % (l8, b8, l8 - 1))
arena = int(re.search(r'#define\s+OSRDN_TEX_ARENA_BYTES\s+0x([0-9a-fA-F]+)UL', t).group(1), 16)
print('K5: arena %.1f MiB; pak upper bound with mips 21.30 MiB (build/g4/model.py) -> spare %.1f MiB' % (arena / 2**20, arena / 2**20 - 21.30))
# the probe: square i is 128 >> i pixels wide for a 128-texel texture -> texels per pixel 2^i -> lambda = i
print('K5 probe: squares', [128 >> i for i in range(8)], 'px; lambda = log2(texels/pixel) =', list(range(8)),
      '; Mesa NEAREST picks floor(lambda + 0.5) = the same levels (texture.c 391-397)')
# the old mask, decomposed
print('K5 fields: MIN mip modes', [hex(v << 1) for v in (2, 3, 6, 7)], 'all carry bit 2 (0x4); aniso 8..11 carry bit 4 (0x10);',
      'old CP_R7_TXFILTER_MIP 0x1c000 = bits', [b for b in range(32) if (0x1c000 >> b) & 1], '= MAX_MIP_LEVEL bit 0 and two bits below it')
