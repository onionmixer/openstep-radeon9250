#!/usr/bin/env python3
"""Run osrdn_cp.m against a fake CP behind a PCI GART (tools/r5/sim/world5.c),
then every mutation (docs/R5_PLAN.md 4, 7-2 B13, 9-1).

  sim_r5.py        the baseline must PASS and every mutation must FAIL, in this run

WHAT THIS PROVES: that the driver does what OUR MODEL of the CP expects -- the
model was written from the same references as the driver, so a rule both have
wrong passes here.  The hardware is judged on the machine only.
"""

import shutil
import atexit
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
TPROJ = os.path.join(PROJ, 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj')
CP = os.path.join(TPROJ, 'osrdn_cp.m')
SNAP = os.path.join(TPROJ, 'osrdn_snap.m')
WORLD = os.path.join(HERE, 'sim', 'world5.c')
INC = os.path.join(PROJ, 'tools', 'r2b', 'sim', 'include')
LIBC32 = '/usr/lib32/libc.so.6'
LD32 = '/lib/ld-linux.so.2'

MUTATIONS = [
    ('the microcode columns are written DATAL first',
     '        rdnMmioWrite32(base, C_CP_ME_RAM_DATAH, osrdnCpUcode[k][1]);\n        rdnMmioWrite32(base, C_CP_ME_RAM_DATAL, osrdnCpUcode[k][0]);',
     '        rdnMmioWrite32(base, C_CP_ME_RAM_DATAL, osrdnCpUcode[k][0]);\n        rdnMmioWrite32(base, C_CP_ME_RAM_DATAH, osrdnCpUcode[k][1]);'),
    ('LOAD does not wait for idle',
     '    if (c->state != CP_ST_NONE)\n        return cpRefused(c, CP_WHY_STATE, (unsigned long)c->state);\n    if (!cpIdleGate(c, base, 1))\n        return CP_RC_REFUSED;\n',
     '    if (c->state != CP_ST_NONE)\n        return cpRefused(c, CP_WHY_STATE, (unsigned long)c->state);\n'),
    ('RB_NO_UPDATE dropped (rptr writeback on)',
     'rdnMmioWrite32(base, C_CP_RB_CNTL, CP_RB_CNTL_VALUE);', 'rdnMmioWrite32(base, C_CP_RB_CNTL, CP_RB_CNTL_VALUE & ~0x08000000UL);'),
    ('SCRATCH_UMSK left on (scratch writeback)',
     'rdnMmioWrite32(base, C_SCRATCH_UMSK, 0UL);', 'rdnMmioWrite32(base, C_SCRATCH_UMSK, 7UL);'),
    ('a ring PTE strides 8 KiB (the host page) instead of 4 KiB',
     '        off = CP_RING_OFF + e * CP_PAGE;', '        off = CP_RING_OFF + e * 2UL * CP_PAGE;'),
    ('ring PTEs 2 and 3 swapped',
     '        off = CP_RING_OFF + e * CP_PAGE;', '        off = CP_RING_OFF + ((e == 2UL) ? 3UL : (e == 3UL) ? 2UL : e) * CP_PAGE;'),
    ('unused entries point at physical 0 (Linux leaves them 0)',
     '    else\n        off = CP_GUARD_OFF;\n    return (phys + off) & 0xfffff000UL;',
     '    else\n        return 0UL;\n    return (phys + off) & 0xfffff000UL;'),
    # M2a put a SECOND wbinvd+serialize pair in the file (cpSubmitFence), so this
    # anchor has to name which one: the general fence, the one the six non-submit
    # call sites use.  The submission one is deliberately skippable now.
    ('no cache flush before the GPU looks',
     'cpFence(vm_address_t base)\n{\n    osrdn_cpu_wbinvd();\n    osrdn_cpu_serialize();',
     'cpFence(vm_address_t base)\n{\n    osrdn_cpu_serialize();'),
    ('M2a/M2e: the submission fence flushes whatever the knob says',
     '    if (c->doWb)\n        osrdn_cpu_wbinvd();', '    osrdn_cpu_wbinvd();'),
    ('WPTR written unmasked at the wrap',
     '    target = (c->wptr + len) & C_RPTR_MASK;', '    target = c->wptr + len;'),
    # M2b put `w->turns = turns;` between the increment and the test, so the
    # anchor names all three lines now.  The mutation is the same one: take the
    # turn bound away and a frozen clock never ends the wait.
    ('a wait loses its turn bound (a frozen clock never ends it)',
     '        turns++;\n        w->turns = turns;\n        if (turns >= maxTurns)\n            break;\n',
     '        turns++;\n        w->turns = turns;\n'),
    ('a SUBMIT that never catches up does not latch',
     '    if (!cpWait(base, W_RPTR, target, C_RPTR_US, &c->wRptr))\n        return cpFail(c, base);\n    if (!cpWait(base, W_IDLE, 0, C_IDLE_US, &c->wIdle))\n        return cpFail(c, base);\n    cpReadBack(c, base);',
     '    if (!cpWait(base, W_RPTR, target, C_RPTR_US, &c->wRptr))\n        return CP_RC_PRE_TIMEOUT;\n    if (!cpWait(base, W_IDLE, 0, C_IDLE_US, &c->wIdle))\n        return cpFail(c, base);\n    cpReadBack(c, base);'),
    ('START that never catches up does not latch',
     '    if (!cpWait(base, W_RPTR, target, C_RPTR_US, &c->wRptr))\n        return cpLatch(c, base);            /* a START that does not run: nothing to recover into */\n',
     '    if (!cpWait(base, W_RPTR, target, C_RPTR_US, &c->wRptr))\n        return CP_RC_PRE_TIMEOUT;\n'),
    ('the latched stop also turns the GART off',
     '    rdnMmioWrite32(base, C_CP_CSQ_CNTL, 0UL);\n    c->postStatus = rdnMmioRead32(base, C_RBBM_STATUS);\n    return CP_RC_LATCHED;',
     '    rdnMmioWrite32(base, C_CP_CSQ_CNTL, 0UL);\n    cpUnmap(c, base);\n    c->postStatus = rdnMmioRead32(base, C_RBBM_STATUS);\n    return CP_RC_LATCHED;'),
    ('the clean stop turns the GART off before the CSQ',
     '        rdnMmioWrite32(base, C_CP_CSQ_CNTL, 0UL);\n        if (!cpWait(base, W_IDLE, 0, C_IDLE_US, &c->wIdle2)) {',
     '        cpUnmap(c, base);\n        rdnMmioWrite32(base, C_CP_CSQ_CNTL, 0UL);\n        if (!cpWait(base, W_IDLE, 0, C_IDLE_US, &c->wIdle2)) {'),
    ('the AGP aperture is not put back',
     '        rdnMmioWrite32(base, C_MC_AGP_LOCATION, c->agpLocation);\n', ''),
    ('MAP leaves the AGP aperture over the window (D3)',
     '    rdnMmioWrite32(base, C_MC_AGP_LOCATION, CP_AGP_OFF);\n', ''),
    ('MAP forgets DIS_OUT_OF_PCI_GART_ACCESS',
     '    rdnMmioWrite32(base, C_AIC_CNTL, v | C_DIS_OUT_OF_GART);\n', ''),
    ('the reset does not put MCLK_CNTL back',
     '    cpMclkPut(base, mclk);\n    rdnMmioWrite32(base, C_CLOCK_CNTL_INDEX, idx);', '    rdnMmioWrite32(base, C_CLOCK_CNTL_INDEX, idx);'),
    ('the reset does not put the PLL index back',
     '    cpMclkPut(base, mclk);\n    rdnMmioWrite32(base, C_CLOCK_CNTL_INDEX, idx);', '    cpMclkPut(base, mclk);'),
    ('the reset pulses other bits',
     '#define C_SOFT_RESET_BITS       0x0000007fUL', '#define C_SOFT_RESET_BITS       0x000000ffUL'),
    ('the reset does not re-check the MAP registers',
     '    if (!cpMapGate(c, base, CP_WHY_RESETGATE))\n        return CP_RC_POST;          /* still MAPPED, CSQ off: STOP unmaps cleanly */\n', ''),
    ('START without the reset (D4)',
     '    if (!c->resetDone)\n        return cpRefused(c, CP_WHY_NO_RESET, 0);\n', ''),
    ('a reused seed is allowed',
     '        return cpRefused(c, CP_WHY_LEN, len);\n    if (seed == 0UL || (c->seedUsed && seed == c->lastSeed))',
     '        return cpRefused(c, CP_WHY_LEN, len);\n    if (seed == 0UL)'),
    ('the length is not checked',
     '    if (len < 16UL || len > CP_RING_WORDS - 16UL || (len & 15UL) != 0UL)\n        return cpRefused(c, CP_WHY_LEN, len);\n', ''),
    ('the sentinels are not written',
     '    for (k = 0; k < 3; k++)\n        rdnMmioWrite32(base, C_SCRATCH_REG0 + 4 * k, c->sentinel[k]);\n', ''),
    ('NEGCTL writes WPTR',
     '    /* a wait that must run out: nothing was asked of the CP */\n',
     '    rdnMmioWrite32(base, C_CP_RB_WPTR, (c->wptr + 16UL) & C_RPTR_MASK);\n'),
    ('REG1 never straddles a boundary',
     '    if (b - 1UL >= p + 2UL && b + 1UL <= p + len - 3UL) {', '    if (0) {'),
    ('the poison is not checked before a SUBMIT',
     '    if (!cpPoisonHolds(c, base))\n        return cpRefused(c, CP_WHY_POISON, c->reg5);\n    c->lastSeed = seed;\n    c->seedUsed = 1;\n    for (k = 0; k < 3; k++) {',
     '    c->lastSeed = seed;\n    c->seedUsed = 1;\n    for (k = 0; k < 3; k++) {'),
    ('a failed SUBMIT does not stop the next',
     '    if (c->failed)\n        return cpRefused(c, CP_WHY_FAILED, 0);\n    if (len < 16UL', '    if (len < 16UL'),
    ('the ring shadow is not compared',
     '        if (r[i] != cpShadow[i])\n            bad++;', '        if (0)\n            bad++;'),
    # ---- M1y: cpCheckBlock's four region loops (docs/M1Y_PLAN.md 8).  Each one
    # moves a bound or an index that the single word loop could not get wrong,
    # because it asked cpBlockWord() instead.
    ('M1y: the canary is indexed by the ABSOLUTE word, not the region-relative one',
     '        if (b[CP_CANARY_OFF / 4UL + i] != C_CANARY_WORD(i))',
     '        if (b[CP_CANARY_OFF / 4UL + i] != C_CANARY_WORD(CP_CANARY_OFF / 4UL + i))'),
    ('M1y: the canary loop stops one word short',
     '    for (i = 0; i < (CP_BLOCK_BYTES - CP_CANARY_OFF) / 4UL; i++)',
     '    for (i = 0; i < (CP_BLOCK_BYTES - CP_CANARY_OFF) / 4UL - 1UL; i++)'),
    ('M1y: the spare is indexed by the ABSOLUTE word',
     '        if (b[CP_SPARE_OFF / 4UL + i] != C_SPARE_WORD(i))',
     '        if (b[CP_SPARE_OFF / 4UL + i] != C_SPARE_WORD(CP_SPARE_OFF / 4UL + i))'),
    ("M1y: the guard's two words are swapped",
     '        if (b[i] != ((i & 1UL) ? CP_PACKET2 : CP_GUARD_HEAD))',
     '        if (b[i] != ((i & 1UL) ? CP_GUARD_HEAD : CP_PACKET2))'),
    ('M1y: the table folds entry 4 into the repeated value',
     '    for (i = 5UL; i < CP_GUARD_OFF / 4UL; i++) {',
     '    for (i = 4UL; i < CP_GUARD_OFF / 4UL; i++) {'),
    ('M1y: the inlined ring-page arithmetic drifts from osrdn_cp_pte',
     '        if (v != ((c->phys + CP_RING_OFF + i * CP_PAGE) & 0xfffff000UL))',
     '        if (v != ((c->phys + CP_RING_OFF + i * 2UL * CP_PAGE) & 0xfffff000UL))'),
    ('M1y: the canary loop starts one word late (a clean block hides it)',
     '    for (i = 0; i < (CP_BLOCK_BYTES - CP_CANARY_OFF) / 4UL; i++)\n        if (b[CP_CANARY_OFF / 4UL + i] != C_CANARY_WORD(i))',
     '    for (i = 1UL; i < (CP_BLOCK_BYTES - CP_CANARY_OFF) / 4UL; i++)\n        if (b[CP_CANARY_OFF / 4UL + i] != C_CANARY_WORD(i))'),
    ('M1y: the table skips entry 5 (a clean block hides it)',
     '    for (i = 5UL; i < CP_GUARD_OFF / 4UL; i++) {',
     '    for (i = 6UL; i < CP_GUARD_OFF / 4UL; i++) {'),
    ('an engine latch does not stop the CP',
     '    else if (engineLatched)\n        (void)cpRefuse(c, CP_WHY_ENGINE, 0);\n', ''),
    ('quiesce does not stop a running CP',
     '    if (c->state == CP_ST_MAPPED || c->state == CP_ST_RUNNING)\n        (void)cpStop(c, base);',
     '    if (c->state == CP_ST_MAPPED)\n        (void)cpStop(c, base);'),
    # not a mutation: "a latched CP allows a mode change" cannot be seen, because a
    # latch is only ever set while RUNNING -- world5 asserts that invariant instead
    ('START does not look at REG5',
     '    if (!cpPoisonHolds(c, base) || cpCheckBlock(c) != 0UL) {\n        c->failed = 1;\n        return CP_RC_CHECK_FAILED;\n    }\n    return CP_RC_RAN;',
     '    (void)cpPoisonHolds(c, base);\n    return CP_RC_RAN;'),
    ('a failed SUBMIT is reported as run',
     '    return c->failed ? CP_RC_CHECK_FAILED : CP_RC_RAN;\n}\n\n/* SUBMIT without',
     '    return CP_RC_RAN;\n}\n\n/* SUBMIT without'),
    # docs/R5_PLAN.md 12-5: the MAP gate keeps every read-back, HI by its low bits,
    # CSQ_STAT only as a record
    ('HI compared exactly again',
     '    for (k = 0; k <= 12; k++)\n        if (v == (want', '    for (k = 0; k <= 0; k++)\n        if (v == (want'),
    ('HI accepts any low 12 bits',
     '        if (v == (want & ~((1UL << k) - 1UL)))', '        if ((v & ~0xfffUL) == (want & ~0xfffUL))'),
    ('the gate stops looking after the first mismatch',
     '    if (m[CP_MG_AGP_LOCATION] != CP_AGP_OFF)', '    if (bad == 0UL && m[CP_MG_AGP_LOCATION] != CP_AGP_OFF)'),
    ('the gate logs the register, not the value read',
     '    return cpRefuse(c, k == CP_MG_REG5 ? CP_WHY_POISON : why, m[k]);',
     '    return cpRefuse(c, k == CP_MG_REG5 ? CP_WHY_POISON : why, cpMgReg[k]);'),
    ('the gate does not name the register',
     '    c->gateReg = cpMgReg[k];\n', ''),
    ('the gate does not keep its mask',
     '    c->mgBad = bad;\n', '    c->mgBad = 0;\n'),
    ('the gate forgets REG5',
     '    if (m[CP_MG_REG5] != CP_REG5_POISON)\n        bad |= 1UL << CP_MG_REG5;\n', ''),
    ('the gate forgets RPTR',
     '    if ((m[CP_MG_RPTR] & C_RPTR_MASK) != c->wptr)\n        bad |= 1UL << CP_MG_RPTR;\n', ''),
    ('a REG5 mismatch is not reported as POISON',
     'k == CP_MG_REG5 ? CP_WHY_POISON : why', 'why'),
    ('the end-of-op CSQ read ignores the CP latch',
     '!c->latched && !engineLatched && op >= CP_OP_RECORD', '!engineLatched && op >= CP_OP_RECORD'),
    ('the end-of-op CSQ read ignores the engine latch',
     '!c->latched && !engineLatched && op >= CP_OP_RECORD', '!c->latched && op >= CP_OP_RECORD'),
    # docs/R5_STOPFIX_PLAN.md 8
    ('the clean STOP compares RPTR after the CSQ is off again (the old check)',
     '        c->wptrOff = rdnMmioRead32(base, C_CP_RB_WPTR);\n',
     '        c->wptrOff = rdnMmioRead32(base, C_CP_RB_WPTR);\n        if ((c->rptrOff & C_RPTR_MASK) != c->wptr) {\n'
     '            (void)cpLatch(c, base);\n            return cpStopLatched(c, base);\n        }\n'),
    ('the clean STOP does not wait for RPTR before the CSQ goes off',
     '        if (!cpWait(base, W_RPTR, c->wptr, C_RPTR_US, &c->wRptr)) {\n            (void)cpLatch(c, base);\n            return cpStopLatched(c, base);\n        }\n        if (!cpWait(base, W_IDLE, 0, C_IDLE_US, &c->wIdle)) {\n            (void)cpLatch(c, base);\n            return cpStopLatched(c, base);\n        }\n        c->rptrAfter',
     '        if (!cpWait(base, W_IDLE, 0, C_IDLE_US, &c->wIdle)) {\n            (void)cpLatch(c, base);\n            return cpStopLatched(c, base);\n        }\n        c->rptrAfter'),
    # R5d (docs/R5D_PLAN.md 7)
    ('INJECT latches even when its read-back is wrong',
     '    if (inject && !c->failed) {', '    if (inject) {'),
    ('INJECT latches before the read-back (no proof of the submission)',
     '    if (!cpWait(base, W_IDLE, 0, C_IDLE_US, &c->wIdle))\n        return cpFail(c, base);\n    cpReadBack(c, base);',
     '    if (!cpWait(base, W_IDLE, 0, C_IDLE_US, &c->wIdle))\n        return cpFail(c, base);\n'
     '    if (inject) {\n        c->latchInjected = 1;\n        c->injectCount++;\n        (void)cpRefuse(c, CP_WHY_INJECTED, 0);\n'
     '        return cpLatch(c, base);\n    }\n    cpReadBack(c, base);'),
    # M1n named the INJECT branch instead of letting it be the wildcard `else`,
    # so the key test moved inside it.  The mutation is the same one: take the
    # key test away and see whether an unkeyed INJECT still reaches the card.
    ('INJECT without its key',
     '        if (!c->injectKey)\n            (void)cpRefuse(c, CP_WHY_KEY, (unsigned long)op);\n        else\n',
     '        '),
    ('the injected latch is not marked (RECORD refused after it)',
     '        c->latchInjected = 1;\n        c->injectCount++;', '        c->injectCount++;'),
    ('the inject count is not kept',
     '        c->latchInjected = 1;\n        c->injectCount++;', '        c->latchInjected = 1;'),
    ('a real latch still lets RECORD read',
     '    else if (op == CP_OP_RECORD && c->latched && !c->latchInjected)\n        (void)cpRefuse(c, CP_WHY_LATCHED, 0);   /* a real latch: nothing more is read (R5d 7) */\n', ''),
    ('MMIO writes are not counted',
     '#define rdnMmioWrite32(b, o, v)     (cpIoWr++, rdnMmioWrite32((b), (o), (v)))\n', ''),
    ('MMIO reads are not counted',
     '#define rdnMmioRead32(b, o)         (cpIoRd++, rdnMmioRead32((b), (o)))\n', ''),
    ('MAP takes a card that still holds our AGP value',
     '    if ((v = rdnMmioRead32(base, C_MC_AGP_LOCATION)) == CP_AGP_OFF)\n        return cpRefused(c, CP_WHY_NOT_FRESH, v);\n', ''),
    ('MAP takes a card with translation on',
     '    if (((v = rdnMmioRead32(base, C_AIC_CNTL)) & C_TRANSLATE_EN) != 0UL)\n        return cpRefused(c, CP_WHY_NOT_FRESH, v);\n', ''),
    ('STOP judges CSQ_STAT again (8-bit, the old gate)',
     '    cpUnmap(c, base);\n    c->state = CP_ST_STOPPED;',
     '    if ((rdnMmioRead32(base, C_CP_CSQ_STAT) & 0xffUL) != ((rdnMmioRead32(base, C_CP_CSQ_STAT) >> 8) & 0xffUL)) {\n'
     '        (void)cpLatch(c, base);\n        return cpStopLatched(c, base);\n    }\n    cpUnmap(c, base);\n    c->state = CP_ST_STOPPED;'),
    ('the CSQ record after an operation is dropped',
     '        c->csqStat = rdnMmioRead32(base, C_CP_CSQ_STAT);\n        c->csq2Stat', '        c->csqStat = 0UL;\n        c->csq2Stat'),
    ('the CSQ record reads without the idle test',
     '\n        && cpCond(base, W_IDLE, 0)) {', ') {'),
    ('MAP ignores BUS_MASTER_DIS',
     '    if ((v & C_BUS_MASTER_DIS) != 0UL)\n        return cpRefused(c, CP_WHY_BUSMASTER, v);\n', ''),
    ('the sentinel FIFO wait does not latch with the CSQ on',
     '        return cpLatch(c, base);        /* the CSQ is on (plan 7-2 B1) */',
     '        return CP_RC_PRE_TIMEOUT;'),
    # G3 (docs/G3_PRESENT_PLAN.md 2-4): the present blit
    ('G3: the GMC word loses WR_MSK_DIS (the reference sets it)',
     '#define C_PRESENT_GMC           0x52cc36f3UL',
     '#define C_PRESENT_GMC           0x12cc36f3UL'),
    ('G3: the two WAITs lose the HOST bit',
     '#define C_PRESENT_WAIT_PRE      0x00060000UL',
     '#define C_PRESENT_WAIT_PRE      0x00020000UL'),
    ('G3: DST_X_Y and SRC_X_Y are swapped',
     '    wd[n++] = C_P0N(C_SRC_X_Y, 2);              wd[n++] = (b->srcX << 16) | b->srcY;\n                                                wd[n++] = (b->dstX << 16) | b->dstY;',
     '    wd[n++] = C_P0N(C_SRC_X_Y, 2);              wd[n++] = (b->dstX << 16) | b->dstY;\n                                                wd[n++] = (b->srcX << 16) | b->srcY;'),
    ('G3: a stride the pitch field cannot encode is accepted',
     '        b->srcStride == 0UL || b->srcStride > C_PRESENT_MAX_STRIDE || ((b->srcStride * 4UL) & 63UL) != 0UL)',
     '        b->srcStride == 0UL || b->srcStride > C_PRESENT_MAX_STRIDE)'),
    ('G3: the destination may run one pixel off the screen',
     '    if (b->w > q->modeW || b->dstX > q->modeW - b->w || b->h > q->modeH || b->dstY > q->modeH - b->h)',
     '    if (b->w > q->modeW || b->dstX > q->modeW - b->w || b->h > q->modeH || b->dstY > q->modeH - b->h + 1UL)'),
    ('G3: the source tail is not checked against the window',
     '    if ((b->srcX + b->w) * 4UL > tail)\n        return cpPresentRefuse(c, OSRDN_PRESENT_E_SRC);\n',
     ''),
    ('G3: a latched CP still presents',
     '    if (c->latched || c->failed)\n        return cpPresentRefuse(c, OSRDN_PRESENT_E_LATCH);\n',
     ''),
    ('G3: the packet header counts one register too many',
     '    wd[n++] = C_P0N(C_SRC_PITCH_OFFSET, 1);     wd[n++] = srcPO;    wd[n++] = dstPO;',
     '    wd[n++] = C_P0N(C_SRC_PITCH_OFFSET, 2);     wd[n++] = srcPO;    wd[n++] = dstPO;'),
    # G3b (docs/G3B_CLEAR_PLAN.md 2-4): the clear
    ('G3b: the fill loses the solid brush (it would copy, not paint)',
     '#define C_CLEAR_GMC             0x10f036d2UL',
     '#define C_CLEAR_GMC             0x10f03602UL'),
    ('G3b: the fill uses ROP3_S instead of ROP3_P',
     '#define C_CLEAR_GMC             0x10f036d2UL',
     '#define C_CLEAR_GMC             0x10cc36d2UL'),
    ('G3b: the depth rectangle\'s vertices come in the wrong order',
     '        wd[n++] = 0UL; wd[n++] = fh;  wd[n++] = b->depthZ; wd[n++] = C_CLEAR_ONE;\n        wd[n++] = fw;  wd[n++] = fh;  wd[n++] = b->depthZ; wd[n++] = C_CLEAR_ONE;',
     '        wd[n++] = fw;  wd[n++] = fh;  wd[n++] = b->depthZ; wd[n++] = C_CLEAR_ONE;\n        wd[n++] = 0UL; wd[n++] = fh;  wd[n++] = b->depthZ; wd[n++] = C_CLEAR_ONE;'),
    ('G3b: the 3D stream is not waited for before the 2D fill',
     '        wd[n++] = C_P0N(C_WAIT_UNTIL, 0);           wd[n++] = C_PRESENT_WAIT_PRE;    /* 3D idle before the 2D fill */',
     '        wd[n++] = C_P0N(C_WAIT_UNTIL, 0);           wd[n++] = C_PRESENT_WAIT_POST;   /* 3D idle before the 2D fill */'),
    ('G3b: a depth clear past the window is accepted',
     '        if (rows > avail / rowBytes)\n            return cpClearRefuse(c, OSRDN_PRESENT_E_SRC);\n',
     ''),
    ('G3b: a clear depth above 1.0 is accepted',
     '        b->depthZ > C_CLEAR_ONE)                /* 0.0 .. 1.0 as float bits, sign clear */',
     '        0)                /* 0.0 .. 1.0 as float bits, sign clear */'),
]


def present_expect():
    """G3: the words world5's present test compares against (19 since REL2), from the
    reference-side oracle and NOT from osrdn_cp.m (docs/G3_PRESENT_PLAN.md 2-4).
    The case is world5's: window WIN0, stride 800, row 599 to screen row 0."""
    import importlib.util
    spec = importlib.util.spec_from_file_location('present_oracle',
                                                  os.path.join(HERE, '..', 'r7', 'present_oracle.py'))
    po = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(po)
    po.self_check()
    win0 = 0x0029e000
    words = po.words(win0, 800, 0, 599, 800, 1, 0, 0, 4096)
    # REL2: the count, the ring length (cpR6Submit pads to a multiple of 16) and where each
    # register's value sits are found in the oracle's words, not written down again -- world5
    # uses only these names, so a change of layout cannot leave a stale index behind
    def after(header, k=1):
        assert words.count(header) == 1, hex(header)
        return words.index(header) + k
    ring = (len(words) + 15) // 16 * 16
    text = ('/* GENERATED by tools/r5/sim_r5.py from tools/r7/present_oracle.py -- do not edit */\n'
            '#define G3_PRESENT_WORDS %d\n#define G3_PRESENT_RING %d\n' % (len(words), ring) +
            '#define G3_IX_GMC %d\n#define G3_IX_SRC_PO %d\n#define G3_IX_DST_PO %d\n'
            '#define G3_IX_SRC_XY %d\n#define G3_IX_DST_XY %d\n#define G3_IX_WH %d\n' % (
                after(po.packet0(po.DP_GUI_MASTER_CNTL, 0)), after(po.packet0(po.SRC_PITCH_OFFSET, 1)),
                after(po.packet0(po.SRC_PITCH_OFFSET, 1), 2), after(po.packet0(po.SRC_X_Y, 2)),
                after(po.packet0(po.SRC_X_Y, 2), 2), after(po.packet0(po.SRC_X_Y, 2), 3)) +
            'static const unsigned long g3PresentWant[G3_PRESENT_WORDS] = {\n    ' +
            ', '.join('0x%08xUL' % v for v in words) + '\n};\n')
    with open(os.path.join(HERE, 'sim', 'present_expect.h'), 'w') as f:
        f.write(text)
    # G3b: the clear, both parts, over the block's colour area (window offset 0x10000, pitch 64) and
    # the depth area (window offset 0, pitch 64), 64 x 64, colour 0x11223344, depth 1.0
    cw = po.clear_words(3, win0 + 0x10000, 64, 0x11223344, win0 + 0, 64, po.f32(1.0), 64, 64)
    text = ('/* GENERATED by tools/r5/sim_r5.py from tools/r7/present_oracle.py -- do not edit */\n'
            '#define G3B_CLEAR_WANT_N %d\n' % len(cw) +
            'static const unsigned long g3bClearWant[%d] = {\n    ' % len(cw) +
            ', '.join('0x%08xUL' % v for v in cw) + '\n};\n')
    with open(os.path.join(HERE, 'sim', 'clear_expect.h'), 'w') as f:
        f.write(text)


def build(cp, out):
    present_expect()
    cmd = ['gcc-12', '-m32', '-std=gnu89', '-O0', '-Wall', '-Wno-deprecated', '-nostdinc',
           '-I', INC, '-I', TPROJ, '-x', 'c', cp, SNAP, WORLD,
           '-x', 'none', '-nostdlib', '-nostartfiles', LIBC32, '-Wl,-dynamic-linker,' + LD32, '-o', out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode == 0, r.stderr


def run(exe):
    try:
        r = subprocess.run([exe], capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return 124, 'world5: FAIL (it never came back: a wait with no bound)\n'
    out = r.stdout + r.stderr
    if r.returncode < 0 and 'world5: FAIL' not in out:
        out += '\nFAIL killed by signal %d' % -r.returncode
    return r.returncode, out


def main():
    if not os.path.exists(LIBC32):
        print('  --   %s not present, CP simulation skipped' % LIBC32)
        return 0
    work = tempfile.mkdtemp(prefix='simr5.', dir=os.environ.get('TMPDIR'))
    # 2026-09-24: none of these tools removed what they made, and /tmp
    # reached 35.6 GiB of our scratch.  atexit, so a failure path cleans
    # up too -- the tool exits on a bad verdict from several places.
    atexit.register(shutil.rmtree, work, True)
    failures = 0
    exe = os.path.join(work, 'base')
    ok, err = build(CP, exe)
    if not ok:
        print('  FAIL baseline does not build\n' + err[-2000:])
        return 1
    rc, out = run(exe)
    if rc == 0 and 'world5: PASS' in out:
        print('  ok   baseline: %d world checks' % sum(1 for l in out.splitlines() if l.strip().startswith('ok')))
    else:
        print('  FAIL baseline\n' + out)
        failures += 1
    text = open(CP).read()
    for n, (label, old, new) in enumerate(MUTATIONS):
        if text.count(old) != 1:
            print('  FAIL mutation %-60s anchor found %d times' % (label, text.count(old)))
            failures += 1
            continue
        path = os.path.join(work, 'mut%d.m' % n)
        open(path, 'w').write(text.replace(old, new))
        exe = os.path.join(work, 'mut%d' % n)
        ok, err = build(path, exe)
        if not ok:
            print('  FAIL mutation %-60s does not build\n%s' % (label, err[-400:]))
            failures += 1
            continue
        rc, out = run(exe)
        caught = (rc != 0 and 'world5: FAIL' in out) or rc < 0
        first = [l.strip() for l in out.splitlines() if l.strip().startswith('FAIL')]
        print('  %-4s mutation %-60s %s' % ('ok' if caught else 'FAIL', label,
                                            (first[0][:70] if first else 'caught') if caught else 'NOT CAUGHT'))
        failures += 0 if caught else 1
    print('sim_r5: %s' % ('PASS' if not failures else 'FAIL (%d)' % failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
