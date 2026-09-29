#!/usr/bin/env python3
"""The FreeBSD legacy DRM's CP lifecycle as it runs on an RV280 PCI card.

  cp_sequence.py --check          classify every register access, verify, exit 1 on a gap
  cp_sequence.py --markdown       the generated tables for docs/R5_CP_SEQUENCE.md
  cp_sequence.py --self-test      --check plus negative controls

Source: ref/upstream/freebsd-stable9/sys/dev/drm/radeon_cp.c (the primary
kernel-side reference, PLAN section 1).  Nothing here is typed from memory:

  1. Every function below is located in the source by name and brace
     matching, and every register access or helper call inside it is
     extracted mechanically.
  2. DECISIONS says, for each of those accesses in order, whether it is on
     the RV280 path ('P'), off it ('X'), or decided at run time ('R'), and
     names the condition that decides it.
  3. Each condition's source text must occur in the function above the
     access, and its truth value for an RV280 is computed: chip-family
     comparisons against the enum order parsed from radeon_drv.h, and the
     fixed facts of this card and build (PCI, not AGP, not PCIE, not IGP,
     little-endian, xf86's new memory map).
  4. An access with no decision, a decision with no access, a condition text
     that is not in the function, or a 'P' under a false condition (or 'X'
     under a true one) is a failure.

What 'new memory map' rests on: xf86-video-ati 6.14.6 sets
RADEON_SETPARAM_NEW_MEMMAP (radeon_driver.c:3681) before
RADEONDRIFinishScreenInit (radeon_driver.c:3780), which initialises the CP
through RADEONDRIKernelInit (radeon_dri.c:1755), when the kernel module is
1.23 or newer (radeon_driver.c:1674-1685).
"""

import importlib.util
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
DRM = os.path.join(PROJ, 'ref', 'upstream', 'freebsd-stable9', 'sys', 'dev', 'drm')
CP = os.path.join(DRM, 'radeon_cp.c')

_spec = importlib.util.spec_from_file_location('cmacro', os.path.join(HERE, 'cmacro.py'))
cmacro = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cmacro)

HELPERS = ('radeon_write_fb_location', 'radeon_write_agp_location', 'radeon_write_agp_base',
           'radeon_read_fb_location', 'radeon_enable_bm', 'radeon_do_wait_for_idle',
           'radeon_do_wait_for_fifo', 'radeon_do_pixcache_flush', 'radeon_init_pipes',
           'radeon_do_cp_reset', 'radeon_set_pcigart', 'radeon_setup_pcigart_surface',
           'radeon_cp_load_microcode', 'radeon_cp_init_ring_buffer', 'radeon_do_engine_reset',
           'radeon_test_writeback', 'radeon_do_cp_idle', 'radeon_do_cp_stop', 'radeon_do_cp_start',
           'radeon_do_cp_flush', 'radeon_freelist_reset', 'drm_ati_pcigart_init',
           'drm_ati_pcigart_cleanup', 'r600_page_table_init', 'r600_page_table_cleanup',
           'radeon_set_igpgart', 'rs600_set_igpgart', 'radeon_set_pciegart', 'radeon_do_cleanup_cp',
           'r600_do_cp_idle', 'r600_do_cp_stop', 'r600_do_engine_reset', 'r600_do_cp_start')
ACCESS = re.compile(
    r'\b(RADEON_WRITE_PLL|RADEON_READ_PLL|RADEON_WRITE|RADEON_READ|R500_WRITE_MCIND|R500_READ_MCIND|'
    r'RS690_WRITE_MCIND|RS690_READ_MCIND|RS600_WRITE_MCIND|RS600_READ_MCIND|OUT_RING|'
    r'RADEON_PURGE_CACHE|RADEON_PURGE_ZCACHE|RADEON_WAIT_UNTIL_IDLE|radeon_write_ring_rptr|'
    r'radeon_read_ring_rptr|SET_RING_HEAD|GET_RING_HEAD|' + '|'.join(HELPERS) + r')\s*\(\s*(?:dev,\s*)?([A-Za-z_0-9]*)')

# ---- the card and the build --------------------------------------------------

FACTS = {
    'IS_AGP': False, 'IS_PCIE': False, 'IS_IGPGART': False, 'BIG_ENDIAN': False,
    'OS_HAS_AGP_RUNTIME': False,        # #if __OS_HAS_AGP compiled in, but the card is PCI
    'new_memmap': True,
    'pcigart_offset_set': False,         # xf86 gives a table offset only on PCIE (ANALYSIS section 10)
}


def family_order():
    text = open(os.path.join(DRM, 'radeon_drv.h')).read()
    body = re.search(r'enum radeon_family \{(.*?)\};', text, re.S).group(1)
    names = [n.strip() for n in body.split(',') if n.strip()]
    return dict((n, i) for i, n in enumerate(names))


FAM = family_order()
RV280 = FAM['CHIP_RV280']


def fam(op, name):
    v = FAM[name]
    return {'<=': RV280 <= v, '>=': RV280 >= v, '==': RV280 == v, '<': RV280 < v, '>': RV280 > v}[op]


# condition key -> (source text that must appear in the function above the access, value)
COND = {
    'rs690': ('== CHIP_RS690', fam('==', 'CHIP_RS690') or fam('==', 'CHIP_RS740')),
    'le_rv350': ('<= CHIP_RV350', fam('<=', 'CHIP_RV350')),
    'le_rv280': ('<= CHIP_RV280', fam('<=', 'CHIP_RV280')),
    'ge_r600': ('>= CHIP_R600', fam('>=', 'CHIP_R600')),
    'ge_rv770': ('>= CHIP_RV770', fam('>=', 'CHIP_RV770')),
    'eq_rv515': ('== CHIP_RV515', fam('==', 'CHIP_RV515')),
    'eq_rs600': ('== CHIP_RS600', fam('==', 'CHIP_RS600')),
    'gt_rv515': ('> CHIP_RV515', fam('>', 'CHIP_RV515')),
    'eq_rv530': ('== CHIP_RV530', fam('==', 'CHIP_RV530')),
    'ge_r420': ('>= CHIP_R420', fam('>=', 'CHIP_R420')),
    'ge_rv515': ('>= CHIP_RV515', fam('>=', 'CHIP_RV515')),
    'le_rv410': ('<= CHIP_RV410', fam('<=', 'CHIP_RV410')),
    'ge_r300': ('>= CHIP_R300', fam('>=', 'CHIP_R300')),
    'r200_ucode': ('case CHIP_RV280:', True),
    'agp': ('RADEON_IS_AGP', FACTS['IS_AGP']),
    'pcie': ('RADEON_IS_PCIE', FACTS['IS_PCIE']),
    'big_endian': ('#ifdef __BIG_ENDIAN', FACTS['BIG_ENDIAN']),
    'old_memmap': ('!dev_priv->new_memmap', not FACTS['new_memmap']),
    'pcigart_on': ('if (on)', True),
    'pcigart_off': ('} else {', True),
    'offset_set': ('pcigart_offset_set', FACTS['pcigart_offset_set']),
    'gart_bus_addr': ('if (dev_priv->gart_info.bus_addr)', True),
    'writeback': ('if (dev_priv->writeback_works)', None),      # run time
    'wb_failed': ('if (!dev_priv->writeback_works)', None),     # run time
    'always': ('', True),
    'loop_ucode': ('for (i = 0; i != 256; i++)', True),
    'surfaces': ('for (i = 0; i < RADEON_MAX_SURFACES; i++)', True),
    'release_lt_r600': ('< CHIP_R600', not fam('>=', 'CHIP_R600')),
    'mmio': ('if (dev_priv->mmio)', True),
    'cp_running': ('if (dev_priv->cp_running)', None),
    'aligned': ('if (tail_aligned)', None),
}

# function -> ordered [(access, token, decision, condition, note)]
#   access: the macro or helper name; token: the first argument (register)
DECISIONS = {
    'radeon_enable_bm': [
        ('RADEON_READ', 'RADEON_BUS_CNTL', 'X', 'rs690', 'RS600_BUS_MASTER_DIS variant'),
        ('RADEON_WRITE', 'RADEON_BUS_CNTL', 'X', 'rs690', ''),
        ('RADEON_READ', 'RADEON_BUS_CNTL', 'P', 'le_rv350', ''),
        ('RADEON_WRITE', 'RADEON_BUS_CNTL', 'P', 'le_rv350', 'clears BUS_MASTER_DIS'),
    ],
    'radeon_do_pixcache_flush': [
        ('RADEON_READ', 'RADEON_RB3D_DSTCACHE_CTLSTAT', 'P', 'le_rv280', ''),
        ('RADEON_WRITE', 'RADEON_RB3D_DSTCACHE_CTLSTAT', 'P', 'le_rv280', '|= RB3D_DC_FLUSH_ALL'),
        ('RADEON_READ', 'RADEON_RB3D_DSTCACHE_CTLSTAT', 'P', 'le_rv280', 'poll !RB3D_DC_BUSY, usec_timeout x 1 us'),
    ],
    'radeon_do_wait_for_fifo': [
        ('RADEON_READ', 'RADEON_RBBM_STATUS', 'P', 'always', 'poll FIFOCNT >= entries'),
        ('RADEON_READ', 'RADEON_RBBM_STATUS', 'P', 'always', 'debug print on timeout'),
        ('RADEON_READ', 'R300_VAP_CNTL_STATUS', 'P', 'always', 'debug print on timeout: 0x2140, R200_SE_VAP_CNTL_STATUS on RV280'),
    ],
    'radeon_do_wait_for_idle': [
        ('radeon_do_wait_for_fifo', 'dev_priv', 'P', 'always', '64 entries'),
        ('RADEON_READ', 'RADEON_RBBM_STATUS', 'P', 'always', 'poll !RBBM_ACTIVE'),
        ('radeon_do_pixcache_flush', 'dev_priv', 'P', 'always', 'return value ignored'),
        ('RADEON_READ', 'RADEON_RBBM_STATUS', 'P', 'always', 'debug print on timeout'),
        ('RADEON_READ', 'R300_VAP_CNTL_STATUS', 'P', 'always', 'debug print on timeout'),
    ],
    'radeon_init_pipes': [
        ('RADEON_READ', 'RV530_GB_PIPE_SELECT2', 'X', 'eq_rv530', ''),
        ('RADEON_READ', 'R400_GB_PIPE_SELECT', 'X', 'ge_r420', ''),
        ('RADEON_WRITE_PLL', 'R500_DYN_SCLK_PWMEM_PIPE', 'X', 'ge_rv515', ''),
        ('RADEON_WRITE', 'R300_SU_REG_DEST', 'X', 'ge_rv515', ''),
        ('RADEON_WRITE', 'R300_GB_TILE_CONFIG', 'X', 'always', 'whole function is only called for >= CHIP_R300'),
        ('radeon_do_wait_for_idle', 'dev_priv', 'X', 'always', 'idem'),
        ('RADEON_WRITE', 'R300_DST_PIPE_CONFIG', 'X', 'always', 'idem'),
        ('RADEON_READ', 'R300_DST_PIPE_CONFIG', 'X', 'always', 'idem'),
        ('RADEON_WRITE', 'R300_RB2D_DSTCACHE_MODE', 'X', 'always', 'idem'),
        ('RADEON_READ', 'R300_RB2D_DSTCACHE_MODE', 'X', 'always', 'idem'),
    ],
    'radeon_cp_load_microcode': [
        ('radeon_do_wait_for_idle', 'dev_priv', 'P', 'r200_ucode', 'R200_cp_microcode; result ignored'),
        ('RADEON_WRITE', 'RADEON_CP_ME_RAM_ADDR', 'P', 'r200_ucode', '0'),
        ('RADEON_WRITE', 'RADEON_CP_ME_RAM_DATAH', 'P', 'loop_ucode', 'cp[i][1], 256 times'),
        ('RADEON_WRITE', 'RADEON_CP_ME_RAM_DATAL', 'P', 'loop_ucode', 'cp[i][0], 256 times'),
    ],
    'radeon_do_cp_idle': [
        ('RADEON_PURGE_CACHE', '', 'P', 'always', 'ring: PACKET0(RB3D_DSTCACHE_CTLSTAT), DC_FLUSH|DC_FREE'),
        ('RADEON_PURGE_ZCACHE', '', 'P', 'always', 'ring: PACKET0(RB3D_ZCACHE_CTLSTAT), ZC_FLUSH|ZC_FREE'),
        ('RADEON_WAIT_UNTIL_IDLE', '', 'P', 'always', 'ring: PACKET0(WAIT_UNTIL), 2D|3D|HOST idleclean'),
        ('radeon_do_wait_for_idle', 'dev_priv', 'P', 'always', ''),
    ],
    'radeon_do_cp_start': [
        ('radeon_do_wait_for_idle', 'dev_priv', 'P', 'always', 'result ignored'),
        ('RADEON_WRITE', 'RADEON_CP_CSQ_CNTL', 'P', 'always', 'cp_mode (xf86: CSQ_PRIBM_INDBM)'),
        ('OUT_RING', 'CP_PACKET0', 'P', 'always', 'ring: PACKET0(ISYNC_CNTL)'),
        ('OUT_RING', 'RADEON_ISYNC_ANY2D_IDLE3D', 'P', 'always', 'ring: ISYNC value'),
        ('RADEON_PURGE_CACHE', '', 'P', 'always', ''),
        ('RADEON_PURGE_ZCACHE', '', 'P', 'always', ''),
        ('RADEON_WAIT_UNTIL_IDLE', '', 'P', 'always', ''),
    ],
    'radeon_do_cp_reset': [
        ('RADEON_READ', 'RADEON_CP_RB_RPTR', 'P', 'always', ''),
        ('RADEON_WRITE', 'RADEON_CP_RB_WPTR', 'P', 'always', '= RPTR'),
        ('SET_RING_HEAD', 'dev_priv', 'P', 'always', 'memory: rptr page word 0'),
    ],
    'radeon_do_cp_stop': [
        ('RADEON_WRITE', 'RADEON_CP_CSQ_CNTL', 'P', 'always', 'CSQ_PRIDIS_INDDIS'),
    ],
    'radeon_do_engine_reset': [
        ('radeon_do_pixcache_flush', 'dev_priv', 'P', 'always', ''),
        ('RADEON_READ', 'RADEON_CLOCK_CNTL_INDEX', 'P', 'le_rv410', 'saved'),
        ('RADEON_READ_PLL', 'RADEON_MCLK_CNTL', 'P', 'le_rv410', 'saved'),
        ('RADEON_WRITE_PLL', 'RADEON_MCLK_CNTL', 'P', 'le_rv410', '| FORCEON_MCLKA|MCLKB|YCLKA|YCLKB|MC|AIC'),
        ('RADEON_READ', 'RADEON_RBBM_SOFT_RESET', 'P', 'always', 'saved'),
        ('RADEON_WRITE', 'RADEON_RBBM_SOFT_RESET', 'P', 'always', '| SOFT_RESET_CP|HI|SE|RE|PP|E2|RB'),
        ('RADEON_READ', 'RADEON_RBBM_SOFT_RESET', 'P', 'always', 'no delay'),
        ('RADEON_WRITE', 'RADEON_RBBM_SOFT_RESET', 'P', 'always', '& ~ those bits'),
        ('RADEON_READ', 'RADEON_RBBM_SOFT_RESET', 'P', 'always', 'no delay'),
        ('RADEON_WRITE_PLL', 'RADEON_MCLK_CNTL', 'P', 'le_rv410', 'restored'),
        ('RADEON_WRITE', 'RADEON_CLOCK_CNTL_INDEX', 'P', 'le_rv410', 'restored'),
        ('RADEON_WRITE', 'RADEON_RBBM_SOFT_RESET', 'P', 'le_rv410', 'restored to the saved value'),
        ('radeon_init_pipes', 'dev_priv', 'X', 'ge_r300', ''),
        ('radeon_do_cp_reset', 'dev_priv', 'P', 'always', ''),
        ('radeon_freelist_reset', 'dev', 'P', 'always', 'software only'),
    ],
    'radeon_cp_init_ring_buffer': [
        ('radeon_write_fb_location', 'dev_priv', 'X', 'old_memmap', 'MC_FB_LOCATION rewrite only with the old map'),
        ('radeon_write_agp_base', 'dev_priv', 'X', 'agp', ''),
        ('radeon_write_agp_location', 'dev_priv', 'X', 'agp', ''),
        ('RADEON_WRITE', 'RADEON_CP_RB_BASE', 'P', 'always', 'ring offset in the SG area + gart_vm_start'),
        ('RADEON_WRITE', 'RADEON_CP_RB_WPTR_DELAY', 'P', 'always', '0'),
        ('RADEON_READ', 'RADEON_CP_RB_RPTR', 'P', 'always', ''),
        ('RADEON_WRITE', 'RADEON_CP_RB_WPTR', 'P', 'always', '= RPTR'),
        ('SET_RING_HEAD', 'dev_priv', 'P', 'always', 'memory'),
        ('RADEON_WRITE', 'RADEON_CP_RB_RPTR_ADDR', 'X', 'agp', ''),
        ('RADEON_WRITE', 'RADEON_CP_RB_RPTR_ADDR', 'P', 'always', 'rptr page offset in the SG area + gart_vm_start'),
        ('RADEON_WRITE', 'RADEON_CP_RB_CNTL', 'X', 'big_endian', 'BUF_SWAP_32BIT variant'),
        ('RADEON_WRITE', 'RADEON_CP_RB_CNTL', 'P', 'always', '(fetch_l2ow << 18) | (rptr_update_l2qw << 8) | size_l2qw'),
        ('RADEON_WRITE', 'RADEON_SCRATCH_ADDR', 'P', 'always', '= RPTR_ADDR + RADEON_SCRATCH_REG_OFFSET'),
        ('RADEON_READ', 'RADEON_CP_RB_RPTR_ADDR', 'P', 'always', ''),
        ('RADEON_WRITE', 'RADEON_SCRATCH_UMSK', 'P', 'always', '0x7: writeback of scratch 0-2 ON'),
        ('radeon_enable_bm', 'dev_priv', 'P', 'always', 'bus mastering ON after writeback ON'),
        ('radeon_write_ring_rptr', 'dev_priv', 'P', 'always', 'memory scratch 0 = 0'),
        ('RADEON_WRITE', 'RADEON_LAST_FRAME_REG', 'P', 'always', '0'),
        ('radeon_write_ring_rptr', 'dev_priv', 'P', 'always', 'memory scratch 1 = 0'),
        ('RADEON_WRITE', 'RADEON_LAST_DISPATCH_REG', 'P', 'always', '0'),
        ('radeon_write_ring_rptr', 'dev_priv', 'P', 'always', 'memory scratch 2 = 0'),
        ('RADEON_WRITE', 'RADEON_LAST_CLEAR_REG', 'P', 'always', '0'),
        ('radeon_do_wait_for_idle', 'dev_priv', 'P', 'always', 'result ignored'),
        ('RADEON_WRITE', 'RADEON_ISYNC_CNTL', 'P', 'always', 'ANY2D_IDLE3D|ANY3D_IDLE2D|WAIT_IDLEGUI|CPSCRATCH_IDLEGUI'),
    ],
    'radeon_test_writeback': [
        ('radeon_write_ring_rptr', 'dev_priv', 'P', 'always', 'memory scratch 1 = 0'),
        ('RADEON_WRITE', 'RADEON_SCRATCH_REG1', 'P', 'always', '0xdeadbeef'),
        ('radeon_read_ring_rptr', 'dev_priv', 'P', 'always', 'poll memory, usec_timeout x 1 us'),
        ('RADEON_WRITE', 'RADEON_CP_RB_CNTL', 'R', 'wb_failed', '|= RB_NO_UPDATE'),
        ('RADEON_READ', 'RADEON_CP_RB_CNTL', 'R', 'wb_failed', ''),
        ('RADEON_WRITE', 'RADEON_SCRATCH_UMSK', 'R', 'wb_failed', '0'),
    ],
    'radeon_set_pcigart': [
        ('radeon_set_igpgart', 'dev_priv', 'X', 'rs690', ''),
        ('rs600_set_igpgart', 'dev_priv', 'X', 'eq_rs600', ''),
        ('radeon_set_pciegart', 'dev_priv', 'X', 'pcie', ''),
        ('RADEON_READ', 'RADEON_AIC_CNTL', 'P', 'always', ''),
        ('RADEON_WRITE', 'RADEON_AIC_CNTL', 'P', 'pcigart_on', '| PCIGART_TRANSLATE_EN  (on)'),
        ('RADEON_WRITE', 'RADEON_AIC_PT_BASE', 'P', 'pcigart_on', 'table bus address  (on)'),
        ('RADEON_WRITE', 'RADEON_AIC_LO_ADDR', 'P', 'pcigart_on', 'gart_vm_start  (on)'),
        ('RADEON_WRITE', 'RADEON_AIC_HI_ADDR', 'P', 'pcigart_on', 'gart_vm_start + gart_size - 1  (on)'),
        ('radeon_write_agp_location', 'dev_priv', 'P', 'pcigart_on', '0xffffffc0: AGP aperture off  (on)'),
        ('RADEON_WRITE', 'RADEON_AGP_COMMAND', 'P', 'pcigart_on', '0  (on)'),
        ('RADEON_WRITE', 'RADEON_AIC_CNTL', 'P', 'pcigart_off', '& ~PCIGART_TRANSLATE_EN  (off)'),
    ],
    'radeon_setup_pcigart_surface': [
        ('RADEON_WRITE', 'RADEON_SURFACE0_INFO', 'P', 'always', 'first free surface i: 0'),
        ('RADEON_WRITE', 'RADEON_SURFACE0_LOWER_BOUND', 'P', 'always', 'table bus address'),
        ('RADEON_WRITE', 'RADEON_SURFACE0_UPPER_BOUND', 'P', 'always', 'bus address + table_size'),
    ],
    'radeon_read_fb_location': [
        ('RADEON_READ', 'R700_MC_VM_FB_LOCATION', 'X', 'ge_rv770', ''),
        ('RADEON_READ', 'R600_MC_VM_FB_LOCATION', 'X', 'ge_r600', ''),
        ('R500_READ_MCIND', 'dev_priv', 'X', 'eq_rv515', ''),
        ('RS690_READ_MCIND', 'dev_priv', 'X', 'rs690', ''),
        ('RS600_READ_MCIND', 'dev_priv', 'X', 'eq_rs600', ''),
        ('R500_READ_MCIND', 'dev_priv', 'X', 'gt_rv515', ''),
        ('RADEON_READ', 'RADEON_MC_FB_LOCATION', 'P', 'always', 'the final else'),
    ],
    'radeon_write_fb_location': [
        ('RADEON_WRITE', 'R700_MC_VM_FB_LOCATION', 'X', 'ge_rv770', ''),
        ('RADEON_WRITE', 'R600_MC_VM_FB_LOCATION', 'X', 'ge_r600', ''),
        ('R500_WRITE_MCIND', 'RV515_MC_FB_LOCATION', 'X', 'eq_rv515', ''),
        ('RS690_WRITE_MCIND', 'RS690_MC_FB_LOCATION', 'X', 'rs690', ''),
        ('RS600_WRITE_MCIND', 'RS600_MC_FB_LOCATION', 'X', 'eq_rs600', ''),
        ('R500_WRITE_MCIND', 'R520_MC_FB_LOCATION', 'X', 'gt_rv515', ''),
        ('RADEON_WRITE', 'RADEON_MC_FB_LOCATION', 'P', 'always', 'the final else (only reached with the old map)'),
    ],
    'radeon_write_agp_location': [
        ('RADEON_WRITE', 'R700_MC_VM_AGP_BOT', 'X', 'ge_rv770', ''),
        ('RADEON_WRITE', 'R700_MC_VM_AGP_TOP', 'X', 'ge_rv770', ''),
        ('RADEON_WRITE', 'R600_MC_VM_AGP_BOT', 'X', 'ge_r600', ''),
        ('RADEON_WRITE', 'R600_MC_VM_AGP_TOP', 'X', 'ge_r600', ''),
        ('R500_WRITE_MCIND', 'RV515_MC_AGP_LOCATION', 'X', 'eq_rv515', ''),
        ('RS690_WRITE_MCIND', 'RS690_MC_AGP_LOCATION', 'X', 'rs690', ''),
        ('RS600_WRITE_MCIND', 'RS600_MC_AGP_LOCATION', 'X', 'eq_rs600', ''),
        ('R500_WRITE_MCIND', 'R520_MC_AGP_LOCATION', 'X', 'gt_rv515', ''),
        ('RADEON_WRITE', 'RADEON_MC_AGP_LOCATION', 'P', 'always', 'the final else'),
    ],
}

# radeon_do_init_cp has many error exits that call radeon_do_cleanup_cp; they
# are not on the success path.  Its remaining accesses, in order:
INIT_CP_PATH = [
    ('radeon_read_fb_location', 'dev_priv', 'P', 'always', 'fb_location = (MC_FB_LOCATION & 0xffff) << 16'),
    ('radeon_read_fb_location', 'dev_priv', 'P', 'always', 'fb_size = ((MC_FB_LOCATION & 0xffff0000) + 0x10000) - fb_location'),
    ('RADEON_READ', 'RADEON_CONFIG_APER_SIZE', 'X', 'old_memmap', 'old map: gart_vm_start = fb_location + APER_SIZE'),
    ('radeon_set_pcigart', 'dev_priv', 'X', 'agp', 'AGP: PCI GART off'),
    ('RADEON_READ', 'RADEON_SURFACE_CNTL', 'P', 'always', 'saved'),
    ('RADEON_WRITE', 'RADEON_SURFACE_CNTL', 'P', 'always', '0 while the table is built'),
    ('r600_page_table_init', 'dev', 'X', 'eq_rs600', ''),
    ('drm_ati_pcigart_init', '', 'P', 'always', 'table in system memory (DRM_ATI_GART_MAIN)'),
    ('RADEON_WRITE', 'RADEON_SURFACE_CNTL', 'P', 'always', 'restored'),
    ('radeon_setup_pcigart_surface', 'dev_priv', 'P', 'always', ''),
    ('r600_page_table_cleanup', '', 'X', 'eq_rs600', 'error exit'),
    ('drm_ati_pcigart_cleanup', '', 'X', 'always', 'error exit only'),
    ('radeon_set_pcigart', 'dev_priv', 'P', 'always', 'on'),
    ('radeon_cp_load_microcode', 'dev_priv', 'P', 'always', ''),
    ('radeon_cp_init_ring_buffer', 'dev_priv', 'P', 'always', ''),
    ('radeon_do_engine_reset', 'dev', 'P', 'always', ''),
    ('radeon_test_writeback', 'dev_priv', 'P', 'always', ''),
]

DECISIONS['radeon_do_cleanup_cp'] = [
    ('radeon_set_pcigart', 'dev_priv', 'P', 'gart_bus_addr', 'off: clears only PCIGART_TRANSLATE_EN'),
    ('r600_page_table_cleanup', '', 'X', 'eq_rs600', ''),
    ('drm_ati_pcigart_cleanup', '', 'P', 'gart_bus_addr', 'frees the table after translation is off'),
]
DECISIONS['radeon_do_release'] = [
    ('r600_do_cp_idle', 'dev_priv', 'X', 'ge_r600', ''),
    ('radeon_do_cp_idle', 'dev_priv', 'R', 'cp_running', 'retried with no bound until it succeeds'),
    ('r600_do_cp_stop', 'dev_priv', 'X', 'ge_r600', ''),
    ('r600_do_engine_reset', 'dev', 'X', 'ge_r600', ''),
    ('radeon_do_cp_stop', 'dev_priv', 'R', 'cp_running', ''),
    ('radeon_do_engine_reset', 'dev', 'R', 'cp_running', ''),
    ('RADEON_WRITE', 'RADEON_GEN_INT_CNTL', 'P', 'mmio', '0'),
    ('RADEON_WRITE', 'RADEON_SURFACE0_INFO', 'P', 'surfaces', '0 for every surface'),
    ('RADEON_WRITE', 'RADEON_SURFACE0_LOWER_BOUND', 'P', 'surfaces', '0'),
    ('RADEON_WRITE', 'RADEON_SURFACE0_UPPER_BOUND', 'P', 'surfaces', '0'),
    ('radeon_do_cleanup_cp', 'dev', 'P', 'release_lt_r600', 'the else of >= CHIP_R600'),
]
DECISIONS['radeon_commit_ring'] = [
    ('GET_RING_HEAD', 'dev_priv', 'P', 'always', 'after padding the tail to 16 words with PACKET2'),
    ('RADEON_WRITE', 'R600_CP_RB_WPTR', 'X', 'ge_r600', ''),
    ('RADEON_READ', 'R600_CP_RB_RPTR', 'X', 'ge_r600', ''),
    ('RADEON_WRITE', 'RADEON_CP_RB_WPTR', 'P', 'always', 'tail'),
    ('RADEON_READ', 'RADEON_CP_RB_RPTR', 'P', 'always', '"read from PCI bus to ensure correct posting"'),
]
DECISIONS['radeon_get_ring_head'] = [
    ('radeon_read_ring_rptr', 'dev_priv', 'R', 'writeback', 'memory copy of RPTR'),
    ('RADEON_READ', 'R600_CP_RB_RPTR', 'X', 'ge_r600', ''),
    ('RADEON_READ', 'RADEON_CP_RB_RPTR', 'R', 'writeback', 'register, when writeback failed'),
]

# lifecycle, for the document: (entry point, [function in call order])
LIFECYCLE = [
    ('radeon_do_init_cp (DRM_RADEON_CP_INIT)', 'radeon_do_init_cp'),
    ('radeon_do_cp_start (DRM_RADEON_CP_START)', 'radeon_do_cp_start'),
    ('radeon_commit_ring (every submission)', 'radeon_commit_ring'),
    ('radeon_do_cp_idle (CP_STOP with idle, release)', 'radeon_do_cp_idle'),
    ('radeon_do_release (last close)', 'radeon_do_release'),
    ('radeon_do_cleanup_cp', 'radeon_do_cleanup_cp'),
]


# ---- extraction ------------------------------------------------------------------

def function_body(lines, name):
    starts = [i for i, l in enumerate(lines)
              if re.match(r'^[A-Za-z].*\b%s\s*\(' % re.escape(name), l) and not l.rstrip().endswith(';')]
    if len(starts) != 1:
        raise ValueError('%s defined %d times' % (name, len(starts)))
    s = starts[0]
    j = s
    while '{' not in lines[j]:
        j += 1
    depth = 0
    k = j
    while True:
        depth += lines[k].count('{') - lines[k].count('}')
        if depth == 0:
            break
        k += 1
    return s, k


def accesses(lines, s, k, name):
    out = []
    for i in range(s + 1, k + 1):
        text = lines[i]
        stripped = text.lstrip()
        if stripped.startswith(('#', '/*', '*')):
            continue
        for m in ACCESS.finditer(text):
            if m.group(1) == name:
                continue
            out.append((i + 1, m.group(1), m.group(2)))
    return out


def check(lines=None, decisions=None, init_path=None, quiet=False):
    lines = lines if lines is not None else open(CP).read().split('\n')
    decisions = decisions if decisions is not None else dict(DECISIONS)
    init_path = init_path if init_path is not None else INIT_CP_PATH
    decisions = dict(decisions)
    failures = []
    rows = {}
    for fn in list(decisions) + ['radeon_do_init_cp']:
        if fn == 'radeon_do_init_cp':
            want = init_path
        else:
            want = decisions[fn]
        try:
            s, k = function_body(lines, fn)
        except ValueError as e:
            failures.append(str(e))
            continue
        got = accesses(lines, s, k, fn)
        if fn == 'radeon_do_init_cp':
            # error exits: every call of radeon_do_cleanup_cp in this function
            # must sit in an error branch (the line before it is DRM_ERROR/DEBUG,
            # or it is inside an 'if (...)' that returns)
            exits = [g for g in got if g[1] == 'radeon_do_cleanup_cp']
            for ln, _, _ in exits:
                nxt = lines[ln].strip()
                if not nxt.startswith('return'):
                    failures.append('radeon_do_init_cp:%d cleanup not followed by return' % ln)
            got = [g for g in got if g[1] != 'radeon_do_cleanup_cp']
            if not quiet:
                print('  radeon_do_init_cp: %d error exits call radeon_do_cleanup_cp then return' % len(exits))
        if len(got) != len(want):
            failures.append('%s: %d accesses in the source, %d decisions' % (fn, len(got), len(want)))
        fn_rows = []
        for idx, (g, w) in enumerate(zip(got, want)):
            ln, acc, tok = g
            wacc, wtok, dec, cond, note = w
            if acc != wacc or tok != wtok:
                failures.append('%s access %d at line %d is %s(%s), decision says %s(%s)' % (fn, idx, ln, acc, tok, wacc, wtok))
                continue
            text, value = COND[cond]
            if text:
                above = '\n'.join(lines[s:ln])
                if text not in above:
                    failures.append('%s:%d condition text %r not found above the access' % (fn, ln, text))
            if dec == 'P' and value is False:
                failures.append('%s:%d on path under a false condition %s' % (fn, ln, cond))
            if dec == 'X' and value is True and cond not in ('always', 'pcigart_off'):
                failures.append('%s:%d excluded under a true condition %s' % (fn, ln, cond))
            if dec == 'R' and value is not None:
                failures.append('%s:%d marked run-time but condition %s is fixed' % (fn, ln, cond))
            fn_rows.append((ln, acc, tok, dec, cond, note))
        rows[fn] = (s + 1, k + 1, fn_rows)
    return failures, rows


# ---- computed values ---------------------------------------------------------------

def drm_order(size):
    """Linux 3.10 drivers/gpu/drm/drm_bufs.c drm_order(): floor(log2), plus one
    if size is not a power of two."""
    order = 0
    tmp = size >> 1
    while tmp:
        tmp >>= 1
        order += 1
    if size & (size - 1):
        order += 1
    return order


def values():
    h = cmacro.Headers([os.path.join(DRM, 'radeon_drv.h'), os.path.join(DRM, 'radeon_drm.h')])
    v = h.value

    def p0(reg, n=0):
        return v('RADEON_CP_PACKET0') | (n << 16) | (reg >> 2)
    ring_size = 1 << 20                   # xf86 RADEON_DEFAULT_RING_SIZE 1 MB (radeon_dri.h:44)
    size_l2qw = drm_order(ring_size // 8)
    rptr_update_l2qw = drm_order(4096 // 8)
    fetch_size_l2ow = drm_order(32 // 16)
    start_words = [
        p0(v('RADEON_ISYNC_CNTL')),
        v('RADEON_ISYNC_ANY2D_IDLE3D') | v('RADEON_ISYNC_ANY3D_IDLE2D') |
        v('RADEON_ISYNC_WAIT_IDLEGUI') | v('RADEON_ISYNC_CPSCRATCH_IDLEGUI'),
        p0(v('RADEON_RB3D_DSTCACHE_CTLSTAT')), v('RADEON_RB3D_DC_FLUSH') | v('RADEON_RB3D_DC_FREE'),
        p0(v('RADEON_RB3D_ZCACHE_CTLSTAT')), v('RADEON_RB3D_ZC_FLUSH') | v('RADEON_RB3D_ZC_FREE'),
        p0(v('RADEON_WAIT_UNTIL')),
        v('RADEON_WAIT_2D_IDLECLEAN') | v('RADEON_WAIT_3D_IDLECLEAN') | v('RADEON_WAIT_HOST_IDLECLEAN'),
    ]
    padded = start_words + [v('RADEON_CP_PACKET2')] * ((16 - len(start_words) % 16) % 16)
    soft = sum(v('RADEON_SOFT_RESET_' + b) for b in ('CP', 'HI', 'SE', 'RE', 'PP', 'E2', 'RB'))
    forceon = sum(v('RADEON_FORCEON_' + b) for b in ('MCLKA', 'MCLKB', 'YCLKA', 'YCLKB', 'MC', 'AIC'))
    return {
        'ring_size': ring_size,
        'CP_RB_CNTL': (fetch_size_l2ow << 18) | (rptr_update_l2qw << 8) | size_l2qw,
        'fields': (size_l2qw, rptr_update_l2qw, fetch_size_l2ow),
        'RB_NO_UPDATE': v('RADEON_RB_NO_UPDATE'),
        'SCRATCH_REG_OFFSET': v('RADEON_SCRATCH_REG_OFFSET'),
        'start_words': start_words,
        'padded': padded,
        'soft_reset_bits': soft,
        'mclk_forceon': forceon,
        'CSQ_PRIBM_INDBM': v('RADEON_CSQ_PRIBM_INDBM'),
        'CSQ_PRIBM_INDDIS': v('RADEON_CSQ_PRIBM_INDDIS'),
        'CSQ_PRIDIS_INDDIS': v('RADEON_CSQ_PRIDIS_INDDIS'),
        'reg': dict((n, v(n)) for n in (
            'RADEON_CP_CSQ_CNTL', 'RADEON_CP_RB_BASE', 'RADEON_CP_RB_CNTL', 'RADEON_CP_RB_RPTR',
            'RADEON_CP_RB_WPTR', 'RADEON_CP_RB_RPTR_ADDR', 'RADEON_CP_RB_WPTR_DELAY', 'RADEON_SCRATCH_ADDR',
            'RADEON_SCRATCH_UMSK', 'RADEON_ISYNC_CNTL', 'RADEON_AIC_CNTL', 'RADEON_AIC_PT_BASE',
            'RADEON_AIC_LO_ADDR', 'RADEON_AIC_HI_ADDR', 'RADEON_AGP_COMMAND', 'RADEON_MC_AGP_LOCATION',
            'RADEON_MC_FB_LOCATION', 'RADEON_SURFACE_CNTL', 'RADEON_RBBM_SOFT_RESET', 'RADEON_MCLK_CNTL',
            'RADEON_BUS_CNTL', 'RADEON_CP_ME_RAM_ADDR', 'RADEON_CP_ME_RAM_DATAH', 'RADEON_CP_ME_RAM_DATAL',
            'RADEON_WAIT_UNTIL', 'RADEON_RB3D_DSTCACHE_CTLSTAT', 'RADEON_RB3D_ZCACHE_CTLSTAT',
            'RADEON_SCRATCH_REG1', 'RADEON_GEN_INT_CNTL')),
    }


def cross_headers(reg):
    """Each offset against NetBSD radeonfbreg.h and xf86 radeon_reg.h, where
    they define the name: 'same', 'DIFFERENT', or 'not defined'."""
    spec = importlib.util.spec_from_file_location('regtable', os.path.join(HERE, 'regtable.py'))
    rt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rt)
    tabs = dict((k, rt.load(p)) for k, p in rt.HEADERS if k in ('N', 'X'))
    linux = cmacro.Headers([os.path.join(PROJ, 'ref', 'upstream', 'linux-3.10', 'drivers', 'gpu', 'drm',
                                         'radeon', 'radeon_drv.h')])
    out = {}
    for n, off in reg.items():
        cells = []
        for k in ('N', 'X'):
            # regtable keys drop the RADEON_ prefix (regtable.py DEF)
            defs = tabs[k].get(n[len('RADEON_'):] if n.startswith('RADEON_') else None)
            if not defs:
                cells.append('%s: —' % k)
            else:
                vals = set(d[0] for d in defs)
                cells.append('%s: %s' % (k, 'same' if vals == {off} else 'DIFFERENT %s' % sorted(hex(x) for x in vals)))
        # Linux 3.10 radeon_drv.h: the same DRM lineage as FreeBSD, so only a
        # copy check, reported separately (L)
        try:
            lv = linux.value(n)
            cells.append('L: %s' % ('same' if lv == off else 'DIFFERENT 0x%x' % lv))
        except KeyError:
            cells.append('L: —')
        out[n] = ', '.join(cells)
    return out


# ---- output ------------------------------------------------------------------------

def markdown(rows):
    v = values()
    out = []
    out.append('### 생성표 A — 함수별 레지스터 접근과 RV280 판정')
    out.append('')
    out.append('판정: **P** RV280 PCI 경로, **X** 경로 밖, **R** 실행 중 결정.  줄은 `radeon_cp.c`.')
    for fn, (s, k, fr) in rows.items():
        out.append('')
        out.append('#### `%s` (`radeon_cp.c:%d-%d`)' % (fn, s, k))
        out.append('')
        out.append('| 줄 | 접근 | 대상 | 판정 | 조건 | 비고 |')
        out.append('|---|---|---|---|---|---|')
        for ln, acc, tok, dec, cond, note in fr:
            ctext = COND[cond][0] or '—'
            out.append('| %d | `%s` | `%s` | %s | `%s` | %s |' % (ln, acc, tok or '', dec, ctext.replace('|', '\\|'), note.replace('|', '\\|')))
    out.append('')
    out.append('### 생성표 B — 계산값')
    out.append('')
    out.append('| 항목 | 값 | 근거 |')
    out.append('|---|---|---|')
    s, r, f = v['fields']
    out.append('| `CP_RB_CNTL` (링 1 MiB, 리틀엔디안) | `0x%08x` (size_l2qw=%d, rptr_update_l2qw=%d, fetch_size_l2ow=%d) | `drm_order` = Linux `drm_bufs.c` 1602–1613, 링 1 MB = xf86 `radeon_dri.h:44` |' % (v['CP_RB_CNTL'], s, r, f))
    out.append('| `RB_NO_UPDATE` | `0x%08x` | `radeon_drv.h` |' % v['RB_NO_UPDATE'])
    out.append('| `SCRATCH_ADDR` − `CP_RB_RPTR_ADDR` | `%d` (0x%x) | `RADEON_SCRATCH_REG_OFFSET` |' % (v['SCRATCH_REG_OFFSET'], v['SCRATCH_REG_OFFSET']))
    out.append('| `RBBM_SOFT_RESET` 비트 CP·HI·SE·RE·PP·E2·RB | `0x%08x` | 엔진 리셋 |' % v['soft_reset_bits'])
    out.append('| `MCLK_CNTL` FORCEON 비트 | `0x%08x` | 엔진 리셋(PLL 공간) |' % v['mclk_forceon'])
    out.append('| `CP_CSQ_CNTL` 모드 | PRIBM_INDBM `0x%08x`(xf86), PRIBM_INDDIS `0x%08x`, PRIDIS_INDDIS `0x%08x`(stop) | `radeon_drv.h`, xf86 `radeon_dri.c:1193` |' % (v['CSQ_PRIBM_INDBM'], v['CSQ_PRIBM_INDDIS'], v['CSQ_PRIDIS_INDDIS']))
    out.append('')
    out.append('CP 시작 스트림(`radeon_do_cp_start` 의 8 워드, `radeon_commit_ring` 이 16 워드로 `PACKET2` 패딩):')
    out.append('')
    out.append('```')
    names = ['PACKET0(ISYNC_CNTL)', 'ISYNC value', 'PACKET0(RB3D_DSTCACHE_CTLSTAT)', 'DC_FLUSH|DC_FREE',
             'PACKET0(RB3D_ZCACHE_CTLSTAT)', 'ZC_FLUSH|ZC_FREE', 'PACKET0(WAIT_UNTIL)', '2D|3D|HOST_IDLECLEAN']
    for i, w in enumerate(v['padded']):
        out.append('%2d  0x%08x  %s' % (i, w, names[i] if i < len(names) else 'PACKET2'))
    out.append('```')
    out.append('')
    out.append('레지스터 오프셋(`radeon_drv.h` 에서 계산):')
    out.append('')
    out.append('N = NetBSD `radeonfbreg.h`, X = xf86 `radeon_reg.h`, L = Linux 3.10 `radeon_drv.h`(FreeBSD 와 같은 계보라 사본 확인일 뿐).')
    out.append('')
    out.append('| 레지스터 | 오프셋 | 다른 헤더 |')
    out.append('|---|---|---|')
    cross = cross_headers(v['reg'])
    for n, off in sorted(v['reg'].items(), key=lambda kv: kv[1]):
        out.append('| `%s` | `0x%04x` | %s |' % (n, off, cross[n]))
    return '\n'.join(out)


def self_test():
    failures, rows = check(quiet=True)
    ok = not failures
    print('%-4s real source: %d functions classified%s' % ('ok' if ok else 'FAIL', len(rows),
                                                          '' if ok else ' -- ' + '; '.join(failures[:3])))
    bad = 0 if ok else 1
    lines = open(CP).read().split('\n')
    # negative controls: each must produce a failure
    controls = []
    d = dict(DECISIONS)
    d['radeon_enable_bm'] = d['radeon_enable_bm'][:-1]
    controls.append(('a decision removed', dict(decisions=d), 'decisions'))
    d = dict(DECISIONS)
    d['radeon_do_engine_reset'] = [r if r[0] != 'radeon_init_pipes' else (r[0], r[1], 'P', r[3], r[4])
                                   for r in d['radeon_do_engine_reset']]
    controls.append(('path under a false family condition', dict(decisions=d), 'on path under a false condition'))
    d = dict(DECISIONS)
    d['radeon_do_pixcache_flush'] = [(r[0], r[1], 'X', r[3], r[4]) for r in d['radeon_do_pixcache_flush']]
    controls.append(('excluded under a true condition', dict(decisions=d), 'excluded under a true condition'))
    l2 = lines[:]
    ln = [i for i, l in enumerate(l2) if 'RADEON_WRITE(RADEON_SCRATCH_UMSK, 0x7);' in l][0]
    l2.insert(ln + 1, '\tRADEON_WRITE(RADEON_BUS_CNTL, 0);')
    controls.append(('an access added to the source', dict(lines=l2), 'accesses in the source'))
    l3 = [l.replace('<= CHIP_RV410', '<= CHIP_R420') for l in lines]
    controls.append(('condition text changed in the source', dict(lines=l3), 'not found above'))
    p = list(INIT_CP_PATH)
    p[4], p[5] = p[5], p[4]
    controls.append(('init path reordered', dict(init_path=p), 'decision says'))
    for label, kw, want in controls:
        f, _ = check(quiet=True, **kw)
        got = any(want in x for x in f)
        print('%-4s control: %-40s -> %s' % ('ok' if got else 'FAIL', label, f[0] if f else 'no failure'))
        bad += 0 if got else 1
    # computed-value checks
    v = values()
    exp_order = [(1, 0), (2, 1), (3, 2), (4, 2), (5, 3), (4096, 12), (4097, 13), (131072, 17)]
    for n, o in exp_order:
        if drm_order(n) != o:
            print('FAIL drm_order(%d) = %d, want %d' % (n, drm_order(n), o))
            bad += 1
    cross = cross_headers(v['reg'])
    diffs = [n for n, c in cross.items() if 'DIFFERENT' in c]
    confirmed = [n for n, c in cross.items() if 'N: same' in c or 'X: same' in c]
    copies = [n for n, c in cross.items() if n not in confirmed and 'L: same' in c]
    orphans = [n for n in cross if n not in confirmed and n not in copies]
    print('%-4s %d offsets only in the DRM lineage (FreeBSD = Linux), %d in no other tree%s' % (
        'ok' if not orphans else 'FAIL', len(copies), len(orphans), '' if not orphans else ': %s' % orphans))
    bad += 1 if orphans else 0
    print('%-4s %d of %d offsets confirmed by NetBSD or xf86 headers' % (
        'ok' if len(confirmed) * 2 > len(cross) else 'FAIL', len(confirmed), len(cross)))
    if len(confirmed) * 2 <= len(cross):
        bad += 1
    if diffs:
        print('FAIL offsets differ between header trees: %s' % diffs)
        bad += 1
    if len(v['padded']) != 16 or v['padded'][8:] != [0x80000000] * 8:
        print('FAIL ring padding')
        bad += 1
    print('cp_sequence self-test:', 'PASS' if bad == 0 else 'FAIL (%d)' % bad)
    return 1 if bad else 0


def main(argv):
    if argv[1:] == ['--self-test']:
        return self_test()
    failures, rows = check(quiet=argv[1:] == ['--markdown'])
    if argv[1:] == ['--markdown']:
        if failures:
            sys.stderr.write('\n'.join(failures) + '\n')
            return 1
        print(markdown(rows))
        return 0
    for f in failures:
        print('FAIL', f)
    total = sum(len(r[2]) for r in rows.values())
    print('cp_sequence: %d functions, %d accesses classified, %s' % (len(rows), total,
                                                                 'PASS' if not failures else 'FAIL (%d)' % len(failures)))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
