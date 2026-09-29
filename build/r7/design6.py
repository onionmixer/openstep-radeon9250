#!/usr/bin/env python3
"""R7b design: how the batch page is allocated, and why it is not the CP block.

  python3 build/r7/design6.py

d_mmap's contract on this target was measured in R4c: the kernel asks for one page frame
number per page, and the page is 8192 bytes (`page=8192 shift=13`, the R4c gate line).  A pfn
is a shift, not a range, so the 8192 bytes behind it must be ONE physical run at an 8192-byte
boundary.  Nothing in the header promises that of a heap allocation, so the driver measures it
the same way cpBlock already measures the CP block (OSRDNDisplay.m 647-661) -- page by page,
before anything is told the address.

The question this file answers with numbers rather than preference: how much must be allocated
so that an 8192-aligned physical run of 8192 bytes can be FOUND inside it, under the weakest
assumption we are entitled to make about the allocator.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
H = os.path.join(PROJ, 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj', 'osrdn_cp.h')


def const(name):
    m = re.search(r'#define\s+%s\s+(0x[0-9a-fA-F]+|\d+)' % name, open(H).read())
    if m is None:
        raise SystemExit('%s is not defined in osrdn_cp.h' % name)
    return int(m.group(1), 0)


PAGE = 8192                     # R4c: the kernel's page, and d_mmap's unit
HW_PAGE = 4096                  # the MMU's page, and what IOPhysicalFromVirtual resolves
CONV_END = 0xa0000              # the arena cpBlock already requires itself to sit below


def main():
    bad = 0
    block = const('CP_BLOCK_BYTES')

    print('1. why the batch page is NOT carved out of the CP block')
    print('   the CP block is %d KiB and the GART maps it to the CARD (CP_GART_BASE)' % (block // 1024))
    print('   a client that could write any of it could write the ring itself')
    print('   -> a separate allocation, so that a bounds slip lands in memory the card cannot see')

    print('2. how much to allocate so an aligned run can be found')
    # The weakest useful assumption: the physical base is HW_PAGE-aligned (it is DMA memory
    # carved in hardware pages) but nothing more.  Then the candidate starts are the multiples
    # of HW_PAGE, and one of every PAGE/HW_PAGE of them is PAGE-aligned.
    stride = PAGE // HW_PAGE
    need = PAGE + (stride - 1) * HW_PAGE
    print('   a page is %d B, the MMU page is %d B -> %d candidate starts per page' % (PAGE, HW_PAGE, stride))
    print('   worst case the first aligned start is %d B in, so the request is %d + %d = %d B'
          % ((stride - 1) * HW_PAGE, PAGE, (stride - 1) * HW_PAGE, need))
    # prove it: every possible physical base, at HW_PAGE granularity, yields a usable offset
    miss = [b for b in range(0, PAGE, HW_PAGE)
            if not any((b + o) % PAGE == 0 and o + PAGE <= need
                       for o in range(0, need - PAGE + 1, HW_PAGE))]
    if miss:
        print('   FAIL: no aligned run for physical base(s) %s' % miss)
        bad += 1
    else:
        print('   checked all %d physical bases at %d B granularity: every one yields a run' %
              (PAGE // HW_PAGE, HW_PAGE))

    print('3. the arena can hold it')
    total = block + need
    print('   cpBlock already takes %d B and requires itself below %#x' % (block, CONV_END))
    print('   this adds %d B -> %d B of %d B (%.1f%%)' % (need, total, CONV_END, 100.0 * total / CONV_END))
    if total > CONV_END // 2:
        print('   FAIL: more than half the arena')
        bad += 1
    else:
        print('   room to spare; the allocation is refused (not retried) if it does not fit')

    print('4. what the driver must check before offering the window')
    for k, s in enumerate((
            'IOMallocLow(%d) returned non-zero' % need,
            'IOPhysicalFromVirtual succeeds at every %d B step across the request' % HW_PAGE,
            'those addresses are contiguous (phys[i] == phys[0] + i*%d)' % HW_PAGE,
            'an offset o exists with (phys[0]+o) %% %d == 0 and o + %d <= %d' % (PAGE, PAGE, need),
            'phys[0] + %d <= %#x (the arena bound cpBlock also asserts)' % (need, CONV_END)), 1):
        print('   C%d %s' % (k, s))
    print('   any one failing: IOFreeLow, no device, one log line -- the display is untouched')

    print('design6: %s' % ('PASS' if not bad else 'FAIL (%d)' % bad))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
