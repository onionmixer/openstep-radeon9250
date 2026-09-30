#!/usr/bin/env python3
"""Pin the R5 CP invariants in the source text (docs/R5_PLAN.md 4, 7-2, 8, 9).

  check_r5_src.py            run every rule on the real files, then every mutation

Every rule carries at least one mutation, and each mutation must be caught by
the rule it targets in this same run.

  r5-offsets      every C_* register offset in osrdn_cp.m equals the reference
                  header's (FreeBSD radeon_drv.h; DIS_OUT_OF_PCI_GART_ACCESS from
                  Linux 3.10 radeon_reg.h, the only header naming it), and lies
                  inside OSRDN_MMIO_LENGTH
  r5-only-here    no other unit names a CP, GART, AGP or ME RAM register
  r5-forbidden    osrdn_cp.m never writes MC_FB_LOCATION, SURFACE_*, BUS_CNTL,
                  HOST_PATH_CNTL, SCLK_CNTL; RBBM_SOFT_RESET only inside cpReset;
                  the PLL is written only through cpMclkPut, only from cpReset
  r5-quiet        osrdn_cp.m never logs or sleeps
  r5-latched      the latched STOP writes CP_CSQ_CNTL and nothing else
  r5-scratch      the CPU writes a scratch register only in cpMap (REG5 poison)
                  and cpPrepare (the sentinels)
  r5-block        the block is freed only on the allocation's failure path, before
                  anything is told its address; osrdn_cp.m never frees it
  r5-fence        MAP, START and every SUBMIT flush the caches (cpFence) after
                  writing the block and before the GPU is told to look
  r5-tables       both bundle tables turn "RDN CP Test" on
  r5d-count       osrdn_cp.m counts every MMIO access: the three accessor macros,
                  each expanding to its counter and the real call (docs/R5D_PLAN.md 7)
  r5d-key         the inject key is only ever on together with the CP key, and
                  INJECT latches only after a read-back that did not fail
  r6-ring         only cpZclear puts registers on the ring by name, and only the R6a set
  r6c-cases       the case table: each row's IMMD count is 3 x (4 + the colour word
                  SE_VTX_FMT_0 asks for), PP_CNTL is on exactly when colour is, VF_CNTL is
                  RECT_LIST | WALK_RING | 3 (| COLOR_ORDER_RGBA); the four blend registers
                  equal Mesa 6.5.3 r200_reg.h; rdnr5cp's case bound is CP_R6_CASES
                  (docs/R6C_PLAN.md 6); R6f (docs/R6F_PLAN.md 3-2): every row has the four
                  depth fields, the R6f rows and tables equal tools/r6/depth_oracle.py's, the
                  word array is the file static of CP_R6_WORDS with the count checked first; R6g
                  (docs/R6G_PLAN.md 2): every row has rb3d and gidx, the R6g rows and the cpR6G
                  table equal the oracle's, and the prefill is verified before the draw; R6h
                  (docs/R6H_PLAN.md 2): every row has tidx, the R6h rows and the cpR6T table equal
                  tools/r6/tex_oracle.py's, and the texture is verified before the draw
  r5-stop         cpStop never compares with c->wptr after it writes CP_CSQ_CNTL
                  (RPTR reads 0 once the CSQ is off -- docs/R5_STOPFIX_PLAN.md)
"""

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'r4'))
from check_r4_src import blank, bodies, method  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
TPROJ = os.path.join(PROJ, 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj')
BUNDLE = os.path.join(PROJ, 'OSRDNDisplay')
FDRV = os.path.join(PROJ, 'ref', 'upstream', 'freebsd-stable9', 'sys', 'dev', 'drm', 'radeon_drv.h')
KREG = os.path.join(PROJ, 'ref', 'upstream', 'linux-3.10', 'drivers', 'gpu', 'drm', 'radeon', 'radeon_reg.h')
UNITS = ['OSRDNDisplay.m', 'osrdn_mode.m', 'osrdn_snap.m', 'osrdn_engine.m', 'osrdn_record.m', 'osrdn_pll.m',
         'osrdn_modelog.m', 'osrdn_window.m', 'osrdn_vmap.m', 'osrdn_cpu.m', 'osrdn_cp.m']
FILES = dict((u, TPROJ) for u in UNITS)
FILES.update({'osrdn_cp.h': TPROJ, 'osrdn_record.h': TPROJ, 'Default.table': BUNDLE, 'Instance0.table': BUNDLE})
# M2a: the user tool carries a SECOND operation-name table, and the join between
# the two is a rule now, so it must be mutable like the rest.
FILES['rdnr5cp.m'] = os.path.join(PROJ, 'tools', 'r5')
FILES.setdefault('osrdn_r7b.h', TPROJ)        # G3: the present block and verdicts
FILES.setdefault('OSRDNDisplay.m', TPROJ)      # G3: the class's r7bPresent

# C_* name in osrdn_cp.m -> (header, name in it)
HEADER_NAME = {
    'C_CLOCK_CNTL_INDEX': 'RADEON_CLOCK_CNTL_INDEX', 'C_CLOCK_CNTL_DATA': 'RADEON_CLOCK_CNTL_DATA',
    'C_BUS_CNTL': 'RADEON_BUS_CNTL', 'C_GEN_INT_CNTL': 'RADEON_GEN_INT_CNTL', 'C_GEN_INT_STATUS': 'RADEON_GEN_INT_STATUS',
    'C_RBBM_SOFT_RESET': 'RADEON_RBBM_SOFT_RESET', 'C_MC_FB_LOCATION': 'RADEON_MC_FB_LOCATION',
    'C_MC_AGP_LOCATION': 'RADEON_MC_AGP_LOCATION', 'C_AGP_BASE_2': 'RADEON_AGP_BASE_2', 'C_AGP_BASE': 'RADEON_AGP_BASE',
    'C_AIC_CNTL': 'RADEON_AIC_CNTL', 'C_AIC_STAT': 'RADEON_AIC_STAT', 'C_AIC_PT_BASE': 'RADEON_AIC_PT_BASE',
    'C_AIC_LO_ADDR': 'RADEON_AIC_LO_ADDR', 'C_AIC_HI_ADDR': 'RADEON_AIC_HI_ADDR', 'C_CP_RB_BASE': 'RADEON_CP_RB_BASE',
    'C_CP_RB_CNTL': 'RADEON_CP_RB_CNTL', 'C_CP_RB_RPTR_ADDR': 'RADEON_CP_RB_RPTR_ADDR', 'C_CP_RB_RPTR': 'RADEON_CP_RB_RPTR',
    'C_CP_RB_WPTR': 'RADEON_CP_RB_WPTR', 'C_CP_RB_WPTR_DELAY': 'RADEON_CP_RB_WPTR_DELAY',
    'C_CP_CSQ_CNTL': 'RADEON_CP_CSQ_CNTL', 'C_CP_CSQ_MODE': 'K:RADEON_CP_CSQ_MODE', 'C_SCRATCH_UMSK': 'RADEON_SCRATCH_UMSK',
    'C_SCRATCH_ADDR': 'RADEON_SCRATCH_ADDR', 'C_CP_ME_RAM_ADDR': 'RADEON_CP_ME_RAM_ADDR',
    'C_CP_ME_RAM_DATAH': 'RADEON_CP_ME_RAM_DATAH', 'C_CP_ME_RAM_DATAL': 'RADEON_CP_ME_RAM_DATAL',
    'C_CP_CSQ_STAT': 'K:RADEON_CP_CSQ_STAT', 'C_CP_CSQ2_STAT': 'K:RADEON_CP_CSQ2_STAT', 'C_RBBM_STATUS': 'RADEON_RBBM_STATUS', 'C_AGP_COMMAND': 'RADEON_AGP_COMMAND',
    'C_SCRATCH_REG0': 'RADEON_SCRATCH_REG0', 'C_SCRATCH_REG5': 'RADEON_SCRATCH_REG5', 'C_ISYNC_CNTL': 'RADEON_ISYNC_CNTL',
    'C_RB3D_DEPTHOFFSET': 'RADEON_RB3D_DEPTHOFFSET', 'C_RB3D_COLOROFFSET': 'RADEON_RB3D_COLOROFFSET',
    'C_RB3D_DSTCACHE_CTLSTAT': 'RADEON_RB3D_DSTCACHE_CTLSTAT', 'C_PLL_MCLK_CNTL': 'RADEON_MCLK_CNTL',
    # R6a (docs/R6_PLAN.md 7)
    'C_SURFACE_CNTL': 'RADEON_SURFACE_CNTL', 'C_SE_TCL_STATE_FLUSH': 'RADEON_SE_TCL_STATE_FLUSH',
    'C_SE_VAP_CNTL_STATUS': 'R200_SE_VAP_CNTL_STATUS', 'C_PP_CNTL_X': 'R200_PP_CNTL_X',
    'C_PP_TXMULTI_CTL_0': 'K:R200_PP_TXMULTI_CTL_0', 'C_SE_VTX_STATE_CNTL': 'R200_SE_VTX_STATE_CNTL',
    'C_RB3D_DEPTHPITCH': 'RADEON_RB3D_DEPTHPITCH', 'C_RB3D_COLORPITCH': 'RADEON_RB3D_COLORPITCH',
    'C_RB3D_CNTL': 'RADEON_RB3D_CNTL', 'C_RB3D_ZCACHE_CTLSTAT': 'RADEON_RB3D_ZCACHE_CTLSTAT',
    'C_WAIT_UNTIL': 'RADEON_WAIT_UNTIL', 'C_RE_TOP_LEFT': 'RADEON_RE_TOP_LEFT', 'C_RE_WIDTH_HEIGHT': 'RADEON_RE_WIDTH_HEIGHT',
    'C_RB3D_DEPTHXY_OFFSET': 'R200_RB3D_DEPTHXY_OFFSET',
}
# R6a: the only registers ZCLEAR may write through the ring (the precedent's own come from a table the sim compares)
R6_RING_OK = {'C_SE_TCL_STATE_FLUSH', 'C_SE_VAP_CNTL_STATUS', 'C_PP_CNTL_X', 'C_PP_TXMULTI_CTL_0', 'C_SE_VTX_STATE_CNTL',
              'C_RB3D_DEPTHOFFSET', 'C_RB3D_DEPTHPITCH', 'C_RB3D_COLOROFFSET', 'C_RB3D_COLORPITCH', 'C_SCRATCH_REG0',
              'C_RE_TOP_LEFT', 'C_RE_WIDTH_HEIGHT', 'C_RB3D_DSTCACHE_CTLSTAT', 'C_RB3D_ZCACHE_CTLSTAT', 'C_WAIT_UNTIL',
              'C_RB3D_CNTL', 'C_RB3D_DEPTHXY_OFFSET',
              'C_PP_TXCBLEND_0', 'C_PP_TXCBLEND2_0', 'C_PP_TXABLEND_0', 'C_PP_TXABLEND2_0',      # R6c
              'C_RB3D_ZSTENCILCNTL',                                                           # R6g: the second draw's test
              'C_PP_TXFILTER_0', 'C_PP_TXFORMAT_0', 'C_PP_TXFORMAT_X_0', 'C_PP_TXSIZE_0',
              'C_PP_TXPITCH_0', 'C_PP_TXOFFSET_0',                                             # R6h: the texture unit
              'C_RB3D_BLENDCNTL',                                               # R6j: the blend unit (docs/R6J_PLAN.md 1)
              'C_RE_AUX_SCISSOR_CNTL', 'C_RE_SCISSOR_TL_0', 'C_RE_SCISSOR_BR_0', 'C_RE_SCISSOR_TL_1',
              'C_RE_SCISSOR_BR_1', 'C_RE_SCISSOR_TL_2', 'C_RE_SCISSOR_BR_2',     # R6k (docs/R6K_PLAN.md 4)
              'C_SE_VTX_FMT_0', 'C_SE_VTX_FMT_1',   # R7a: the prefix DEFINES the vertex format, so a
                                                    # client can never inherit the last one's
                                                    # (docs/R7_PLAN.md 4-1 c)
              'C_PP_TRI_PERF', 'C_PP_PERF_CNTL',    # G4-7 (docs/G4_7_TRIPERF_PLAN.md 2-3): the prefix writes the
                                                    # reference's 0 for both (r200_state_init.c 984-986)
              'C_PP_TAM_DEBUG3'}                    # G4-9 (docs/G4_8_REPLAY_PLAN.md 11): the DRI's LRU workaround, 0x6
MESA_REG = os.path.join(PROJ, 'ref', 'upstream', 'unpacked', 'Mesa-6.5.3', 'src', 'mesa', 'drivers', 'dri', 'r200',
                        'r200_reg.h')
MESA_BLEND = {'C_PP_TXCBLEND_0': 'R200_PP_TXCBLEND_0', 'C_PP_TXCBLEND2_0': 'R200_PP_TXCBLEND2_0',
              'C_PP_TXABLEND_0': 'R200_PP_TXABLEND_0', 'C_PP_TXABLEND2_0': 'R200_PP_TXABLEND2_0'}
RDNR5CP = os.path.join(PROJ, 'tools', 'r5', 'rdnr5cp.m')
import importlib.util  # noqa: E402
_ts = importlib.util.spec_from_file_location('tri_oracle', os.path.join(PROJ, 'tools', 'r6', 'tri_oracle.py'))
TO = importlib.util.module_from_spec(_ts)
_ts.loader.exec_module(TO)
_gs = importlib.util.spec_from_file_location('gouraud_oracle', os.path.join(PROJ, 'tools', 'r6', 'gouraud_oracle.py'))
GO = importlib.util.module_from_spec(_gs)
_gs.loader.exec_module(GO)
_ds = importlib.util.spec_from_file_location('depth_oracle', os.path.join(PROJ, 'tools', 'r6', 'depth_oracle.py'))
DO = importlib.util.module_from_spec(_ds)
_ds.loader.exec_module(DO)
_es = importlib.util.spec_from_file_location('tex_oracle', os.path.join(PROJ, 'tools', 'r6', 'tex_oracle.py'))
TE = importlib.util.module_from_spec(_es)
_es.loader.exec_module(TE)
_ps = importlib.util.spec_from_file_location('persp_oracle', os.path.join(PROJ, 'tools', 'r6', 'persp_oracle.py'))
PE = importlib.util.module_from_spec(_ps)
_ps.loader.exec_module(PE)
_ss = importlib.util.spec_from_file_location('scissor_oracle', os.path.join(PROJ, 'tools', 'r6', 'scissor_oracle.py'))
SC = importlib.util.module_from_spec(_ss)
_ss.loader.exec_module(SC)
_bs = importlib.util.spec_from_file_location('batch_oracle', os.path.join(PROJ, 'tools', 'r6', 'batch_oracle.py'))
BA = importlib.util.module_from_spec(_bs)
_bs.loader.exec_module(BA)
_rs = importlib.util.spec_from_file_location('reuse_oracle', os.path.join(PROJ, 'tools', 'r6', 'reuse_oracle.py'))
RU = importlib.util.module_from_spec(_rs)
_rs.loader.exec_module(RU)
_vs = importlib.util.spec_from_file_location('verify_oracle', os.path.join(PROJ, 'tools', 'r7', 'verify_oracle.py'))
VO = importlib.util.module_from_spec(_vs)
_vs.loader.exec_module(VO)


def ring_writes(body):
    return [m.split('+')[0].strip() for m in re.findall(r'C_P0\(([^)]*)\)', body)]
BITS = {'C_TRANSLATE_EN': 'RADEON_PCIGART_TRANSLATE_EN', 'C_DIS_OUT_OF_GART': 'K:RADEON_DIS_OUT_OF_PCI_GART_ACCESS',
        'C_PLL_WR_EN': 'RADEON_PLL_WR_EN'}
# registers nobody else may name (offsets)
CP_ONLY = {0x0700, 0x0704, 0x070c, 0x0710, 0x0714, 0x0718, 0x0744, 0x0770, 0x0774, 0x07d4, 0x07dc, 0x07e0, 0x07f8, 0x07fc,
           0x014c, 0x015c, 0x0170, 0x01d8, 0x01dc, 0x01e0, 0x0f60}
FORBIDDEN_WRITE = {'C_MC_FB_LOCATION', 'C_BUS_CNTL'}


def header_defs(path):
    out = {}
    for m in re.finditer(r'^#\s*define\s+(\w+)\s+\(?\s*(1\s*<<\s*\d+|0x[0-9a-fA-F]+|\d+)\s*\)?', open(path, errors='replace').read(), re.M):
        v = m.group(2).replace(' ', '')
        out[m.group(1)] = (1 << int(v.split('<<')[1])) if '<<' in v else int(v, 0)
    return out


def cp_defs(text):
    return dict((m.group(1), int(m.group(2), 16)) for m in
                re.finditer(r'^#define\s+(C_\w+)\s+(0x[0-9a-fA-F]+)U?L?\b', text, re.M))


def writes(body):
    """(offset name, value text) for every rdnMmioWrite32/8 in a body"""
    return re.findall(r'rdnMmioWrite(?:32|8)\(base,\s*(\w+(?:\s*\+\s*[^,]+)?),', body)


def rules(src):
    r = {}
    b = dict((n, blank(t)) for n, t in src.items())
    cp = b['osrdn_cp.m']
    fn = bodies(cp)
    cpd = cp_defs(src['osrdn_cp.m'])
    fh, kh = header_defs(FDRV), header_defs(KREG)

    p = []
    mmio_len = int(re.search(r'#define OSRDN_MMIO_LENGTH\s+(0x[0-9a-fA-F]+)', src['osrdn_record.h']).group(1), 16)
    for name, hname in list(HEADER_NAME.items()) + list(BITS.items()):
        h = kh if hname.startswith('K:') else fh
        hn = hname[2:] if hname.startswith('K:') else hname
        if name not in cpd:
            p.append('%s is not defined in osrdn_cp.m' % name)
        elif h.get(hn) != cpd[name]:
            p.append('%s = %#x, the header says %s = %s' % (name, cpd[name], hn, h.get(hn)))
        elif name in HEADER_NAME and name != 'C_PLL_MCLK_CNTL' and cpd[name] + 4 > mmio_len:
            p.append('%s %#x lies outside the MMIO map (%#x)' % (name, cpd[name], mmio_len))
    r['r5-offsets'] = p

    p = []
    for u in UNITS:
        if u == 'osrdn_cp.m':
            continue
        for m in re.finditer(r'0x0?([0-9a-fA-F]{3,4})\b', b[u]):
            if int(m.group(1), 16) in CP_ONLY and re.search(r'#define\s+\w+\s+$', b[u][max(0, m.start() - 60):m.start()]):
                p.append('%s names the CP/GART register %s' % (u, m.group(0)))
    r['r5-only-here'] = p

    p = []
    for f, body in fn.items():
        for off, _ in [(w, None) for w in writes(body)]:
            o = off.split('+')[0].strip()
            if o in FORBIDDEN_WRITE:
                p.append('%s writes %s' % (f, o))
            if o == 'C_RBBM_SOFT_RESET' and f != 'cpResetPulse':     # M3j: the pulse, shared by cpReset and cpFail
                p.append('%s writes RBBM_SOFT_RESET' % f)
            if o == 'C_CLOCK_CNTL_DATA' and f != 'cpMclkPut':
                p.append('%s writes a PLL register directly' % f)
            if re.match(r'0x', o):
                p.append('%s writes a bare offset %s' % (f, o))
    callers = [f for f, body in fn.items() if re.search(r'\bcpMclkPut\(', body)]
    if sorted(callers) != ['cpResetPulse']:
        p.append('cpMclkPut is called from %s, not only cpResetPulse' % callers)
    # R6a reads SURFACE_CNTL and the surface registers (REC3D); writing any of them, by MMIO or
    # through the ring, stays forbidden, as does naming HOST_PATH_CNTL or the PLL table writer at all
    if re.search(r'osrdn_pll_put|HOST_PATH|0x0d\b', cp):
        p.append('osrdn_cp.m reaches a forbidden register or the PLL table writer')
    for f, body in fn.items():
        for o in writes(body) + ring_writes(body):
            if 'SURF' in o or re.match(r'0x0?b[0-7]', o) or o in FORBIDDEN_WRITE or o == 'C_RBBM_SOFT_RESET' and f != 'cpResetPulse':
                p.append('%s writes %s' % (f, o))
    if re.search(r'rdnMmioWrite\w*\([^;]*osrdnCpR3Regs', cp):
        p.append('a REC3D register is written')
    r['r5-forbidden'] = p

    p = []
    for f, body in fn.items():
        for o in re.findall(r'C_P0\(([^)]*)\)', body):
            o = re.sub(r'\s+', ' ', o.strip())
            # an offset past a name is a different register: only the second marker has one
            # G5-2: cpAsubmit puts cpZclear's own client-case words, held equal by g52-same-words
            if f not in ('cpZclear', 'cpAsubmit') or (o not in R6_RING_OK and o != 'C_SCRATCH_REG0 + 8'):
                p.append('%s puts %s on the ring' % (f, o))
    r['r6-ring'] = p

    p = []
    if re.search(r'\bIOLog\s*\(|\bIOSleep\s*\(', cp):
        p.append('osrdn_cp.m logs or sleeps')
    r['r5-quiet'] = p

    #
    # M1m: THE CLIENT SAMPLES, THE R6 CASES SCAN.
    #
    # Two digest passes over 4096 words each is 16,384 uncached reads through
    # the VRAM alias, and M1l measured that as the WHOLE fixed cost of a client
    # submission (13.5 ms at 826-867 ns a read).  The client narrows it; the R6
    # cases must not, because their oracles compare the full digest.
    #
    p = []
    zb = fn.get('cpZclear', '')
    hdr = src.get('osrdn_cp.h', '')
    m = re.search(r'#define\s+CP_R7_DIGEST_WORDS\s+(\d+)', hdr)
    m6 = re.search(r'#define\s+CP_R6_BUF_WORDS\s+(\d+)', hdr)
    if not m or not m6:
        p.append('CP_R7_DIGEST_WORDS or CP_R6_BUF_WORDS is not defined')
    elif int(m.group(1)) >= int(m6.group(1)):
        p.append('the client digest (%s words) is not narrower than the R6 one (%s)'
                 % (m.group(1), m6.group(1)))
    elif int(m.group(1)) < 1:
        p.append('the client digest is empty: the aperture is never touched and '
                 'a torn buffer can no longer be seen')
    if 'CP_R7_DIGEST_WORDS : CP_R6_BUF_WORDS' not in re.sub(r'\s+', ' ', zb):
        p.append('cpZclear does not choose the digest width by case')
    n = len(re.findall(r'cpR6Digest\s*\(', zb))
    if n != 2:
        p.append('cpZclear calls cpR6Digest %d times; two (depth and colour) is '
                 'the shape' % n)
    for bad in re.findall(r'cpR6Digest\s*\([^;]*?CP_R6_BUF_WORDS', zb):
        p.append('a digest in cpZclear still asks for CP_R6_BUF_WORDS directly, '
                 'so the client would scan too')
    r['m1m-digest-width'] = p

    #
    # M1n: THE SUBMIT LOG HAS A SWITCH, AND THE SWITCH HAS AN END.
    #
    # A flag that a dying tool can leave set would take the evidence away for
    # ever; the lease is what makes that impossible, so it is pinned here.  The
    # dispatch is pinned too: it used to end in a wildcard `else` that turned
    # any unnamed in-range op into an INJECT.
    #
    p = []
    dsp = fn.get('osrdn_cp_run', '') or cp
    hdr = src.get('osrdn_cp.h', '')
    # M1x: the rule used to name QUIET as the last op, which was true when M1n
    # wrote it and stopped being true when TDUMP was added.  What it MEANS is
    # that CP_OP_LAST is the highest op there is -- otherwise the range check
    # and the name table disagree and a real op becomes unreachable, or an
    # unnamed one becomes reachable.  So it is checked that way now: the highest
    # CP_OP_* wins, whatever it is called.
    ops = dict((m.group(1), int(m.group(2))) for m in
               re.finditer(r'#define\s+(CP_OP_[A-Z0-9_]+)\s+(\d+)', hdr))
    ml = re.search(r'#define\s+CP_OP_LAST\s+(\d+)', hdr)
    named = dict((k, v) for k, v in ops.items() if k != 'CP_OP_LAST')
    if not named or not ml:
        p.append('the CP_OP_* table or CP_OP_LAST is not defined')
    else:
        top = max(named.values())
        tops = [k for k, v in named.items() if v == top]
        if int(ml.group(1)) != top:
            p.append('CP_OP_LAST is %s but the highest op is %s = %d: the name '
                     'table and the range check would disagree'
                     % (ml.group(1), '/'.join(sorted(tops)), top))
    if 'op == CP_OP_INJECT' not in dsp:
        p.append('the dispatch does not name INJECT: an unnamed op in range '
                 'would be submitted to the card instead of refused')
    if 'cpRefuse(c, CP_WHY_BAD_OP, (unsigned long)op)' not in dsp:
        p.append('the dispatch has no terminal refusal for an unnamed op')
    q = fn.get('osrdn_cp_quiet_take', '')
    if not q:
        p.append('osrdn_cp_quiet_take is not defined')
    else:
        # M2g: SILENCE IS THE DEFAULT, and the lease is on `loud` now -- a tool
        # that dies must not leave the machine paying 1.25 ms a submission for
        # ever (docs/M2G_PLAN.md 3).  So: speaking is gated on the loud lease,
        # the lease is spent, and the old flag no longer decides anything --
        # reading it here would let `quiet 0` make a submission speak again.
        if 'if (c->loudBudget != 0UL) {' not in q:
            p.append('M2g: speaking is not gated on the loud lease')
        if 'c->loudBudget--' not in q:
            p.append('M2g: the loud lease is never spent: a tool that dies would '
                     'leave the driver loud for ever')
        if re.search(r'c->quiet\b(?!Swallowed|Budget)', q):
            p.append('M2g: quiet_take still reads c->quiet -- `quiet 0` could make '
                     'a submission speak again')
    cq = fn.get('cpQuiet', ''); cl = fn.get('cpLoud', '')
    if 'c->loudBudget = 0UL;' not in cq:
        p.append('M2g: quiet N does not cancel a loud lease -- the loud lease could '
                 'hide under it and come back in another arm')
    if not cl:
        p.append('M2g: cpLoud is not defined')
    elif 'c->quietBudget = 0UL;' not in cl:
        p.append('M2g: loud does not cancel a quiet lease')
    lg = src.get('osrdn_modelog.m', '')
    if '"plane", "quiet"' not in lg:
        p.append('the op name table does not end with "quiet"')
    if 'cpOpNamesFull' not in lg:
        p.append('nothing checks the op name table is full; C89 fills a short '
                 'one with nulls and says nothing')
    dm = src.get('OSRDNDisplay.m', '')
    n = len(re.findall(r'osrdn_cp_quiet_take\s*\(', dm))
    if n != 1:
        p.append('the client path reads the quiet flag %d times; once is the '
                 'shape, or one submission could log its start and not its end' % n)
    r['m1n-quiet'] = p

    # ---- M2g: THE PER-OPERATION QUIET LIVES ONLY UNDER THE CLAIM.
    #
    # cpZclear's three gates decide whether a submission computes the digest
    # and the coverage map.  Set around the call by the caller, the flag leaked
    # through a staging failure that returns first, and a second caller could
    # take the claim between modeFinish and the reset and see it -- an R6
    # diagnostic would then skip what its oracles judge (docs/M2G_PLAN.md 10).
    p = []
    mm = src.get('osrdn_mode.m', '')
    mc = fn.get('osrdn_mode_cp', '') or ''
    if not mc:
        mb = re.search(r'\nosrdn_mode_cp\(.*?\n\}', mm, re.S)
        mc = mb.group(0) if mb else ''
    ic, iset, iclr, ifin = (mc.find('modeClaim(mode)'), mc.find('cp->subQuiet = quiet;'),
                            mc.find('cp->subQuiet = 0;'), mc.find('modeFinish(mode, base);'))
    if min(ic, iset, iclr, ifin) < 0:
        p.append('osrdn_mode_cp does not set and clear subQuiet (claim %d set %d clear %d finish %d)'
                 % (ic, iset, iclr, ifin))
    elif not (ic < iset < iclr < ifin):
        p.append('subQuiet is set or cleared outside the claim (claim %d set %d clear %d finish %d)'
                 % (ic, iset, iclr, ifin))
    else:
        # EVERY assignment, not the first: a second one after modeFinish would
        # leave the first in place and this check green (a mutation showed it).
        outside = [m_.start() for m_ in re.finditer(r'cp->subQuiet\s*=[^=]', mc)
                   if not (ic < m_.start() < ifin)]
        if outside:
            p.append('subQuiet is assigned %d time(s) outside the claim' % len(outside))
    for f_ in ('OSRDNDisplay.m', 'osrdn_cp.m'):
        if re.search(r'subQuiet\s*=[^=]', src.get(f_, '')):
            p.append('%s assigns subQuiet: only osrdn_mode_cp may, under the claim' % f_)
    dflat = re.sub(r'\s+', ' ', src.get('OSRDNDisplay.m', ''))
    if dflat.count('&rdnCpCopy, quiet);') != 1:
        p.append('the client submission does not hand its quiet decision to osrdn_mode_cp')
    if dflat.count('&rdnCpCopy, 0);') != 1:
        p.append('the diagnostic path does not pass 0: an R6 op could run quiet')
    if 'if (!quiet || !staged)' not in dflat:
        p.append('M2g: a failed staging is swallowed when quiet -- with silence the '
                 'default it would leave no line at all')
    r['m2g-subquiet-under-claim'] = p

    # ---- M3c: a failure on the card speaks, quiet or not; REFUSED gets the head
    #      line only, so a latch's record is not pushed out by the refusals
    #      after it (docs/M3C_PLAN.md 2-4)
    p = []
    dflat = re.sub(r'\s+', ' ', src.get('OSRDNDisplay.m', ''))
    if ('if (!quiet || (live != CP_RC_RAN && live != CP_RC_REFUSED)) '
            'osrdn_cp_lines(&rdnCpCopy, rdnState.nonce, live);') not in dflat:
        p.append('M3c: a quiet client submission that failed on the card leaves no record')
    if ('else if (live == CP_RC_REFUSED) osrdn_cp_head(&rdnCpCopy, rdnState.nonce, live);'
            not in dflat):
        p.append('M3c: a quiet REFUSED leaves no head line (rc, why, the gate)')
    if 'if (!quiet) IOLog("RDN-R5 skip' in dflat:
        p.append('M3c: the skip line is swallowed when quiet')
    mlog = src.get('osrdn_modelog.m', '')
    fmt = 'IOLog("RDN-R5 %s boot=%08x n=%u arg=%08x len=%u rc=%d why=%d gv=%08x greg=%04x us=%u'
    if mlog.count(fmt) != 1:
        p.append('M3c: the head line format is written %d times -- once, in osrdn_cp_head'
                 % mlog.count(fmt))
    # the body out of osrdn_modelog.m itself: `fn` indexes other units
    mb = re.search(r'\nosrdn_cp_lines\(const osrdn_cp_state \*c, unsigned long nonce, int rc\)\n\{(.*?)\n\}', mlog, re.S)
    fl = mb.group(1) if mb else ''
    if not fl:
        p.append('M3c: osrdn_cp_lines is not found in osrdn_modelog.m the way this rule reads it')
    elif 'osrdn_cp_head(c, nonce, rc);' not in fl:
        p.append('M3c: osrdn_cp_lines does not print the head line through osrdn_cp_head')
    r['m3c-failures-speak'] = p

    # ---- M3e: the first failure on the card is kept whole, never overwritten,
    #      and a RECORD refused for the latch prints the kept copy -- from
    #      memory, the RECORD rule in osrdn_cp.m untouched (docs/M3E_PLAN.md 2)
    p = []
    if ('if (live != CP_RC_RAN && live != CP_RC_REFUSED && rdnCpKeptSub == 0UL) { '
            'rdnCpKept = rdnCpCopy;') not in dflat:
        p.append('M3e: the first card failure is not kept, or a later one overwrites it')
    if 'rdnCpKeptSub = rdnR7bSubmits;' not in dflat:
        p.append('M3e: the kept copy does not say which submission it was')
    if ('keptNow = (parameterArray[1] == (unsigned)CP_OP_RECORD && rdnCpKeptSub != 0UL && '
            '(live == CP_RC_RAN || (live == CP_RC_REFUSED && rdnCpCopy.why == CP_WHY_LATCHED)));') not in dflat:
        p.append('M3e/M3j: the kept copy is not re-printed by a RECORD the latch refused or a RECORD that ran')
    if 'else if (!keptNow) osrdn_cp_lines(&rdnCpCopy, rdnState.nonce, live);' not in dflat:
        p.append('M3j: a RECORD that re-prints the kept copy also prints its own lines -- past the 4 KB buffer')
    if dflat.count('osrdn_cp_lines(&rdnCpKept, rdnState.nonce, rdnCpKeptRc);') != 1:
        p.append('M3e: the kept copy is printed %d times -- once, on the refused RECORD'
                 % dflat.count('osrdn_cp_lines(&rdnCpKept, rdnState.nonce, rdnCpKeptRc);'))
    csrc = re.sub(r'\s+', ' ', src.get(CPM, ''))
    if 'else if (op == CP_OP_RECORD && c->latched && !c->latchInjected) (void)cpRefuse(c, CP_WHY_LATCHED, 0);' not in csrc:
        p.append('M3e: a RECORD on a real latch no longer refuses -- it would read the card')
    r['m3e-kept-latch'] = p

    # ---- M3f: cpR6Submit wraps the ring's end like FreeBSD's OUT_RING; the old
    #      fill to the end latched the CP (docs/M3E_PLAN.md 8, docs/M3F_PLAN.md)
    p = []
    mb = re.search(r'\ncpR6Submit\(osrdn_cp_state \*c, vm_address_t base, const unsigned long \*w, unsigned long n\)\n\{(.*?)\n\}', src.get(CPM, ''), re.S)
    body = re.sub(r'\s+', ' ', mb.group(1)) if mb else ''
    if not body:
        p.append('M3f: cpR6Submit is not found the way this rule reads it')
    else:
        if 'CP_RING_WORDS' in body or 'pad' in re.sub(r'/\*.*?\*/', '', body):
            p.append('M3f: cpR6Submit fills to the ring end again')
        if 'for (k = 0; k < len; k++) cpPut(c, p + k, (k < n) ? w[k] : CP_PACKET2);' not in body:
            p.append('M3f: the words are not written from wptr through cpPut')
        if 'target = (p + len) & C_RPTR_MASK;' not in body:
            p.append('M3f: the new wptr is not (p + len) masked')
    r['m3f-wrap-like-bsd'] = p

    # ---- G4-3 K1 (docs/G4_3_KERNEL_PLAN.md 2): the submit's idle wait is re-asked the reference's
    #      count of rounds, the count is READ from xorg's header, and the rptr wait restarts on progress
    p = []
    cpm = src.get(CPM, '')
    hdr = src.get('osrdn_cp.h', '')
    xh = os.path.join(PROJ, 'ref', 'upstream', 'unpacked', 'xf86-video-ati-6.14.6', 'src', 'radeon.h')
    mx = re.search(r'#define\s+RADEON_IDLE_RETRY\s+(\d+)', open(xh, errors='replace').read()) if os.path.exists(xh) else None
    mh = re.search(r'#define\s+CP_IDLE_RETRY\s+(\d+)UL', hdr)
    if not mx:
        p.append('K1: xorg radeon.h (RADEON_IDLE_RETRY) is not in ref/upstream')
    elif not mh:
        p.append('K1: osrdn_cp.h has no CP_IDLE_RETRY')
    elif mh.group(1) != mx.group(1):
        p.append('K1: CP_IDLE_RETRY is %s, xorg RADEON_IDLE_RETRY is %s' % (mh.group(1), mx.group(1)))
    mb = re.search(r'\ncpR6Submit\(osrdn_cp_state \*c, vm_address_t base, const unsigned long \*w, unsigned long n\)\n\{(.*?)\n\}', cpm, re.S)
    body = re.sub(r'\s+', ' ', mb.group(1)) if mb else ''
    if 'cpWaitRetry(base, W_IDLE, 0, C_IDLE_US, C_IDLE_RETRY, &c->wIdle)' not in body:
        p.append('K1: cpR6Submit does not re-ask the idle wait C_IDLE_RETRY rounds')
    if 'cpWait(base, W_RPTR, target, C_RPTR_US, &c->wRptr)' not in body:
        p.append('K1: cpR6Submit no longer waits for the read pointer before idle')
    mw = re.search(r'\ncpWait\(vm_address_t base, int kind, unsigned long need, unsigned long limitUs, osrdn_cp_wait \*w\)\n\{(.*?)\n\}', cpm, re.S)
    wbody = re.sub(r'\s+', ' ', mw.group(1)) if mw else ''
    if 'if (kind == W_RPTR) {' not in wbody or 'w->resets++;' not in wbody or 'IOGetTimestamp(&t0); turns = 0; w->resets++;' not in wbody:
        p.append('K1: cpWait does not restart its clock when the read pointer moves (radeon_wait_ring)')
    if wbody.count('rdnMmioRead32(base, C_CP_RB_RPTR)') != 1:
        p.append('K1: the rptr progress sample is not the one read that decides the condition')
    if 'retry=%u resets=%u' not in src.get(MLG, ''):
        p.append('K1: the RDN-R5 wait line does not carry the retries and resets')
    r['g43-k1-wait'] = p

    # ---- G4-4 K7 (docs/G4_4_KERNEL_PLAN.md 3): the verifier judges the surfaces at EVERY draw,
    #      with the values in force then, and once more after the loop; the four checks live in
    #      one helper so the two judgements cannot differ
    p = []
    mv = re.search(r'\ncpR7Verify\(osrdn_cp_state \*c, const unsigned long \*w, unsigned long n,\n[^\n]*\n\{(.*?)\n\}', cpm, re.S)
    vb = re.sub(r'\s+', ' ', mv.group(1)) if mv else ''
    call = 'if (!cpR7SurfacesOk(c, coff, cpitch, zoff, zpitch, wh, haveWH, toff, tfmt, tfil, haveT, haveTF)) return CP_R7_WHY_SURFACE;'
    if not vb:
        p.append('K7: cpR7Verify is not where the rule looks')
    else:
        if vb.count(call) != 2:
            p.append('K7: the surfaces are judged %d times in cpR7Verify, want 2 (at each draw, and at the end)' % vb.count(call))
        else:
            first, last, drew, end = vb.index(call), vb.rindex(call), vb.index('drew = 1;'), vb.index('c->r7At = n;')
            if not (first < drew < end < last):
                p.append('K7: the two judgements are not one before `drew = 1` and one after the loop')
        for bad in ('if (!haveWH) return CP_R7_WHY_SURFACE;', 'cpR7SurfaceFits(c, coff', 'cpR7TextureFits(c, toff'):
            if bad in vb:
                p.append('K7: cpR7Verify judges a surface itself (%s) instead of through the helper' % bad)
    mh = re.search(r'\ncpR7SurfacesOk\(const osrdn_cp_state \*c,[^{]*\{(.*?)\n\}', cpm, re.S)
    hb = re.sub(r'\s+', ' ', mh.group(1)) if mh else ''
    for want in ('if (!haveWH) return 0;', 'cpR7SurfaceFits(c, coff, cpitch,', 'cpR7SurfaceFits(c, zoff, zpitch,',
                 'if (haveT && (!haveTF || !cpR7TextureFits(c, toff, tfmt, tfil))) return 0;'):
        if want not in hb:
            p.append('K7: the helper lacks %r' % want)
    r['g44-k7-per-draw'] = p

    # ---- M3i: a latch takes the CP's own account (Linux r100 debugfs registers and
    #      the CSQ fifo), and every submission reads WPTR back (docs/M3I_PLAN.md 3)
    p = []
    lb = re.search(r'\ncpLatchDump\(osrdn_cp_state \*c, vm_address_t base\)\n\{(.*?)\n\}', src.get(CPM, ''), re.S)   # M3j: the dump moved out of cpLatch
    body = re.sub(r'\s+', ' ', lb.group(1)) if lb else ''
    if not body:
        p.append('M3i: cpLatchDump is not found the way this rule reads it')
    else:
        for want in ('c->cpStat = rdnMmioRead32(base, C_CP_STAT);', 'c->rbRptr = rdnMmioRead32(base, C_CP_RB_RPTR);',
                     'c->rbWptr = rdnMmioRead32(base, C_CP_RB_WPTR);', 'c->csqStat = rdnMmioRead32(base, C_CP_CSQ_STAT);',
                     'c->csq2Stat = rdnMmioRead32(base, C_CP_CSQ2_STAT);', 'c->csqMode = rdnMmioRead32(base, C_CP_CSQ_MODE);',
                     'for (k = 0; k < CP_LATCH_FIFO_WORDS; k++) { rdnMmioWrite32(base, C_CP_CSQ_ADDR, k << 2); c->fifo[k] = rdnMmioRead32(base, C_CP_CSQ_DATA); }',
                     'c->latchRead = 1;',
                     # D3: the reference's kick, after the dump, and its evidence
                     'rdnMmioWrite32(base, C_CP_RB_WPTR, kt);', '(void)cpWait(base, W_RPTR, kt, C_KICK_US, &c->wKick);',
                     'c->kickMoved = (c->kickRptr != (c->rbRptr & C_RPTR_MASK)) ? 1 : 0;'):
            if want not in body:
                p.append('M3i: cpLatch does not %r' % want)
        if body.find('c->kickWptr = kt;') < body.find('c->latchRead = 1;'):
            p.append('M3i: the kick comes before the dump -- the dump must see the CP as the wait left it')
        if 'C_AIC' in body or 'C_CP_CSQ_CNTL' in body or 'C_CP_RB_CNTL' in body:
            p.append('M3i: cpLatch touches the CSQ control, the ring control or the GART -- it may only read')
    cflat = re.sub(r'\s+', ' ', src.get(CPM, ''))
    want = ('c->wptrRead = rdnMmioRead32(base, C_CP_RB_WPTR) & C_RPTR_MASK; if (c->wptrRead != target) { '
            '(void)cpRefuse(c, CP_WHY_WPTR, c->wptrRead); return cpFail(c, base); }')
    wantStart = ('c->wptrRead = rdnMmioRead32(base, C_CP_RB_WPTR) & C_RPTR_MASK; if (c->wptrRead != target) { '
                 '(void)cpRefuse(c, CP_WHY_WPTR, c->wptrRead); return cpLatch(c, base); }')
    if cflat.count(want) != 2 or cflat.count(wantStart) != 1:
        p.append('M3i: the WPTR read-back after the doorbell is at %d recovering + %d latching places, '
                 'want 2 (cpSubmit, cpR6Submit) + 1 (cpStartCore)' % (cflat.count(want), cflat.count(wantStart)))
    r['m3i-latch-dump'] = p

    # ---- M3j: a submission whose wait ran out recovers as the references do
    #      (docs/M3J_PLAN.md 5): dump, kick, then CSQ off, the reset pulse, both
    #      pointers forced to 0 (Linux r100_asic_reset), restart; latch last
    p = []
    fb = re.search(r'\ncpFail\(osrdn_cp_state \*c, vm_address_t base\)\n\{(.*?)\n\}', src.get(CPM, ''), re.S)
    body = re.sub(r'\s+', ' ', fb.group(1)) if fb else ''
    if not body:
        p.append('M3j: cpFail is not found the way this rule reads it')
    else:
        order = ('cpLatchDump(c, base);', 'if (c->kickMoved &&', 'rdnMmioWrite32(base, C_CP_CSQ_CNTL, 0UL);',
                 'if (cpResetPulse(c, base) == CP_RC_RAN) {', 'rdnMmioWrite32(base, C_CP_RB_CNTL, v | C_RB_RPTR_WR_ENA);',
                 'rdnMmioWrite32(base, C_CP_RB_RPTR_WR, 0UL);', 'rdnMmioWrite32(base, C_CP_RB_WPTR, 0UL);',
                 'rdnMmioWrite32(base, C_CP_RB_CNTL, v);', 'c->wptr = 0;', 'if (cpStartCore(c, base) == CP_RC_RAN)',
                 'c->recovers++; return CP_RC_RECOVERED;', 'c->latched = 1; return CP_RC_LATCHED;')
        at = [body.find(o) for o in order]
        if -1 in at:
            p.append('M3j: cpFail lacks %r' % order[at.index(-1)])
        elif at != sorted(at):
            p.append('M3j: cpFail does its steps out of the reference order')
        if 'C_AIC' in body or 'cpLoad' in body or 'C_CP_RB_BASE' in body:
            p.append('M3j: the recovery touches the GART, the microcode or the ring base -- the reference reset does not')
    # G5-2 (docs/G5_2_ASYNC_SUBMIT_PLAN.md 2-2, 2-3): the space wait in cpR6Submit and the two waits of
    # cpRetire recover the same way -- nine, each named, rather than a count that anything could reach
    if cflat.count('return cpFail(c, base);') != 9:
        p.append('M3j: cpFail is returned from %d places, want 9 (read-back + two waits in cpSubmit and cpR6Submit, '
                 'the space wait in cpR6Submit, the ring and idle waits in cpRetire)' % cflat.count('return cpFail(c, base);'))
    for f, want in (('cpR6Submit', 4), ('cpSubmit', 3), ('cpRetire', 2)):
        got = re.sub(r'\s+', ' ', fn.get(f, '')).count('return cpFail(c, base);')
        if got != want:
            p.append('M3j: %s returns cpFail %d times, want %d' % (f, got, want))
    r['m3j-recover'] = p

    # ---- G3 (docs/G3_PRESENT_PLAN.md 2-1, 2-4): the present blit is the reference's,
    # kernel-built, and never a client packet.  The constants are rebuilt here
    # from the named bits (the XOR gate of read-the-reference-before-measuring).
    p = []
    r7b = src.get('osrdn_r7b.h', '')
    pr = fn.get('cpPresent', '')
    if not pr:
        p.append('cpPresent is missing')
    else:
        if 'cpR7Verify' in pr:
            p.append('cpPresent runs the client verifier over its own words')
        if pr.count('cpR6Submit(c, base, wd, n)') != 1:
            p.append('cpPresent does not submit its words through cpR6Submit exactly once')
        # REL2 (docs/REL2_PRESENT_STATE_PLAN.md): the blit carries the 2D state the swap leaves to the
        # X server -- scissor, write mask, direction -- with the clear's values, before the GMC word,
        # because the CP's own start resets the engine and nothing else here would write them again
        state = ('wd[n++] = C_P0N(C_DEFAULT_SC_BOTTOM_RIGHT, 0); wd[n++] = C_SC_MAX;',
                 'wd[n++] = C_P0N(C_DP_WRITE_MASK, 0);        wd[n++] = 0xffffffffUL;',
                 'wd[n++] = C_P0N(C_DP_CNTL, 0);              wd[n++] = C_DP_CNTL_L2R_T2B;')
        gmc_at = pr.find('wd[n++] = C_P0N(C_DP_GUI_MASTER_CNTL, 0);   wd[n++] = C_PRESENT_GMC;')
        for want in state:
            at = pr.find(want)
            if at < 0:
                p.append('REL2: cpPresent does not write %s' % want.split('(')[1].split(',')[0])
            elif gmc_at >= 0 and at > gmc_at:
                p.append('REL2: cpPresent writes %s after the GMC word' % want.split('(')[1].split(',')[0])
        m = re.search(r'#define\s+C_PRESENT_WORDS\s+(\d+)', cp)
        if not m or int(m.group(1)) != 19:
            p.append('REL2: C_PRESENT_WORDS is not 19 (13 of the swap + 3 state pairs)')
        if not re.search(r'if \(c->latched \|\| c->failed\)\s*return cpPresentRefuse\(c, OSRDN_PRESENT_E_LATCH\);', pr):
            p.append('a latched or failed CP is not refused as LATCH before anything else')
        for name in ('E_MAGIC', 'E_LATCH', 'E_MODE', 'E_GEOM', 'E_DST', 'E_SRC'):
            if 'OSRDN_PRESENT_%s' % name not in pr:
                p.append('cpPresent never refuses with %s' % name)
        if not re.search(r'\(\(b->srcStride \* 4UL\) & 63UL\) != 0UL', pr):
            p.append('the source stride is not held to 64-byte pitch units')
        if not re.search(r'\(b->srcOrg & 1023UL\) != 0UL', pr):
            p.append('the source origin is not held to the 1 KiB offset unit')
        if 'IOLog' in pr:
            p.append('cpPresent logs: SDL calls it once a row')
    gmc = (1 << 0) | (1 << 1) | (15 << 4) | (6 << 8) | (3 << 12) | 0x00cc0000 | (2 << 24) | (1 << 28) | (1 << 30)
    for name, want in (('C_PRESENT_GMC', gmc), ('C_PRESENT_WAIT_PRE', (1 << 17) | (1 << 18)),
                       ('C_PRESENT_WAIT_POST', (1 << 16) | (1 << 18)), ('C_DP_GUI_MASTER_CNTL', 0x146c),
                       ('C_SRC_PITCH_OFFSET', 0x1428), ('C_DST_PITCH_OFFSET', 0x142c), ('C_SRC_X_Y', 0x1590),
                       ('C_DST_X_Y', 0x1594), ('C_DST_WIDTH_HEIGHT', 0x1598)):
        m = re.search(r'#define\s+%s\s+(0x[0-9a-fA-F]+)' % name, cp)
        if not m:
            p.append('%s is not defined' % name)
        elif int(m.group(1), 16) != want:
            p.append('%s is %s, the reference bits make 0x%x' % (name, m.group(1), want))
    # the verdict numbers SDL reads by value (SDL_openstepvideo.m 2579-2583): DST 3, BUSY 5
    for name, want in (('OSRDN_PRESENT_E_DST', 3), ('OSRDN_PRESENT_E_BUSY', 5)):
        m = re.search(r'#define\s+%s\s+(\d+)UL' % name, r7b)
        if not m or int(m.group(1)) != want:
            p.append('%s must be %d: SDL reads that number' % (name, want))
    # the class: one log line, behind the once-per-verdict mask
    r7b = src.get('osrdn_r7b.h', '')
    md = re.search(r'- \(void\)r7bPresent:.*?(?=\n- \()', src.get('OSRDNDisplay.m', ''), re.S)
    dp = md.group(0) if md else ''
    if not dp:
        p.append('r7bPresent is missing from OSRDNDisplay.m')
    if dp and (dp.count('IOLog(') != 1 or 'rdnPresentSaid & (1UL << pb->verdict)' not in dp):
        p.append('r7bPresent must log once per verdict and never per call')
    r['g3-present'] = p

    # ---- G3b (docs/G3B_CLEAR_PLAN.md 2-1, 2-2): the clear is the reference's, kernel-built,
    # and the ordinary submission no longer speaks
    p = []
    cl = fn.get('cpClear', '')
    if not cl:
        p.append('cpClear is missing')
    else:
        if 'cpR7Verify' in cl:
            p.append('cpClear runs the client verifier over its own words')
        if cl.count('cpR6Submit(c, base, wd, n)') != 1:
            p.append('cpClear does not submit its words through cpR6Submit exactly once')
        if 'wd[n++] = cpR6State[k];' not in cl:
            p.append('the depth clear does not take the precedent state block word for word')
        # G3c (docs/G3B_CLEAR_PLAN.md 7): ONE word of that block is then replaced -- ZSTENCILCNTL, with
        # the CLIENT's depth format (16-bit), as the reference's clear carries depth_clear->
        # rb3d_zstencilcntl (radeon_state.c 1145, radeon_cp.c 1215-1221).  Boot 5 sent the
        # precedent's 24-bit word and the card cleared twice the bytes, none of them the client's.
        if 'wd[n - 26UL + 9UL] = C_CLEAR_ZSTENCIL;' not in cl:
            p.append('the depth clear does not put the client format (C_CLEAR_ZSTENCIL) in the ZSTENCILCNTL word')
        for name in ('E_MAGIC', 'E_LATCH', 'E_MODE', 'E_GEOM', 'E_SRC'):
            if 'OSRDN_PRESENT_%s' % name not in cl:
                p.append('cpClear never refuses with %s' % name)
        if 'IOLog' in cl:
            p.append('cpClear logs')
        # G3d: the fill is the X driver's register sequence, with DP_CNTL in it, and packs DST_HEIGHT_WIDTH as h << 16 | w
        if 'C_P3(C_CNTL_PAINT_MULTI' in cl:
            p.append('G3d: the colour fill still goes out as PAINT_MULTI, which wrote nothing through this CP (boot 6)')
        if 'C_P0N(C_DP_CNTL, 0)' not in cl or 'C_DP_CNTL_L2R_T2B' not in cl:
            p.append('G3d: the fill goes out without DP_CNTL (left-to-right, top-to-bottom), which nobody else writes')
        if '(b->h << 16) | b->w' not in cl:
            p.append('G3d: DST_HEIGHT_WIDTH is not packed h << 16 | w (radeon_exa_funcs.c 224)')
        if 'C_P0N(C_DST_HEIGHT_WIDTH, 0)' not in cl:
            p.append('G3d: the fill is not triggered by DST_HEIGHT_WIDTH')
    tab = open(os.path.join(HERE, '..', '..', 'mesa', 'OSRDNMesaTriTable.h')).read()
    mt = re.search(r'#define OSRDN_TRI_ZSTENCIL_LESS\s+0x([0-9a-fA-F]+)UL', tab)
    less = int(mt.group(1), 16) if mt else 0
    clear_z = (less & ~(7 << 4)) | (7 << 4)         # the client's word with Z_TEST_ALWAYS
    if (less & 0xf) != 0:
        p.append('the client LESS word in OSRDNMesaTriTable.h is not the 16-bit format')
    gmc = (1 << 1) | (13 << 4) | (6 << 8) | (3 << 12) | 0x00f00000 | (1 << 28)
    for name, want in (('C_CLEAR_GMC', gmc), ('C_CLEAR_PRIM', (8 << 0) | (3 << 4) | (3 << 16)),
                       ('C_DP_WRITE_MASK', 0x16cc), ('C_CLEAR_ONE', 0x3f800000),
                       # G3d (docs/G3B_CLEAR_PLAN.md 7-2): the X driver's fill registers (radeon_reg.h 669-672, 774, 784, 800)
                       ('C_DEFAULT_SC_BOTTOM_RIGHT', 0x16e8), ('C_SC_MAX', 0x1fff1fff), ('C_DP_BRUSH_FRGD_CLR', 0x147c),
                       ('C_DP_BRUSH_BKGD_CLR', 0x1478), ('C_DP_SRC_FRGD_CLR', 0x15d8), ('C_DP_SRC_BKGD_CLR', 0x15dc),
                       ('C_DP_CNTL', 0x16c0), ('C_DP_CNTL_L2R_T2B', 3), ('C_DST_Y_X', 0x1438), ('C_DST_HEIGHT_WIDTH', 0x143c),
                       ('C_CLEAR_ZSTENCIL', clear_z)):
        m = re.search(r'#define\s+%s\s+(0x[0-9a-fA-F]+)' % name, cp)
        if not m:
            p.append('%s is not defined' % name)
        elif int(m.group(1), 16) != want:
            p.append('%s is %s, the reference bits make 0x%x' % (name, m.group(1), want))
    # G4-4 K8 moved the tail both submission paths share into r7bRun:; the gate lives there now
    md = re.search(r'- \(void\)r7bRun:.*?(?=\n- \()', src.get('OSRDNDisplay.m', ''), re.S)
    sm = md.group(0) if md else ''
    if 'if (!quiet || live != CP_RC_RAN)\n        IOLog("RDN-R7B submit boot=' not in sm:
        p.append('the submit line is not gated on the loud lease or a failure (G3b 2-2: 4.2 ms a submission)')
    r['g3b-clear'] = p

    # ---- M1x: the stage marks are complete, in order, and guarded.
    #
    # They are a measurement, so a missing or out-of-order one does not break
    # the driver -- it silently reports the wrong stage's time, which is worse
    # than a crash because it would be believed.
    p = []
    zc = fn.get('cpZclear', '') or cp
    marks = [int(m.group(1)) for m in
             re.finditer(r'cpTMark\(c, &tmark, (\d+)\)', zc)]
    # M1z made the array longer than the chain: CP_T_CHAIN links between the
    # CP_T_MARKS checkpoints, then accumulators that are NOT links (the fence and
    # the waits, gathered inside cpR6Submit, which runs twice).  The rule is
    # sharpened, not loosened: the chain must still be 0..CP_T_CHAIN-1 in order,
    # and cpTMark must refuse at CP_T_CHAIN so a chain mark can never land on
    # one of the extra accumulators.
    nm = re.search(r'#define\s+CP_T_MARKS\s+(\d+)', hdr)
    nc = re.search(r'#define\s+CP_T_CHAIN\s+\(CP_T_MARKS - 1\)', hdr)
    ns = re.search(r'#define\s+CP_T_STAGES\s+\(CP_T_CHAIN \+ (\d+)\)', hdr)
    want = (int(nm.group(1)) - 1) if nm else 0
    if not nm or not nc or not ns:
        p.append('CP_T_MARKS / CP_T_CHAIN / CP_T_STAGES are not defined the way the chain needs')
    else:
        extra = int(ns.group(1))
        if marks != list(range(want)):
            p.append('the stage marks are %s, want 0..%d each once in order'
                     % (marks, want - 1))
        if not re.search(r'if \(mark < 0 \|\| mark >= CP_T_CHAIN\)', cp):
            p.append('cpTMark does not refuse at CP_T_CHAIN, so a chain mark can '
                     'land on an accumulator that is not a link in the chain')
        # every index above the chain must be a named constant, and named once
        named = dict((m.group(1), m.group(2)) for m in
                     re.finditer(r'#define\s+CP_T_(FENCE|WAIT|PUT)\s+(\S+)', hdr))
        if len(named) != extra:
            p.append('CP_T_STAGES leaves %d slots above the chain but %d are named'
                     % (extra, len(named)))
        for nmx in named:
            k = 'CP_T_' + nmx
            uses = len(re.findall(r'c->tAcc\[%s\] \+=' % k, cp))
            if uses != 1:
                p.append('%s is accumulated %d times, want once' % (k, uses))
            if not re.search(r'if \(c->tOn\)[^;]*\n?[^;]*c->tAcc\[%s\]' % k, cp) and \
               not re.search(r'if \(c->tOn\) \{[^}]*c->tAcc\[%s\]' % k, cp):
                p.append('%s is accumulated without the c->tOn guard' % k)
        # the fence is timed with its OWN clock: cpTMark writes through its `t`
        # argument, so using the chain's would move time between the buckets
        sub = fn.get('cpR6Submit', '')
        if 'cpTMark' in sub:
            p.append('cpR6Submit calls cpTMark: that moves the caller\'s chain boundary')
        if sub and 'IOGetTimestamp(&f0)' not in sub:
            p.append('cpR6Submit does not take its own timestamp around the fence')
        if src['osrdn_cp.h'].count('int             tOn;') != 1:
            p.append('tOn is not in the state exactly once')
        if cp.count('c->tOn = 1;') != 1 or cp.count('c->tOn = 0;') != 1:
            p.append('tOn is set %d times and cleared %d times, want once each'
                     % (cp.count('c->tOn = 1;'), cp.count('c->tOn = 0;')))
    # every one of them must sit behind the `timing` guard, or a non-client
    # operation would add its own times into the client's buckets
    guarded = len(re.findall(r'if \(timing\)\s*\n\s*cpTMark\(c, &tmark,', zc))
    guarded += len(re.findall(r'if \(timing\) \{[^}]*cpTMark\(c, &tmark,', zc))
    if guarded != len(marks):
        p.append('%d of %d stage marks are behind `if (timing)`'
                 % (guarded, len(marks)))
    if 'c->tAccN++;' not in zc:
        p.append('tAccN is never stepped: the stage sums would divide by nothing')
    if zc.count('c->tAccN++;') != 1:
        p.append('tAccN is stepped %d times, not once at the end'
                 % zc.count('c->tAccN++;'))
    r['m1x-stage-marks'] = p

    #
    # M1o: A QUIET SUBMISSION DOES NOT COMPUTE WHAT IT CANNOT REPORT.
    #
    # The digests and the coverage map leave the driver only through
    # osrdn_cp_lines, which the client path skips when quiet.  Computing them
    # anyway was 1,344 uncached reads thrown away -- 89% of a submission.  Two
    # reads are kept on purpose, and that is pinned: dropping them would remove
    # whatever barrier an uncached read gives, silently.
    #
    p = []
    zb = fn.get('cpZclear', '')
    flat = re.sub(r'\s+', ' ', zb)
    if 'if (drawn && !c->subQuiet)' not in flat:
        p.append('the coverage scan is not skipped when quiet')
    if 'c->digestWords = c->subQuiet ? 0UL : dw;' not in flat:
        p.append('digestWords does not say the digest was skipped')
    if 'if (c->subQuiet) { c->qTouch[0]' not in flat:
        p.append('the digests are not skipped when quiet')
    n = len(re.findall(r'c->qTouch\[[01]\] = ', zb))
    if n != 2:
        p.append('a quiet submission reads %d words of the surfaces; two (one '
                 'per buffer) is the shape -- none would drop whatever barrier '
                 'an uncached read gives' % n)
    r['m1o-quiet-skips-analysis'] = p

    p = []
    body = fn.get('cpStopLatched', '')
    w = writes(body)
    if w != ['C_CP_CSQ_CNTL'] or re.search(r'\bcp(Unmap|Wait|Mclk)\w*\(', body):
        p.append('the latched STOP writes %s' % w)
    r['r5-latched'] = p

    p = []
    for f, body in fn.items():
        for off in writes(body):
            if off.startswith('C_SCRATCH_REG') and f not in ('cpMap', 'cpPrepare', 'cpZclear'):
                p.append('%s writes a scratch register' % f)
    if not any(o == 'C_SCRATCH_REG5' for o in writes(fn.get('cpMap', ''))):
        p.append('cpMap does not poison REG5')
    r['r5-scratch'] = p

    p = []
    if re.search(r'\bIOFree(Low)?\s*\(', cp):
        p.append('osrdn_cp.m frees memory')
    blk = method(b['OSRDNDisplay.m'], 'cpBlock')
    frees = [m.start() for m in re.finditer(r'IOFreeLow\(', blk)]
    ok_at = blk.find('rdnCp.blockOk = 1;')
    if len(frees) != 1 or ok_at < 0 or not re.search(r'\}\s*else\s*\{\s*IOFreeLow\(', blk):
        p.append('the block is freed other than on the allocation failure path')
    # R7b: the batch page is a SECOND low allocation, so the rule is asked of it
    # too rather than relaxed -- one free, on the branch that publishes nothing,
    # and the publishing assignment ahead of it (docs/R7_PLAN.md 10-6).
    bat = method(b['OSRDNDisplay.m'], 'r7bBlock')
    bfrees = [m.start() for m in re.finditer(r'IOFreeLow\(', bat)]
    # the address is published in exactly one place, and that place is ahead of
    # the free -- a second publish anywhere is what a `find` would have missed
    bpub = [m.start() for m in re.finditer(r'rdnR7bPhys = \(unsigned long\)', bat)]
    if len(bfrees) != 1 or len(bpub) != 1 or not re.search(r'\}\s*else\s*\{\s*IOFreeLow\(', bat):
        p.append('the batch page is freed, or published, other than once on its own path')
    elif bpub[0] > bfrees[0]:
        p.append('the batch page is published after the path that frees it')
    if re.search(r'IOFreeLow\(', b['OSRDNDisplay.m'].replace(blk, '').replace(bat, '')):
        p.append('OSRDNDisplay.m frees a low allocation outside -cpBlock and -r7bBlock')
    r['r5-block'] = p

    p = []
    for f, before in (('cpMap', 'rdnMmioWrite32(base, C_MC_AGP_LOCATION'), ('cpStartCore', 'rdnMmioWrite32(base, C_CP_CSQ_CNTL'),   # M3j: the stream part of cpStart
                      ('cpPrepare', None)):
        body = fn.get(f, '')
        k = body.find('cpFence(base);')
        if k < 0:
            p.append('%s does not flush' % f)
        elif before and (body.find(before) < 0 or body.find(before) < k):
            p.append('%s tells the GPU before it flushes' % f)
    sub = fn.get('cpSubmit', '')
    if sub.find('cpPrepare(') < 0 or sub.find('cpPrepare(') > sub.find('C_CP_RB_WPTR'):
        p.append('cpSubmit writes WPTR before the prepared (flushed) words')
    r['r5-fence'] = p

    p = []
    for tb in ('Default.table', 'Instance0.table'):
        if '"RDN CP Test" = "Yes";' not in src[tb]:
            p.append('%s does not turn "RDN CP Test" on' % tb)
    r['r5-tables'] = p

    p = []
    for name, ctr, args in (('rdnMmioRead32', 'cpIoRd', '(b), (o)'), ('rdnMmioWrite32', 'cpIoWr', '(b), (o), (v)'),
                            ('rdnMmioWrite8', 'cpIoWr', '(b), (o), (v)')):
        want = r'^#define %s\(b, o(?:, v)?\)\s+\(%s\+\+, %s\(%s\)\)\s*$' % (name, ctr, name, re.escape(args))
        if not re.search(want, cp, re.M):
            p.append('%s is not counted (%s)' % (name, ctr))
    r['r5d-count'] = p

    p = []
    if 'rdnCp.injectKey = rdnCp.keyOn && osrdn_name_is(key, "Yes");' not in src['OSRDNDisplay.m']:
        p.append('the inject key is not tied to the CP key')
    sub = fn.get('cpSubmit', '')
    if 'if (inject && !c->failed) {' not in sub or sub.find('if (inject && !c->failed) {') < sub.find('cpReadBack('):
        p.append('INJECT does not latch only after a clean read-back')
    r['r5d-key'] = p

    p = []
    stop = fn.get('cpStop', '')
    off = stop.find('C_CP_CSQ_CNTL')
    if off < 0:
        p.append('cpStop writes no CP_CSQ_CNTL')
    elif re.search(r'[!=]=\s*c->wptr\b|\bc->wptr\s*[!=]=', stop[off:]):
        p.append('cpStop compares with c->wptr after the CSQ goes off')
    r['r5-stop'] = p

    p = []
    mh = header_defs(MESA_REG)
    for name, hn in MESA_BLEND.items():
        if cpd.get(name) != mh.get(hn):
            p.append('%s = %s, Mesa says %s = %s' % (name, cpd.get(name), hn, mh.get(hn)))
    tt = re.search(r'cpR6Tris\[CP_R6_TRIS\] = \{(.*?)\n\};', cp, re.S)
    tri_nv = dict((k + 1, int(m)) for k, m in enumerate(re.findall(r'\{ (\d+)UL, \{', tt.group(1)))) if tt else {}
    ntri = int(re.search(r'#define CP_R6_TRIS\s+(\d+)', src['osrdn_cp.h']).group(1))
    if len(tri_nv) != ntri:
        p.append('the triangle table has %d rows, CP_R6_TRIS is %d' % (len(tri_nv), ntri))
    if 'if (tr->nv == 0UL || tr->nv > 6UL || tr->nv % 3UL != 0UL)' not in cp:
        p.append('the triangle guard (0 < nv <= 6, a multiple of 3) is gone')
    # R6f: the words live in a file static of CP_R6_WORDS, the length is known and checked before
    # anything is sent, and the built count must equal it
    cpw = re.search(r'#define CP_R6_WORDS\s+(\d+)', src['osrdn_cp.h'])
    # R7a: the array must also hold a full client submission plus what the driver wraps round it
    r7max = int(re.search(r'#define CP_R7_BATCH_MAX\s+(\d+)', src['osrdn_cp.h']).group(1))
    if not cpw or int(cpw.group(1)) < r7max + 12:
        p.append('CP_R6_WORDS %s cannot hold a full R7 submission (%d + 12)' % (cpw and cpw.group(1), r7max))
    if not cpw or int(cpw.group(1)) != DO.WORDS_MAX or max(DO.words_needed(n) for n in DO.ORDER) > DO.WORDS_MAX:
        p.append('CP_R6_WORDS %s, the oracle wants %d (largest submission %d)' % (
            cpw and cpw.group(1), DO.WORDS_MAX, max(DO.words_needed(n) for n in DO.ORDER)))
    for need in ('static unsigned long cpR6Words[CP_R6_WORDS];', 'unsigned long *w = cpR6Words,',
                 '    need = 26UL + ((cs->ppcntl != 0UL) ? 8UL : 0UL) + 4UL + 2UL + nvert * vw + 10UL;',
                 '    if (need > (unsigned long)CP_R6_WORDS)\n        return cpRefused(c, CP_WHY_WORDS, need);',
                 '    if (n != need) {'):
        if need not in cp:
            p.append('the R6f word array or its count check is gone: %r' % need[:60])
    if re.search(r'unsigned long w\[\d+\]', cp):
        p.append('a stack word array is back')
    flat = re.sub(r'\s+', '', re.sub(r'/\*.*?\*/', '', cp, flags=re.S))
    tt2 = re.search(r'cpR6T\[(\d+)\]\[15\] = \{(.*?)\n\};', cp, re.S)          # R6h, R6i: the texture table
    trows = re.findall(r'\{([^{}]*)\}', tt2.group(2)) if tt2 else []
    twant = ([(n, TE.tex_values(n) + [0, 0]) for n in TE.ORDER] +
             [(n, PE.tex_values(n)) for n in PE.TEX_ORDER])
    if len(trows) != len(twant) or (tt2 and int(tt2.group(1)) != len(twant)):
        p.append('cpR6T has %d rows, the oracles have %d' % (len(trows), len(twant)))
    for k, row in enumerate(trows[:len(twant)]):
        got = [int(x, 0) for x in re.findall(r'(0x[0-9a-fA-F]+|\d+)UL', row)]
        if got != twant[k][1]:
            p.append('cpR6T row %d (%s): %s, the oracle says %s' % (k + 1, twant[k][0], [hex(x) for x in got],
                                                                    [hex(x) for x in twant[k][1]]))
    # R6l (docs/R6L_PLAN.md 3): the word array must leave room for the ring's padding
    cpr = re.search(r'#define CP_R6_WORDS\s+(\d+)', src['osrdn_cp.h'])
    rw = re.search(r'#define CP_RING_WORDS\s+(\d+)', src['osrdn_cp.h'])
    if not cpr or not rw or int(cpr.group(1)) + 16 > int(rw.group(1)):
        p.append('CP_R6_WORDS %s + 16 must fit in CP_RING_WORDS %s' %
                 (cpr and cpr.group(1), rw and rw.group(1)))
    pt = re.search(r'cpR6Poly\[(\d+)\]\[6\] = \{(.*?)\n\};', cp, re.S)          # R6l: the batch triangles
    prows = re.findall(r'\{([^{}]*)\}', pt.group(2)) if pt else []
    if len(prows) != len(BA.POLY) or (pt and int(pt.group(1)) != len(BA.POLY)):
        p.append('cpR6Poly has %d rows, the oracle has %d' % (len(prows), len(BA.POLY)))
    for k, row in enumerate(prows[:len(BA.POLY)]):
        got = [int(x, 0) for x in re.findall(r'(0x[0-9a-fA-F]+|\d+)UL', row)]
        if got != BA.poly_values(BA.POLY[k]):
            p.append('cpR6Poly row %d: %s, the oracle says %s' % (k + 1, [hex(x) for x in got],
                                                                  [hex(x) for x in BA.poly_values(BA.POLY[k])]))
    kt = re.search(r'cpR6Pack\[(\d+)\]\[6\] = \{(.*?)\n\};', cp, re.S)          # R6l: the packets
    krows = re.findall(r'\{([^{}]*)\}', kt.group(2)) if kt else []
    if len(krows) != len(BA.PACK_ROWS) or (kt and int(kt.group(1)) != len(BA.PACK_ROWS)):
        p.append('cpR6Pack has %d rows, the oracle has %d' % (len(krows), len(BA.PACK_ROWS)))
    for k, row in enumerate(krows[:len(BA.PACK_ROWS)]):
        got = [int(x, 0) for x in re.findall(r'(0x[0-9a-fA-F]+|\d+)UL', row)]
        if got != BA.PACK_ROWS[k]:
            p.append('cpR6Pack row %d: %s, the oracle says %s' % (k + 1, [hex(x) for x in got],
                                                                  [hex(x) for x in BA.PACK_ROWS[k]]))
    if max(BA.words_needed(n) for n in BA.ORDER) > int(cpr.group(1) if cpr else 0):
        p.append('an R6l submission is longer than CP_R6_WORDS (%d)' % max(BA.words_needed(n) for n in BA.ORDER))
    st = re.search(r'cpR6S\[(\d+)\]\[7\] = \{(.*?)\n\};', cp, re.S)             # R6k: the auxiliary scissor
    srows = re.findall(r'\{([^{}]*)\}', st.group(2)) if st else []
    if len(srows) != len(SC.S_ORDER) or (st and int(st.group(1)) != len(SC.S_ORDER)):
        p.append('cpR6S has %d rows, the oracle has %d' % (len(srows), len(SC.S_ORDER)))
    for k, row in enumerate(srows[:len(SC.S_ORDER)]):
        got = [int(x, 0) for x in re.findall(r'(0x[0-9a-fA-F]+|\d+)UL', row)]
        if got != SC.s_values(SC.S_ORDER[k]):
            p.append('cpR6S row %d (%s): %s, the oracle says %s' % (k + 1, SC.S_ORDER[k], [hex(x) for x in got],
                                                                    [hex(x) for x in SC.s_values(SC.S_ORDER[k])]))
    if max(SC.words_needed(n) for n in SC.ORDER) > DO.WORDS_MAX:
        p.append('an R6k submission is longer than CP_R6_WORDS (%d)' % max(SC.words_needed(n) for n in SC.ORDER))
    wt = re.search(r'cpR6W\[(\d+)\]\[3\] = \{(.*?)\n\};', cp, re.S)             # R6i: the W table
    wrows = re.findall(r'\{([^{}]*)\}', wt.group(2)) if wt else []
    if len(wrows) != len(PE.W_ORDER) or (wt and int(wt.group(1)) != len(PE.W_ORDER)):
        p.append('cpR6W has %d rows, the oracle has %d' % (len(wrows), len(PE.W_ORDER)))
    for k, row in enumerate(wrows[:len(PE.W_ORDER)]):
        got = [int(x, 0) for x in re.findall(r'(0x[0-9a-fA-F]+|\d+)UL', row)]
        if got != PE.w_values(PE.W_ORDER[k]) or 0 in got:
            p.append('cpR6W row %d (%s): %s, the oracle says %s' % (k + 1, PE.W_ORDER[k], [hex(x) for x in got],
                                                                    [hex(x) for x in PE.w_values(PE.W_ORDER[k])]))
    for need in ('    if (cs->widx > CP_R6_WROWS || (cs->widx != 0UL && (tr == 0 || tr->nv != 3UL)))',
                 '    if (wv != 0 && (wv[0] == 0UL || wv[1] == 0UL || wv[2] == 0UL))',
                 '        w[st + 17] = cs->vte;'):
        if need not in cp:                                # R6i: the W bound, the zero guard, the VTE patch
            p.append('an R6i guard or patch is gone: %r' % need.strip()[:60])
    for need in ('                if (al[(cpR6TexOff(cs) + vv * stride) / 4UL + u] != cpR6Texel(pat, u, vv))\n                    c->pfBad++;',
                 '            if (got != (unsigned long)val)\n                c->pfBad++;'):
        if need not in cp:                                # docs/R6G_PLAN.md 2-1, docs/R6H_PLAN.md 2-1
            p.append('a CPU fill is written without its read-back: %r' % need[:50])
    gt = re.search(r'cpR6G\[(\d+)\]\[12\] = \{(.*?)\n\};', cp, re.S)          # R6g / R6j: the second-draw table
    grows = re.findall(r'\{([^{}]*)\}', gt.group(2)) if gt else []
    gwant = ([(n, DO.g_table_values(n) + [0, 0]) for n in DO.GORDER] +
             [(n, PE.blend_g_values(n)) for n in PE.ORDER4])
    if len(grows) != len(gwant) or (gt and int(gt.group(1)) != len(gwant)):
        p.append('cpR6G has %d rows, the oracles have %d' % (len(grows), len(gwant)))
    for k, row in enumerate(grows[:len(gwant)]):
        got = [int(x, 0) for x in re.findall(r'(0x[0-9a-fA-F]+|\d+)UL', row)]
        if got != gwant[k][1]:
            p.append('cpR6G row %d (%s): %s, the oracle says %s' % (k + 1, gwant[k][0], [hex(x) for x in got],
                                                                    [hex(x) for x in gwant[k][1]]))
    for need in ('        if (c->pfBad != 0UL) {\n            c->failed = 1;\n            return cpRefused(c, CP_WHY_PREFILL, c->pfBad);',
                 '        w[n++] = C_P0(C_RB3D_DSTCACHE_CTLSTAT); w[n++] = C_PURGE_DC;\n'
                 '        w[n++] = C_P0(C_RB3D_ZCACHE_CTLSTAT);   w[n++] = C_PURGE_ZC;'):
        if need not in cp:                              # R6g: the prefill is checked, the caches purged first
            p.append('the R6g prefill check or the purge before the draw is gone: %r' % need[:50])
    ing = False
    for line in DO.c_tables().splitlines():             # R6f: cells, anchors, z rows, triangle rows
        if line.startswith('static const unsigned long cpR6G['):
            ing = True                                   # R6j widened cpR6G: the ordered comparison
            continue                                     # above covers those rows, padding included
        if line.startswith('};') or line.startswith('/*'):
            ing = False
        if ing or not line.startswith('    { ') or line.startswith('    { 0, 0, 64, 64'):
            continue                                     # (a case row: its values are compared below)
        want = re.sub(r'\s+', '', re.sub(r'/\*.*?\*/', '', line)).rstrip(',')
        if want not in flat:
            p.append('R6f table line not in osrdn_cp.m: %s' % line.strip()[:70])
    # R6l (docs/R6L_PLAN.md 7, Z3): the KMS checker's relation -- a 3D_DRAW_IMMD_2's count field is
    # the vertex word count times the vertex count (r100.c 2331-2336).  Every case row must satisfy
    # it, whatever rung wrote the row; the grid cases build their own header, so they are exempt here
    # and the simulator's stream comparison covers them.
    for m in re.finditer(r'0x(c[0-9a-f]{7})UL, 0x([0-9a-f]+)UL,', cp):
        hdr, vf = int(m.group(1), 16), int(m.group(2), 16)
        if (hdr & 0xc000ffff) != 0xc0003500:
            continue                                     # not a 3D_DRAW_IMMD_2 header
        cnt, nv = (hdr >> 16) & 0x3fff, (vf >> 16) & 0xffff
        if nv == 0 or cnt % nv != 0 or cnt // nv not in (4, 5, 7):
            p.append('a draw header says %d words for %d vertices -- not 4, 5 or 7 per vertex' % (cnt, nv))
    tbl = re.search(r'cpR6Cases\[CP_R6_CASES\] = \{(.*?)\n\};', cp, re.S)
    rows = re.findall(r'\{([^{}]*)\}', tbl.group(1)) if tbl else []
    ncase = int(re.search(r'#define CP_R6_CASES\s+(\d+)', src['osrdn_cp.h']).group(1))
    if len(rows) != ncase:
        p.append('the case table has %d rows, CP_R6_CASES is %d' % (len(rows), ncase))
    for k, row in enumerate(rows):
        v = [int(x, 0) for x in re.findall(r'(0x[0-9a-fA-F]+|\d+)UL|\b(\d+)\b(?=,|\s*$)', row) for x in x if x]
        if len(v) != 39:
            p.append('case row %d has %d values, want 39' % (k + 1, len(v)))
            continue
        if k + 1 == 171:
            # R7a: the row carries only read-back parameters -- T1's colour and clip -- and no
            # geometry at all, because the words come from the client (docs/R7_PLAN.md 4)
            if v[14] != 0 or v[15] != 0 or v[17] != 0:
                p.append('case 171 (UC) carries geometry: hdr %#x vf %#x tri %d' % (v[14], v[15], v[17]))
            if (v[18], v[19]) != (0x78123456, 0x78123456):
                p.append('case 171 (UC) does not carry T1\'s colour')
            continue
        if k + 1 >= RU.FIRST:
            # R6m (docs/R6M_PLAN.md 4): the whole row is the oracle's, offsets included
            rname = RU.ORDER[k + 1 - RU.FIRST] if k + 1 - RU.FIRST < len(RU.ORDER) else None
            if rname is None or v != RU.case_values(rname):
                p.append('case %d (%s): row %s, the oracle says %s' % (k + 1, rname, [hex(x) for x in v[10:]],
                                                                       rname and [hex(x) for x in RU.case_values(rname)[10:]]))
            continue
        if k + 1 >= BA.FIRST:
            # R6l (docs/R6L_PLAN.md 4): the whole row is the oracle's
            bname = BA.ORDER[k + 1 - BA.FIRST] if k + 1 - BA.FIRST < len(BA.ORDER) else None
            if bname is None or v != BA.case_values(bname) + [0, 0, 0]:
                p.append('case %d (%s): row %s, the oracle says %s' % (k + 1, bname, [hex(x) for x in v[10:]],
                                                                       bname and [hex(x) for x in BA.case_values(bname)[10:]]))
            continue
        if k + 1 >= SC.FIRST:
            # R6k (docs/R6K_PLAN.md 4): the whole row is the oracle's
            sname = SC.ORDER[k + 1 - SC.FIRST] if k + 1 - SC.FIRST < len(SC.ORDER) else None
            if sname is None or v != SC.case_values(sname) + [0] * 5:
                p.append('case %d (%s): row %s, the oracle says %s' % (k + 1, sname, [hex(x) for x in v[10:]],
                                                                       sname and [hex(x) for x in SC.case_values(sname)[10:]]))
            continue
        if k + 1 >= PE.FIRST:
            # R6i (docs/R6I_PLAN.md 2-2): the whole row is the oracle's
            pname = PE.ORDER[k + 1 - PE.FIRST] if k + 1 - PE.FIRST < len(PE.ORDER) else None
            if pname is None or v != PE.case_values(pname) + [0] * 6:
                p.append('case %d (%s): row %s, the oracle says %s' % (k + 1, pname, [hex(x) for x in v[10:]],
                                                                       pname and [hex(x) for x in PE.case_values(pname)[10:]]))
            continue
        if k + 1 >= TE.FIRST:
            # R6h (docs/R6H_PLAN.md 2-2): the whole row is the oracle's
            tname = TE.ORDER[k + 1 - TE.FIRST] if k + 1 - TE.FIRST < len(TE.ORDER) else None
            if tname is None or v != TE.case_values(tname) + [0] * 8:
                p.append('case %d (%s): row %s, the oracle says %s' % (k + 1, tname, [hex(x) for x in v[10:]],
                                                                       tname and [hex(x) for x in TE.case_values(tname)[10:]]))
            continue
        ppcntl, pm, fmt, vsc, hdr, vf, col, tri, cp1, cp2, secntl, lanes, gconst, gvary = v[10:24]
        if k + 1 >= DO.GFIRST:
            # R6g (docs/R6G_PLAN.md 2-2): the whole row and its cpR6G row are the oracle's
            gname = DO.GORDER[k + 1 - DO.GFIRST] if k + 1 - DO.GFIRST < len(DO.GORDER) else None
            if gname is None or v != DO.g_case_values(gname) + [0] * 9:
                p.append('case %d (%s): row %s, the oracle says %s' % (k + 1, gname, [hex(x) for x in v[10:]],
                                                                       gname and [hex(x) for x in DO.g_case_values(gname)[10:]]))
            continue
        if k + 1 >= DO.FIRST:
            # R6f (docs/R6F_PLAN.md 3-1): the whole row is the oracle's
            dname = DO.ORDER[k + 1 - DO.FIRST] if k + 1 - DO.FIRST < len(DO.ORDER) else None
            if dname is None or v != DO.case_values(dname) + [0] * 9:
                p.append('case %d (%s): row %s, the oracle says %s' % (k + 1, dname, [hex(x) for x in v[10:]],
                                                                       dname and [hex(x) for x in (DO.case_values(dname) + [0])[10:]]))
            continue
        if v[24:] != [0x42227072, 0, 0, 0, 0x1902, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]:
            p.append('case %d: R6f/R6g fields %s on a case before R6f' % (k + 1, [hex(x) for x in v[24:]]))
        gname = GO.ALL_ORDER[k - 25] if 0 <= k - 25 < len(GO.ALL_ORDER) else None
        if gname is None and (secntl, lanes, gconst, gvary) != (0x480055de, 0, 0, 0):
            p.append('case %d: R6e fields %s on a case before R6e' % (k + 1, [hex(x) for x in (secntl, lanes, gconst, gvary)]))
        if gname is not None:
            # R6e (docs/R6E_PLAN.md 9): SE_CNTL diffuse + alpha GOURAUD, the lanes and constants the oracle names
            want = (GO.se_cntl_gouraud(), GO.lanes_mask(gname)) + GO.const_pixel(gname)
            if (secntl, lanes, gconst, gvary) != want or (cp1, cp2) != (0, 0) or tri != k - 7:
                p.append('case %d (%s): R6e fields %s, the oracle says %s' % (
                    k + 1, gname, [hex(x) for x in (secntl, lanes, gconst, gvary)], [hex(x) for x in want]))
        if tri:
            # R6d (docs/R6D_PLAN.md 10): a triangle row -- TRIANGLES with colour, the whole-buffer clip,
            # and the map colours the oracle names (code review m3); R6e rows map nothing (0, 0)
            want = TO.map_colours(TO.ORDER[k - 8]) if 0 <= k - 8 < len(TO.ORDER) else (0, 0)
            if want != (cp1, cp2):
                p.append('case %d: map colours %#x %#x, the oracle says %s' % (k + 1, cp1, cp2, want and tuple(hex(x) for x in want)))
            nv = tri_nv.get(tri)
            if nv is None or nv % 3 or not 3 <= nv <= 6:
                p.append('case %d: triangle table %d has %s vertices' % (k + 1, tri, nv))
            elif hdr != (0xc0003500 | ((5 * nv) << 16)) or vf != (0x74 | (nv << 16)) or fmt != 0x803 or ppcntl != 0x1000 \
                    or pm != 0xffffffff or v[:4] != [0, 0, 64, 64] or v[9] != 2 or col:
                p.append('case %d: triangle row words %#x %#x fmt %#x clip %s' % (k + 1, hdr, vf, fmt, v[:4]))
            continue
        colour = (fmt >> 11) & 3
        if colour not in (0, 1) or fmt & ~0x1803 != 0 or fmt & 3 != 3:
            p.append('case %d: SE_VTX_FMT_0 %#x is not Z0|W0 (| PK_RGBA)' % (k + 1, fmt))
        if (hdr & 0xc000ffff) != 0xc0003500 or ((hdr >> 16) & 0x3fff) != 3 * (4 + colour):
            p.append('case %d: header %#x does not count 3 x %d words' % (k + 1, hdr, 4 + colour))
        if (ppcntl != 0) != (colour == 1) or ppcntl not in (0, 0x1000) or pm not in (0, 0xffffffff) or (pm != 0) != (colour == 1):
            p.append('case %d: PP_CNTL %#x / PLANEMASK %#x do not follow the colour field' % (k + 1, ppcntl, pm))
        if vf not in (0x00030038, 0x00030078) or (vf & 0x40 and not colour):
            p.append('case %d: VF_CNTL %#x' % (k + 1, vf))
        if vsc not in (0, 0x10000) or (vsc and not colour) or (col and not colour):
            p.append('case %d: SE_VTX_STATE_CNTL %#x / colour %#x without colour' % (k + 1, vsc, col))
    m = re.search(r'len < 1UL \|\| len > (\d+)UL', open(RDNR5CP).read())
    if not m or int(m.group(1)) != ncase:
        p.append('rdnr5cp accepts cases up to %s, CP_R6_CASES is %d' % (m and m.group(1), ncase))
    r['r6c-cases'] = p
    # ---- R6m (docs/R6M_PLAN.md 7): the surfaces are per case, and EVERY read-back follows them
    p = []
    for name, helper in (('CP_R6_COLOR_OFF', 'cpR6ColorOff'), ('CP_R6_DEPTH_OFF', 'cpR6DepthOff'),
                         ('CP_R6_TEX_OFF', 'cpR6TexOff')):
        n = cp.count(name)
        if n != 1:
            p.append('%s appears %d times in osrdn_cp.m -- only %s may name it (R6m)' % (name, n, helper))
        if ('%s(const cpR6Case *cs)' % helper) not in cp:
            p.append('the %s helper is gone' % helper)
    for a in ('cpR6Digest(c, cpR6DepthOff(cs) / 4UL', 'cpR6Digest(c, cpR6ColorOff(cs) / 4UL',
              'w[n++] = c->winStart + cpR6DepthOff(cs);', 'w[n++] = c->winStart + cpR6ColorOff(cs);',
              'w[n++] = c->winStart + cpR6TexOff(cs);',
              'unsigned long at = cpR6ColorOff(cs) / 4UL + (i >> 5) * CP_R6_PITCH + (i & 31UL), code;',
              'unsigned long at = cpR6ColorOff(cs) / 4UL + (i >> 5) * CP_R6_PITCH + (i & 31UL), b;',
              'return c->winStart + cpR6DepthOff(cs);', 'return c->winStart + cpR6ColorOff(cs);',
              'c->zColorOff = cpR6ColorOff(cs);'):
        if a not in cp:
            p.append('a surface read-back or register no longer follows the case: %r' % a[:60])
    if 'want = cpR6Pattern(cpR6TexOff(cs) / 4UL + i);' not in cp or 'c->texPost++' not in cp:
        p.append('the post-draw texture check is gone (docs/R6M_PLAN.md 5 N3)')
    # every case row's three surfaces are whole words, inside the window and disjoint
    bb, ab, tb = 4 * 4096, 0x40000, 1024
    for k, row in enumerate(rows):
        v = [int(x, 0) for x in re.findall(r'(0x[0-9a-fA-F]+|\d+)UL|\b(\d+)\b(?=,|\s*$)', row) for x in x if x]
        if len(v) != 39:
            continue                                    # already reported above
        co, zf, tf = v[36] or RU.COLOR_OFF, v[37] or RU.DEPTH_OFF, v[38] or RU.TEX_OFF
        if (v[36] | v[37] | v[38]) & 3:
            p.append('case %d: a surface offset is not a whole word' % (k + 1))
        if co + bb > ab or zf + bb > ab or tf + tb > ab:
            p.append('case %d: a surface runs past the %d KiB window' % (k + 1, ab // 1024))
        if co < zf + bb and zf < co + bb:
            p.append('case %d: the colour and depth surfaces overlap' % (k + 1))
        if v[30] and (co < tf + tb and tf < co + bb or zf < tf + tb and tf < zf + bb):
            p.append('case %d: the texture overlaps a drawn surface' % (k + 1))
    r['r6m-surfaces'] = p
    # ---- R7a (docs/R7_PLAN.md 4): the verifier's tables are the oracle's, and its rules are all there
    p = []
    m2 = re.search(r'static const unsigned short cpR7Allow\[(\d+)\] = \{(.*?)\};', cp, re.S)
    if not m2:
        p.append('the R7 allow-list table is gone')
    else:
        got = [int(x, 0) for x in re.findall(r'0x[0-9a-fA-F]+', m2.group(2))]
        if got != VO.ALLOW or int(m2.group(1)) != len(VO.ALLOW):
            p.append('cpR7Allow has %d registers, the oracle derives %d%s' % (
                len(got), len(VO.ALLOW),
                '' if len(got) != len(VO.ALLOW) else ' (same count, different registers)'))
        for a in VO.RESERVED:
            if a in got:
                p.append('cpR7Allow contains the reserved register %#06x' % a)
    for want, why in ((r'#define CP_R7_BATCH_MAX\s+%d' % VO.BATCH_MAX_WORDS, 'the batch limit'),
                      (r'#define CP_R7_APPEND_MAX\s+%d' % VO.APPEND_MAX_WORDS, 'the append limit')):
        if not re.search(want, src['osrdn_cp.h']):
            p.append('%s does not match the oracle' % why)
    # every rule the plan lists must be reachable in the C: one return per code
    for code in ('TYPE', 'TRUNC', 'P0_COUNT', 'P0_REG', 'P0_VALUE', 'P3_OP', 'VF', 'VTX_FMT',
                 'VTX_UNSET', 'COUNT', 'SURFACE', 'WORDS', 'EMPTY'):
        if ('return CP_R7_WHY_%s' % code) not in cp:
            p.append('no rule can return CP_R7_WHY_%s any more' % code)
    # R7a: the packet type is the top two bits taken as a 0..3 number, not three 32-bit constants.
    # The first version compared constants and the target's cc read a type-3 header as a PACKET0
    # (boot ebfec1ec) while the host compiler did not -- a difference no host check can see, so the
    # ROBUST FORM is what is checked here instead.
    if 't = hdr >> 30;' not in cp:
        p.append('the packet type is no longer taken as the top two bits (docs/R7_PLAN.md 9)')
    if re.search(r't\s*=\s*hdr\s*&\s*0xc0000000', cp):
        p.append('the packet type is compared against 32-bit constants again')
    # the words must be judged before they are copied: the verify call comes first, and its
    # refusal returns rather than falling through
    # G5-2: per function -- cpAsubmit is a second place the client's words reach the ring, and a
    # file-wide search let either one lose its refusal while the other still had it
    for f in ('cpZclear', 'cpAsubmit'):
        body = fn.get(f, '')
        if 'return cpRefused(c, CP_WHY_R7, c->r7Why);' not in body:
            p.append('%s: a refused stream is not refused: the verdict does not return' % f)
        iv, iw = body.find('cpR7Verify(c, cpR7Buf'), body.find('w[n++] = cpR7Buf[i];')
        if iv < 0 or iw < 0 or iv > iw:
            p.append('%s: the client\'s words are copied to the ring before they are verified' % f)
    r['r7-verify'] = p

    # ---- M1z: the operation-name table (docs/M1Z_PLAN.md 0)
    #
    # The driver printed a null through %s on a real boot because cpOpNames was
    # declared [CP_OP_LAST + 1] with one name missing, and the compile-time check
    # beside it compared the array's size with the constant that DECLARED it --
    # an identity.  Two rules, because the defect had two halves.
    p = []
    ml = src['osrdn_modelog.m']
    mdecl = re.search(r'static const char \*const cpOpNames\[([^\]]*)\] = \{(.*?)\};', ml, re.S)
    if mdecl is None:
        p.append('cpOpNames is not declared the way this rule can read')
    else:
        if mdecl.group(1).strip() != '':
            p.append('cpOpNames is declared with a size (%s): sizeof then counts the SIZE and '
                     'the check beside it becomes an identity that cannot fail'
                     % mdecl.group(1).strip())
        names = re.findall(r'"([^"]*)"', mdecl.group(2))
        last = re.search(r'#define\s+CP_OP_LAST\s+(\d+)', src['osrdn_cp.h'])
        if last is None:
            p.append('CP_OP_LAST is not in osrdn_cp.h')
        elif len(names) != int(last.group(1)) + 1:
            p.append('cpOpNames has %d names but CP_OP_LAST is %s, so index %d..%s prints a null'
                     % (len(names), last.group(1), len(names), last.group(1)))
        else:
            # and each numbered operation's name must be at its own index
            for nm, num in re.findall(r'#define\s+CP_OP_([A-Z0-9_]+)\s+(\d+)', src['osrdn_cp.h']):
                if nm == 'LAST':
                    continue
                i = int(num)
                if i < len(names) and names[i] != nm.lower():
                    p.append('CP_OP_%s is %d but cpOpNames[%d] is "%s"' % (nm, i, i, names[i]))
    # M2a: THE JOIN.  There are TWO name tables -- the driver's (osrdn_modelog.m)
    # and the user tool's (rdnr5cp.m) -- and each has its own compile-time size
    # check.  Nothing checked that they say the SAME thing, so a new operation
    # could be named differently in the two and the tool would send one number
    # while the log printed another name ([[check-the-join-not-just-the-sides]]).
    tl = src['rdnr5cp.m']
    mt = re.search(r'static const char \*const opNames\[([^\]]*)\] = \{(.*?)\};', tl, re.S)
    if mt is None:
        p.append('rdnr5cp opNames is not declared the way this rule can read')
    elif mdecl is not None:
        if mt.group(1).strip() != '':
            p.append("rdnr5cp opNames is declared with a size (%s): its own check "
                     "becomes an identity" % mt.group(1).strip())
        tnames = re.findall(r'"([^"]*)"', mt.group(2))
        dnames = re.findall(r'"([^"]*)"', mdecl.group(2))
        oc = re.search(r'#define\s+OP_COUNT\s+(\d+)', tl)
        if not oc or int(oc.group(1)) != len(tnames):
            p.append('rdnr5cp OP_COUNT is %s but the table has %d names'
                     % (oc and oc.group(1), len(tnames)))
        elif last is not None and int(oc.group(1)) != int(last.group(1)) + 1:
            p.append('rdnr5cp OP_COUNT is %s, CP_OP_LAST + 1 is %d'
                     % (oc.group(1), int(last.group(1)) + 1))
        # index 0 differs on purpose: the driver prints "bad", the tool never sends 0
        for i in range(1, min(len(tnames), len(dnames))):
            if tnames[i] != dnames[i]:
                p.append('operation %d is "%s" in the driver and "%s" in rdnr5cp'
                         % (i, dnames[i], tnames[i]))
    r['m1z-opnames'] = p

    # ---- M2a: the WBINVD knob reaches exactly ONE path (docs/M2A_PLAN.md 4)
    #
    # Every reference does a barrier and no cache operation in the SUBMISSION
    # path, and puts its one wbinvd where the GART table is built.  This rule
    # pins that shape: the knob is read in the submission fence and nowhere
    # else, and the six other cpFence call sites keep their WBINVD.
    p = []
    nfence = cp.count('cpFence(base);')
    nsub = cp.count('cpSubmitFence(c, base);')
    if nfence != 7:
        p.append('cpFence is called %d times, want 7 (MAP, START, PREPARE, ZPREP, the two prefills '
                 'and the M3i kick at a latch) -- the submission path must use cpSubmitFence' % nfence)
    if nsub != 1:
        p.append('cpSubmitFence is called %d times, want once' % nsub)
    sub = fn.get('cpR6Submit', '')
    if 'cpFence(base);' in sub:
        p.append('cpR6Submit still calls cpFence: the knob would not reach it')
    if 'cpSubmitFence(c, base);' not in sub:
        p.append('cpR6Submit does not call cpSubmitFence')
    sf = fn.get('cpSubmitFence', '')
    if not sf:
        p.append('cpSubmitFence is not defined')
    else:
        # M2e: the SENSE of the flag is the design.  The state is cleared byte by
        # byte at init, so whatever means "fast" has to be the zero -- then no
        # initialiser can be forgotten and no clear added later can undo it.
        if not re.search(r'if \(c->doWb\)\s*\n\s*osrdn_cpu_wbinvd\(\);', sf):
            p.append('cpSubmitFence does not guard the wbinvd with c->doWb -- M2e made '
                     'the ZERO state the fast one, so the flag says "do it", not "skip it"')
        if 'osrdn_cpu_serialize();' not in sf:
            p.append('cpSubmitFence dropped the barrier -- that is NOT what the references do')
    # the flag is read only there, and written only by its own operation
    # `cp` is the BLANKED text, so comments do not count: one guard, one setter
    reads = len(re.findall(r'c->doWb', cp))
    if reads != 2:
        p.append('c->doWb appears %d times in the code of osrdn_cp.m, want 2 '
                 '(one guard in cpSubmitFence, one setter in cpNoWb)' % reads)
    if re.search(r'c->noWb', cp):
        p.append('c->noWb is back: M2e renamed it to doWb so the zero state is the '
                 'fast one, and the old name reading the other way round is the bug')
    if not re.search(r'c->doWb = \(on != 0UL\) \? 0 : 1;', cp):
        p.append('cpNoWb does not INVERT its argument into doWb -- `nowb 1` must mean '
                 '"do not write back", which is doWb 0')
    # M2e: AND THERE MUST BE NO INITIALISER.  The default is the zeroed state and
    # nothing else; an assignment anywhere but cpNoWb ties the default to the
    # reset lifecycle and would silently undo an operator's `nowb 0`.
    setters = re.findall(r'c->doWb\s*=', cp)
    if len(setters) != 1:
        p.append('c->doWb is assigned %d times, want exactly 1 (cpNoWb).  An '
                 'initialiser anywhere else ties the default to the reset lifecycle'
                 % len(setters))
    if 'doWb' in fn.get('cpReset', '') or 'doWb' in fn.get('cpStart', '') \
            or 'doWb' in fn.get('cpLoad', ''):
        p.append('the bring-up touches doWb: the default must come from the zeroed '
                 'state, not from a line in cpReset/cpStart/cpLoad')
    # and the two comments that used to say the default was OFF
    # NARROWLY: the two sentences that were about THE WBINVD.  A blanket search
    # for "DEFAULT IS OFF" also catches the stage instrument's comment, whose
    # default really is off -- the first form of this rule failed on that.
    for nm_, phrase in (('osrdn_cp.h', 'len != 0 turns the skip ON.  The DEFAULT IS OFF'),
                        ('osrdn_cp.m', 'the default is OFF and c->noWb must be turned')):
        if phrase in src.get(nm_, ''):
            p.append('%s still says the WBINVD default is OFF -- M2e made the skip '
                     'the default' % nm_)
    # MAP keeps its WBINVD: that is where ati_pcigart.c puts its one
    if 'cpFence(base);' not in fn.get('cpMap', ''):
        p.append('cpMap no longer flushes: that is the one place the reference DOES flush')
    r['m2a-nowb'] = p


    # ---- M2b: the spin knob, and the two bounds it must NOT touch
    #
    # The time check is what enforces the 100 ms; the turn cap is the
    # frozen-clock backstop (osrdn_cp.m:123-124).  The spin sits AFTER both, so
    # it can lengthen the gap between two time checks but never skip one.
    p = []
    wt = fn.get('cpWait', '')
    if not wt:
        p.append('cpWait is not defined')
    else:
        if 'if (w->us >= limitUs)' not in wt:
            p.append('cpWait lost its TIME bound -- that is what enforces the limit')
        if 'if (turns >= maxTurns)' not in wt:
            p.append('cpWait lost its TURN bound -- the frozen-clock backstop')
        # the spin must come after both, and before the sleep
        i_time = wt.find('if (w->us >= limitUs)')
        i_turn = wt.find('if (turns >= maxTurns)')
        i_spin = wt.find('for (k = 0; k < cpSpin; k++)')
        i_dly = wt.find('IODelay((unsigned)C_TICK_US);')
        if i_spin < 0:
            p.append('cpWait has no spin loop')
        elif not (i_time < i_spin and i_turn < i_spin and i_spin < i_dly):
            p.append('the spin is not between the two bounds and the sleep '
                     '(time %d turn %d spin %d sleep %d)' % (i_time, i_turn, i_spin, i_dly))
        # and it must refresh the clock on the way out, or the wait undercounts
        spin_body = wt[i_spin:i_dly] if i_spin >= 0 else ''
        if 'IOGetTimestamp(&t1);' not in spin_body or 'w->us = cpElapsedUs(t0, t1);' not in spin_body:
            p.append('the spin returns without refreshing w->us: a spinning arm would '
                     'report a smaller wait than it had')
        # turns is recorded, because evals stops meaning turns once the spin runs
        if 'w->turns = turns;' not in wt or 'w->turns = 0;' not in wt:
            p.append('cpWait does not record w->turns; with a spin, evals is not a turn count')
    if src['osrdn_cp.h'].count('unsigned long   turns;') != 1:
        p.append('osrdn_cp_wait has no turn count, or more than one')
    # the knob is bounded, and only one place sets it
    if not re.search(r'if \(n > CP_SPIN_MAX\)', cp):
        p.append('cpSpinSet does not bound the spin: the claim is held with noSleep')
    if len(re.findall(r'cpSpin = ', cp)) != 1:
        p.append('cpSpin is assigned %d times, want once' % len(re.findall(r'cpSpin = ', cp)))
    if len(re.findall(r'k < cpSpin', cp)) != 1:
        p.append('cpSpin is read in %d places, want once (cpWait)'
                 % len(re.findall(r'k < cpSpin', cp)))
    # M2b: EVERY FIELD OF osrdn_cp_wait IS CLEARED PER OPERATION.
    #
    # Written because it was not.  M2b added `turns` to the struct and to the
    # log, but not to the per-operation clear, and the first boot's log carried
    # `rptr evals=0 turns=2` on refused submissions -- cpWait had never run, so
    # the line reported the PREVIOUS operation's turns as this one's.  A counter
    # that is not cleared reports an old run's number
    # ([[stale-log-grep-fakes-evidence]]).  The rule reads the struct rather than
    # a list, so the next field added is covered without anyone remembering.
    # the LAST `typedef struct {` before the closing line, or the non-greedy match
    # runs from the first typedef in the file and drags other structs' fields in
    # (it did: osrdn_cp_digest.nvals was reported as an uncleared wait field)
    hh = src['osrdn_cp.h']
    ws = None
    if '} osrdn_cp_wait;' in hh:
        head = hh[:hh.index('} osrdn_cp_wait;')]
        if 'typedef struct {' in head:
            ws = head[head.rindex('typedef struct {') + len('typedef struct {'):]
    if ws is None:
        p.append('osrdn_cp_wait is not declared the way this rule can read')
    else:
        fields = re.findall(r'^\s*(?:unsigned long|int)\s+(\w+);', ws, re.M)
        if not fields:
            p.append('osrdn_cp_wait has no fields this rule can see')
        for f in fields:
            # each wait struct in the state must have this field zeroed per operation
            if not re.search(r'c->wFifo\.%s\s*=' % f, cp):
                p.append('osrdn_cp_wait.%s is never cleared per operation: a wait that '
                         'does not run reports the previous operation\'s value' % f)
    r['m2b-spin'] = p

    # ---- M2c: the instrument runs only when asked (docs/M2C_PLAN.md 3)
    p = []
    zc2 = fn.get('cpZclear', '')
    if 'timing = 1;' in zc2 and 'if (c->timeOn) {' not in zc2:
        p.append('cpZclear turns the instrument on unconditionally: every client '
                 'submission would pay seventeen clock reads')
    # the three lines that start the timing must be INSIDE the knob, the first
    # clock read included -- leaving it outside makes the on/off difference
    # exclude its own cost
    m = re.search(r'if \(c->timeOn\) \{(.*?)\}', zc2, re.S)
    if m is None:
        p.append('cpZclear has no c->timeOn guard')
    else:
        body = m.group(1)
        for want in ('IOGetTimestamp(&tmark);', 'timing = 1;', 'c->tOn = 1;'):
            if want not in body:
                p.append('%s is outside the c->timeOn guard' % want)
    # timeOn is persistent: the per-operation clear may touch tOn and nothing else
    if re.search(r'c->timeOn\s*=\s*0;', cp) and 'cpTimeSet' not in cp[:cp.find('c->timeOn = 0;')]:
        p.append('c->timeOn is cleared outside its own operation')
    if len(re.findall(r'c->timeOn = \(on != 0UL\) \? 1 : 0;', cp)) != 1:
        p.append('cpTimeSet does not set timeOn from its argument exactly once')
    # and a latched submission must leave NO accumulator behind
    sub2 = fn.get('cpR6Submit', '')
    for acc in ('CP_T_PUT', 'CP_T_FENCE', 'CP_T_WAIT'):
        if len(re.findall(r'c->tAcc\[%s\] \+=' % acc, sub2)) != 1:
            p.append('%s is committed %d times in cpR6Submit, want once'
                     % (acc, len(re.findall(r'c->tAcc\[%s\] \+=' % acc, sub2))))
    i_put = sub2.find('c->tAcc[CP_T_PUT] +=')
    i_w1 = sub2.find('cpWait(base, W_RPTR')
    if i_put >= 0 and i_w1 >= 0 and i_put < i_w1:
        p.append('the put total is committed BEFORE the waits can fail: a latched '
                 'submission would leave a numerator with no denominator')
    r['m2c-time'] = p

    # ---- G5-2 (docs/G5_2_ASYNC_SUBMIT_PLAN.md 2): the accepted submission.
    #
    # cpAsubmit is allowed on the ring (r6-ring) ONLY because it sends cpZclear's client-case words:
    # the prefix, the driver's WAIT_UNTIL and the stream, and the tail, statement for statement.
    # What it may not do is ask the card anything on the way, and what cpR6Submit may not do for it
    # is return before the doorbell has been read back.
    p = []
    def stmts(body, first, last, from_end=False):
        flat = re.sub(r'\s+', ' ', body)
        b = flat.rfind(first, 0, flat.find(last)) if from_end else flat.find(first)
        e = flat.find(last, b)
        if b < 0 or e < 0:
            return None
        return re.findall(r'w\[n\+\+\] = [^;]*;', flat[b:e + len(last)])
    zc, asb = fn.get('cpZclear', ''), fn.get('cpAsubmit', '')
    if not asb:
        p.append('cpAsubmit is missing')
    else:
        for part, a, z in (('prefix', 'w[n++] = C_P0(C_SE_TCL_STATE_FLUSH);', 'c->zstage = 1;'),
                           ('tail', 'w[n++] = C_P0(C_RB3D_DSTCACHE_CTLSTAT);', 'w[n++] = ~seed;')):
            sz, sa = stmts(zc, a, z, part == 'tail'), stmts(asb, a, z, part == 'tail')
            if sz is None or sa is None:
                p.append('the %s is not where the rule looks (cpZclear %s, cpAsubmit %s)' % (part, sz is not None, sa is not None))
            elif sz != sa:
                p.append('cpAsubmit\'s %s differs from cpZclear\'s: %s' % (part, sorted(set(sz) ^ set(sa)) or 'the order'))
        fa = re.sub(r'\s+', ' ', asb)
        for mid in ('w[n++] = C_P0(C_WAIT_UNTIL); w[n++] = cpR6State[1]; for (i = 0; i < c->subWords; i++) w[n++] = cpR7Buf[i];',):
            if mid not in fa or mid not in re.sub(r'\s+', ' ', zc):
                p.append('the driver WAIT_UNTIL and the stream are not the same in both')
        for bad in ('cpWait(', 'cpWaitRetry(', 'cpIdleGate(', 'cpCheckBlock(', 'cpR6Digest(', 'DC_FLUSH'):
            if bad in fa:
                p.append('cpAsubmit asks the card something (%s)' % bad)
        subs = [m.start() for m in re.finditer(r'rc = cpR6Submit\(c, base, w, n\);', fa)]
        if len(subs) != 2:
            p.append('cpAsubmit writes the ring %d times, want 2 (the prefix, then the stream)' % len(subs))
        for at in subs:
            if not fa[:at].rstrip().endswith('c->noWait = 1;') or not fa[at:].startswith('rc = cpR6Submit(c, base, w, n); c->noWait = 0;'):
                p.append('a cpAsubmit write is not bracketed by noWait = 1 / noWait = 0')
        if 'cpR7Verify(' not in fa or fa.find('cpR7Verify(') > (subs[0] if subs else 0):
            p.append('cpAsubmit does not verify the stream before the first write')
    sub = re.sub(r'\s+', ' ', fn.get('cpR6Submit', ''))
    i_sp, i_put = sub.find('if (!cpWaitSpace(c, base, len)) return cpFail(c, base);'), sub.find('cpPut(c, p + k')
    i_rb, i_nw, i_w = sub.find('if (c->wptrRead != target)'), sub.find('if (c->noWait) return CP_RC_RAN;'), sub.find('cpWait(base, W_RPTR')
    if i_sp < 0 or i_put < 0 or i_sp > i_put:
        p.append('cpR6Submit does not wait for space before it writes the ring')
    if i_nw < 0 or not (i_rb < i_nw < i_w):
        p.append('cpR6Submit does not return after the WPTR read-back and before the waits when noWait is set')
    if 'c->inflight = 0;' not in sub[i_w:]:
        p.append('a drained synchronous submission does not clear inflight')
    ws = re.sub(r'\s+', ' ', fn.get('cpWaitSpace', ''))
    if 'room = (cur - c->wptr - 1UL) & C_RPTR_MASK;' not in ws or 'if (room >= len) {' not in ws:
        p.append('the space is not the reference\'s: (rptr - wptr - 1) & mask >= len')
    if 'IOGetTimestamp(&t0); turns = 0; w->resets++;' not in ws:
        p.append('the space wait does not restart its clock when rptr moves (radeon_wait_ring)')
    ld = re.sub(r'\s+', ' ', fn.get('cpLatchDump', ''))
    g, k = ld.find('if ((((c->rbRptr & C_RPTR_MASK) - c->wptr - 1UL) & C_RPTR_MASK) < 16UL) {'), ld.find('rdnMmioWrite32(base, C_CP_RB_WPTR, kt);')
    if g < 0 or k < 0 or g > k:
        p.append('the kick is not guarded by sixteen free ring words')
    run = re.sub(r'\s+', ' ', fn.get('osrdn_cp_run', ''))
    if 'c->noWait = 0;' not in run:
        p.append('an operation does not start synchronous (noWait cleared at osrdn_cp_run)')
    rt = re.sub(r'\s+', ' ', fn.get('cpRetire', ''))
    order = ('cpWait(base, W_RPTR, c->wptr, C_RPTR_US, &c->wRptr)', 'cpWaitRetry(base, W_IDLE, 0, C_IDLE_US, C_IDLE_RETRY, &c->wIdle)',
             'rdnMmioWrite32(base, C_RB3D_DSTCACHE_CTLSTAT, v | C_DC_FLUSH_ALL);', 'cpWait(base, W_DC, 0, C_DC_US, &c->wDc)', 'c->inflight = 0;')
    at = [rt.find(o) for o in order]
    if -1 in at or at != sorted(at):
        p.append('cpRetire is not ring, idle (re-asked), pixel cache, then inflight = 0')
    r['g52-async'] = p

    # ---- REL1 B7 (docs/REL1_PACKAGING_PLAN.md 16): the first client's open brings the CP up,
    # with the six ops the privileged tool sent, in its order, only from CP_ST_NONE, only with
    # the keys on and the mode written, and stopping at the first op that does not run.
    p = []
    disp = src['OSRDNDisplay.m']
    m = re.search(r'- \(void\)r7bAutoStart\n\{(.*?)\n\}\n', disp, re.S)
    if not m:
        p.append('r7bAutoStart is missing')
    else:
        a = re.sub(r'\s+', ' ', m.group(1))
        if ('static const int ops[6] = { CP_OP_RECORD, CP_OP_REC3D, CP_OP_LOAD, '
                'CP_OP_MAP, CP_OP_RESET, CP_OP_START };') not in a:
            p.append('the six ops are not RECORD REC3D LOAD MAP RESET START, in that order')
        i_try, i_loop = a.find('rdnAutoTries++;'), a.find('for (k = 0; k < 6; k++)')
        for g in ('rdnCp.state != CP_ST_NONE', '!rdnCp.keyOn', '!rdnCp.key3d', '!rdnMode.modeWritten',
                  '!rdnMode.snapshotValid', '!rdnState.recordEnabled', '!mmioMapped'):
            at = a.find(g)
            if at < 0 or i_try < 0 or at > i_try:
                p.append('the guard %s is missing or comes after the attempt is counted' % g)
        if i_loop < 0 or i_try > i_loop:
            p.append('the attempt is not counted before the ops run')
        if ('live = osrdn_mode_cp(&rdnMode, mmioBase, &rdnCp, rdnEngine.latched, ops[k], '
                '0UL, 0UL, &rdnAutoCopy, 0); if (live != CP_RC_RAN) break;') not in a:
            p.append('an op does not go through osrdn_mode_cp with quiet 0, or the chain does not stop at the first failure')
    o = re.search(r'\nrdnDevOpen\(int dev, int flag, int devtype\)\n\{(.*?)\n\}\n', disp, re.S)
    ob = re.sub(r'\s+', ' ', o.group(1)) if o else ''
    h, c, e = ob.find('rdnR7bHeld = 1;'), ob.find('[rdnR7bInstance r7bAutoStart];'), ob.find('return ENXIO;')
    if c < 0 or h < 0 or e < 0 or not (e < h < c):
        p.append('rdnDevOpen does not call r7bAutoStart after the open is accepted (after the latch is taken)')
    r['rel1-autostart'] = p
    return r


CPM = 'osrdn_cp.m'
MLG = 'osrdn_modelog.m'
MUTATIONS = [
    # REL1 B7 (docs/REL1_PACKAGING_PLAN.md 16)
    ('OSRDNDisplay.m', 'REL1 B7: MAP before LOAD',
     'CP_OP_LOAD,\n                                CP_OP_MAP,', 'CP_OP_MAP,\n                                CP_OP_LOAD,', ['rel1-autostart']),
    ('OSRDNDisplay.m', 'REL1 B7: the 3D key is not asked',
     '!rdnCp.keyOn || !rdnCp.key3d ||', '!rdnCp.keyOn ||', ['rel1-autostart']),
    ('OSRDNDisplay.m', 'REL1 B7: the chain goes on past a failure',
     '        if (live != CP_RC_RAN)\n            break;\n', '', ['rel1-autostart']),
    ('OSRDNDisplay.m', 'REL1 B7: open no longer brings the CP up',
     '    if (rdnR7bInstance != nil)\n        [rdnR7bInstance r7bAutoStart];\n', '', ['rel1-autostart']),
    # G5-2 (docs/G5_2_ASYNC_SUBMIT_PLAN.md 2)
    (CPM, 'G5-2: cpAsubmit drops a prefix register',
     '    w[n++] = C_P0(C_PP_TAM_DEBUG3);         w[n++] = C_PP_TAM_DEBUG3_LRU;\n    w[n++] = C_P0(C_SCRATCH_REG0);          w[n++] = seed;\n    c->zstage = 1;\n    c->noWait = 1;',
     '    w[n++] = C_P0(C_SCRATCH_REG0);          w[n++] = seed;\n    c->zstage = 1;\n    c->noWait = 1;', ['g52-async']),
    (CPM, 'G5-2: cpAsubmit waits for the card after all',
     '    c->asubmits++;\n', '    (void)cpWait(base, W_IDLE, 0, C_IDLE_US, &c->wIdle);\n    c->asubmits++;\n', ['g52-async']),
    (CPM, 'G5-2: noWait outlives the second write',
     '    rc = cpR6Submit(c, base, w, n);\n    c->noWait = 0;\n    if (rc != CP_RC_RAN)\n        return rc;\n    c->asubmits++;',
     '    rc = cpR6Submit(c, base, w, n);\n    if (rc != CP_RC_RAN)\n        return rc;\n    c->asubmits++;', ['g52-async']),
    (CPM, 'G5-2: cpR6Submit writes without waiting for space',
     '    if (!cpWaitSpace(c, base, len))\n        return cpFail(c, base);\n', '', ['g52-async', 'm3j-recover']),
    (CPM, 'G5-2: the accepted return comes before the doorbell is read back',
     '    /* G5-2: accepted.  The next ring contact queues behind it; RETIRE waits for it */\n    if (c->noWait)\n        return CP_RC_RAN;\n',
     '', ['g52-async']),
    (CPM, 'G5-2: the space forgets the reserved word',
     'room = (cur - c->wptr - 1UL) & C_RPTR_MASK;', 'room = (cur - c->wptr) & C_RPTR_MASK;', ['g52-async']),
    (CPM, 'G5-2: the kick writes whatever is free',
     'if ((((c->rbRptr & C_RPTR_MASK) - c->wptr - 1UL) & C_RPTR_MASK) < 16UL) {', 'if (0) {', ['g52-async']),
    (CPM, 'G5-2: an operation inherits noWait',
     '    c->noWait = 0;              /* G5-2: ... and synchronous', '    /* G5-2: ... and synchronous', ['g52-async']),
    (CPM, 'G5-2: RETIRE skips the pixel cache',
     '    rdnMmioWrite32(base, C_RB3D_DSTCACHE_CTLSTAT, v | C_DC_FLUSH_ALL);\n    if (!cpWait(base, W_DC, 0, C_DC_US, &c->wDc))\n        return cpLatch(c, base);\n    IOGetTimestamp(&t1);',
     '    IOGetTimestamp(&t1);', ['g52-async']),
    # G4-4 K7
    (CPM, 'K7: the draw is no longer judged where it stands',
     '        /* G4-4 K7: this draw reads and writes the surfaces as they are NOW */\n        if (!cpR7SurfacesOk(c, coff, cpitch, zoff, zpitch, wh, haveWH, toff, tfmt, tfil, haveT, haveTF))\n            return CP_R7_WHY_SURFACE;\n',
     '', ['g44-k7-per-draw']),
    (CPM, 'K7: the helper forgets the clip',
     '    if (!haveWH)\n        return 0;\n', '', ['g44-k7-per-draw']),
    # G4-3 K1
    ('osrdn_cp.h', 'K1: the retry count drifts from xorg', '#define CP_IDLE_RETRY           16UL', '#define CP_IDLE_RETRY           1UL',
     ['g43-k1-wait']),
    (CPM, 'K1: the submit asks idle once again',
     '    if (!cpWaitRetry(base, W_IDLE, 0, C_IDLE_US, C_IDLE_RETRY, &c->wIdle))     /* G4-3 K1 */',
     '    if (!cpWait(base, W_IDLE, 0, C_IDLE_US, &c->wIdle))', ['g43-k1-wait']),
    (CPM, 'K1: the rptr wait stops restarting on progress',
     '                IOGetTimestamp(&t0);\n                turns = 0;\n                w->resets++;\n', '', ['g43-k1-wait']),
    # M3i
    (CPM, 'M3i: the latch no longer dumps the CSQ fifo',
     '        rdnMmioWrite32(base, C_CP_CSQ_ADDR, k << 2);\n        c->fifo[k] = rdnMmioRead32(base, C_CP_CSQ_DATA);\n',
     '        c->fifo[k] = 0UL;\n', ['m3i-latch-dump']),
    (CPM, 'M3i: the latch dump writes the CSQ control',
     '    c->latchRead = 1;\n',
     '    rdnMmioWrite32(base, C_CP_CSQ_CNTL, 0UL);\n    c->latchRead = 1;\n', ['m3i-latch-dump']),
    (CPM, 'M3i: the kick is gone',
     '        (void)cpWait(base, W_RPTR, kt, C_KICK_US, &c->wKick);\n', '', ['m3i-latch-dump']),
    (CPM, 'M3i: a lost doorbell is not caught (cpR6Submit)',
     '    /* M3i: did the doorbell take? (docs/M3I_PLAN.md 3 D2); M3j: a wait that runs out recovers */\n    c->wptrRead = rdnMmioRead32(base, C_CP_RB_WPTR) & C_RPTR_MASK;\n    if (c->wptrRead != target) {\n        (void)cpRefuse(c, CP_WHY_WPTR, c->wptrRead);\n        return cpFail(c, base);\n    }\n',
     '', ['m3i-latch-dump', 'm3j-recover']),
    # G3
    (CPM, 'G3: cpPresent runs the client verifier over its own words',
     '    if (n != (unsigned long)C_PRESENT_WORDS) {\n        c->failed = 1;\n        return cpRefused(c, CP_WHY_WORDS, n);\n    }\n    rc = cpR6Submit(c, base, wd, n);\n',
     '    if (n != (unsigned long)C_PRESENT_WORDS) {\n        c->failed = 1;\n        return cpRefused(c, CP_WHY_WORDS, n);\n    }\n    c->r7Why = cpR7Verify(c, wd, n, 0UL, 0UL);\n    rc = cpR6Submit(c, base, wd, n);\n', ['g3-present']),
    # G3b
    (CPM, 'G3b: cpClear runs the client verifier over its own words',
     '    if (n > (unsigned long)C_CLEAR_WORDS) {\n        c->failed = 1;\n        return cpRefused(c, CP_WHY_WORDS, n);\n    }\n    rc = cpR6Submit(c, base, wd, n);\n',
     '    if (n > (unsigned long)C_CLEAR_WORDS) {\n        c->failed = 1;\n        return cpRefused(c, CP_WHY_WORDS, n);\n    }\n    c->r7Why = cpR7Verify(c, wd, n, 0UL, 0UL);\n    rc = cpR6Submit(c, base, wd, n);\n', ['g3b-clear']),
    (CPM, 'G3b: the GMC of the fill drifts from the reference bits',
     '#define C_CLEAR_GMC             0x10f036d2UL', '#define C_CLEAR_GMC             0x10f036d0UL', ['g3b-clear']),
    (CPM, 'G3b: the depth state is not the precedent\'s word for word',
     '        for (k = 0; k < 26UL; k++)                  /* WAIT_UNTIL 2D|HOST and the twelve state pairs */\n            wd[n++] = cpR6State[k];\n',
     '        for (k = 0; k < 26UL; k++)                  /* WAIT_UNTIL 2D|HOST and the twelve state pairs */\n            wd[n++] = (k == 9UL) ? 0x40007070UL : cpR6State[k];\n', ['g3b-clear']),
    (CPM, 'G3d: the fill goes out without DP_CNTL',
     "        wd[n++] = C_P0N(C_DP_CNTL, 0);              wd[n++] = C_DP_CNTL_L2R_T2B;\n", '', ['g3b-clear']),
    (CPM, 'G3d: DST_HEIGHT_WIDTH packed w << 16 | h',
     '(b->h << 16) | b->w', '(b->w << 16) | b->h', ['g3b-clear']),
    (CPM, 'G3c: the clear keeps the precedent 24-bit ZSTENCILCNTL (boot 5)',
     "        wd[n - 26UL + 9UL] = C_CLEAR_ZSTENCIL;      /* G3c: the client's 16-bit format, not the precedent's 24-bit */\n", '', ['g3b-clear']),
    (CPM, 'G3c: C_CLEAR_ZSTENCIL is the 24-bit word',
     '#define C_CLEAR_ZSTENCIL        0x42227070UL', '#define C_CLEAR_ZSTENCIL        0x42227072UL', ['g3b-clear']),
    ('OSRDNDisplay.m', 'G3b: the submit line speaks on the ordinary path again',
     '    if (!quiet || live != CP_RC_RAN)\n        IOLog("RDN-R7B submit boot=%08x', '    if (1)\n        IOLog("RDN-R7B submit boot=%08x', ['g3b-clear']),
    (CPM, 'REL2: the present blit leaves the scissor to whoever wrote it last',
     '    wd[n++] = C_P0N(C_DEFAULT_SC_BOTTOM_RIGHT, 0); wd[n++] = C_SC_MAX;              /* REL2 */\n', '', ['g3-present']),
    (CPM, 'REL2: the present blit leaves the write mask to whoever wrote it last',
     '    wd[n++] = C_P0N(C_DP_WRITE_MASK, 0);        wd[n++] = 0xffffffffUL;          /* REL2 */\n', '', ['g3-present']),
    (CPM, 'REL2: the present blit leaves the direction to whoever wrote it last',
     '    wd[n++] = C_P0N(C_DP_CNTL, 0);              wd[n++] = C_DP_CNTL_L2R_T2B;     /* REL2 */\n', '', ['g3-present']),
    (CPM, 'G3: the GMC word drifts from the reference bits',
     '#define C_PRESENT_GMC           0x52cc36f3UL', '#define C_PRESENT_GMC           0x52cc36f2UL', ['g3-present']),
    (CPM, 'G3: the source origin alignment gate is gone',
     '    if (b->srcOrg >= winBytes || (b->srcOrg & 1023UL) != 0UL)', '    if (b->srcOrg >= winBytes)', ['g3-present']),
    # M3j
    (CPM, 'M3j: the reset path of the recovery is gone',
     '        if (cpResetPulse(c, base) == CP_RC_RAN) {', '        if (0) {', ['m3j-recover']),
    (CPM, 'M3j: the read pointer is not forced before the restart',
     '            rdnMmioWrite32(base, C_CP_RB_RPTR_WR, 0UL);\n', '', ['m3j-recover']),
    (CPM, 'M3j: a recovered submission is reported as drawn',
     '        c->recovers++;\n        return CP_RC_RECOVERED;', '        c->recovers++;\n        return CP_RC_RAN;', ['m3j-recover']),
    (CPM, 'M3j: the recovery touches the GART',
     '            c->wptr = 0;\n            c->resetDone = 1;', '            rdnMmioWrite32(base, C_AIC_CNTL, 0UL);\n            c->wptr = 0;\n            c->resetDone = 1;', ['m3j-recover']),
    # M3f
    (CPM, 'M3f: the fill to the ring end comes back',
     '    len = (n + 15UL) & ~15UL;\n',
     '    len = (n + 15UL) & ~15UL;\n    if (len > CP_RING_WORDS - p) { for (k = p; k < CP_RING_WORDS; k++) cpPut(c, k, CP_PACKET2); p = 0; }\n',
     ['m3f-wrap-like-bsd']),
    (CPM, 'M3f: the words skip the mask (written past the ring)',
     '        cpPut(c, p + k, (k < n) ? w[k] : CP_PACKET2);',
     '        cpRing(c)[p + k] = (k < n) ? w[k] : CP_PACKET2;',
     ['m3f-wrap-like-bsd']),
    # M3e
    ('OSRDNDisplay.m', 'M3e: every failure overwrites the kept copy',
     'live != CP_RC_REFUSED && rdnCpKeptSub == 0UL) {', 'live != CP_RC_REFUSED) {',
     ['m3e-kept-latch']),
    ('OSRDNDisplay.m', 'M3e: the kept copy is never printed',
     '            osrdn_cp_lines(&rdnCpKept, rdnState.nonce, rdnCpKeptRc);\n', '',
     ['m3e-kept-latch']),
    ('OSRDNDisplay.m', 'M3e/M3j: the kept copy is printed on any RECORD, whatever came back',
     '                   (live == CP_RC_RAN || (live == CP_RC_REFUSED && rdnCpCopy.why == CP_WHY_LATCHED)));',
     '                   1);', ['m3e-kept-latch']),
    ('OSRDNDisplay.m', 'M3j: the RECORD that re-prints the kept copy prints its own lines too',
     '        else if (!keptNow)\n            osrdn_cp_lines(&rdnCpCopy, rdnState.nonce, live);',
     '        else\n            osrdn_cp_lines(&rdnCpCopy, rdnState.nonce, live);', ['m3e-kept-latch']),
    (CPM, 'M3e: RECORD on a real latch reads the card',
     '    else if (op == CP_OP_RECORD && c->latched && !c->latchInjected)\n        (void)cpRefuse(c, CP_WHY_LATCHED, 0);   /* a real latch: nothing more is read (R5d 7) */\n',
     '', ['m3e-kept-latch']),
    # M3c
    ('OSRDNDisplay.m', 'M3c: a failure on the card is swallowed when quiet again',
     '        if (!quiet || (live != CP_RC_RAN && live != CP_RC_REFUSED))\n',
     '        if (!quiet)\n', ['m3c-failures-speak']),
    ('OSRDNDisplay.m', 'M3c: a quiet REFUSED leaves no line',
     '        else if (live == CP_RC_REFUSED)\n            osrdn_cp_head(&rdnCpCopy, rdnState.nonce, live);\n',
     '', ['m3c-failures-speak']),
    ('OSRDNDisplay.m', 'M3c: the skip line is quiet-gated again',
     'rare. */\n        IOLog("RDN-R5 skip boot=%08x op=%u rc=%d\\n", (unsigned int)rdnState.nonce,',
     'rare. */\n        if (!quiet) IOLog("RDN-R5 skip boot=%08x op=%u rc=%d\\n", (unsigned int)rdnState.nonce,',
     ['m3c-failures-speak']),
    ('osrdn_modelog.m', 'M3c: osrdn_cp_lines prints the head line itself again',
     '    osrdn_cp_head(c, nonce, rc);\n    IOLog("RDN-R5 state',
     '    IOLog("RDN-R5 zz boot=%08x\\n", (unsigned int)nonce);\n    IOLog("RDN-R5 state',
     ['m3c-failures-speak']),
    (CPM, 'M2b: a wait field is left out of the per-operation clear',
     '    c->wFifo.turns = c->wIdle.turns = c->wRptr.turns = c->wIdle2.turns = c->wDc.turns = 0;\n',
     '', ['m2b-spin']),
    # ---- M2c: the instrument's knob, one mutation a clause
    (CPM, 'M2c: the instrument runs unconditionally again',
     '        if (c->timeOn) {\n            IOGetTimestamp(&tmark);\n            timing = 1;',
     '        if (1) {\n            IOGetTimestamp(&tmark);\n            timing = 1;',
     ['m2c-time']),
    (CPM, 'M2c: the first clock read is left outside the knob',
     '        if (c->timeOn) {\n            IOGetTimestamp(&tmark);\n',
     '        IOGetTimestamp(&tmark);\n        if (c->timeOn) {\n',
     ['m2c-time']),
    (CPM, 'M2c: the put total is committed before the waits can fail',
     '        qUs = cpElapsedUs(q0, q1);          /* M2c: held, not committed yet */',
     '        c->tAcc[CP_T_PUT] += cpElapsedUs(q0, q1);',
     ['m2c-time']),
    # ---- M2b: the spin, one mutation a clause
    (CPM, 'M2b: the spin is put BEFORE the time check, so it can skip it',
     '        turns++;\n        w->turns = turns;',
     '        for (k = 0; k < cpSpin; k++)\n            (void)cpCond(base, kind, need);\n        turns++;\n        w->turns = turns;',
     ['m2b-spin']),
    (CPM, 'M2b: the spin returns without refreshing the clock',
     '            if (cpCond(base, kind, need)) {\n                IOGetTimestamp(&t1);\n                w->us = cpElapsedUs(t0, t1);\n                return 1;\n            }',
     '            if (cpCond(base, kind, need))\n                return 1;',
     ['m2b-spin']),
    (CPM, 'M2b: the turn count is never recorded',
     '        w->turns = turns;\n', '', ['m2b-spin']),
    (CPM, 'M2b: the spin is unbounded',
     '    if (n > CP_SPIN_MAX)\n        return cpRefused(c, CP_WHY_SPIN, n);\n', '', ['m2b-spin']),
    (CPM, 'M2b: cpWait loses its time bound',
     '        if (w->us >= limitUs)\n            break;\n', '', ['m2b-spin']),
    # ---- M2a: the knob's blast radius, one mutation a clause
    (CPM, 'M2a: the knob leaks into the general fence',
     '    if (c->doWb)\n        osrdn_cpu_wbinvd();\n    osrdn_cpu_serialize();\n    (void)rdnMmioRead32(base, C_RBBM_STATUS);\n}',
     '    if (c->doWb)\n        osrdn_cpu_wbinvd();\n    osrdn_cpu_serialize();\n    (void)rdnMmioRead32(base, C_RBBM_STATUS);\n}\nstatic void cpUnused(osrdn_cp_state *c) { if (c->doWb) c->doWb = 1; }',
     ['m2a-nowb']),
    (CPM, 'M2a: the submission path goes back to the unconditional fence',
     '    cpSubmitFence(c, base);', '    cpFence(base);', ['m2a-nowb']),
    (CPM, 'M2a: the barrier is dropped along with the wbinvd',
     '    if (c->doWb)\n        osrdn_cpu_wbinvd();\n    osrdn_cpu_serialize();',
     '    if (c->doWb)\n        osrdn_cpu_wbinvd();',
     ['m2a-nowb']),
    (CPM, 'M2a: MAP stops flushing, where the reference DOES flush',
     '    if (!cpFillBlock(c))\n        return CP_RC_REFUSED;\n    cpFence(base);',
     '    if (!cpFillBlock(c))\n        return CP_RC_REFUSED;',
     ['m2a-nowb']),
    (CPM, 'M2a: the guard is inverted, so the knob turns the wbinvd ON',
     'if (c->doWb)\n        osrdn_cpu_wbinvd();', 'if (!c->doWb)\n        osrdn_cpu_wbinvd();',
     ['m2a-nowb']),
    # ---- M2e: the sense of the flag IS the design, so each way of losing it
    (CPM, 'M2e: the old name comes back, and with it the old sense',
     '    c->doWb = (on != 0UL) ? 0 : 1;',
     '    c->noWb = (on != 0UL) ? 1 : 0;',
     ['m2a-nowb']),
    (CPM, 'M2e: the setter stops inverting, so `nowb 1` would mean DO write back',
     '    c->doWb = (on != 0UL) ? 0 : 1;',
     '    c->doWb = (on != 0UL) ? 1 : 0;',
     ['m2a-nowb']),
    (CPM, 'M2e: an initialiser creeps into the reset, tying the default to the lifecycle',
     '    c->wptr = rp;\n    c->resetDone = 1;',
     '    c->wptr = rp;\n    c->doWb = 1;\n    c->resetDone = 1;',
     ['m2a-nowb']),
    ('osrdn_cp.h', 'M2e: the header goes back to saying the WBINVD default is OFF',
     ' * len != 0 turns the skip ON.\n',
     ' * len != 0 turns the skip ON.  The DEFAULT IS OFF\n',
     ['m2a-nowb']),
    (CPM, 'M2e: the .m comment goes back to saying the default is OFF',
     ' * Only the machine could answer, and it has:',
     ' * the default is OFF and c->noWb must be turned on.  Also:',
     ['m2a-nowb']),
    # ---- M1z: the new accumulators, one mutation a clause
    ('osrdn_cp.h', 'M1z: CP_T_STAGES goes back to the chain length',
     '#define CP_T_STAGES             (CP_T_CHAIN + 3)',
     '#define CP_T_STAGES             (CP_T_MARKS - 1)', ['m1x-stage-marks']),
    (CPM, 'M1z: cpTMark refuses at CP_T_STAGES again, so a chain mark can reach the extras',
     'if (mark < 0 || mark >= CP_T_CHAIN)', 'if (mark < 0 || mark >= CP_T_STAGES)',
     ['m1x-stage-marks']),
    (CPM, 'M1z: the commit loses its c->tOn guard',
     '    if (c->tOn) {\n        c->tAcc[CP_T_PUT] += qUs;',
     '    if (1) {\n        c->tAcc[CP_T_PUT] += qUs;', ['m1x-stage-marks']),
    (CPM, 'M1z: tOn is never cleared, so one operation times the next',
     '    c->tOn = 0;                 /* M1z: every operation starts untimed */\n', '',
     ['m1x-stage-marks']),
    (CPM, 'M1z: cpR6Submit times the fence with the CALLER chain clock',
     '    if (c->tOn)\n        IOGetTimestamp(&f0);\n    cpSubmitFence(c, base);\n    if (c->tOn) {\n        IOGetTimestamp(&f1);\n        fUs = cpElapsedUs(f0, f1);          /* M2c: held, not committed yet */\n    }',
     '    cpSubmitFence(c, base);\n    if (c->tOn)\n        cpTMark(c, &f0, CP_T_FENCE);',
     ['m1x-stage-marks']),
    (CPM, 'M1z: the wait total is added twice',
     '        c->tAcc[CP_T_WAIT] += c->wRptr.us + c->wIdle.us;',
     '        c->tAcc[CP_T_WAIT] += c->wRptr.us + c->wIdle.us;\n    if (c->tOn)\n        c->tAcc[CP_T_WAIT] += 0UL;',
     ['m1x-stage-marks']),
    # ---- M1z: the two halves of the operation-name defect
    (MLG, 'M1z: a name is left out of cpOpNames', '"rec3d", "zprep", "zclear", "plane", "quiet", "tdump"',
     '"rec3d", "zprep", "zclear", "plane", "quiet"', ['m1z-opnames']),
    (MLG, 'M1z: cpOpNames gets its size back, so the check beside it is an identity again',
     'static const char *const cpOpNames[] = {', 'static const char *const cpOpNames[CP_OP_LAST + 1] = {',
     ['m1z-opnames']),
    (MLG, 'M1z: two names swapped', '"rec3d", "zprep", "zclear", "plane", "quiet", "tdump"',
     '"rec3d", "zprep", "plane", "zclear", "quiet", "tdump"', ['m1z-opnames']),
    (CPM, 'an offset typo (CP_CSQ2_STAT 0x07f4)', '#define C_CP_CSQ2_STAT          0x07fc', '#define C_CP_CSQ2_STAT          0x07f4',
     ['r5-offsets']),
    (CPM, 'an offset typo (CP_RB_WPTR 0x0718)', '#define C_CP_RB_WPTR            0x0714', '#define C_CP_RB_WPTR            0x0718',
     ['r5-offsets']),
    (CPM, 'DIS_OUT_OF_PCI_GART_ACCESS on the wrong bit', '#define C_DIS_OUT_OF_GART       0x2UL',
     '#define C_DIS_OUT_OF_GART       0x4UL', ['r5-offsets']),
    ('osrdn_engine.m', 'the engine unit names CP_RB_BASE', '#define E_CONFIG_MEMSIZE        0x00f8',
     '#define E_CONFIG_MEMSIZE        0x00f8\n#define E_CP_RB_BASE            0x0700', ['r5-only-here']),
    (CPM, 'MAP rewrites MC_FB_LOCATION', '    rdnMmioWrite32(base, C_AGP_COMMAND, 0UL);\n\n',
     '    rdnMmioWrite32(base, C_AGP_COMMAND, 0UL);\n    rdnMmioWrite32(base, C_MC_FB_LOCATION, 0UL);\n\n', ['r5-forbidden']),
    (CPM, 'STOP soft-resets the engine', '    cpUnmap(c, base);\n    c->state = CP_ST_STOPPED;',
     '    rdnMmioWrite32(base, C_RBBM_SOFT_RESET, 0x7fUL);\n    cpUnmap(c, base);\n    c->state = CP_ST_STOPPED;',
     ['r5-forbidden']),
    (CPM, 'RECORD writes MCLK_CNTL', '        r[CP_REC_MCLK_CNTL] = (idx & C_PLL_WR_EN) ? 0xffffffffUL : cpMclkGet(base);',
     '        r[CP_REC_MCLK_CNTL] = (idx & C_PLL_WR_EN) ? 0xffffffffUL : cpMclkGet(base);\n        cpMclkPut(base, r[CP_REC_MCLK_CNTL]);',
     ['r5-forbidden']),
    (CPM, 'the CP unit logs', '    cpLatchDump(c, base);\n    if (c->inflight) {', '    cpLatchDump(c, base);\n    IOLog("latched\\n");\n    if (c->inflight) {', ['r5-quiet']),   # M3j: cpLatch's copy of the line
    (CPM, 'the latched STOP turns the GART off', '    rdnMmioWrite32(base, C_CP_CSQ_CNTL, 0UL);\n    c->postStatus',
     '    rdnMmioWrite32(base, C_CP_CSQ_CNTL, 0UL);\n    cpUnmap(c, base);\n    c->postStatus', ['r5-latched']),
    (CPM, 'START writes a scratch register', '    cpFence(base);\n    c->rptrBefore = rdnMmioRead32(base, C_CP_RB_RPTR) & C_RPTR_MASK;',
     '    cpFence(base);\n    rdnMmioWrite32(base, C_SCRATCH_REG0, 0UL);\n    c->rptrBefore = rdnMmioRead32(base, C_CP_RB_RPTR) & C_RPTR_MASK;',
     ['r5-scratch']),
    ('OSRDNDisplay.m', 'the block is freed on success too', '            rdnCp.blockOk = 1;\n',
     '            rdnCp.blockOk = 1;\n            IOFreeLow((void *)va, (int)CP_BLOCK_BYTES);\n', ['r5-block']),
    # R7b: the same three ways the batch page's discipline could slip
    ('OSRDNDisplay.m', 'the batch page is freed on success too',
     '            rdnR7bPhys = (unsigned long)p0 + o;\n',
     '            rdnR7bPhys = (unsigned long)p0 + o;\n            IOFreeLow((void *)va, R7B_ALLOC_BYTES);\n',
     ['r5-block']),
    ('OSRDNDisplay.m', 'the batch page is published on the failing path',
     '            IOFreeLow((void *)va, R7B_ALLOC_BYTES);     /* nothing has seen it yet */\n',
     '            IOFreeLow((void *)va, R7B_ALLOC_BYTES);\n            rdnR7bPhys = (unsigned long)p0 + o;\n',
     ['r5-block']),
    ('OSRDNDisplay.m', 'a low allocation is freed somewhere else in the file',
     '- (void)r7bCaps:(osrdn_r7b_caps *)cb\n{\n',
     '- (void)r7bCaps:(osrdn_r7b_caps *)cb\n{\n    IOFreeLow((void *)rdnR7bAlloc, R7B_ALLOC_BYTES);\n',
     ['r5-block']),
    (CPM, 'MAP tells the GPU before it flushes', '    if (!cpFillBlock(c))\n        return CP_RC_REFUSED;\n    cpFence(base);\n',
     '    if (!cpFillBlock(c))\n        return CP_RC_REFUSED;\n', ['r5-fence']),
    (CPM, 'START flushes after the CSQ is on', '    cpFence(base);\n    c->rptrBefore = rdnMmioRead32(base, C_CP_RB_RPTR) & C_RPTR_MASK;\n    rdnMmioWrite32(base, C_CP_CSQ_CNTL, CP_CSQ_ON);',
     '    c->rptrBefore = rdnMmioRead32(base, C_CP_RB_RPTR) & C_RPTR_MASK;\n    rdnMmioWrite32(base, C_CP_CSQ_CNTL, CP_CSQ_ON);\n    cpFence(base);',
     ['r5-fence']),
    ('Instance0.table', 'the key is off', '"RDN CP Test" = "Yes";', '"RDN CP Test" = "No";', ['r5-tables']),
    (CPM, 'byte writes are not counted', '#define rdnMmioWrite8(b, o, v)      (cpIoWr++, rdnMmioWrite8((b), (o), (v)))',
     '#define rdnMmioWrite8x(b, o, v)     (cpIoWr++, rdnMmioWrite8((b), (o), (v)))', ['r5d-count']),
    (CPM, 'reads counted as writes', '#define rdnMmioRead32(b, o)         (cpIoRd++, rdnMmioRead32((b), (o)))',
     '#define rdnMmioRead32(b, o)         (cpIoWr++, rdnMmioRead32((b), (o)))', ['r5d-count']),
    ('OSRDNDisplay.m', 'the inject key alone turns INJECT on', 'rdnCp.injectKey = rdnCp.keyOn && osrdn_name_is(key, "Yes");',
     'rdnCp.injectKey = osrdn_name_is(key, "Yes");', ['r5d-key']),
    (CPM, 'INJECT latches whatever the read-back said', '    if (inject && !c->failed) {', '    if (inject) {', ['r5d-key']),
    (CPM, 'ZCLEAR writes SURFACE_CNTL by MMIO', '        return cpRefused(c, CP_WHY_NOT_CAUGHT_UP, v);\n    if (!cpPoisonHolds(c, base))\n        return cpRefused(c, CP_WHY_POISON, c->reg5);\n    c->surfaceCntl = rdnMmioRead32(base, C_SURFACE_CNTL);\n',
     '        return cpRefused(c, CP_WHY_NOT_CAUGHT_UP, v);\n    if (!cpPoisonHolds(c, base))\n        return cpRefused(c, CP_WHY_POISON, c->reg5);\n    c->surfaceCntl = rdnMmioRead32(base, C_SURFACE_CNTL);\n    rdnMmioWrite32(base, C_SURFACE_CNTL, 0x100UL);\n',
     ['r5-forbidden']),
    (CPM, 'ZCLEAR writes SURFACE_CNTL through the ring', '    /* 1: the prefix, then its read-back -- nothing is drawn unless all of it holds */\n    n = 0;\n    w[n++] = C_P0(C_SE_TCL_STATE_FLUSH);    w[n++] = 0UL;\n',
     '    /* 1: the prefix, then its read-back -- nothing is drawn unless all of it holds */\n    n = 0;\n    w[n++] = C_P0(C_SE_TCL_STATE_FLUSH);    w[n++] = 0UL;\n    w[n++] = C_P0(C_SURFACE_CNTL);    w[n++] = 0UL;\n',
     ['r5-forbidden', 'r6-ring']),
    (CPM, 'ZCLEAR puts MC_FB_LOCATION on the ring', '    /* 1: the prefix, then its read-back -- nothing is drawn unless all of it holds */\n    n = 0;\n    w[n++] = C_P0(C_SE_TCL_STATE_FLUSH);    w[n++] = 0UL;\n',
     '    /* 1: the prefix, then its read-back -- nothing is drawn unless all of it holds */\n    n = 0;\n    w[n++] = C_P0(C_SE_TCL_STATE_FLUSH);    w[n++] = 0UL;\n    w[n++] = C_P0(C_MC_FB_LOCATION);    w[n++] = 0UL;\n',
     ['r6-ring']),
    (CPM, 'the unit names HOST_PATH_CNTL', '#define C_WAIT_UNTIL            0x1720\n',
     '#define C_WAIT_UNTIL            0x1720\n#define C_HOST_PATH_CNTL        0x0130\n', ['r5-forbidden']),
    (CPM, 'ZPREP writes a scratch register', '    for (i = 0; i < CP_R6_ALIAS_BYTES / 4UL; i++)\n        a[i] = cpR6Pattern(i);\n',
     '    for (i = 0; i < CP_R6_ALIAS_BYTES / 4UL; i++)\n        a[i] = cpR6Pattern(i);\n    rdnMmioWrite32(base, C_SCRATCH_REG0, 0UL);\n',
     ['r5-scratch']),
    (CPM, 'the clean STOP compares RPTR after the CSQ is off', '        c->wptrOff = rdnMmioRead32(base, C_CP_RB_WPTR);\n',
     '        c->wptrOff = rdnMmioRead32(base, C_CP_RB_WPTR);\n        if ((c->rptrOff & C_RPTR_MASK) != c->wptr)\n'
     '            return cpStopLatched(c, base);\n', ['r5-stop']),
    (CPM, 'F counts 12 words with a colour vertex', '      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030078UL, 0x78563412UL, 0UL, 0UL, 0UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },\n    { 5, 3, 37, 21, 0x40a00000UL, 0x40400000UL, 0x42140000UL, 0x41a80000UL, 0x3f800000UL, 2UL,     /* G: F, order bit off */',
     '      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00c3500UL, 0x00030078UL, 0x78563412UL, 0UL, 0UL, 0UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },\n    { 5, 3, 37, 21, 0x40a00000UL, 0x40400000UL, 0x42140000UL, 0x41a80000UL, 0x3f800000UL, 2UL,     /* G: F, order bit off */',
     ['r6c-cases']),
    (CPM, 'A turns the pixel pipe on without colour', '      0UL, 0UL, 3UL, 0UL, 0xc00c3500UL, 0x00030038UL, 0UL, 0UL, 0UL, 0UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },\n    { 5, 3, 37, 21, 0x40a00000UL, 0x40400000UL, 0x42140000UL, 0x41a80000UL, 0x3f000000UL, 0UL,     /* B: z 0.5 */',
     '      0x1000UL, 0UL, 3UL, 0UL, 0xc00c3500UL, 0x00030038UL, 0UL, 0UL, 0UL, 0UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },\n    { 5, 3, 37, 21, 0x40a00000UL, 0x40400000UL, 0x42140000UL, 0x41a80000UL, 0x3f000000UL, 0UL,     /* B: z 0.5 */',
     ['r6c-cases']),
    (CPM, 'a blend register offset typo', '#define C_PP_TXABLEND_0         0x2f08', '#define C_PP_TXABLEND_0         0x2f10', ['r6c-cases']),
    ('osrdn_cp.h', 'a case added without its row', '#define CP_R6_CASES             171', '#define CP_R6_CASES             172', ['r6c-cases']),
    (CPM, 'S1 reads only its R plane', '22UL, 0UL, 0UL, 0x48005adeUL, 0xcUL,', '22UL, 0UL, 0UL, 0x48005adeUL, 0x4UL,', ['r6c-cases']),
    (CPM, 'G1 keeps flat shading', '19UL, 0UL, 0UL, 0x48005adeUL,', '19UL, 0UL, 0UL, 0x480055deUL,', ['r6c-cases']),
    (CPM, 'a flat case turns Gouraud on', ', 1UL, 0x78123456UL, 0x78123456UL, 0x480055deUL,', ', 1UL, 0x78123456UL, 0x78123456UL, 0x48005adeUL,', ['r6c-cases']),
    (CPM, 'the triangle guard accepts 7 vertices', '        if (tr->nv == 0UL || tr->nv > 6UL || tr->nv % 3UL != 0UL)',
     '        if (tr->nv == 0UL || tr->nv > 7UL)', ['r6c-cases']),
    (CPM, 'a draw header one word too long', '0xc00f3500UL, 0x00030074UL, 0UL, 1UL,',
     '0xc0103500UL, 0x00030074UL, 0UL, 1UL,', ['r6c-cases']),
    (CPM, 'a triangle table row with 4 vertices', 'cpR6Tris[CP_R6_TRIS] = {\n    { 3UL, {',
     'cpR6Tris[CP_R6_TRIS] = {\n    { 4UL, {', ['r6c-cases']),
    (CPM, 'T3 is drawn as a RECT_LIST', '0xc01e3500UL, 0x00060074UL, 0UL, 3UL,', '0xc01e3500UL, 0x00060078UL, 0UL, 3UL,', ['r6c-cases']),
    (CPM, 'T7 names its middle vertex as code 2', '0x00030074UL, 0UL, 16UL, 0x78123456UL, 0x3c9abcdeUL',
     '0x00030074UL, 0UL, 16UL, 0x78123456UL, 0x44112233UL', ['r6c-cases']),
    # M1m added `dw` to this declaration; the anchor follows the source rather
    # than pinning a list that grows every rung
    # M1o
    (CPM, 'the coverage scan runs even when quiet',
     'if (drawn && !c->subQuiet) {', 'if (drawn) {', ['m1o-quiet-skips-analysis']),
    (CPM, 'a quiet submission touches neither surface',
     '            c->qTouch[0] = ((volatile unsigned long *)c->alias)[cpR6ColorOff(cs) / 4UL];\n'
     '            c->qTouch[1] = ((volatile unsigned long *)c->alias)[cpR6DepthOff(cs) / 4UL];\n',
     '', ['m1o-quiet-skips-analysis']),
    (CPM, 'digestWords still claims the full width when quiet',
     'c->digestWords = c->subQuiet ? 0UL : dw;', 'c->digestWords = dw;',
     ['m1o-quiet-skips-analysis']),
    # M1n
    # M1x: the stage marks
    (CPM, 'a stage mark is out of order',
     "        cpTMark(c, &tmark, 5);              /* M1x: stage 2's ring submit */",
     "        cpTMark(c, &tmark, 6);              /* M1x: stage 2's ring submit */",
     ['m1x-stage-marks']),
    (CPM, 'a stage mark loses its `timing` guard',
     "    if (timing)\n        cpTMark(c, &tmark, 0);",
     "    if (1)\n        cpTMark(c, &tmark, 0);",
     ['m1x-stage-marks']),
    (CPM, 'the operation count is never stepped',
     '        c->tAccN++;', '        c->tAccN += 0;',
     ['m1x-stage-marks']),
    ('rdnr5cp.m', 'M2a: the tool names an operation differently from the driver',
     '"rec3d", "zprep", "zclear", "plane", "quiet", "tdump"',
     '"rec3d", "zprep", "zclear", "plane", "quiet", "tdmp"', ['m1z-opnames']),
    ('rdnr5cp.m', 'M2a: the tool table gets a size, so its own check is an identity',
     'static const char *const opNames[] = {', 'static const char *const opNames[OP_COUNT] = {',
     ['m1z-opnames']),
    ('rdnr5cp.m', 'M2a: OP_COUNT drifts from the table',
     '#define OP_COUNT        24', '#define OP_COUNT        23', ['m1z-opnames']),
    ('osrdn_cp.h', 'CP_OP_LAST is not the highest op (the name table would disagree)',
     '#define CP_OP_LAST              23', '#define CP_OP_LAST              24', ['m1n-quiet']),
    # and the other direction: an op above CP_OP_LAST is unreachable
    ('osrdn_cp.h', 'an op is defined above CP_OP_LAST',
     '#define CP_OP_RETIRE            23', '#define CP_OP_RETIRE            24', ['m1n-quiet']),
    (CPM, 'the dispatch goes back to a wildcard INJECT',
     '    else if (op == CP_OP_INJECT) {', '    else if (0) {', ['m1n-quiet']),
    (CPM, 'M2g: the loud lease never ends',
     '        c->loudBudget--;\n', '', ['m1n-quiet']),
    (CPM, 'M2g: quiet_take reads the old flag again',
     '    if (c->loudBudget != 0UL) {', '    if (c->loudBudget != 0UL || !c->quiet) {', ['m1n-quiet']),
    (CPM, 'M2g: quiet no longer cancels loud',
     '    c->loudBudget = 0UL;                /* M2g: quiet of any N cancels loud (exclusive) */\n', '',
     ['m1n-quiet']),
    (CPM, 'M2g: loud no longer cancels quiet',
     '    c->quietBudget = 0UL;\n    return CP_RC_RAN;\n}\n', '    return CP_RC_RAN;\n}\n', ['m1n-quiet']),
    ('osrdn_mode.m', 'M2g: subQuiet is set before the claim',
     '        cp->subQuiet = quiet;\n', '', ['m2g-subquiet-under-claim']),
    ('osrdn_mode.m', 'M2g: subQuiet is set by the caller side, BEFORE the claim is taken',
     '    if (!modeClaim(mode))\n        return CP_RC_BUSY;\n',
     '    cp->subQuiet = quiet;\n    if (!modeClaim(mode))\n        return CP_RC_BUSY;\n',
     ['m2g-subquiet-under-claim']),
    ('osrdn_mode.m', 'M2g: subQuiet is cleared AFTER the claim is released',
     '    *copy = *cp;                        /* while the claim is still ours */\n    modeFinish(mode, base);\n    return rc;\n}',
     '    *copy = *cp;                        /* while the claim is still ours */\n    modeFinish(mode, base);\n    cp->subQuiet = 0;\n    return rc;\n}',
     ['m2g-subquiet-under-claim']),
    ('osrdn_mode.m', 'M2g: subQuiet is never cleared',
     '        cp->subQuiet = 0;\n', '', ['m2g-subquiet-under-claim']),
    ('OSRDNDisplay.m', 'M2g: the diagnostic path runs quiet',
     '                             0);         /* M2g: a diagnostic always computes and speaks */',
     '                             1);', ['m2g-subquiet-under-claim']),
    ('OSRDNDisplay.m', 'M2g: a failed staging is swallowed again',
     '    if (!quiet || !staged)', '    if (!quiet)', ['m2g-subquiet-under-claim']),
    ('osrdn_modelog.m', 'the op name table loses its last entry',
     '"plane", "quiet"', '"plane"', ['m1n-quiet']),
    ('OSRDNDisplay.m', 'the client path reads the quiet flag twice',
     '    quiet = osrdn_cp_quiet_take(&rdnCp);',
     '    quiet = osrdn_cp_quiet_take(&rdnCp);\n    quiet = osrdn_cp_quiet_take(&rdnCp);',
     ['m1n-quiet']),
    # M1m
    ('osrdn_cp.h', 'the client digest is as wide as the R6 one',
     '#define CP_R7_DIGEST_WORDS      64UL',
     '#define CP_R7_DIGEST_WORDS      4096UL', ['m1m-digest-width']),
    ('osrdn_cp.h', 'the client digest is empty',
     '#define CP_R7_DIGEST_WORDS      64UL',
     '#define CP_R7_DIGEST_WORDS      0UL', ['m1m-digest-width']),
    (CPM, 'the width is not chosen by case',
     'dw = (zc == (unsigned long)CP_R7_CASE) ? CP_R7_DIGEST_WORDS : CP_R6_BUF_WORDS;',
     'dw = CP_R6_BUF_WORDS;', ['m1m-digest-width']),
    (CPM, 'a digest goes back to scanning the whole buffer',
     'cpR6Digest(c, cpR6ColorOff(cs) / 4UL, dw, &c->dColor[k]);',
     'cpR6Digest(c, cpR6ColorOff(cs) / 4UL, CP_R6_BUF_WORDS, &c->dColor[k]);',
     ['m1m-digest-width']),
    (CPM, 'the words back on the stack', 'unsigned long *w = cpR6Words, n, v, i, need, nvert, vw, st, dw;',
     'unsigned long w[96], n, v, i, need, nvert, vw, st, dw;', ['r6c-cases']),
    # R6f (docs/R6F_PLAN.md 3-2)
    ('osrdn_cp.h', 'CP_R6_WORDS below the biggest submission', '#define CP_R6_WORDS             4080',
     '#define CP_R6_WORDS             1240', ['r6c-cases']),
    ('osrdn_cp.h', 'CP_R6_WORDS leaves no room for the ring padding', '#define CP_R6_WORDS             4080',
     '#define CP_R6_WORDS             4090', ['r6c-cases']),
    (CPM, 'the length check leaves out the tail', '+ 4UL + 2UL + nvert * vw + 10UL;', '+ 4UL + 2UL + nvert * vw;', ['r6c-cases']),
    (CPM, 'K24a reads the 16-bit plane source', '0x480055deUL, 7UL, 0UL, 0UL, 0x42227072UL, 0UL, 1UL, 1UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL }',
     '0x480055deUL, 7UL, 0UL, 0UL, 0x42227072UL, 0UL, 1UL, 2UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL }', ['r6c-cases']),
    (CPM, 'I5_24 takes I6\'s z row', '0x42227072UL, 5UL, 0UL, 1UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL }', '0x42227072UL, 6UL, 0UL, 1UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL }', ['r6c-cases']),
    (CPM, 'an anchor in the table moves', '0x3f5a7f3eUL, 0x3cc076d0UL', '0x3f5a7f3eUL, 0x3cc076d1UL', ['r6c-cases']),
    (CPM, 'a cell corner moves', '    { 0x41200000UL, 0x41200000UL, 0x41500000UL, 0x41500000UL },',
     '    { 0x41200000UL, 0x41200000UL, 0x41500000UL, 0x41580000UL },', ['r6c-cases']),
    # R6g (docs/R6G_PLAN.md 2)
    (CPM, 'GL compares LEQUAL, not LESS', '0x42227010UL, 0UL, 0UL, 2UL, 0x1902UL, 2UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL }', '0x42227020UL, 0UL, 0UL, 2UL, 0x1902UL, 2UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL }', ['r6c-cases']),
    (CPM, 'GAW keeps the write bit', '0x2227070UL, 0UL, 0UL, 2UL, 0x1902UL, 10UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL }', '0x42227070UL, 0UL, 0UL, 2UL, 0x1902UL, 10UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL }', ['r6c-cases']),
    (CPM, 'GZE leaves Z_ENABLE on', '0x1802UL, 11UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL }', '0x1902UL, 11UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL }', ['r6c-cases']),
    (CPM, 'the prefill ramp of GN differs from the oracle', '{ 1UL, 0x3c00UL, 0x400UL, 0x200UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL }   /* GN */',
     '{ 1UL, 0x3c00UL, 0x400UL, 0x100UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL }   /* GN */', ['r6c-cases']),
    (CPM, 'the prefill read-back check is gone', '            if (got != (unsigned long)val)\n                c->pfBad++;',
     '            if (0)\n                c->pfBad++;', ['r6c-cases']),
    # R6h (docs/R6H_PLAN.md 2)
    # six later rows (R6i PA .. PF) carry the same texture: the comment keeps the anchor on XA's
    (CPM, 'XA asks for the wrap clamp', '{ 8UL, 8UL, 32UL, 0x11000000UL, 0x3346UL, 0x70007UL, 0UL, 0UL, 0UL, 0x3f800000UL, 0UL, 0UL, 0x3f800000UL, 0UL, 0UL }   /* XA */',
     '{ 8UL, 8UL, 32UL, 0UL, 0x3346UL, 0x70007UL, 0UL, 0UL, 0UL, 0x3f800000UL, 0UL, 0UL, 0x3f800000UL, 0UL, 0UL }   /* XA */', ['r6c-cases']),
    (CPM, 'XF keeps the 8x8 size field', '{ 4UL, 4UL, 16UL, 0x11000000UL, 0x2246UL', '{ 4UL, 4UL, 16UL, 0x11000000UL, 0x3346UL', ['r6c-cases']),
    (CPM, 'the texture read-back check is gone', '                if (al[(cpR6TexOff(cs) + vv * stride) / 4UL + u] != cpR6Texel(pat, u, vv))\n                    c->pfBad++;',
     '                if (0)\n                    c->pfBad++;', ['r6c-cases']),
    # R6i (docs/R6I_PLAN.md 2-1)
    (CPM, 'a W row differs from the oracle', '{ 0x3f800000UL, 0x3e000000UL, 0x3f000000UL }   /* WB */',
     '{ 0x3f800000UL, 0x3e000000UL, 0x3f800000UL }   /* WB */', ['r6c-cases']),
    (CPM, 'a W row carries a zero', '{ 0x3f800000UL, 0x3e800000UL, 0x3e800000UL }   /* WC */',
     '{ 0x3f800000UL, 0x3e800000UL, 0UL }   /* WC */', ['r6c-cases']),
    (CPM, 'PB loses its W row', '0x1902UL, 0UL, 9UL, 1UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },\n    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 10UL,     /* PC */',
     '0x1902UL, 0UL, 9UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },\n    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 10UL,     /* PC */', ['r6c-cases']),
    (CPM, 'LN is 8 wide and 2 high', '{ 2UL, 8UL, 32UL, 0x11000000UL, 0x3146UL, 0x70001UL',
     '{ 8UL, 2UL, 32UL, 0x11000000UL, 0x3146UL, 0x70001UL', ['r6c-cases']),
    (CPM, 'SE_VTE_CNTL is not patched', '        w[st + 17] = cs->vte;', '        w[st + 16] = cs->vte;', ['r6c-cases']),
    (CPM, 'the W bound check is gone', '    if (cs->widx > CP_R6_WROWS || (cs->widx != 0UL && (tr == 0 || tr->nv != 3UL)))',
     '    if (0)', ['r6c-cases']),
    (CPM, 'a flat case carries the 16-bit format', '      0UL, 0UL, 3UL, 0UL, 0xc00c3500UL, 0x00030038UL, 0UL, 0UL, 0UL, 0UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },\n    { 5, 3, 37, 21, 0x40a00000UL, 0x40400000UL, 0x42140000UL, 0x41a80000UL, 0x3f000000UL, 0UL,     /* B: z 0.5 */',
     '      0UL, 0UL, 3UL, 0UL, 0xc00c3500UL, 0x00030038UL, 0UL, 0UL, 0UL, 0UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227070UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },\n    { 5, 3, 37, 21, 0x40a00000UL, 0x40400000UL, 0x42140000UL, 0x41a80000UL, 0x3f000000UL, 0UL,     /* B: z 0.5 */',
     ['r6c-cases']),
    (CPM, 'the R7 allow-list gains a register the ladder never measured',
     '    0x2f08, 0x2f0c\n};', '    0x2f08, 0x2f0c, 0x1c30\n};', ['r7-verify']),
    (CPM, 'the R7 allow-list gains a reserved register', '    0x1c14, 0x1c20, 0x1c24,', '    0x1c14, 0x1720, 0x1c24,', ['r7-verify']),
    (CPM, 'a verifier rule becomes unreachable', '            return CP_R7_WHY_P0_REG;', '            return CP_R7_WHY_TRUNC;',
     ['r7-verify']),
    (CPM, 'a refused stream is not refused', '            return cpRefused(c, CP_WHY_R7, c->r7Why);',
     '            c->r7At = 0UL;', ['r7-verify']),
    (CPM, 'G5-2: the accepted path loses its refusal', '        return cpRefused(c, CP_WHY_R7, c->r7Why);\n    need = c->subWords + 2UL + 10UL;    /* our WAIT_UNTIL, its words, our tail -- as cpZclear counts */',
     '        c->r7At = 0UL;\n    need = c->subWords + 2UL + 10UL;    /* our WAIT_UNTIL, its words, our tail -- as cpZclear counts */', ['r7-verify']),
    (CPM, 'the coverage map reads the old colour place', 'unsigned long at = cpR6ColorOff(cs) / 4UL + (i >> 5) * CP_R6_PITCH + (i & 31UL), code;',
     'unsigned long at = CP_R6_COLOR_OFF / 4UL + (i >> 5) * CP_R6_PITCH + (i & 31UL), code;', ['r6m-surfaces']),
    (CPM, 'the post-draw texture check is gone', '            want = cpR6Pattern(cpR6TexOff(cs) / 4UL + i);',
     '            want = v;', ['r6m-surfaces']),
    (CPM, 'MA stops moving the colour surface', '19UL, 1UL, 0x8010UL, 0UL, 0UL },',
     '19UL, 1UL, 0UL, 0UL, 0UL },', ['r6c-cases']),
    (CPM, "a case's colour surface lands on its depth", '0x8010UL, 0x10000UL, 0x14020UL },',
     '0x10010UL, 0x10000UL, 0x14020UL },', ['r6m-surfaces']),
    (CPM, 'ZCLEAR puts TXCBLEND_1 on the ring', '        w[n++] = C_P0(C_PP_TXCBLEND_0);     w[n++] = pass;\n',
     '        w[n++] = C_P0(C_PP_TXCBLEND_0);     w[n++] = pass;\n        w[n++] = C_P0(C_PP_TXCBLEND_0 + 16);     w[n++] = 0UL;\n',
     ['r6-ring']),
]


def main():
    src = dict((f, open(os.path.join(d, f), encoding='utf-8', errors='replace').read()) for f, d in FILES.items())
    failures = 0
    print('  == rules on the real files ==')
    base = rules(src)
    for name in sorted(base):
        for why in base[name]:
            print('    FAIL %-15s %s' % (name, why))
        failures += len(base[name])
    if not failures:
        print('    ok   %d rules' % len(base))
    print('  == mutations (each caught by the rule it targets) ==')
    for path, label, old, new, want in MUTATIONS:
        text = src[path]
        if text.count(old) != 1:
            print('    FAIL %-52s anchor found %d times' % (label, text.count(old)))
            failures += 1
            continue
        got = rules(dict(src, **{path: text.replace(old, new)}))
        caught = sorted(n for n in got if got[n])
        ok = all(w in caught for w in want)
        print('    %-4s %-52s %s' % ('ok' if ok else 'FAIL', label, caught if ok else 'caught by %s, want %s' % (caught, want)))
        failures += 0 if ok else 1
    print('check_r5_src: %s' % ('PASS' if not failures else 'FAIL (%d)' % failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
