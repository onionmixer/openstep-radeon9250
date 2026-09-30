#!/usr/bin/env python3
"""Run osrdn_snap.m and osrdn_mode.m against a fake card, and prove it has teeth.

  sim_r2b.py            build and run the baseline, then every mutation

docs/R2B_IMPL_PLAN.md 12-5, 12-12.  The baseline must PASS and every mutation
must FAIL in this same invocation: a check that cannot fail proves nothing.
The mutations are plausible defects, not noise -- the first one in the table
is a defect this harness actually found while the file was being written.
"""

import shutil
import atexit
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
TPROJ = os.path.join(PROJ, 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj')
SNAP = os.path.join(TPROJ, 'osrdn_snap.m')
MODE = os.path.join(TPROJ, 'osrdn_mode.m')
MODESEL = os.path.join(TPROJ, 'osrdn_modesel.m')
ORACLE = os.path.join(PROJ, 'tools', 'oracle', 'radeon_modeset.py')
WORLD = os.path.join(HERE, 'sim', 'simworld2b.c')
INC = os.path.join(HERE, 'sim', 'include')
LIBC32 = '/usr/lib32/libc.so.6'
LD32 = '/lib/ld-linux.so.2'

SNAP_MUTATIONS = [
    ('an undecoded VGA core is trusted (MISC 0xff taken as a console)',
     '    if (snap->vgaMisc == 0xff)\n        return;                 /* not decoded: the caller refuses (SNAP_WHY_VGA_DECODE) */\n',
     ''),
    ('SEQ0 restored as a bare 0x03',
     'osrdn_outb((IOEISAPortAddress)VGA_SEQ_DATA, (unsigned char)(snap->vgaSeq[0] | 0x03));',
     'osrdn_outb((IOEISAPortAddress)VGA_SEQ_DATA, 0x03);'),
    ('the attribute index keeps PAS inside the read loop',
     '        osrdn_outb((IOEISAPortAddress)VGA_ATTR_INDEX, (unsigned char)k);\n        snap->vgaAttr[k]',
     '        osrdn_outb((IOEISAPortAddress)VGA_ATTR_INDEX, (unsigned char)((unsigned char)k | (pas & VGA_PAS)));\n        snap->vgaAttr[k]'),
    ('the palette address source is not put back after the read',
     '    osrdn_outb((IOEISAPortAddress)VGA_ATTR_INDEX, pas);\n    splx(s);',
     '    splx(s);'),
    ('the PLL index is not put back after the snapshot',
     '    rdnMmioWrite8(base, REG_CLOCK_CNTL_INDEX,\n'
     '                  (unsigned char)(snap->mmio[SNAP_CLOCK_CNTL_INDEX] & LOW_BYTE));',
     '    /* mutation: index left where the last read put it */'),
    ('PLL writes without the write-enable bit',
     'rdnMmioWrite8(base, REG_CLOCK_CNTL_INDEX, (unsigned char)(index | PLL_WR_EN));',
     'rdnMmioWrite8(base, REG_CLOCK_CNTL_INDEX, (unsigned char)(index & PLL_INDEX_MASK));'),
    ('PLL writes leave the write-enable bit set',
     '    rdnMmioWrite32(base, REG_CLOCK_CNTL_DATA, value);\n'
     '    rdnMmioWrite8(base, REG_CLOCK_CNTL_INDEX, (unsigned char)(index & PLL_INDEX_MASK));',
     '    rdnMmioWrite32(base, REG_CLOCK_CNTL_DATA, value);'),
    ('CR0-7 write protection is not lifted before the CRTC restore',
     '    osrdn_outb((IOEISAPortAddress)crtcPort, 0x11);\n'
     '    osrdn_outb((IOEISAPortAddress)(crtcPort + 1), (unsigned char)(snap->vgaCrtc[0x11] & 0x7f));',
     '    /* mutation: CR11 left as it is */'),
    ('the MISC register is not restored',
     '    osrdn_outb((IOEISAPortAddress)VGA_MISC_WRITE, snap->vgaMisc);',
     '    /* mutation: MISC left alone */'),
    ('the palette index does not advance',
     'rdnMmioWrite32(base, REG_PALETTE_INDEX, (unsigned long)(first + k));\n        rdnMmioWrite32(base, REG_PALETTE_30_DATA',
     'rdnMmioWrite32(base, REG_PALETTE_INDEX, (unsigned long)first);\n        rdnMmioWrite32(base, REG_PALETTE_30_DATA'),
    ('R3b-2: the LUT read-back index does not advance',
     'rdnMmioWrite32(base, REG_PALETTE_INDEX, (unsigned long)(first + k));\n        values[k]',
     'rdnMmioWrite32(base, REG_PALETTE_INDEX, (unsigned long)first);\n        values[k]'),
    ('the attribute controller is not restored',
     '        osrdn_outb((IOEISAPortAddress)VGA_ATTR_INDEX, (unsigned char)k);\n'
     '        osrdn_outb((IOEISAPortAddress)VGA_ATTR_INDEX, snap->vgaAttr[k]);',
     '        osrdn_outb((IOEISAPortAddress)VGA_ATTR_INDEX, (unsigned char)k);'),
    ('the snapshot writes palette data (it must only read)',
     '        snap->palette[k] = rdnMmioRead32(base, REG_PALETTE_30_DATA);\n',
     '        snap->palette[k] = rdnMmioRead32(base, REG_PALETTE_30_DATA);\n'
     '        rdnMmioWrite32(base, REG_PALETTE_30_DATA, 0UL);\n'),
    ('the snapshot reads every entry at index 0',
     '        rdnMmioWrite32(base, REG_PALETTE_INDEX, (unsigned long)k);\n',
     '        rdnMmioWrite32(base, REG_PALETTE_INDEX, (unsigned long)k << 16);\n'),
    ('a register outside the tables is written',
     'void\nosrdn_mmio_put(vm_address_t base, int which, unsigned long value)\n{\n'
     '    if (which < 0 || which >= OSRDN_SNAP_MMIO_COUNT)\n        return;',
     'void\nosrdn_mmio_put(vm_address_t base, int which, unsigned long value)\n{\n'
     '    rdnMmioWrite32(base, 0x0b00, 0);\n'
     '    if (which < 0 || which >= OSRDN_SNAP_MMIO_COUNT)\n        return;'),
]

MODE_MUTATIONS = [
    # R4 (docs/R4_ENGINE_PLAN.md 13 #8): the engine wrapper
    ('R4: the engine wrapper releases instead of finishing (a kernel revert is lost)',
     '    *copy = *eng;                       /* while the claim is still ours */\n    modeFinish(mode, base);',
     '    *copy = *eng;                       /* while the claim is still ours */\n    modeRelease(mode);'),
    ('R4: the engine wrapper forgets noSleep (the owed revert sleeps in setIntValues)',
     '    mode->noSleep = 1;                  /* setIntValues must not sleep, and a revert',
     '    mode->noSleep = 0;                  /* setIntValues must not sleep, and a revert'),
    ('R4: the engine wrapper runs with no mode on the card',
     '    if (!mode->snapshotValid || !mode->modeWritten)\n        rc = ENG_RC_NOT_LIVE;\n    else\n        rc',
     '    if (0)\n        rc = ENG_RC_NOT_LIVE;\n    else\n        rc'),
    # R5 (docs/R5_PLAN.md 7-2 B2 B3 B10): the mode module's side of the CP
    ('R5: the CP is stopped only when a mode is on the card',
     '    if (mode->cp != 0)\n        osrdn_cp_quiesce(mode->cp, base);\n    mode->revertCount++;\n'
     '    if (!mode->snapshotValid || !mode->modeWritten)\n        return;\n',
     '    mode->revertCount++;\n    if (!mode->snapshotValid || !mode->modeWritten)\n        return;\n'
     '    if (mode->cp != 0)\n        osrdn_cp_quiesce(mode->cp, base);\n'),
    ('R5: a cycle is not refused while the CP holds the card',
     '    if (mode->cp != 0 && !osrdn_cp_allows_mode(mode->cp)) {\n        mode->cycleWhy = MODE_WHY_CP;',
     '    if (0) {\n        mode->cycleWhy = MODE_WHY_CP;'),
    ('R5: the engine runs while the CP holds the card',
     '        rc = (mode->cp != 0 && !osrdn_cp_allows_mode(mode->cp))',
     '        rc = (0)'),
    ('R5: the CP wrapper forgets noSleep',
     '    mode->noSleep = 1;                  /* setIntValues must not sleep (R5, as the engine\'s) */',
     '    mode->noSleep = 0;                  /* setIntValues must not sleep (R5, as the engine\'s) */'),
    ('R5: STOP needs a live mode',
     '    if (op != CP_OP_STOP && op != CP_OP_RECORD && op != CP_OP_REC3D && (!mode->snapshotValid || !mode->modeWritten))',
     '    if (op != CP_OP_RECORD && op != CP_OP_REC3D && (!mode->snapshotValid || !mode->modeWritten))'),
    ('R5: the CP wrapper releases instead of finishing (an owed revert is lost)',
     '    *copy = *cp;                        /* while the claim is still ours */\n    modeFinish(mode, base);',
     '    *copy = *cp;                        /* while the claim is still ours */\n    modeRelease(mode);'),
    ('the PLL gain is recomputed and written, as xf86 does',
     'osrdn_pll_put(base, SNAP_PPLL_CNTL, v | PPLL_RESET | PPLL_ATOMIC_UPDATE_EN | PPLL_VGA_ATOMIC_EN);',
     'osrdn_pll_put(base, SNAP_PPLL_CNTL, (v & ~0x3800UL) | (7UL << 11) | PPLL_RESET |\n'
     '                  PPLL_ATOMIC_UPDATE_EN | PPLL_VGA_ATOMIC_EN);'),
    ('the reference divider is taken from the oracle instead of the boot',
     '(v & ~PPLL_REF_DIV_MASK) | (mode->refdiv & PPLL_REF_DIV_MASK));',
     '(v & ~PPLL_REF_DIV_MASK) | 12UL);'),
    ('the divider slot the console uses is written too',
     '    /* 6e, 6f: feedback then post, two writes as the reference does */',
     '    osrdn_pll_put(base, SNAP_PPLL_DIV_3 - 1, div3);\n'
     '    /* 6e, 6f: feedback then post, two writes as the reference does */'),
    ('the revert restores a constant divider selector instead of the read word',
     'osrdn_mmio_put(base, SNAP_CLOCK_CNTL_INDEX, mode->snap.mmio[SNAP_CLOCK_CNTL_INDEX]);',
     'osrdn_mmio_put(base, SNAP_CLOCK_CNTL_INDEX, 0x00000303UL);'),
    ('the DAC pixel clock gate is not put back after the palette',
     '    osrdn_pll_put(base, SNAP_VCLK_ECP_CNTL, saved);',
     '    /* mutation: the gate is left off */'),
    ('the revert stops when a wait reached its limit',
     '    /* 4.5 the PLL, same code as the entry, snapshot values */',
     '    if (mode->atomicReadLimit) return;\n'
     '    /* 4.5 the PLL, same code as the entry, snapshot values */'),
    ('the revert does not restore the CRTC pitch',
     '    osrdn_mmio_put(base, SNAP_CRTC_PITCH, mode->snap.mmio[SNAP_CRTC_PITCH]);',
     '    /* mutation: pitch left as the mode set it */'),
    ('the entry writes the mode before taking the snapshot',
     '    if (!modeSnapshot(mode, base))\n        return 0;',
     '    modeBlank(mode, base);\n    if (!modeSnapshot(mode, base))\n        return 0;'),
    ('the read-back judges before letting the offset trigger clear',
     '    modeOffsetSettle(mode, base);',
     '    /* mutation: no wait, judge at once */'),
    ('a pending trigger is called a restore failure',
     '        mode->revertVerdict = onlyOffset ? 1 : 2;',
     '        mode->revertVerdict = 2;'),
    ('a real mismatch is excused as a pending trigger',
     '            onlyOffset = 0;\n        }\n        for (k = 0; onlyOffset && k < OSRDN_SNAP_PLL_COUNT; k++)',
     '            ;\n        }\n        for (k = 0; onlyOffset && k < OSRDN_SNAP_PLL_COUNT; k++)'),
    ('the trigger wait has no bound at all',
     '        if (turns >= MODE_POLL_LOOPS) {\n            mode->revertOffsetPending = 1;\n            break;\n        }',
     '        /* mutation: no turn bound */'),
    ('a wrong VGA byte is counted but not named',
     '    n = mode->revertVgaBad;\n    if (n < OSRDN_VGA_NAMED) {',
     '    n = mode->revertVgaBad;\n    if (0) {'),
    ('the cycle blackens the desktop',
     '    if (fb != 0 && !mode->skipShow)\n        osrdn_mode_black(mode, fb);',
     '    if (fb != 0)\n        osrdn_mode_black(mode, fb);'),
    ('the GART translation gate is dropped',
     '    if (!modeGate(mode, GATE_GART, osrdn_peek(base, PEEK_AIC_CNTL), PCIGART_TRANSLATE_EN, 0))\n        return 0;\n',
     ''),
    ('the surface gate forgets translation must be disabled',
     'SURF_TRANSLATION_DIS | SURF_AP_SWAP_MASK, SURF_TRANSLATION_DIS))',
     'SURF_AP_SWAP_MASK, 0))'),
    ('the divider-slot gate accepts any value',
     '    if (v != 1UL && v != 3UL)\n        return modeRefuse(mode, GATE_DIVSEL, v);',
     '    (void)v;'),
    ('the step-0 gates are skipped on re-entry',
     '    mode->clientWhich = 0;\n    mode->clientValue = 0;\n',
     '    mode->clientWhich = 0;\n    mode->clientValue = 0;\n    if (mode->snapshotValid)\n        return 1;\n'),
    ('an atomic wait counts only busy turns, so a quick success reads as "never ran"',
     '        v = osrdn_pll_get(base, SNAP_PPLL_REF_DIV);\n        w->evals++;\n        if (!(v & PPLL_ATOMIC_UPDATE_BIT))\n            break;\n        loops++;',
     '        v = osrdn_pll_get(base, SNAP_PPLL_REF_DIV);\n        if (!(v & PPLL_ATOMIC_UPDATE_BIT))\n            break;\n        w->evals++;\n        loops++;'),
    ('the turn cap goes back to limit/tick + 8 (it fired on the machine)',
     '    maxTurns = (limitUs / tickUs) * MODE_TURN_FACTOR + MODE_SETTLE_SLACK;',
     '    maxTurns = limitUs / tickUs + MODE_SETTLE_SLACK;'),
    ('the cycle releases without honouring a revert that came during re-entry',
     '    while ((work = modeReleaseOrWork(mode)) != MODE_WORK_NONE) {',
     '    modeRelease(mode);\n    while (0) {'),
    ('the cycle sleeps on the setIntValues path',
     '    mode->noSleep = 1;\n    mode->skipShow = 1;',
     '    mode->noSleep = 0;\n    mode->skipShow = 1;'),
    ('the cycle leaves the shutdown path in no-sleep mode',
     '        mode->noSleep = 0;\n        mode->skipShow = 0;\n        mode->wantRevertCheck = 0;\n        mode->inSequence = 0;',
     '        mode->skipShow = 0;\n        mode->wantRevertCheck = 0;\n        mode->inSequence = 0;'),
    ('a kernel revert writes underneath a held claim',
     '    if (mode->inSequence) {\n        mode->kernelRevertSeen = 1;',
     '    if (0) {\n        mode->kernelRevertSeen = 1;'),
    ('the cycle does not read the snapshot back',
     '    mode->wantRevertCheck = 1;',
     '    mode->wantRevertCheck = 0;'),
    ('a text console is entered although the snapshot holds no glyph planes',
     '    if ((mode->snap.vgaAttr[0x10] & 0x01) == 0) {\n        mode->why = MODE_WHY_TEXT_CONSOLE;\n        return 0;\n    }',
     '    /* mutation: the graphics gate is gone */'),
    ('the revert read-back leaves the PLL index where it last read',
     '    modePllRead(base, mode->verifyPll);',
     '    { int j; for (j = 0; j < OSRDN_SNAP_PLL_COUNT; j++)\n'
     '          mode->verifyPll[j] = osrdn_pll_get(base, j); }'),
    ('a refdiv outside the table is let through with no divider word',
     '    if (mode->div3 == 0) {\n        mode->why = MODE_WHY_REFDIV;\n        return 0;\n    }',
     '    /* mutation: the table no longer gates the entry */'),
    ('a second entry takes a second snapshot, so the revert restores our own mode',
     '    if (mode->snapshotValid) {',
     '    if (0) {'),
    ('R3b-2: the pixel format is always 32 bpp',
     '((unsigned long)osrdn_fmt(mode->fmt)->crtcFormat << CRTC_PIX_WIDTH_SHIFT);',
     '(6UL << CRTC_PIX_WIDTH_SHIFT);'),
    ('R3b-2: the FIFO row is always the 4-byte one',
     '    int          col = (bytes == 4) ? 0 : ((bytes == 2) ? 1 : 2);',
     '    int          col = (bytes == 4) ? 0 : 0;'),
    ('R3b-2: the divider row comes from the default resolution',
     '    r = osrdn_res(mode->res);\n    if (!mode->selected',
     '    r = osrdn_res(OSRDN_RES_DEFAULT);\n    if (!mode->selected'),
    ('R3b-2: the blackening writes one pixel per word',
     '    per = 4U / bytes;',
     '    per = 1U;'),
    ('REL3: the boot paints colour again',
     '            rdnMmioWrite32(fb, (unsigned int)(y * rowBytes + x * bytes), 0);',
     '            rdnMmioWrite32(fb, (unsigned int)(y * rowBytes + x * bytes), 0x00ff00ffUL);'),
    ('REL3: the entry writes the table sync word, not the adjusted one',
     '    osrdn_mmio_put(base, SNAP_CRTC_H_SYNC,\n                   osrdn_mode_hsync_word(r->hTotalDisp, r->hSync, mode->hsyncAdj,\n                                         &mode->hsyncRefused));',
     '    osrdn_mmio_put(base, SNAP_CRTC_H_SYNC, r->hSync);'),
    ('REL3: the read-back expects the table sync word',
     '    if (mode->verifyGot[SNAP_CRTC_H_SYNC] !=\n        osrdn_mode_hsync_word(r->hTotalDisp, r->hSync, mode->hsyncAdj, &refused))',
     '    refused = 0;\n    if (mode->verifyGot[SNAP_CRTC_H_SYNC] != r->hSync)'),
    ('REL3: the lower bound lets the sync into the picture',
     '    if (start + adj < hdisp - 8L || start + adj + width > htotal - 8L) {',
     '    if (start + adj < 0L || start + adj + width > htotal - 8L) {'),
    ('REL3: the upper bound lets the sync past the line',
     '    if (start + adj < hdisp - 8L || start + adj + width > htotal - 8L) {',
     '    if (start + adj < hdisp - 8L || start + adj > htotal - 8L) {'),
    ('REL3: the sync width is dropped when the start moves',
     '    return (hSync & ~0x1fffUL) | ((unsigned long)(start + adj) & 0x1fffUL);',
     '    return (hSync & ~0x3f1fffUL) | ((unsigned long)(start + adj) & 0x1fffUL);'),
    ('REL3: the live move skips the claim',
     '    if (!modeClaim(mode))\n        return MODE_HSYNC_BUSY;\n    mode->kernelRevertSeen = 0;\n    mode->noSleep = 1;',
     '    (void)modeClaim(mode);\n    mode->kernelRevertSeen = 0;\n    mode->noSleep = 1;'),
    ('REL3: the live move writes with no mode of ours on the card',
     '    if (!mode->snapshotValid || !mode->modeWritten || r == 0) {\n        rc = MODE_HSYNC_NOT_LIVE;',
     '    if (r == 0) {\n        rc = MODE_HSYNC_NOT_LIVE;'),
    ('REL3: the live move is not kept for the next entry',
     '            mode->hsyncAdj = adj;\n            mode->hsyncRefused = 0;',
     '            mode->hsyncRefused = 0;'),
    ('R3b-2: the divider row is looked up after the blank',
     '    mode->step = 3;\n    if (!modeRow(mode, base))\n        return 0;\n\n'
     '    /* from here every failure reverts: -enterLinearMode cannot report one */\n'
     '    mode->step = 4;\n    modeBlank(mode, base);\n',
     '\n    /* from here every failure reverts: -enterLinearMode cannot report one */\n'
     '    mode->step = 4;\n    modeBlank(mode, base);\n'
     '    mode->step = 3;\n    if (!modeRow(mode, base))\n        return 0;\n'),
    ('R3b-2: no selection is taken as 640x480',
     '    if (!mode->selected || r == 0',
     '    if (r == 0'),
    ('R3b-2: the live divider is not compared with the snapshot',
     '    osrdn_mmio_put(base, SNAP_CLOCK_CNTL_INDEX, index);\n    if (live != mode->refdiv) {',
     '    osrdn_mmio_put(base, SNAP_CLOCK_CNTL_INDEX, index);\n    if (0) {'),
    ('R3b-2: the read-back ignores the pixel format',
     '    if (mode->verifyFormat != (unsigned long)osrdn_fmt(mode->fmt)->crtcFormat)\n        mode->verifyBad++;',
     ''),
    ('R3b-2: the read-back ignores the FIFO',
     '    if ((mode->verifyGot[SNAP_GRPH_BUFFER_CNTL] & f->clear) != f->set)\n        mode->verifyBad++;',
     ''),
    ('R3b-2: the read-back ignores the DAC',
     '    if ((mode->verifyGot[SNAP_DAC_CNTL] & (DAC_MASK_ALL | DAC_8BIT_EN)) != (DAC_MASK_ALL | DAC_8BIT_EN))\n        mode->verifyBad++;',
     ''),
    ('R3b-2: the LUT compare never finds a difference',
     '        if ((modeLutBack[k] & LUT_TOP_BITS) == (modeLut[k] & LUT_TOP_BITS))\n            continue;',
     '        if (1)\n            continue;'),
    ('R3b-2: the LUT compare ignores red',
     '#define LUT_TOP_BITS            0x3fcff3fcUL',
     '#define LUT_TOP_BITS            0x000ff3fcUL'),
    ('R3b-2: the read-back ignores the LUT',
     '    if (mode->verifyLutBad)\n        mode->verifyBad++;',
     ''),
    ('R3b-2: the re-entry check leaves the PLL index where its reads put it',
     '        vclk = osrdn_pll_get(base, SNAP_VCLK_ECP_CNTL);\n        osrdn_mmio_put(base, SNAP_CLOCK_CNTL_INDEX, index);',
     '        vclk = osrdn_pll_get(base, SNAP_VCLK_ECP_CNTL);'),
    ('R3b-2: modeRow leaves the PLL index where its read put it',
     '    osrdn_mmio_put(base, SNAP_CLOCK_CNTL_INDEX, index);\n    if (live != mode->refdiv) {',
     '    if (live != mode->refdiv) {'),
    ('R3b-2b: the table is stored after the claim is tried (a lost update)',
     '    mode->xferCount = n;\n    mode->lutPending = 1;',
     '    mode->xferCount = n;'),
    ('R3b-2b: the release does not look for a pending table',
     '    } else if (mode->lutPending && mode->modeWritten && !mode->kernelRevertSeen) {',
     '    } else if (0) {'),
    # (not a mutation here: modeLutApply's kernelRevertSeen test is defence --
    #  modeReleaseOrWork always takes the revert first, so the mutant is
    #  equivalent; docs/R3_MULTIMODE_PLAN.md 24-10)
    ('R3b-2b: the brightness is stored as the level (zero-filled is black)',
     '    level = LUT_FULL - (unsigned long)lutDim;',
     '    level = (unsigned long)lutDim;'),
    ('R3b-2b: a table is not spread over the LUT',
     '            rep = 256UL / (unsigned long)lutCount;',
     '            rep = 1UL;'),
    ('G2: a direct-colour format puts the table on the LUT',
     '        } else if (lutCount > 0 && lutCount <= OSRDN_SNAP_PALETTE && !direct) {',
     '        } else if (lutCount > 0 && lutCount <= OSRDN_SNAP_PALETTE) {'),
    ('G2: the 555 ramp is not spread over the 5-bit index',
     '            r = ((k >> 3) * 255UL) / 31UL;',
     '            r = k;'),
    ('R3b-2b: a grey table is read from the colour bytes',
     '    mono = (f->ioColorSpace == LUT_CSPACE_ONE_IS_WHITE);',
     '    mono = 0;'),
    ('R3b-2b: Gray Levels also quantizes colour formats',
     '        if (f != 0 && f->ioColorSpace == LUT_CSPACE_ONE_IS_WHITE && (n == 16 || n == 4 || n == 2)) {',
     '        if (f != 0 && (n == 16 || n == 4 || n == 2)) {'),
    ('R3d: Gray Levels 16 is not quantized',
     '        if (f != 0 && f->ioColorSpace == LUT_CSPACE_ONE_IS_WHITE && (n == 16 || n == 4 || n == 2)) {',
     '        if (f != 0 && f->ioColorSpace == LUT_CSPACE_ONE_IS_WHITE && (n == 4 || n == 2)) {'),
    ('R3d: Gray Levels 2 is not quantized',
     '        if (f != 0 && f->ioColorSpace == LUT_CSPACE_ONE_IS_WHITE && (n == 16 || n == 4 || n == 2)) {',
     '        if (f != 0 && f->ioColorSpace == LUT_CSPACE_ONE_IS_WHITE && (n == 16 || n == 4)) {'),
    ('R3b-2b: the brightness is not applied',
     '        r = (r * level) >> 6;',
     '        r = r;'),
    ('R3b-2b: the entry loads the ramp, not the stored table',
     '    modeLutTake(mode);\n    modeLutMake(mode);\n    modePalette(mode, base, modeLut);',
     '    modeLutTake(mode);\n    lutCount = 0;\n    lutDim = 0;\n    modeLutMake(mode);\n    modePalette(mode, base, modeLut);'),
    ('R3b-2b: the apply leaves the PLL index where the palette gate put it',
     '    osrdn_mmio_put(base, SNAP_CLOCK_CNTL_INDEX, index);    /* 24-9 B8 */',
     ''),
    ('R3b-2b: a brightness above 64 is taken',
     '    if (level < 0 || level > (int)LUT_FULL)\n        return MODE_LUT_IGNORED;',
     '    if (level < 0)\n        return MODE_LUT_IGNORED;'),
    ('R3b-2b: a table longer than 256 overruns',
     '    n = (count > OSRDN_SNAP_PALETTE) ? OSRDN_SNAP_PALETTE : count;',
     '    n = (count > OSRDN_SNAP_PALETTE + 1) ? OSRDN_SNAP_PALETTE + 1 : count;'),
    ('R3b-2b: the kick sleeps (a revert owed there would IOSleep)',
     '    mode->noSleep = 1;                  /* a revert owed here must not sleep */',
     '    mode->noSleep = 0;'),
    ('R3b-2b: the entry builds the LUT without taking the stored table',
     '    modeLutTake(mode);\n    modeLutMake(mode);\n    modePalette(mode, base, modeLut);\n    mode->step = 10;',
     '    modeLutMake(mode);\n    modePalette(mode, base, modeLut);\n    mode->step = 10;'),
    ('R3b-2b: the apply does not read the LUT back',
     '    mode->applyLutBad = modeLutCheck(base, &mode->applyLutIndex, &mode->applyLutGot,\n                                     &mode->applyLutWant);',
     '    mode->applyLutBad = 0;'),
    ('modeWritten is never cleared, so a second revert repeats the writes',
     '    mode->modeWritten = 0;\n\n    /* 4.11 only when asked',
     '\n    /* 4.11 only when asked'),
]


RECORD_H = os.path.join(TPROJ, 'osrdn_record.h')


def mapped_length():
    """OSRDN_FB_LENGTH as the class maps it, read from the header the driver
    builds with, so the fake card's gates test the real value (22-5 V4)."""
    m = re.search(r'^#define\s+OSRDN_FB_LENGTH\s+(0x[0-9a-fA-F]+)UL\b', open(RECORD_H).read(), re.M)
    if not m:
        sys.exit('OSRDN_FB_LENGTH not found in %s' % RECORD_H)
    return m.group(1)


# ---- REL3 (docs/REL3_DISPLAY_FIX_PLAN.md 3-2): the sync word for an adjustment,
#      from the mode's own timings (hdisp, htotal, hsstart, hsend), written here
#      separately from osrdn_mode.m's osrdn_mode_hsync_word
# the panel's range and one past each end (640x480 sets them), the default,
# and 800x600's own two ends past the panel's (its bounds are -40..88)
HSYNC_ADJ_CASES = [-41, -17, -16, 0, 7, 48, 49, 89]
HSYNC_DEFAULT = 7


def hsync_expect(rm, m, adj):
    """(word, refused): the start moves by adj while the whole sync stays in
    the blanking, else the table word unchanged and refused."""
    table = rm.rfb_crtc_words(m)[1]
    start = m['hsstart'] - 8
    width = (m['hsend'] - m['hsstart']) // 8 * 8
    assert table & 0x1fff == start and (table >> 16) & 0x3f == width // 8
    if start + adj < m['hdisp'] - 8 or start + adj + width > m['htotal'] - 8:
        return table, 1
    return (table & ~0x1fff) | ((start + adj) & 0x1fff), 0


# ---- R3b-2b: transfer tables and the LUTs they must give (docs/R3_MULTIMODE_PLAN.md 24-3),
#      written here from the rule, separately from osrdn_mode.m's modeLutMake
def lut_rule(mono, gray, entries, level, direct=False, bpp15=False):
    """entries: [(r, g, b)] as the driver stores them; 256 LUT words.
    direct: RGB:888/32 or RGB:555/16 -- the table is never on the LUT (G2,
    docs/G2_LUT_PLAN.md 5); bpp15: the 5-bit component reaches entries v*8..v*8+7,
    so the ramp spans 0..255 in 32 steps."""
    out = []
    for k in range(256):
        if mono and gray in (16, 4, 2):
            v = (k * gray // 256) * 255 // (gray - 1)
            r = g = b = v
        elif entries and not direct:
            idx = min(k // (256 // len(entries)), len(entries) - 1)
            r, g, b = entries[idx]
        elif direct and bpp15:
            r = g = b = ((k >> 3) * 255) // 31
        else:
            r = g = b = k
        r, g, b = (r * level) >> 6, (g * level) >> 6, (b * level) >> 6
        out.append((r << 22) | (g << 12) | (b << 2))
    return out


SIM_T1 = [(k << 24) | ((255 - k) << 16) | (((k * k) >> 8) << 8) | 0x5a for k in range(256)]
SIM_T2 = [0x12345600 | (255 - k) for k in range(256)]
SIM_T3 = [((k * 8) << 24) | ((k * 8) << 16) | ((255 - k * 8) << 8) for k in range(32)]


def colour(t):
    return [((v >> 24) & 255, (v >> 16) & 255, (v >> 8) & 255) for v in t]


def mono(t):
    return [(v & 255,) * 3 for v in t]


def lut_expect():
    words = lambda name, vs: ['static const unsigned long %s[%d] = {' % (name, len(vs))] + \
        ['    ' + ', '.join('0x%08xUL' % v for v in vs[i:i + 6]) + ',' for i in range(0, len(vs), 6)] + ['};']
    tabs = lambda name, vs: ['static const unsigned int %s[%d] = {' % (name, len(vs))] + \
        ['    ' + ', '.join('0x%08xU' % v for v in vs[i:i + 6]) + ',' for i in range(0, len(vs), 6)] + ['};']
    out = []
    out += tabs('simxT1', SIM_T1) + tabs('simxT2', SIM_T2) + tabs('simxT3', SIM_T3)
    out += tabs('simxT1long', SIM_T1 + [0xffffffff])
    out += words('simxLutRamp', lut_rule(False, 0, [], 64))
    out += words('simxLutRamp15', lut_rule(False, 0, colour(SIM_T3), 64, direct=True, bpp15=True))
    out += words('simxLutRampHalf', lut_rule(False, 0, colour(SIM_T1), 32, direct=True))
    out += words('simxLutT1', lut_rule(False, 0, colour(SIM_T1), 64))
    out += words('simxLutT1half', lut_rule(False, 0, colour(SIM_T1), 32))
    out += words('simxLutT1short', lut_rule(False, 0, colour(SIM_T1[:255]), 64))
    out += words('simxLutT2', lut_rule(True, 0, mono(SIM_T2), 64))
    out += words('simxLutT2spread', lut_rule(True, 0, mono(SIM_T2[:32]), 64))
    out += words('simxLutGray4', lut_rule(True, 4, mono(SIM_T2), 64))
    out += words('simxLutGray16', lut_rule(True, 16, mono(SIM_T2), 64))
    out += words('simxLutGray2', lut_rule(True, 2, mono(SIM_T2), 64))
    out += words('simxLutBlack', lut_rule(False, 0, [], 0))
    return out


def sim_expect(path):
    """The fake card's expectations for every resolution and format, written
    from tools/oracle/radeon_modeset.py directly -- NOT from the generated
    header the driver compiles with, so the two cannot agree by sharing a
    mistake (docs/R3_MULTIMODE_PLAN.md 23-6)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location('rm_for_sim', ORACLE)
    rm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rm)
    out = ['/* GENERATED by tools/r2b/sim_r2b.py from radeon_modeset.py */',
           '#define SIMX_RES %d' % len(rm.MODES), '#define SIMX_FMT %d' % len(rm.FORMATS),
           '#define SIMX_REFDIVS 256',
           'typedef struct { unsigned long w, h, hTot, hSync, vTot, vSync, pitch, htotalCntl; } simx_res;',
           'typedef struct { unsigned long bytes, crtcFormat; } simx_fmt;',
           'typedef struct { unsigned long set, clear, preserve; } simx_fifo;',
           '#define SIMX_RES_DEFAULT %d' % [m['name'] for m in rm.MODES].index('800x600@60'),
           'static const simx_res simxRes[SIMX_RES] = {']
    for m in rm.MODES:
        w = rm.rfb_crtc_words(m)
        out.append('    { %d, %d, 0x%08xUL, 0x%08xUL, 0x%08xUL, 0x%08xUL, 0x%08xUL, %dUL },' % (
            m['hdisp'], m['vdisp'], w[0], w[1], w[2], w[3], rm.crtc_pitch(m, 32), m['htotal'] & 7))
    out.append('};')
    out.append('static const simx_fmt simxFmt[SIMX_FMT] = {')
    for f in rm.FORMATS:
        out.append('    { %d, %d },' % (f['bytes'], f['crtc_format']))
    out.append('};')
    out.append('static const simx_fifo simxFifo[SIMX_RES][SIMX_FMT] = {')
    for m in rm.MODES:
        cells = []
        for f in rm.FORMATS:
            x = rm.fifo(m, f['bytes'])
            cells.append('{ 0x%08xUL, 0x%08xUL, 0x%08xUL }' % (x['set_bits'], x['clear_bits'], x['preserve_mask']))
        out.append('    { %s },' % ', '.join(cells))
    out.append('};')
    out.append('/* REL3: [resolution][case] the CRTC_H_SYNC_STRT_WID word and whether the row refuses */')
    out.append('#define SIMX_HADJ %d' % len(HSYNC_ADJ_CASES))
    out.append('#define SIMX_HADJ_DEFAULT %dL' % HSYNC_DEFAULT)
    out.append('static const long simxHadj[SIMX_HADJ] = { %s };' % ', '.join('%dL' % a for a in HSYNC_ADJ_CASES))
    out.append('static const unsigned long simxHword[SIMX_RES][SIMX_HADJ] = {')
    for m in rm.MODES:
        out.append('    { %s },' % ', '.join('0x%08xUL' % hsync_expect(rm, m, a)[0] for a in HSYNC_ADJ_CASES))
    out.append('};')
    out.append('static const int simxHref[SIMX_RES][SIMX_HADJ] = {')
    for m in rm.MODES:
        out.append('    { %s },' % ', '.join('%d' % hsync_expect(rm, m, a)[1] for a in HSYNC_ADJ_CASES))
    out.append('};')
    out.append('static const unsigned long simxHwordDefault[SIMX_RES] = { %s };'
               % ', '.join('0x%08xUL' % hsync_expect(rm, m, HSYNC_DEFAULT)[0] for m in rm.MODES))
    out += lut_expect()
    out.append('/* [resolution][refdiv]: the PPLL_DIV_3 word, 0 where the table has no row */')
    out.append('static const unsigned long simxDiv3[SIMX_RES][SIMX_REFDIVS] = {')
    for m in rm.MODES:
        t = rm.pll_table(m)
        words = ['0x%08xUL' % (t[rd]['word'] if rd in t else 0) for rd in range(256)]
        out.append('    { ' + ', '.join(words) + ' },')
    out.append('};')
    open(path, 'w').write('\n'.join(out) + '\n')


def build(snap_path, mode_path, out):
    work = os.path.dirname(out)
    sim_expect(os.path.join(work, 'simx_expect.h'))
    cmd = ['gcc-12', '-m32', '-std=gnu89', '-O0', '-Wall', '-Wno-deprecated', '-nostdinc',
           '-DSIM_MAPPED_LENGTH=%sUL' % mapped_length(), '-I', work,
           '-I', INC, '-I', TPROJ, '-x', 'c', snap_path, mode_path, MODESEL, WORLD,
           '-x', 'none', '-nostdlib', '-nostartfiles', LIBC32,
           '-Wl,-dynamic-linker,' + LD32, '-o', out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode == 0, r.stderr


def run(exe):
    """A hang is a result, not a crash of this harness: the turn bounds exist so
    that a wait ends even when the clock it watches does not advance, and the
    world that freezes the clock would otherwise spin here for ever."""
    try:
        r = subprocess.run([exe], capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired as e:
        # a timeout hands back bytes even with text=True: decode each part
        out = ''.join(x.decode('utf-8', 'replace') if isinstance(x, bytes) else (x or '')
                      for x in (e.stdout, e.stderr))
        return 124, out + '\nsimworld2b: FAIL (it never came back: a wait with no bound)\n'
    return r.returncode, r.stdout + r.stderr


def main():
    if not os.path.exists(LIBC32):
        print('  --   %s not present, snapshot simulation skipped' % LIBC32)
        return 0
    work = tempfile.mkdtemp(prefix='simr2b.', dir=os.environ.get('TMPDIR'))
    # 2026-09-24: none of these tools removed what they made, and /tmp
    # reached 35.6 GiB of our scratch.  atexit, so a failure path cleans
    # up too -- the tool exits on a bad verdict from several places.
    atexit.register(shutil.rmtree, work, True)
    failures = 0
    text = open(SNAP, encoding='utf-8').read()

    exe = os.path.join(work, 'base')
    ok, err = build(SNAP, MODE, exe)
    if not ok:
        print('  FAIL baseline does not build\n' + err[-800:])
        return 1
    rc, cout = run(exe)
    if rc == 0 and 'simworld2b: PASS' in cout:
        print('  ok   baseline: %d world checks (both measured boots, the divider table, '
              'the sticky atomic bit and a second entry)'
              % sum(1 for l in cout.splitlines() if l.strip().startswith('ok')))
    else:
        print('  FAIL baseline\n' + cout)
        failures += 1

    modeText = open(MODE, encoding='utf-8').read()
    table = ([(SNAP, text, m) for m in SNAP_MUTATIONS] +
             [(MODE, modeText, m) for m in MODE_MUTATIONS])
    for n, (src, srcText, (label, old, new)) in enumerate(table):
        if srcText.count(old) != 1:
            print('  FAIL mutation %-52s anchor found %d times' % (label, srcText.count(old)))
            failures += 1
            continue
        path = os.path.join(work, 'mut%d.m' % n)
        open(path, 'w', encoding='utf-8').write(srcText.replace(old, new))
        exe = os.path.join(work, 'mut%d' % n)
        ok, err = build(path if src == SNAP else SNAP, path if src == MODE else MODE, exe)
        if not ok:
            print('  FAIL mutation %-52s does not build' % label)
            failures += 1
            continue
        rc, cout = run(exe)
        caught = rc != 0 and 'simworld2b: FAIL' in cout
        first = [l.strip() for l in cout.splitlines() if l.strip().startswith('FAIL')]
        print('  %-4s mutation %-52s %s' % ('ok' if caught else 'FAIL', label,
                                            first[0][:70] if caught and first else
                                            ('caught' if caught else 'NOT CAUGHT')))
        failures += 0 if caught else 1

    print('sim_r2b: %s' % ('PASS' if not failures else 'FAIL (%d)' % failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
