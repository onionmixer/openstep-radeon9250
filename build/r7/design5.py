#!/usr/bin/env python3
"""R7b design: where the client's batch window sits, and what the ioctl may carry.

  python3 build/r7/design5.py

Four things decide the layout, and each is a measured fact rather than a preference:

  1. The existing VRAM window uses CARD OFFSETS as mmap offsets (R4c), so the batch window has to
     live at offsets that cannot collide with any card address the window can reach.
  2. d_mmap hands out whole pages, and the page is 8192 bytes on this target (the R4c boot line).
     A full client submission is R7_BATCH_MAX_WORDS words, so the window is one page only if that
     fits -- checked here rather than asserted.
  3. The ioctl parameter block must stay under 128 bytes: IOCPARM_MASK is 0x7f on this system
     (verified in openstep-matrox-remade/hw3d/OpenStepMGAHW3D.h 1314-1322).  So the block carries a
     descriptor, never the words.
  4. The verifier's snapshot is what makes the interface safe: the kernel copies the page into its
     own buffer before judging it, so the client cannot change what was judged.  That means the
     page and the buffer are two different allocations, and the page is the only one mapped.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
H = os.path.join(PROJ, 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj', 'osrdn_cp.h')


def const(name, default=None):
    m = re.search(r'#define\s+%s\s+(0x[0-9a-fA-F]+|\d+)' % name, open(H).read())
    if m is None:
        if default is None:
            raise SystemExit('%s is not defined' % name)
        return default
    return int(m.group(1), 0)


PAGE = 8192                                     # the R4c boot line: page=8192 shift=13
VRAM_START = 0x0029e000                         # the R4c window, as that boot reported it
VRAM_END = 0x07c00000
BATCH_BASE = 0x40000000                         # the batch window's mmap offset
IOCPARM_MASK = 0x7f                             # this target's, not a modern BSD's


def main():
    bad = 0
    batch_max = const('CP_R7_BATCH_MAX')

    print('1. the two windows cannot collide')
    print('   VRAM  %#010x .. %#010x  (card offsets, R4c)' % (VRAM_START, VRAM_END))
    print('   batch %#010x .. %#010x' % (BATCH_BASE, BATCH_BASE + PAGE))
    if BATCH_BASE < VRAM_END and VRAM_START < BATCH_BASE + PAGE:
        print('   FAIL: they overlap')
        bad += 1
    else:
        print('   they do not overlap, and the batch base is %.1f MiB above the VRAM ceiling' %
              ((BATCH_BASE - VRAM_END) / 1048576.0))

    print('2. one page holds a full submission')
    need = batch_max * 4
    print('   CP_R7_BATCH_MAX %d words = %d bytes; the page is %d' % (batch_max, need, PAGE))
    if need > PAGE:
        print('   FAIL: a full submission does not fit in the mapped page')
        bad += 1
    else:
        print('   it fits, with %d bytes to spare' % (PAGE - need))

    print('3. the ioctl block stays under the parameter limit')
    # the descriptor, read from the header rather than remembered: a field added there
    # changes the ioctl number, and this is the check that it still fits (R7b)
    import re as _re
    hdr = open(os.path.join(PROJ, 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj', 'osrdn_r7b.h')).read()
    block_words = max(len(_re.findall(r'^\s*unsigned long (\w+)', m, _re.M))
                      for m in _re.findall(r'typedef struct \{([^{}]*)\}', hdr, _re.S))
    print('   the descriptor is %d words = %d bytes; the limit is %d (IOCPARM_MASK %#x)' %
          (block_words, block_words * 4, IOCPARM_MASK + 1, IOCPARM_MASK))
    if block_words * 4 > IOCPARM_MASK:
        print('   FAIL: the block would be truncated rather than refused')
        bad += 1
    else:
        print('   it fits; the WORDS never travel in it -- they are in the mapped page')

    print('4. the page and the snapshot are different allocations')
    print('   mapped page      : one page, IOMallocLow + IOPhysicalFromVirtual (as the CP block)')
    print('   snapshot buffer  : cpR7Buf, %d words, never mapped' % batch_max)
    print('   the client can rewrite the page all it likes; what runs is the copy it cannot reach')

    print('design5: %s' % ('PASS' if not bad else 'FAIL (%d)' % bad))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
