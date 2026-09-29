#!/usr/bin/env python3
"""Cross-check RV280 register offsets across three independent headers.

Reads `#define RADEON_<NAME> <value>` from
  N  NetBSD      ref/upstream/netbsd/sys/dev/pci/radeonfbreg.h   (primary)
  X  xf86-video-ati 6.14.6  src/radeon_reg.h
  F  FreeBSD stable/9       sys/dev/drm/radeon_drv.h
and prints, for every register this project uses, the offset and the
file:line where each header defines it.  A register is OK only when every
header that defines it agrees and its group's primary header defines it
(NetBSD for display groups, FreeBSD DRM for cp/gart -- see PRIMARY).
SINGLE-SOURCE marks a register only one header defines: not cross-checked.

  --markdown   emit the table for ANALYSIS.md
  (default)    human summary; exit status 1 on any disagreement or a name
               the primary header lacks

Values that are expressions (e.g. "(1 << 7)") are bit definitions, not
offsets; only plain hex/decimal literals are compared here.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
UP = os.path.join(HERE, '..', '..', 'ref', 'upstream')
HEADERS = [
    ('N', os.path.join(UP, 'netbsd/sys/dev/pci/radeonfbreg.h')),
    ('X', os.path.join(UP, 'unpacked/xf86-video-ati-6.14.6/src/radeon_reg.h')),
    ('F', os.path.join(UP, 'freebsd-stable9/sys/dev/drm/radeon_drv.h')),
]

# (group, name) -- every MMIO register named in PLAN.md R1/R2/R4/R5.
REGISTERS = [
    ('config', 'CONFIG_MEMSIZE'), ('config', 'CONFIG_APER_SIZE'),
    ('config', 'CONFIG_APER_0_BASE'), ('config', 'HOST_PATH_CNTL'),
    ('config', 'BUS_CNTL'), ('config', 'SURFACE_CNTL'),
    ('mc', 'MC_FB_LOCATION'), ('mc', 'MC_AGP_LOCATION'), ('mc', 'MC_STATUS'),
    ('mc', 'DISPLAY_BASE_ADDR'), ('mc', 'DISPLAY2_BASE_ADDR'), ('mc', 'OV0_BASE_ADDR'),
    ('crtc', 'CRTC_GEN_CNTL'), ('crtc', 'CRTC_EXT_CNTL'), ('crtc', 'CRTC2_GEN_CNTL'),
    ('crtc', 'CRTC_H_TOTAL_DISP'), ('crtc', 'CRTC_H_SYNC_STRT_WID'),
    ('crtc', 'CRTC_V_TOTAL_DISP'), ('crtc', 'CRTC_V_SYNC_STRT_WID'),
    ('crtc', 'CRTC_VLINE_CRNT_VLINE'), ('crtc', 'CRTC_CRNT_FRAME'),
    ('crtc', 'CRTC_OFFSET'), ('crtc', 'CRTC_OFFSET_CNTL'), ('crtc', 'CRTC_PITCH'),
    ('crtc', 'DISP_MERGE_CNTL'), ('crtc', 'CRTC_MORE_CNTL'), ('crtc', 'GRPH_BUFFER_CNTL'),
    ('config', 'MEM_SDRAM_MODE_REG'),
    ('pll', 'CLOCK_CNTL_INDEX'), ('pll', 'CLOCK_CNTL_DATA'),
    ('pll', 'PPLL_CNTL'), ('pll', 'PPLL_REF_DIV'), ('pll', 'PPLL_DIV_0'),
    ('pll', 'PPLL_DIV_3'), ('pll', 'VCLK_ECP_CNTL'), ('pll', 'HTOTAL_CNTL'),
    ('pll', 'MCLK_CNTL'), ('pll', 'PIXCLKS_CNTL'),
    ('dac', 'DAC_CNTL'), ('dac', 'DAC_CNTL2'), ('dac', 'DAC_MACRO_CNTL'),
    ('dac', 'TV_DAC_CNTL'), ('dac', 'DISP_OUTPUT_CNTL'), ('dac', 'DISP_HW_DEBUG'),
    ('dac', 'PALETTE_INDEX'), ('dac', 'PALETTE_30_DATA'),
    ('fp', 'FP_GEN_CNTL'), ('fp', 'FP2_GEN_CNTL'), ('fp', 'TMDS_PLL_CNTL'),
    ('fp', 'TMDS_TRANSMITTER_CNTL'),
    ('misc', 'OVR_CLR'), ('misc', 'OVR_WID_LEFT_RIGHT'), ('misc', 'OVR_WID_TOP_BOTTOM'),
    ('misc', 'OV0_SCALE_CNTL'), ('misc', 'SUBPIC_CNTL'), ('misc', 'VIPH_CONTROL'),
    ('misc', 'I2C_CNTL_1'), ('misc', 'GEN_INT_CNTL'), ('misc', 'GEN_INT_STATUS'),
    ('misc', 'CAP0_TRIG_CNTL'), ('misc', 'CAP1_TRIG_CNTL'),
    ('misc', 'BIOS_0_SCRATCH'), ('misc', 'BIOS_4_SCRATCH'),
    ('engine', 'RBBM_STATUS'), ('engine', 'RBBM_SOFT_RESET'), ('engine', 'RBBM_CNTL'),
    ('engine', 'RB3D_CNTL'), ('engine', 'DP_GUI_MASTER_CNTL'), ('engine', 'DP_DATATYPE'),
    ('engine', 'DEFAULT_PITCH_OFFSET'), ('engine', 'DST_PITCH_OFFSET'),
    ('engine', 'SRC_PITCH_OFFSET'), ('engine', 'DEFAULT_SC_BOTTOM_RIGHT'),
    ('engine', 'SC_TOP_LEFT'), ('engine', 'SC_BOTTOM_RIGHT'),
    ('engine', 'RB2D_DSTCACHE_MODE'), ('engine', 'WAIT_UNTIL'),
    # R4 (docs/R4_ENGINE_PLAN.md 12): what the engine unit reads and writes
    ('engine', 'RB2D_DSTCACHE_CTLSTAT'), ('engine', 'RB3D_DSTCACHE_CTLSTAT'),
    ('engine', 'DSTCACHE_CTLSTAT'), ('engine', 'DEFAULT_OFFSET'), ('engine', 'DEFAULT_PITCH'),
    ('engine', 'AUX_SC_CNTL'), ('engine', 'DP_CNTL'), ('engine', 'DP_WRITE_MASK'),
    ('engine', 'DP_BRUSH_FRGD_CLR'), ('engine', 'DST_Y_X'), ('engine', 'SRC_Y_X'),
    ('engine', 'DST_WIDTH_HEIGHT'),
    ('cp', 'CP_CSQ_CNTL'), ('cp', 'CP_RB_BASE'), ('cp', 'CP_RB_CNTL'),
    ('cp', 'CP_RB_RPTR'), ('cp', 'CP_RB_WPTR'), ('cp', 'CP_RB_RPTR_ADDR'),
    ('cp', 'CP_ME_RAM_ADDR'), ('cp', 'CP_ME_RAM_RADDR'), ('cp', 'CP_ME_RAM_DATAH'),
    ('cp', 'CP_ME_RAM_DATAL'), ('cp', 'SCRATCH_ADDR'), ('cp', 'SCRATCH_UMSK'),
    ('cp', 'SCRATCH_REG0'), ('cp-pio', 'CP_CSQ_APER_PRIMARY'),
    ('gart', 'AIC_CNTL'), ('gart', 'AIC_STAT'), ('gart', 'AIC_PT_BASE'),
    ('gart', 'AIC_LO_ADDR'), ('gart', 'AIC_HI_ADDR'),
]

# Primary header per group: BSD radeonfb for display, FreeBSD DRM for the CP
# and GART, which radeonfb never touches (PLAN.md section 1).
PRIMARY = {'cp': 'F', 'gart': 'F'}
# Same register, different name in some headers: {name: {header: alias}}.
ALIASES = {'SCRATCH_REG0': {'N': 'GUI_SCRATCH_REG0', 'X': 'GUI_SCRATCH_REG0'}}

# Address space is decided by how the references ACCESS a register, not by the
# header comment: radeonfbreg.h has no "/* PLL */" on PIXCLKS_CNTL (0x2d) yet
# radeonfb only touches it through PATCHPLL, and TMDS_PLL_CNTL (0x2a8) is MMIO
# despite its name.  0x08 is CLOCK_CNTL_INDEX in MMIO and VCLK_ECP_CNTL in PLL
# space, so getting this wrong writes a different register.
ACCESS_SOURCES = [
    'netbsd/sys/dev/pci/radeonfb.c',
    'unpacked/xf86-video-ati-6.14.6/src/legacy_crtc.c',
    'unpacked/xf86-video-ati-6.14.6/src/legacy_output.c',
    'unpacked/xf86-video-ati-6.14.6/src/radeon_driver.c',
    'freebsd-stable9/sys/dev/drm/radeon_cp.c',
]
PLL_ACCESS = re.compile(r'(?:GETPLL|PUTPLL|SETPLL|CLRPLL|PATCHPLL|INPLL|OUTPLLP?|'
                        r'RADEON_READ_PLL|RADEON_WRITE_PLL)\s*\(\s*(?:sc|pScrn|dev_priv)?\s*,?\s*'
                        r'RADEON_([A-Z0-9_]+)')
MMIO_ACCESS = re.compile(r'(?:GET32|PUT32|SET32|CLR32|PATCH32|INREG|OUTREGP?|'
                         r'RADEON_READ|RADEON_WRITE)\s*\(\s*(?:sc\s*,)?\s*RADEON_([A-Z0-9_]+)')


def access_spaces():
    pll, mmio = set(), set()
    for rel in ACCESS_SOURCES:
        with open(os.path.join(UP, rel), errors='replace') as f:
            text = f.read()
        pll.update(PLL_ACCESS.findall(text))
        mmio.update(MMIO_ACCESS.findall(text))
    return pll, mmio


DEF = re.compile(rb'^\s*#\s*define\s+RADEON_([A-Z0-9_]+)\s+(0x[0-9A-Fa-f]+|\d+)\b(.*)$')


def load(path):
    table = {}
    with open(path, 'rb') as f:
        for n, line in enumerate(f, 1):
            m = DEF.match(line)
            if not m:
                continue
            name = m.group(1).decode()
            rest = m.group(3).decode('latin-1')
            # PLL-indexed registers are commented "/* PLL */" in N and X
            pll = 'PLL' in rest
            # keep every definition so duplicates show up as +DUP
            table.setdefault(name, []).append((int(m.group(2), 0), n, pll))
    return table


def judge(cells, pk):
    """(status, counts as bad) for one register's definitions in each header.

    A name defined twice in one header with the SAME value is shown (+DUP) but
    is not a failure: NetBSD radeonfbreg.h defines RADEON_RB3D_DSTCACHE_CTLSTAT
    0x325C at lines 1560 and 1592 (R4, docs/R4_ENGINE_PLAN.md 12-4 #4).  A
    duplicate with a DIFFERENT value is two values, i.e. DISAGREE, and still
    fails -- --self-test shows both in one run."""
    prim = cells[pk]
    values = {d[0] for k in cells if cells[k] for d in cells[k]}
    status = 'OK'
    if not prim:
        status = 'NOT-IN-PRIMARY'
    elif len(values) != 1:
        status = 'DISAGREE'
    if any(cells[k] and len(cells[k]) > 1 for k in cells):
        status += '+DUP'
    return status, status not in ('OK', 'SINGLE-SOURCE', 'OK+DUP')


def self_test():
    cases = [
        ('one value in every header', {'N': [(1, 1, 0)], 'X': [(1, 2, 0)], 'F': None}, ('OK', False)),
        ('the same value twice in one header', {'N': [(1, 1, 0), (1, 9, 0)], 'X': [(1, 2, 0)], 'F': None},
         ('OK+DUP', False)),
        ('two values in one header', {'N': [(1, 1, 0), (2, 9, 0)], 'X': [(1, 2, 0)], 'F': None},
         ('DISAGREE+DUP', True)),
        ('headers disagree', {'N': [(1, 1, 0)], 'X': [(2, 2, 0)], 'F': None}, ('DISAGREE', True)),
        ('missing from the primary', {'N': None, 'X': [(1, 2, 0)], 'F': None}, ('NOT-IN-PRIMARY', True)),
    ]
    fails = 0
    for label, cells, want in cases:
        got = judge(cells, 'N')
        print('  %-4s %-36s %s' % ('ok' if got == want else 'FAIL', label, got))
        fails += 0 if got == want else 1
    print('regtable self-test: %s' % ('PASS' if not fails else 'FAIL'))
    return 1 if fails else 0


def main():
    if '--self-test' in sys.argv:
        return self_test()
    md = '--markdown' in sys.argv
    tabs = {k: load(p) for k, p in HEADERS}
    pll_used, mmio_used = access_spaces()
    bad = 0
    rows = []
    for group, name in REGISTERS:
        cells = {}
        for k, _ in HEADERS:
            alias = ALIASES.get(name, {}).get(k, name)
            cells[k] = tabs[k].get(alias)
        pk = PRIMARY.get(group, 'N')
        values = {d[0] for k in cells if cells[k] for d in cells[k]}
        status, isbad = judge(cells, pk)
        if isbad:
            bad += 1
        ndef = sum(1 for k in cells if cells[k])
        comment_pll = any(d[2] for k in cells if cells[k] for d in cells[k])
        if name in pll_used and name in mmio_used:
            space = 'BOTH?'
        elif name in pll_used:
            space = 'PLL idx'
        elif name in mmio_used:
            space = 'MMIO'
        else:
            space = 'PLL idx?' if comment_pll else 'MMIO?'
        if space in ('BOTH?',) or (space == 'MMIO' and comment_pll) or (space == 'PLL idx' and not comment_pll):
            space += ' (주석과 다름)' if space != 'BOTH?' else ''
        if space.startswith('BOTH'):
            bad += 1
        if status == 'OK' and ndef == 1:
            status = 'SINGLE-SOURCE'
        rows.append((group, name, cells, status, values, pk, ndef, space))
    if md:
        print('| 군 | 레지스터 | 오프셋 | 공간 | 주 | NetBSD radeonfbreg.h | xf86 radeon_reg.h | FreeBSD radeon_drv.h | 대조 |')
        print('|---|---|---|---|---|---|---|---|---|')
    for group, name, cells, status, values, pk, ndef, space in rows:
        prim = cells[pk]
        off = '0x%04x' % prim[0][0] if prim else '-'

        def where(k):
            d = cells[k]
            if not d:
                return '—'
            return ', '.join(':%d=0x%x' % (n, v) for v, n, _ in d)
        if md:
            print('| %s | `%s` | `%s` | %s | %s | %s | %s | %s | %s |' % (
                group, name, off, space, pk, where('N'), where('X'), where('F'), status))
        else:
            if status != 'OK' or '?' in space or '다름' in space:
                print('%-8s %-24s %s %-22s N[%s] X[%s] F[%s]' % (status, name, off, space, where('N'), where('X'), where('F')))
    if not md:
        single = sum(1 for r in rows if r[3] == 'SINGLE-SOURCE')
        print('registers: %d, not OK: %d, single-source: %d' % (len(rows), bad, single))
        for r in rows:
            if r[3] == 'SINGLE-SOURCE':
                print('  single-source:', r[1])
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
