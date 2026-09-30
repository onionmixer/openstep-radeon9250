/*
 * osrdn_modelog.m - the first mode set's evidence, printed after the sequence.
 *
 * Why its own unit: osrdn_mode.m must not log at all (the kernel VGA console
 * drives the same I/O ports its snapshot reads, docs/R2B_IMPL_PLAN.md 12-9),
 * and osrdn_record.m must stay byte-identical to the module that was verified
 * on the machine as R2b-0 (its hash is tracked by tools/r2b0/sim_r2b0.py).
 *
 * Every line here is printed AFTER osrdn_mode_enter or osrdn_mode_revert has
 * returned, from the class.  It reads only the state those left behind.
 */

#import <driverkit/generalFuncs.h>      /* IOLog */
#import "osrdn_modelog.h"

/* the REC3D lines print four registers each (docs/R6C_PLAN.md 8) */
typedef char osrdnR3CountIsFourWide[(CP_R6_REC_COUNT % 4 == 0) ? 1 : -1];
typedef char osrdnCovIsEightWide[(CP_R6_COV_WORDS % 8 == 0) ? 1 : -1];
typedef char osrdnPlaneIsEightWide[(CP_R6_PLANE_WORDS % 8 == 0) ? 1 : -1];

void
osrdn_mode_lines(const osrdn_mode_state *mode)
{
    int k;

    IOLog("RDN-R2B mode why=%d step=%d refdiv=%u div3=%08x bad=%d written=%d snap=%d gate=%d gval=%08x swhy=%d\n",
          mode->why, mode->step, (unsigned int)mode->refdiv, (unsigned int)mode->div3,
          mode->verifyBad, mode->modeWritten, mode->snapshotValid,
          mode->clientWhich, (unsigned int)mode->clientValue, mode->snap.why);
    IOLog("RDN-R2B wait aw=%u ar=%u awl=%u arl=%u lim=%d/%d settle=%u rsettle=%u\n",
          (unsigned int)mode->atomicWriteUs, (unsigned int)mode->atomicReadUs,
          (unsigned int)mode->atomicWriteLoops, (unsigned int)mode->atomicReadLoops,
          mode->atomicWriteLimit, mode->atomicReadLimit,
          (unsigned int)mode->settleUs, (unsigned int)mode->revertSettleUs);
    osrdn_wait_lines(mode);
    for (k = 0; k < OSRDN_SNAP_MMIO_COUNT; k++)
        IOLog("RDN-R2B reg %s snap=%08x got=%08x\n", osrdnSnapMmio[k].name,
              (unsigned int)mode->snap.mmio[k], (unsigned int)mode->verifyGot[k]);
    for (k = 0; k < OSRDN_SNAP_PLL_COUNT; k++)
        IOLog("RDN-R2B pll %s snap=%08x got=%08x\n", osrdnSnapPll[k].name,
              (unsigned int)mode->snap.pll[k], (unsigned int)mode->verifyPll[k]);
    IOLog("RDN-R2B vga misc=%02x crtcport=%03x taken=%d seq0=%02x crtc0=%02x gr0=%02x attr10=%02x\n",
          mode->snap.vgaMisc, mode->snap.crtcPort, mode->snap.vgaTaken,
          mode->snap.vgaSeq[0], mode->snap.vgaCrtc[0], mode->snap.vgaGr[0],
          mode->snap.vgaAttr[0x10]);
}

void
osrdn_revert_lines(const osrdn_mode_state *mode)
{
    int k;

    IOLog("RDN-R2B cycle n=%u why=%d checked=%d cwhy=%d bad=%d vga=%d palette=%d kernel=%d verdict=%d\n",
          (unsigned int)mode->cycleCount, mode->cycleWhy, mode->revertChecked,
          mode->revertCheckWhy, mode->revertBad, mode->revertVgaBad,
          mode->revertPaletteBad, mode->kernelRevertSeen, mode->revertVerdict);
    /* the separating measurement: both words as they read BEFORE the wait and
       before any re-entry, and how long the trigger bit took to clear */
    IOLog("RDN-R2B trig first_off=%08x first_cntl=%08x turns=%u pending=%d\n",
          (unsigned int)mode->revertOffsetFirst[0], (unsigned int)mode->revertOffsetFirst[1],
          (unsigned int)mode->revertOffsetTurns, mode->revertOffsetPending);
    if (!mode->revertChecked)
        return;
    /* name the VGA bytes that did not come back: kind 1 MISC 2 SEQ 3 CRTC
       4 GR 5 ATTR, then the index inside that group */
    for (k = 0; k < OSRDN_VGA_NAMED && k < mode->revertVgaBad; k++)
        IOLog("RDN-R2B backvga kind=%d index=%02x snap=%02x got=%02x\n",
              mode->revertVgaKind[k], mode->revertVgaIndex[k],
              mode->revertVgaWant[k], mode->revertVgaGot[k]);
    for (k = 0; k < OSRDN_SNAP_MMIO_COUNT; k++)
        IOLog("RDN-R2B back %s snap=%08x got=%08x\n", osrdnSnapMmio[k].name,
              (unsigned int)mode->snap.mmio[k], (unsigned int)mode->revertGot[k]);
    for (k = 0; k < OSRDN_SNAP_PLL_COUNT; k++)
        IOLog("RDN-R2B backpll %s snap=%08x got=%08x\n", osrdnSnapPll[k].name,
              (unsigned int)mode->snap.pll[k], (unsigned int)mode->revertPll[k]);
}

void
osrdn_verify_line(const osrdn_mode_state *mode)
{
    const osrdn_res_row *r = osrdn_res(mode->res);
    const osrdn_fmt_row *f = osrdn_fmt(mode->fmt);

    /* two lines, each well under the longest this machine has delivered */
    IOLog("RDN-R3 verify res=%ux%u fmt=%s sel=%d want=%u got=%u fifo=%08x dac=%08x\n",
          r ? r->width : 0U, r ? r->height : 0U, f ? f->token : "none", mode->selected,
          f ? f->crtcFormat : 0U, (unsigned int)mode->verifyFormat,
          (unsigned int)mode->verifyGot[SNAP_GRPH_BUFFER_CNTL],
          (unsigned int)mode->verifyGot[SNAP_DAC_CNTL]);
    IOLog("RDN-R3 verifylut bad=%d k=%d got=%08x want=%08x dim=%d gray=%d xfer=%d\n",
          mode->verifyLutBad, mode->verifyLutIndex,
          (unsigned int)mode->verifyLutGot, (unsigned int)mode->verifyLutWant,
          mode->dim, mode->grayLevels, mode->xferCount);
    /* a table or brightness that arrived during the entry was applied as it
       let go: its read-back is otherwise logged nowhere (24-11) */
    IOLog("RDN-R3 lutapply applied=%u deferred=%u bad=%d k=%d\n",
          (unsigned int)mode->lutApplied, (unsigned int)mode->lutDeferred,
          mode->applyLutBad, mode->applyLutIndex);
}

/* The table itself is summarised, not dumped: its sum, its ends, and whether
 * it is the identity ramp for its length (a table that changes the picture
 * is then visible in the log, 24-9 B7). */
void
osrdn_xfer_line(const osrdn_mode_state *mode, const unsigned int *table, int count, int result)
{
    const osrdn_fmt_row *f = osrdn_fmt(mode->fmt);
    unsigned long        sum = 0, want;
    int                  k, ident = 1, n, mono;

    mono = (f != 0 && f->ioColorSpace == 1);    /* IO_OneIsWhiteColorSpace: the low byte */
    n = (table == 0 || count <= 0) ? 0 : ((count > 256) ? 256 : count);
    for (k = 0; k < n; k++) {
        sum += (unsigned long)table[k];
        want = (n > 1) ? ((unsigned long)k * 255UL) / (unsigned long)(n - 1) : 255UL;
        if (mono ? ((table[k] & 0xffU) != want)
                             : (((table[k] >> 8) & 0xffffffU) != (want | (want << 8) | (want << 16))))
            ident = 0;
    }
    IOLog("RDN-R3 xfer n=%u count=%d result=%d applied=%u deferred=%u stored=%u lutbad=%d k=%d\n",
          (unsigned int)mode->xferCalls, count, result, (unsigned int)mode->lutApplied,
          (unsigned int)mode->lutDeferred, (unsigned int)mode->lutStored,
          mode->applyLutBad, mode->applyLutIndex);
    IOLog("RDN-R3 xferdata sum=%08x first=%08x last=%08x ident=%d\n", (unsigned int)sum,
          n ? table[0] : 0U, n ? table[n - 1] : 0U, n ? ident : 0);
}

void
osrdn_bright_line(const osrdn_mode_state *mode, int level, int result)
{
    IOLog("RDN-R3 bright n=%u level=%d result=%d applied=%u deferred=%u lutbad=%d\n",
          (unsigned int)mode->brightCalls, level, result, (unsigned int)mode->lutApplied,
          (unsigned int)mode->lutDeferred, mode->applyLutBad);
}

/* Every bounded wait, entry and revert apart: evaluations (counted before the
 * early-success test, so "ran" is > 0) and whether it ended on a limit.  The
 * R2 gate asks for both (PLAN.md R2, docs/R2_CLOSEOUT.md 8). */
void
osrdn_wait_lines(const osrdn_mode_state *mode)
{
    /* sh= was step 13's two-second look, removed by REL3; hs= is the sync
       adjustment the last entry used and whether the row refused it */
    IOLog("RDN-R2B waits enter aw=%u/%d ar=%u/%d%s ps=%u/%d hs=%d/%d\n",
          (unsigned int)mode->wAtomicW.evals, mode->wAtomicW.limit,
          (unsigned int)mode->wAtomicR.evals, mode->wAtomicR.limit,
          mode->atomicReadSkipped ? "(skipped)" : "",
          (unsigned int)mode->wSettle.evals, mode->wSettle.limit,
          (int)mode->hsyncAdj, mode->hsyncRefused);
    IOLog("RDN-R2B waits revert raw=%u/%d rar=%u/%d%s rps=%u/%d rss=%u/%d trig=%u/%d\n",
          (unsigned int)mode->wRevAtomicW.evals, mode->wRevAtomicW.limit,
          (unsigned int)mode->wRevAtomicR.evals, mode->wRevAtomicR.limit,
          mode->revAtomicReadSkipped ? "(skipped)" : "",
          (unsigned int)mode->wRevSettle.evals, mode->wRevSettle.limit,
          (unsigned int)mode->wRevSlot.evals, mode->wRevSlot.limit,
          (unsigned int)mode->wRevTrig.evals, mode->wRevTrig.limit);
}

/* ---- R4: the engine test ---------------------------------------------------
 * Every value through (unsigned int) and %08x or %u: this kernel's sprintf
 * ignores the width of an l-qualified conversion (memory: %08lx printed 303).
 * RECORD's 24 words go out as three lines of eight, well inside the message
 * buffer (the R3b-0 burst lesson). */
static const char *const engRecNames[ENG_REC_COUNT] = {
    "rbbm", "csq", "dc2", "dc3", "dcs", "dc2mode", "rb3d", "defoff",
    "defpitch", "defsc", "sctl", "scbr", "auxsc", "dtype", "gmc", "dpcntl",
    "wmask", "dstpo", "srcpo", "brush", "surf", "sclk", "sclkmore", "pwrmgt"
};

static const char *
engOpName(int op)
{
    if (op == ENG_OP_RECORD)
        return "record";
    if (op == ENG_OP_FILL)
        return "fill";
    if (op == ENG_OP_BLIT)
        return "blit";
    if (op == ENG_OP_UBLIT)
        return "ublit";
    return "bad";
}

void
osrdn_engine_line(const osrdn_engine_state *e, unsigned long nonce, int rc)
{
    int k;

    IOLog("RDN-R4 %s boot=%08x n=%u arg=%08x rc=%d why=%d gv=%08x us=%u latched=%d win=%08x\n",
          engOpName(e->op), (unsigned int)nonce, (unsigned int)e->ops, (unsigned int)e->arg,
          rc, e->why, (unsigned int)e->gateValue, (unsigned int)e->elapsedUs, e->latched,
          (unsigned int)e->winStart);
    /* a refused RECORD still shows the words the gate read (code review 6) */
    if (e->op == ENG_OP_RECORD && rc == ENG_RC_REFUSED && e->why >= ENG_WHY_FIFO && e->why <= ENG_WHY_REACH)
        rc = ENG_RC_RAN;
    /* R4c: where the user's words first failed to read back (docs/R4C_VMAP_PLAN.md 11-2) */
    if (rc == ENG_RC_REFUSED && e->why == ENG_WHY_USER)
        IOLog("RDN-R4 user bad=%u first=%d\n", (unsigned int)e->gateValue, (int)e->first);
    if (rc != ENG_RC_RAN && rc != ENG_RC_POST_TIMEOUT && rc != ENG_RC_PRE_TIMEOUT)
        return;
    if (e->op == ENG_OP_RECORD) {
        for (k = 0; k < ENG_REC_COUNT; k += 8)
            IOLog("RDN-R4 rec%d %s=%08x %s=%08x %s=%08x %s=%08x %s=%08x %s=%08x %s=%08x %s=%08x\n", k / 8,
                  engRecNames[k], (unsigned int)e->rec[k], engRecNames[k + 1], (unsigned int)e->rec[k + 1],
                  engRecNames[k + 2], (unsigned int)e->rec[k + 2], engRecNames[k + 3], (unsigned int)e->rec[k + 3],
                  engRecNames[k + 4], (unsigned int)e->rec[k + 4], engRecNames[k + 5], (unsigned int)e->rec[k + 5],
                  engRecNames[k + 6], (unsigned int)e->rec[k + 6], engRecNames[k + 7], (unsigned int)e->rec[k + 7]);
        return;
    }
    IOLog("RDN-R4 res in=%u not=%u out=%u decoy=%u guard=%u first=%d f64=%u reread=%d defsave=%08x left=%d post=%08x\n",
          (unsigned int)e->inBad, (unsigned int)e->notBad, (unsigned int)e->outBad,
          (unsigned int)e->decoyBad, (unsigned int)e->guardBad, (int)e->first, (unsigned int)e->f64,
          e->rereadDone ? (int)e->reread : -1, (unsigned int)e->defaultSaved, e->defaultLeft,
          (unsigned int)e->postStatus);
    IOLog("RDN-R4 wait fifo=%u/%d/%u idle=%u/%d/%u dc2=%08x:%u/%d dc3=%08x:%u/%d idle2=%u/%d rst=%u/%d\n",
          (unsigned int)e->wFifo.evals, e->wFifo.limit, (unsigned int)e->wFifo.us,
          (unsigned int)e->wIdle.evals, e->wIdle.limit, (unsigned int)e->wIdle.us,
          (unsigned int)e->dc2Pre, (unsigned int)e->wDc2.evals, e->wDc2.limit,
          (unsigned int)e->dc3Pre, (unsigned int)e->wDc3.evals, e->wDc3.limit,
          (unsigned int)e->wIdle2.evals, e->wIdle2.limit,
          (unsigned int)e->wRestore.evals, e->wRestore.limit);
}

/* ---- R5: the CP (docs/R5_PLAN.md 8) ---------------------------------------- */

static const char *const cpRecNames[CP_REC_COUNT] = {
    "rbbm", "csq", "csqmode", "csqstat", "rbbase", "rbcntl", "rptr", "wptr",
    "rptraddr", "wdelay", "umsk", "saddr", "s0", "s1", "s2", "s5",
    "aic", "aicstat", "ptbase", "lo", "hi", "agploc", "agpbase", "agpbase2",
    "bus", "isync", "intcntl", "intstat", "coloff", "depthoff", "meaddr", "mcfb",
    "sclk", "mclk", "softreset", "agpcmd"
};

/* the MAP gate's read-backs, in CP_MG_ order (osrdn_cp.h) */
static const char *const cpMgNames[CP_MG_COUNT] = {
    "rbcntl", "umsk", "ptbase", "lo", "hi", "aic", "rbbase", "rptraddr", "rptr", "wptr",
    "intcntl", "agploc", "s5", "agpcmd", "aicstat"
};

/* a table, not a switch: cc makes a dense switch a jump table, and the reloc
   gate refuses every indirect jump (tools/r2b0/check_reloc_r2b0.py) */
/*
 * M1z: DECLARED WITHOUT A SIZE, deliberately.
 *
 * It used to say [CP_OP_LAST + 1] with fifteen names for sixteen slots, and C89
 * filled the sixteenth -- CP_OP_TDUMP -- with a null.  The check below compared
 * sizeof(cpOpNames)/sizeof(*cpOpNames) against CP_OP_LAST + 1, which is the very
 * constant that declared the array: 16 == 16, an identity that can never fail.
 * So the kernel printed a null through %s and the machine's log carries
 *   "RDN-R5 S? boot=e71333f7 n=28046 ..."  -- a real line from a real boot.
 * With no size, sizeof counts the INITIALISERS and the check below is real:
 * leave a name out and the build stops.
 */
static const char *const cpOpNames[] = {
    "bad", "record", "load", "map", "reset", "start", "submit", "negctl", "stop", "inject",
    "rec3d", "zprep", "zclear", "plane", "quiet", "tdump", "nowb", "spin", "time", "loud",
    "present", "clear", "asubmit", "retire"
};
/* C89 fills a short initialiser with nulls and says nothing, so the count is
   checked here rather than trusted -- a missing name would print "(null)" in
   the kernel, or fault. */
typedef char cpOpNamesFull[(sizeof(cpOpNames) / sizeof(cpOpNames[0]) ==
                            CP_OP_LAST + 1) ? 1 : -1];

static const char *
cpOpName(int op)
{
    if (op < CP_OP_RECORD || op > CP_OP_LAST)
        return "bad";
    return cpOpNames[op];
}

/* one digest (tools/r6/zclear_oracle.py digest) */
static void
cpDigestLine(const char *tag, int pass, const osrdn_cp_digest *d)
{
    IOLog("RDN-R6 %s%d xor=%08x wsum=%08x changed=%u ixor=%u isum=%u n=%d v=%08x,%08x,%08x,%08x\n", tag, pass,
          (unsigned int)d->xr, (unsigned int)d->wsum, (unsigned int)d->changed, (unsigned int)d->ixor,
          (unsigned int)d->isum, d->nvals, (unsigned int)d->vals[0], (unsigned int)d->vals[1],
          (unsigned int)d->vals[2], (unsigned int)d->vals[3]);
}

/*
 * M3c: THE HEAD LINE ON ITS OWN.  A quiet client submission that is REFUSED
 * prints this and nothing else -- rc, why and the gate that held -- because
 * after a latch every submission is refused and the full lines would push the
 * one that matters out of the 4 KB message buffer (docs/M3C_PLAN.md 2).  One
 * format string, used by both.
 */
void
osrdn_cp_head(const osrdn_cp_state *c, unsigned long nonce, int rc)
{
    IOLog("RDN-R5 %s boot=%08x n=%u arg=%08x len=%u rc=%d why=%d gv=%08x greg=%04x us=%u\n",
          cpOpName(c->op), (unsigned int)nonce, (unsigned int)c->ops, (unsigned int)c->arg,
          (unsigned int)c->len, rc, c->why, (unsigned int)c->gateValue, (unsigned int)c->gateReg,
          (unsigned int)c->elapsedUs);
}

void
osrdn_cp_latch_words(const osrdn_cp_state *c, unsigned long nonce)
{
    unsigned long k;

    if (!c->latchRead)
        return;
    for (k = 0; k < CP_LATCH_FIFO_WORDS; k += 8UL)
        IOLog("RDN-R5 fifo boot=%08x at=%u %08x %08x %08x %08x %08x %08x %08x %08x\n",
              (unsigned int)nonce, (unsigned int)k,
              (unsigned int)c->fifo[k], (unsigned int)c->fifo[k + 1], (unsigned int)c->fifo[k + 2],
              (unsigned int)c->fifo[k + 3], (unsigned int)c->fifo[k + 4], (unsigned int)c->fifo[k + 5],
              (unsigned int)c->fifo[k + 6], (unsigned int)c->fifo[k + 7]);
    for (k = 0; k < CP_LATCH_RING_WORDS; k += 8UL)
        IOLog("RDN-R5 near boot=%08x at=%u %08x %08x %08x %08x %08x %08x %08x %08x\n",
              (unsigned int)nonce, (unsigned int)((c->ringNearAt + k) & (CP_RING_WORDS - 1UL)),
              (unsigned int)c->ringNear[k], (unsigned int)c->ringNear[k + 1], (unsigned int)c->ringNear[k + 2],
              (unsigned int)c->ringNear[k + 3], (unsigned int)c->ringNear[k + 4], (unsigned int)c->ringNear[k + 5],
              (unsigned int)c->ringNear[k + 6], (unsigned int)c->ringNear[k + 7]);
}

void
osrdn_cp_lines(const osrdn_cp_state *c, unsigned long nonce, int rc)
{
    int k;

    osrdn_cp_head(c, nonce, rc);
    IOLog("RDN-R5 state state=%d latched=%d reset=%d failed=%d wptr=%u phys=%08x post=%08x csqstat=%08x csq2stat=%08x csqread=%d nowb=%d spin=%u time=%d\n",
          c->state, c->latched, c->resetDone, c->failed, (unsigned int)c->wptr, (unsigned int)c->phys,
          (unsigned int)c->postStatus, (unsigned int)c->csqStat, (unsigned int)c->csq2Stat, c->csqRead,
          !c->doWb, (unsigned int)c->spin, c->timeOn);   /* M2a/M2b/M2c: no transcript
                                              may be read without knowing these three */
    /* M3i: what the CP said the moment the wait ran out (raw: CP_STAT has no
       documented layout, CSQ_STAT two competing ones -- decoded on the host) */
    if (c->latchRead)
        IOLog("RDN-R5 latch cpstat=%08x rptr=%08x wptr=%08x wptrread=%u csqstat=%08x csq2stat=%08x csqmode=%08x nearat=%u nearbad=%u kick=%u/%u kickrptr=%u moved=%d kus=%u/t%u recover=%d recovers=%u\n",
              (unsigned int)c->cpStat, (unsigned int)c->rbRptr, (unsigned int)c->rbWptr,
              (unsigned int)c->wptrRead, (unsigned int)c->csqStat, (unsigned int)c->csq2Stat,
              (unsigned int)c->csqMode, (unsigned int)c->ringNearAt, (unsigned int)c->ringNearBad,
              (unsigned int)c->kickWptr, (unsigned int)c->kickWptrRead, (unsigned int)c->kickRptr,
              c->kickMoved, (unsigned int)c->wKick.us, (unsigned int)c->wKick.turns,
              c->recoverKind, (unsigned int)c->recovers);
    /*
     * M1x: the stage times, and ONLY for the operation that asked for them.
     *
     * The shape starts `RDN-R5 tstage` -- the word before `boot=` -- so it can
     * never be read as an operation line, which the runner selects by
     * `boot=<nonce> n=` (recorded).
     */
    if (c->op == CP_OP_TDUMP) {
        /* M1z: fence and wait go LAST, after tail=, so every reader that keys on
           the prefix up to tail= keeps working (tools/mesa/judge_m1l.py does). */
        IOLog("RDN-R5 tstage boot=%08x ops=%u gates=%u pre=%u s1ring=%u "
              "s1read=%u s2asm=%u s2ring=%u flush=%u tail=%u fence=%u wait=%u put=%u\n",
              (unsigned int)nonce, (unsigned int)c->tDumpN,
              (unsigned int)c->tDump[0], (unsigned int)c->tDump[1],
              (unsigned int)c->tDump[2], (unsigned int)c->tDump[3],
              (unsigned int)c->tDump[4], (unsigned int)c->tDump[5],
              (unsigned int)c->tDump[6], (unsigned int)c->tDump[7],
              (unsigned int)c->tDump[CP_T_FENCE], (unsigned int)c->tDump[CP_T_WAIT],
              (unsigned int)c->tDump[CP_T_PUT]);
    }
    /*
     * G5-2 (docs/G5_2_ASYNC_SUBMIT_PLAN.md 2): the accepted submissions and their retirement, on
     * the operations that are about them and on a latch -- never on a quiet one, which does not
     * come here.  Sticky counters, so one RETIRE or TDUMP at the end of a run says the whole run.
     */
    if (c->op == CP_OP_ASUBMIT || c->op == CP_OP_RETIRE || c->op == CP_OP_TDUMP || c->latchRead)
        IOLog("RDN-R5 async boot=%08x asubmits=%u inflight=%d retires=%u waited=%u retireus=%u last=%u "
              "markbad=%u lost=%u space=%u spaceus=%u sres=%u kickskip=%u\n",
              (unsigned int)nonce, (unsigned int)c->asubmits, c->inflight, (unsigned int)c->retires,
              (unsigned int)c->retireWaited, (unsigned int)c->retireUs, (unsigned int)c->retireLastUs,
              (unsigned int)c->retireMarkBad, (unsigned int)c->lostInflight, (unsigned int)c->spaceWaits,
              (unsigned int)c->spaceUs, (unsigned int)c->wSpace.resets, (unsigned int)c->kickSkipped);
    IOLog("RDN-R5 io wr=%u rd=%u aicstat=%08x inject=%u injected=%d\n", (unsigned int)c->ioWr,
          (unsigned int)c->ioRd, (unsigned int)c->aicStat, (unsigned int)c->injectCount, c->latchInjected);
    if (c->op == CP_OP_REC3D)
        for (k = 0; k < CP_R6_REC_COUNT; k += 4)     /* CP_R6_REC_COUNT % 4 == 0 (typedef above) */
            IOLog("RDN-R6 r3 %04x=%08x %04x=%08x %04x=%08x %04x=%08x\n",
                  (unsigned int)osrdnCpR3Regs[k], (unsigned int)c->r3[k],
                  (unsigned int)osrdnCpR3Regs[k + 1], (unsigned int)c->r3[k + 1],
                  (unsigned int)osrdnCpR3Regs[k + 2], (unsigned int)c->r3[k + 2],
                  (unsigned int)osrdnCpR3Regs[k + 3], (unsigned int)c->r3[k + 3]);
    if (c->op == CP_OP_ZCLEAR && c->covValid)   /* R6d: the coverage map, eight words a line */
        for (k = 0; k < CP_R6_COV_WORDS; k += 8)
            IOLog("RDN-R6 cov%d %08x %08x %08x %08x %08x %08x %08x %08x\n", k / 8,
                  (unsigned int)c->cov[k], (unsigned int)c->cov[k + 1], (unsigned int)c->cov[k + 2],
                  (unsigned int)c->cov[k + 3], (unsigned int)c->cov[k + 4], (unsigned int)c->cov[k + 5],
                  (unsigned int)c->cov[k + 6], (unsigned int)c->cov[k + 7]);
    /* R6e: one log block must stay well under MSG_BSIZE (4084 bytes, bsd/sys/msgbuf.h) -- the
       planes leave through PLANE, 64 words at a time (docs/R6E_PLAN.md 13) */
    if (c->op == CP_OP_ZCLEAR && c->planeValid && c->planeZop == c->ops)
        IOLog("RDN-R6 off %u %u %u %u lanes=%x\n", (unsigned int)c->laneOff[0], (unsigned int)c->laneOff[1],
              (unsigned int)c->laneOff[2], (unsigned int)c->laneOff[3], (unsigned int)c->planeLanes);
    if (c->op == CP_OP_PLANE && rc == CP_RC_RAN) {
        int l = (int)(c->planeChunk >> 2), base = (int)(c->planeChunk & 3UL) * 64;

        IOLog("RDN-R6 plh boot=%08x zc=%u case=%d lane=%d chunk=%d src=%u\n", (unsigned int)nonce,
              (unsigned int)c->planeZop, c->planeZcase, l, (int)(c->planeChunk & 3UL),
              (unsigned int)c->planeSrc);                                   /* R6f: 0 colour, 1/2 depth 24/16 */
        for (k = base; k < base + 64; k += 8)
            IOLog("RDN-R6 pl%d %d %08x %08x %08x %08x %08x %08x %08x %08x\n", l, k / 8,
                  (unsigned int)c->plane[l][k], (unsigned int)c->plane[l][k + 1], (unsigned int)c->plane[l][k + 2],
                  (unsigned int)c->plane[l][k + 3], (unsigned int)c->plane[l][k + 4], (unsigned int)c->plane[l][k + 5],
                  (unsigned int)c->plane[l][k + 6], (unsigned int)c->plane[l][k + 7]);
    }
    if (c->op == CP_OP_ZPREP)
        IOLog("RDN-R6 zprep bad=%u\n", (unsigned int)c->prepBad);
    if (c->op == CP_OP_ZCLEAR) {
        IOLog("RDN-R6 zclear case=%d stage=%d surf=%08x reg0=%08x reg2=%08x prebad=%02x pfbad=%u\n", c->zcase, c->zstage,
              (unsigned int)c->surfaceCntl, (unsigned int)c->zreg0, (unsigned int)c->zreg2, (unsigned int)c->prefixBad,
              (unsigned int)c->pfBad);                                  /* R6g: the CPU prefill's read-back */
        IOLog("RDN-R6 zpre %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x\n", (unsigned int)c->pre[0],
              (unsigned int)c->pre[1], (unsigned int)c->pre[2], (unsigned int)c->pre[3], (unsigned int)c->pre[4],
              (unsigned int)c->pre[5], (unsigned int)c->pre[6], (unsigned int)c->pre[7], (unsigned int)c->pre[8],
              (unsigned int)c->pre[9], (unsigned int)c->pre[10], (unsigned int)c->pre[11]);     /* G4-9: twelve (CP_R6_PRE_COUNT) */
        for (k = 0; k < 2; k++) {
            cpDigestLine("zd", k, &c->dDepth[k]);
            cpDigestLine("zc", k, &c->dColor[k]);
        }
        if (c->zcase == CP_R7_CASE)     /* R7a: what the verifier made of the client's stream */
            IOLog("RDN-R7 verify boot=%08x words=%u why=%u at=%u word=%08x win=%08x..%08x dropped=%u\n",
                  (unsigned int)nonce, (unsigned int)c->subWords, (unsigned int)c->r7Why,
                  (unsigned int)c->r7At, (unsigned int)c->r7Word,
                  (unsigned int)c->r7WinStart, (unsigned int)c->r7WinEnd,
                  (unsigned int)c->subDropped);
        IOLog("RDN-R6 zsurf coff=%08x zoff=%08x toff=%08x texbad=%u at=%u val=%08x\n",
              (unsigned int)c->zColorOff, (unsigned int)c->zDepthOff, (unsigned int)c->zTexOff,
              (unsigned int)c->texPost, (unsigned int)c->texPostAt, (unsigned int)c->texPostVal);
        /* M1h: `skipped` is why a 0 may mean "not looked at".  A judge that read
           rest0=0 as "nothing else changed" would be reading a zero nobody
           measured. */
        /* M1m appends dw= at the END on purpose: check_r6a.py's pattern is
           unanchored and treats skipped= as optional, so a field added after
           it is invisible to the readers that do not want it. */
        /* M2g: loud= LAST -- the readers are unanchored (comment above), so a
           field added at the end is invisible to the ones that do not want it */
        IOLog("RDN-R6 zq quiet=%d budget=%u swallowed=%u touch=%08x,%08x loud=%u\n", c->quiet,
              (unsigned int)c->quietBudget, (unsigned int)c->quietSwallowed,
              (unsigned int)c->qTouch[0], (unsigned int)c->qTouch[1],
              (unsigned int)c->loudBudget);
        IOLog("RDN-R6 zr rest0=%u rest1=%u first=%u val=%08x skipped=%u dw=%u\n",
              (unsigned int)c->restChanged[0],
              (unsigned int)c->restChanged[1], (unsigned int)c->restFirst, (unsigned int)c->restFirstVal,
              (unsigned int)c->restSkipped, (unsigned int)c->digestWords);
    }
    if (c->mgDone) {
        IOLog("RDN-R5 mapgate bad=%04x\n", (unsigned int)c->mgBad);
        for (k = 0; k < CP_MG_COUNT; k += 5)
            IOLog("RDN-R5 mg%d %s=%08x %s=%08x %s=%08x %s=%08x %s=%08x\n", k / 5,
                  cpMgNames[k], (unsigned int)c->mg[k], cpMgNames[k + 1], (unsigned int)c->mg[k + 1],
                  cpMgNames[k + 2], (unsigned int)c->mg[k + 2], cpMgNames[k + 3], (unsigned int)c->mg[k + 3],
                  cpMgNames[k + 4], (unsigned int)c->mg[k + 4]);
    }
    if (c->op == CP_OP_RECORD) {
        for (k = 0; k < CP_REC_COUNT; k += 6)
            IOLog("RDN-R5 rec%d %s=%08x %s=%08x %s=%08x %s=%08x %s=%08x %s=%08x\n", k / 6,
                  cpRecNames[k], (unsigned int)c->rec[k], cpRecNames[k + 1], (unsigned int)c->rec[k + 1],
                  cpRecNames[k + 2], (unsigned int)c->rec[k + 2], cpRecNames[k + 3], (unsigned int)c->rec[k + 3],
                  cpRecNames[k + 4], (unsigned int)c->rec[k + 4], cpRecNames[k + 5], (unsigned int)c->rec[k + 5]);
    }
    if (c->op == CP_OP_RESET)
        IOLog("RDN-R5 reset mclk=%08x forced=%08x after=%08x idx=%08x idxafter=%08x soft=%08x softafter=%08x\n",
              (unsigned int)c->mclkBefore, (unsigned int)c->mclkForced, (unsigned int)c->mclkAfter,
              (unsigned int)c->indexBefore, (unsigned int)c->indexAfter, (unsigned int)c->softBefore,
              (unsigned int)c->softAfter);
    if (c->op == CP_OP_SUBMIT || c->op == CP_OP_NEGCTL || c->op == CP_OP_INJECT) {
        IOLog("RDN-R5 marks m0=%08x m1=%08x m2=%08x s0=%08x s1=%08x s2=%08x\n",
              (unsigned int)c->marker[0], (unsigned int)c->marker[1], (unsigned int)c->marker[2],
              (unsigned int)c->sentinel[0], (unsigned int)c->sentinel[1], (unsigned int)c->sentinel[2]);
        IOLog("RDN-R5 got g0=%08x g1=%08x g2=%08x straddle=%d boundary=%u\n",
              (unsigned int)c->got[0], (unsigned int)c->got[1], (unsigned int)c->got[2], c->straddle,
              (unsigned int)c->boundary);
    }
    IOLog("RDN-R5 ptrs rbefore=%u rafter=%u wafter=%u reg5=%08x roff=%08x woff=%08x\n",
          (unsigned int)c->rptrBefore, (unsigned int)c->rptrAfter, (unsigned int)c->wptrAfter,
          (unsigned int)c->reg5, (unsigned int)c->rptrOff, (unsigned int)c->wptrOff);
    IOLog("RDN-R5 block table=%u guard=%u spare=%u canary=%u ring=%u sum=%08x xor=%08x\n",
          (unsigned int)c->tableBad, (unsigned int)c->guardBad, (unsigned int)c->spareBad,
          (unsigned int)c->canaryBad, (unsigned int)c->ringBad, (unsigned int)c->pteSum,
          (unsigned int)c->pteXor);
    /* M2b: `t` beside each eval count.  With the spin knob on, evals stops being
       the number of turns, and a reader with only evals cannot tell how often
       the driver actually slept. */
    IOLog("RDN-R5 wait fifo=%u/%d/t%u idle=%u/%d/%u/t%u rptr=%u/%d/%u/t%u idle2=%u/%d/t%u dc=%u/%d/t%u retry=%u resets=%u\n",
          (unsigned int)c->wFifo.evals, c->wFifo.limit, (unsigned int)c->wFifo.turns,
          (unsigned int)c->wIdle.evals, c->wIdle.limit, (unsigned int)c->wIdle.us,
          (unsigned int)c->wIdle.turns,
          (unsigned int)c->wRptr.evals, c->wRptr.limit, (unsigned int)c->wRptr.us,
          (unsigned int)c->wRptr.turns,
          (unsigned int)c->wIdle2.evals, c->wIdle2.limit, (unsigned int)c->wIdle2.turns,
          (unsigned int)c->wDc.evals, c->wDc.limit, (unsigned int)c->wDc.turns,
          (unsigned int)c->wIdle.retries, (unsigned int)c->wRptr.resets);   /* G4-3 K1, at the END so old readers still parse */
}
