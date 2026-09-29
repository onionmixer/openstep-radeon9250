#!/usr/bin/env python3
"""R6m design 1 (docs/R6M_PLAN.md): where a second colour and depth surface can live in the window,
and what a drawn surface looks like when the texture unit reads it back.

Nothing is assumed: the regions are laid out and checked for overlap here, and the texel addresses
come from the measured row stride (max(width*4, 32) -- docs/R6H_PLAN.md 8).
"""
import sys

sys.path.insert(0, 'tools/r6')
import batch_oracle as ba                        # noqa: E402  (its chain gives go/to/zo/do)
go, to, zo = ba.go, ba.to, ba.zo

WIN = 0x40000
BUF = 0x4000                                     # 64 x 64 x 4: one colour or depth surface
USED = {'depth': (0x00000, BUF), 'texture': (0x20000, 0x400), 'colour': (0x3c000, BUF)}
# codex Z? : every offset 4 KiB aligned would hide a driver that rounds to 4 KiB, so the colour
# surface sits at the 16-byte grain the register mask allows and the texture at its 32-byte grain
NEW = {'colour2': (0x08010, BUF), 'depth2': (0x10000, BUF), 'tex2': (0x14020, 0x400)}


def overlaps(a, b):
    (p, m), (q, n) = a, b
    return p < q + n and q < p + m


print('the window is %d KiB' % (WIN // 1024))
for name, r in sorted(list(USED.items()) + list(NEW.items())):
    print('  %-8s %06x .. %06x' % (name, r[0], r[0] + r[1]))
bad = [(a, b) for a in sorted(USED | NEW) for b in sorted(USED | NEW)
       if a < b and overlaps((USED | NEW)[a], (USED | NEW)[b])]
print('overlaps: %s' % (bad or 'none'))
print('every region inside the window: %s' %
      all(0 <= r[0] and r[0] + r[1] <= WIN for r in (USED | NEW).values()))
for name, r in sorted((USED | NEW).items()):
    print('  %-8s alignment: 16B %s  32B %s  4KiB %s' %
          (name, 'ok' if r[0] % 16 == 0 else 'NO', 'ok' if r[0] % 32 == 0 else 'NO',
           'yes' if r[0] % 4096 == 0 else 'no (on purpose)'))

# what an 8x8 texture reads when it is pointed at a surface the 3D engine drew into
stride = max(8 * 4, 32)
print('an 8x8 texture reads stride %d bytes -> it covers %06x .. %06x of the surface'
      % (stride, 0, 8 * stride))
print('  texel (u, v) is the surface word at v*%d + u*4, i.e. colour pixel (x, y) = (%s)'
      % (stride, 'u + 8v, 0' if stride == 32 else '?'))
# the colour surface is 64 pixels per row (256 bytes), so the first 8 texture rows all sit in row 0
for v in range(3):
    for u in (0, 7):
        addr = v * stride + u * 4
        print('    texel (%d,%d) -> byte %3d -> colour pixel (x=%d, y=%d)'
              % (u, v, addr, (addr // 4) % 64, (addr // 4) // 64))
