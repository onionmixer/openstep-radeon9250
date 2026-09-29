#!/usr/bin/env python3
"""PCI GART arithmetic of the reference stack, for R5b.

  gart_oracle.py --self-test
  gart_oracle.py --markdown          scenario tables for docs/R5_GART.md
  gart_oracle.py MC_FB_LOCATION [gart_MiB] [host_page]   one configuration

Every formula names the source it transcribes; all arithmetic is 32-bit
unsigned where the C is (u32 wrap is modelled, not assumed away).

  window   FreeBSD radeon_cp.c:1312-1314 (fb_location, fb_size from
           MC_FB_LOCATION) and :1355-1361 (new memory map: GART after the
           framebuffer, or before it on overflow, aligned down to 4 MiB);
           AIC_LO/HI :1059-1060; "AGP off" MC_AGP_LOCATION 0xffffffc0 :1065
  layout   xf86 radeon_dri.c RADEONDRIInitGARTValues (lines 654-679): ring at
           0, ring map = ring + one page, read-pointer page, buffers, textures
  table    FreeBSD ati_pcigart.c:184-216 and Linux 3.10 ati_pcigart.c:139-189 (then wbinvd(), :192):
           32 KiB table (radeon_drv.h:1823) of 4 KiB GART pages; entries per
           host page = PAGE_SIZE/4096; FreeBSD limits host pages by the entry
           count (overflows when PAGE_SIZE > 4096), Linux by entries/ratio
  PTE      PCI: le32(bus & 0xfffff000) in FreeBSD, le32(bus) in Linux, no flags
"""

import struct
import sys

M32 = 0xffffffff
MiB = 1 << 20
KiB = 1 << 10
GART_PAGE = 4096
TABLE_SIZE = 32 * KiB               # RADEON_PCIGART_TABLE_SIZE
RING = 1 * MiB                      # xf86 RADEON_DEFAULT_RING_SIZE
BUFS = 2 * MiB                      # xf86 RADEON_DEFAULT_BUFFER_SIZE
NR_TEX_REGIONS = 64                 # radeon_drm.h:316
LOG_TEX_GRANULARITY = 16            # radeon_drm.h:317


def decode_mc(value):
    """MC_*_LOCATION: start in the low 16 bits, top in the high 16 bits, 64 KiB units."""
    return (value & 0xffff) << 16, (((value >> 16) & 0xffff) << 16) | 0xffff


def fb_from_mc(mc_fb_location):
    """radeon_cp.c:1312-1314, in u32."""
    fb_location = ((mc_fb_location & 0xffff) << 16) & M32
    fb_size = ((((mc_fb_location & 0xffff0000) + 0x10000) & M32) - fb_location) & M32
    return fb_location, fb_size


def gart_window(fb_location, fb_size, gart_size):
    """radeon_cp.c:1355-1361 (new memory map, not AGP)."""
    base = (fb_location + fb_size) & M32
    overflowed = base < fb_location or ((base + gart_size) & M32) < base
    if overflowed:
        base = (fb_location - gart_size) & M32
    vm_start = base & 0xffc00000
    return base, vm_start, overflowed


def ranges_overlap(a0, alen, b0, blen):
    """[a0, a0+alen) and [b0, b0+blen) in the unbounded integers (no wrap)."""
    return a0 < b0 + blen and b0 < a0 + alen


def min_bits(val):
    """xf86 radeon_driver.c:986-992 RADEONMinBits."""
    if not val:
        return 1
    bits = 0
    while val:
        val >>= 1
        bits += 1
    return bits


def xf86_layout(gart_size, page_size):
    """radeon_dri.c:654-679."""
    ring_start = 0
    ring_map = RING + page_size
    rptr = ring_start + ring_map
    rptr_map = page_size
    buf = rptr + rptr_map
    buf_map = BUFS
    tex = buf + buf_map
    s = gart_size - tex
    l = min_bits((s - 1) // NR_TEX_REGIONS) if s > 0 else LOG_TEX_GRANULARITY
    if l < LOG_TEX_GRANULARITY:
        l = LOG_TEX_GRANULARITY
    tex_map = (s >> l) << l if s > 0 else 0
    return dict(ring=(ring_start, ring_map), rptr=(rptr, rptr_map), buf=(buf, buf_map),
                tex=(tex, tex_map), log2_tex_gran=l, fits=s > 0 and tex + tex_map <= gart_size)


def table_entries(gart_size, page_size, table_size=TABLE_SIZE):
    """Host pages mapped and GART entries written by each implementation.
    dev->sg->pages is the scatter/gather allocation in host pages."""
    sg_pages = (gart_size + page_size - 1) // page_size
    ratio = page_size // GART_PAGE
    max_ati = table_size // 4
    fb_pages = min(sg_pages, max_ati)                # FreeBSD ati_pcigart.c:184-186
    lx_pages = min(sg_pages, max_ati // ratio)       # Linux ati_pcigart.c:139-143
    return dict(sg_pages=sg_pages, ratio=ratio, capacity=max_ati,
                freebsd_entries=fb_pages * ratio, linux_entries=lx_pages * ratio,
                freebsd_overflow=fb_pages * ratio > max_ati,
                linux_short=lx_pages < sg_pages,
                window_pages=gart_size // GART_PAGE)


def ptes(bus_addrs, page_size, flavour):
    """The table words for host pages at bus_addrs (in order)."""
    out = []
    for addr in bus_addrs:
        for j in range(page_size // GART_PAGE):
            a = (addr + j * GART_PAGE) & M32
            out.append(a & 0xfffff000 if flavour == 'freebsd' else a)
    return out


def table_bytes(words):
    return b''.join(struct.pack('<I', w) for w in words)


def translate(words, vm_start, gpu_addr):
    """GPU address -> host bus address through the table, or None outside."""
    off = gpu_addr - vm_start
    if off < 0 or off // GART_PAGE >= len(words):
        return None
    return (words[off // GART_PAGE] & 0xfffff000) + (off & 0xfff)


def configuration(mc_fb_location, gart_size=8 * MiB, page_size=8 * KiB):
    fb_location, fb_size = fb_from_mc(mc_fb_location)
    base, vm, overflowed = gart_window(fb_location, fb_size, gart_size)
    agp0, agp1 = decode_mc(0xffffffc0)
    lay = xf86_layout(gart_size, page_size)
    tab = table_entries(gart_size, page_size)
    problems = []
    if ranges_overlap(vm, gart_size, fb_location, fb_size):
        problems.append('GART window [%08x,+%x) overlaps the framebuffer [%08x,+%x)' % (vm, gart_size, fb_location, fb_size))
    if vm + gart_size - 1 > M32:
        problems.append('GART window runs past 4 GiB')
    if ranges_overlap(vm, gart_size, agp0, agp1 - agp0 + 1):
        problems.append('GART window overlaps the "AGP off" location %08x-%08x' % (agp0, agp1))
    if base != vm:
        problems.append('aligned down from %08x to %08x' % (base, vm))
    if tab['freebsd_overflow']:
        problems.append('FreeBSD table fill overflows: %d entries into %d' % (tab['freebsd_entries'], tab['capacity']))
    if tab['window_pages'] > tab['capacity']:
        problems.append('window needs %d entries, table holds %d' % (tab['window_pages'], tab['capacity']))
    if not lay['fits']:
        problems.append('xf86 layout does not fit the window')
    return dict(fb_location=fb_location, fb_size=fb_size, base=base, vm_start=vm, overflowed=overflowed,
                aic_lo=vm, aic_hi=(vm + gart_size - 1) & M32, layout=lay, table=tab, problems=problems)


# ---- self-test ------------------------------------------------------------------

def self_test():
    bad = 0

    def expect(label, got, want):
        nonlocal bad
        ok = got == want
        print('%-4s %-58s %s' % ('ok' if ok else 'FAIL', label, '' if ok else 'got %r want %r' % (got, want)))
        bad += 0 if ok else 1

    # 128 MiB aligned at 0xe0000000: GART right after, no alignment needed
    c = configuration(0xe7ffe000)
    expect('fb from MC_FB_LOCATION e7ffe000', (c['fb_location'], c['fb_size']), (0xe0000000, 128 * MiB))
    expect('window after the framebuffer', (c['vm_start'], c['aic_hi'], c['overflowed']), (0xe8000000, 0xe87fffff, False))
    expect('no problem in the plain case', c['problems'], [])
    # framebuffer ending at 4 GiB: u32 wrap of fb_size and base, GART goes before
    c = configuration(0xfffff800)
    expect('fb_size wraps in u32 when the top word is ffff', (c['fb_location'], c['fb_size']), (0xf8000000, 128 * MiB))
    expect('overflow puts the window before the framebuffer', (c['vm_start'], c['overflowed']), (0xf7800000, True))
    # a framebuffer whose end is not on a 4 MiB boundary: align-down overlaps it
    c = configuration(0xe0ffe000 | 0)        # 0xe000_0000 .. 0xe0ff_ffff
    expect('16 MiB fb ends on a 4 MiB boundary', c['problems'], [])
    c = configuration(0xe07ee000)            # 0xe000_0000 .. 0xe07e_ffff (8 MiB - 64 KiB)
    expect('fb end off a 4 MiB boundary is reported as overlap',
           any('overlaps the framebuffer' in p for p in c['problems']), True)
    # table capacity: 32 KiB = 8192 entries = 32 MiB
    t = table_entries(32 * MiB, 8 * KiB)
    expect('32 MiB window, 8 KiB pages: exactly full', (t['freebsd_entries'], t['freebsd_overflow']), (8192, False))
    t = table_entries(64 * MiB, 8 * KiB)
    expect('64 MiB window, 8 KiB pages: FreeBSD writes 16384 into 8192',
           (t['freebsd_entries'], t['freebsd_overflow'], t['linux_entries'], t['linux_short']), (16384, True, 8192, True))
    t = table_entries(64 * MiB, 4 * KiB)
    expect('64 MiB window, 4 KiB pages: both clamp to 8192, no overflow',
           (t['freebsd_entries'], t['freebsd_overflow'], t['linux_entries']), (8192, False, 8192))
    t = table_entries(8 * MiB, 8 * KiB)
    expect('8 MiB default window, 8 KiB pages: 2048 entries', (t['sg_pages'], t['freebsd_entries']), (1024, 2048))
    # PTEs: two 4 KiB entries per 8 KiB host page; the second half's address
    w = ptes([0x12345000, 0x0abcd000], 8 * KiB, 'freebsd')
    expect('8 KiB host pages: entries are both halves', w, [0x12345000, 0x12346000, 0x0abcd000, 0x0abce000])
    expect('table bytes are little-endian', table_bytes(w[:1]), bytes([0x00, 0x50, 0x34, 0x12]))
    expect('Linux and FreeBSD agree on page-aligned addresses', ptes([0x12345000], 8 * KiB, 'linux'), w[:2])
    expect('they differ on a misaligned address (FreeBSD masks)',
           (ptes([0x12345800], 4 * KiB, 'freebsd'), ptes([0x12345800], 4 * KiB, 'linux')), ([0x12345000], [0x12345800]))
    expect('translate: second half of the first host page, offset 0x123',
           translate(w, 0xe8000000, 0xe8001123), 0x12346123)
    expect('translate: outside the table', translate(w, 0xe8000000, 0xe8004000), None)
    # xf86 layout with 8 KiB pages: ring map grows by a page, textures shrink
    l4 = xf86_layout(8 * MiB, 4 * KiB)
    l8 = xf86_layout(8 * MiB, 8 * KiB)
    expect('layout 4 KiB: rptr at ring + 4 KiB', (l4['rptr'][0], l4['buf'][0]), (RING + 4096, RING + 8192))
    expect('layout 8 KiB: rptr at ring + 8 KiB', (l8['rptr'][0], l8['buf'][0]), (RING + 8192, RING + 16384))
    expect('layout 8 KiB still fits 8 MiB', l8['fits'], True)
    expect('ring size field: RADEONMinBits(size/8)-1 = drm_order(size/8)', min_bits(RING // 8) - 1, 17)
    # differential: the window statements compiled as C (u32 semantics by the
    # compiler, not by this file) against the Python transcription
    bad += differential()
    # properties over every framebuffer start on a 256 KiB grid, sizes 4-128 MiB,
    # windows 4-64 MiB: the window never enters the "AGP off" range, and it
    # overlaps the framebuffer only when the 4 MiB align-down moved it
    n = agp_hits = ov_unshifted = ov_total = 0
    for lo in range(0, 0x10000, 4):
        for units in (64, 128, 256, 512, 1024, 2048):
            hi = lo + units - 1
            if hi > 0xffff:
                continue
            fl, fs = fb_from_mc((hi << 16) | lo)
            for gm in (4, 8, 16, 32, 64):
                gs = gm * MiB
                base, vm, _ = gart_window(fl, fs, gs)
                n += 1
                agp_hits += ranges_overlap(vm, gs, 0xffc00000, 0x400000)
                if ranges_overlap(vm, gs, fl, fs):
                    ov_total += 1
                    ov_unshifted += base == vm
    expect('sweep of %d configurations: never in the AGP-off range' % n, agp_hits, 0)
    expect('sweep: framebuffer overlap only after an alignment shift (%d overlaps)' % ov_total, ov_unshifted, 0)
    # negative controls on the checker itself
    c = configuration(0xe7ffe000, gart_size=64 * MiB)
    expect('control: 64 MiB window reports table overflow and capacity',
           sum(1 for p in c['problems'] if 'overflow' in p or 'table holds' in p), 2)
    print('gart_oracle self-test:', 'PASS' if bad == 0 else 'FAIL (%d)' % bad)
    return 1 if bad else 0


C_WINDOW = r"""
#include <stdio.h>
#include <stdint.h>
/* radeon_cp.c:1312-1314 and 1355-1361, the statements as written */
int main(void) {
    uint32_t mc, gart_size;
    while (scanf("%x %x", &mc, &gart_size) == 2) {
        uint32_t fb_location = (mc & 0xffff) << 16;
        uint32_t fb_size = ((mc & 0xffff0000u) + 0x10000) - fb_location;
        uint32_t base = fb_location + fb_size;
        if (base < fb_location || ((base + gart_size) & 0xfffffffful) < base)
            base = fb_location - gart_size;
        printf("%08x %08x %08x\n", fb_location, fb_size, base & 0xffc00000u);
    }
    return 0;
}
"""


def differential(n=20000):
    import os
    import random
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as t:
        src = os.path.join(t, 'w.c')
        exe = os.path.join(t, 'w')
        open(src, 'w').write(C_WINDOW)
        r = subprocess.run(['gcc', '-O0', '-o', exe, src], capture_output=True, text=True)
        if r.returncode != 0:
            print('FAIL differential: cannot compile the C transcription: %s' % r.stderr[:200])
            return 1
        rnd = random.Random(7)
        cases = [(rnd.getrandbits(32), rnd.choice([4, 8, 16, 32, 64, 128]) * MiB) for _ in range(n)]
        cases += [(0xffffffff, 8 * MiB), (0x0000ffff, 8 * MiB), (0xffff0000, 8 * MiB), (0, 0), (0xfffff800, M32)]
        out = subprocess.run([exe], input=''.join('%x %x\n' % c for c in cases),
                             capture_output=True, text=True).stdout.split('\n')
        mism = 0
        for (mc, gs), line in zip(cases, out):
            fl, fs = fb_from_mc(mc)
            vm = gart_window(fl, fs, gs)[1]
            if line != '%08x %08x %08x' % (fl, fs, vm):
                mism += 1
        ok = mism == 0 and len(out) > len(cases)
        print('%-4s %-58s' % ('ok' if ok else 'FAIL', 'window math vs compiled C: %d cases, %d mismatches' % (len(cases), mism)))
        return 0 if ok else 1


def markdown():
    out = ['### 생성표 — 창·표·배치 시나리오', '',
           '호스트 페이지 8 KiB(OPENSTEP i386 커널) 과 4 KiB(참고 구현의 전제) 를 나란히 둔다.', '',
           '| MC_FB_LOCATION | GART | 페이지 | fb | 창(AIC_LO..HI) | 넘침 | 표 항목(FreeBSD/Linux/용량) | 문제 |',
           '|---|---|---|---|---|---|---|---|']
    for mc, g in ((0xe7ffe000, 8), (0xe7ffe000, 32), (0xe7ffe000, 64), (0xfffff800, 8), (0xe07ee000, 8), (0xe3ffe000, 8)):
        for ps in (8 * KiB, 4 * KiB):
            c = configuration(mc, g * MiB, ps)
            t = c['table']
            out.append('| `%08x` | %d MiB | %d KiB | `%08x`+`0x%x` | `%08x..%08x` | %s | %d / %d / %d | %s |' % (
                mc, g, ps // KiB, c['fb_location'], c['fb_size'], c['aic_lo'], c['aic_hi'],
                '예' if c['overflowed'] else '—', t['freebsd_entries'], t['linux_entries'], t['capacity'],
                '; '.join(c['problems']) or '—'))
    out += ['', '### 생성표 — xf86 창 안 배치 (8 MiB 창)', '',
            '| 페이지 | 링 | rptr | 버퍼 | 텍스처 | 텍스처 입자 |', '|---|---|---|---|---|---|']
    for ps in (4 * KiB, 8 * KiB):
        l = xf86_layout(8 * MiB, ps)
        out.append('| %d KiB | `0x%06x`+`0x%x` | `0x%06x`+`0x%x` | `0x%06x`+`0x%x` | `0x%06x`+`0x%x` | 2^%d |' % (
            ps // KiB, l['ring'][0], l['ring'][1], l['rptr'][0], l['rptr'][1], l['buf'][0], l['buf'][1],
            l['tex'][0], l['tex'][1], l['log2_tex_gran']))
    return '\n'.join(out)


def main(argv):
    if argv[1:] == ['--self-test']:
        return self_test()
    if argv[1:] == ['--markdown']:
        print(markdown())
        return 0
    if len(argv) < 2:
        sys.stderr.write(__doc__)
        return 2
    mc = int(argv[1], 16)
    g = int(argv[2]) * MiB if len(argv) > 2 else 8 * MiB
    ps = int(argv[3]) if len(argv) > 3 else 8 * KiB
    c = configuration(mc, g, ps)
    for k in ('fb_location', 'fb_size', 'base', 'vm_start', 'aic_lo', 'aic_hi'):
        print('%-12s 0x%08x' % (k, c[k]))
    print('overflowed  ', c['overflowed'])
    print('table       ', c['table'])
    print('layout      ', c['layout'])
    print('problems    ', c['problems'] or 'none')
    return 1 if c['problems'] else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
