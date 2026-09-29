/*
 * osrdn_mode.h - the R2b first mode set: entry and revert.
 *
 * docs/R2_FIRST_LIGHT_PLAN.md sections 4 and 5, docs/R2B_IMPL_PLAN.md.
 *
 * Contract, in one place:
 *   - nothing is written before the snapshot is complete;
 *   - modeWritten is set immediately before the first write (the blank) and
 *     cleared at the end of the revert;
 *   - a failure after modeWritten calls the revert HERE: -enterLinearMode
 *     returns void, so the kernel cannot be told and will not call the revert
 *     for us (docs/R2B_IMPL_PLAN.md 12-4);
 *   - the revert never breaks off early: a wait that reaches its limit is
 *     recorded and the sequence continues, because stopping loses the console;
 *   - every register the entry writes is in osrdn_snap's tables, which is
 *     what the revert writes back.
 *
 * Nothing here logs.  The kernel VGA console drives the same I/O ports the
 * snapshot reads, so a log line inside would invalidate it; the results are
 * left in osrdn_mode_state for the record to print afterwards.
 */

#import <driverkit/kernelDriver.h>
#import "osrdn_snap.h"
#import "osrdn_modesel.h"      /* the chosen resolution and format (R3b-2) */
#import "osrdn_engine.h"       /* the R4 engine test runs under this module's claim */
#import "osrdn_cp.h"           /* R5: the CP runs under it too, and every revert stops it first */

/* why an entry refused or latched */
#define MODE_WHY_NONE           0
#define MODE_WHY_NO_BASE        1
#define MODE_WHY_SNAPSHOT       2       /* the snapshot itself refused */
#define MODE_WHY_REFDIV         3       /* PPLL_REF_DIV has no row for the chosen resolution,
                                           or it is no longer the value the snapshot read */
#define MODE_WHY_PLL_STATE      4       /* PPLL_CNTL or VCLK_ECP_CNTL not as expected */
#define MODE_WHY_CRTC_STATE     5       /* CRTC or the interfering clients not as expected */
#define MODE_WHY_LATCHED        6       /* a previous entry failed after writing */
#define MODE_WHY_VERIFY         7       /* the read-back did not match */
#define MODE_WHY_TEXT_CONSOLE   8       /* the console was a TEXT mode: the snapshot holds no
                                           character generator planes, so the revert could bring
                                           the timing back and still show nothing readable.  The
                                           reference driver refuses its restore for this reason
                                           (OpenStepMGAReplacementDisplay.m 7622-7629); we refuse
                                           the ENTRY, because a mode we cannot leave is worse. */
#define MODE_WHY_BUSY           9       /* another sequence is in flight (the kernel does not
                                           serialize setIntValues against its own callbacks) */
#define MODE_WHY_NOT_LIVE      10       /* a cycle was asked for with no mode on the card */
#define MODE_WHY_CYCLE_DONE    11       /* one cycle per boot */
#define MODE_WHY_KERNEL_CAME   12       /* the kernel reverted while the cycle held the card */
#define MODE_WHY_CLIENT        13       /* a step-0 condition failed; clientWhich names it */
#define MODE_WHY_NOT_SELECTED  14       /* the class never chose a resolution and format: the
                                           state is a zero-filled ivar, and 0 is 640x480 */
#define MODE_WHY_CP            15       /* a cycle while the CP holds the card or is latched
                                           (docs/R5_PLAN.md 7-2 B3) */

/* the step-0 conditions, in the order modeCheck evaluates them; clientWhich
   holds one of these.  docs/R2_CLOSEOUT.md 11. */
#define GATE_CRTC2              1
#define GATE_FPON               2
#define GATE_CPMODE             3
#define GATE_RBBM               4
#define GATE_GART               5
#define GATE_INTCNTL            6
#define GATE_SCALER             7
#define GATE_I2C                8
#define GATE_VIPH               9
#define GATE_DACSRC             10
#define GATE_DAC2               11
#define GATE_SURFACE            12
#define GATE_HOSTPATH           13
#define GATE_APER0              14
#define GATE_APERSIZE           15
#define GATE_MEMSIZE            16
#define GATE_DISPLAYBASE        17
#define GATE_DIVSEL             18

/* one bounded wait's evidence: how many times its condition was evaluated
   (counted BEFORE the early-success test, so a wait that ran and found the
   condition at once still shows 1) and whether it ended on a limit */
typedef struct {
    unsigned long   evals;
    int             limit;
} osrdn_wait;

/* how many times a bounded wait may go round.  The elapsed-time limits below
 * all rest on IOGetTimestamp advancing; nothing promises it does in every
 * context this code can be called from (shutdown's spl is not ours to know),
 * and a for(;;) that never exits at shutdown never finishes shutting down. */
#define MODE_POLL_LOOPS         200000UL    /* an atomic-update poll: no delay per turn, so the
                                               budget is generous (the machine measured 5 us) */
#define MODE_SETTLE_SLACK       8UL         /* extra turns over the scaled count */
#define MODE_TURN_FACTOR        2UL         /* turns allowed per nominal turn (see modeWaitUs) */
#define MODE_OFFSET_US          100000UL    /* how long to let CRTC_OFFSET's trigger bit clear
                                               before the revert read-back judges anything.  A
                                               frame is ~16.6 ms at this mode's refresh. */

/* CRTC_OFFSET bit 30, RADEON_CRTC_OFFSET__GUI_TRIG_OFFSET (radeon_reg.h 456 and
 * radeonfbreg.h 504).  BOTH reference headers define it for CRTC_OFFSET only:
 * CRTC_OFFSET_CNTL's definitions stop far below bit 30, and xf86 says the two
 * registers are picked up at different times -- "possibly ... the new offset
 * value at the end of each scanline, but the new offset_cntl value only after
 * a vsync" (radeon_driver.c 6099-6104, and it does not claim to be sure).  So
 * the same bit position in CRTC_OFFSET_CNTL is NOT known to mean this; it is
 * only a bit we have seen move with it once, on this machine. */
#define CRTC_OFFSET_GUI_TRIG    0x40000000UL

/* waits, in microseconds */
#define MODE_ATOMIC_US          100000UL    /* 6g and 6i limit */
#define MODE_PLL_SETTLE_US      50000UL     /* 6l, legacy_crtc.c usleep(50000) */
#define MODE_REVERT_SETTLE_US   100000UL    /* revert 4.7, radeon_driver.c usleep(100000) */
#define MODE_SHOW_US            2000000UL   /* step 13, the operator looks; step 12 has already read back */
#define MODE_TICK_MS            5UL         /* one turn of a wait, when we may sleep */
#define MODE_TICK_US            500UL       /* one turn, when we may not (IODelay is a spin, and
                                               doc/driverkit.md 293-309 says it is safe at any
                                               spl while IOSleep is not) */

typedef struct osrdn_mode_state_s {
    osrdn_snap      snap;
    int             snapshotValid;
    int             modeWritten;
    int             latched;            /* a failed entry: refuse the next one */
    int             why;
    int             step;               /* the step that refused or failed */
    unsigned long   enterCount, revertCount;

    /* inputs the class sets once, from what init read */
    unsigned long   bar0;               /* PCI BAR0: CONFIG_APER_0_BASE must equal it */
    unsigned long   mappedLength;       /* the framebuffer length the class MAPPED
                                           (OSRDN_FB_LENGTH), not the mode's memorySize */
    int             res, fmt;           /* rows of osrdn_modesel's tables (R3b-2) */
    int             selected;           /* the class set res and fmt (docs/R3_MULTIMODE_PLAN.md
                                           23-9 B2) */
    int             clientWhich;        /* the step-0 gate that refused, GATE_* */
    osrdn_cp_state *cp;                 /* R5: set once by the class, or 0 */
    unsigned long   clientValue;        /* what that register held */

    /* every bounded wait, entry and revert kept apart (docs/R2_CLOSEOUT.md 8) */
    osrdn_wait      wAtomicW, wAtomicR, wSettle, wShow;
    osrdn_wait      wRevAtomicW, wRevAtomicR, wRevSettle, wRevSlot, wRevTrig;
    int             atomicReadSkipped, revAtomicReadSkipped;

    /* what the waits did, for the record */
    unsigned long   atomicWriteUs, atomicReadUs;
    unsigned long   atomicWriteLoops, atomicReadLoops;
    int             atomicWriteLimit, atomicReadLimit;
    unsigned long   settleUs, revertSettleUs;

    /* the read-back (step 12) */
    unsigned long   verifyGot[OSRDN_SNAP_MMIO_COUNT];
    unsigned long   verifyPll[OSRDN_SNAP_PLL_COUNT];
    int             verifyBad;
    /* R3b-2: what the extended read-back found (23-4) -- the pixel format
     * field, and the first LUT entry that did not come back */
    unsigned long   verifyFormat;       /* CRTC_GEN_CNTL bits 8-11 as read */
    int             verifyLutBad;       /* LUT entries that differ in their top 8 bits */
    int             verifyLutIndex;     /* the first such entry, -1 for none */
    unsigned long   verifyLutGot, verifyLutWant;

    /* The cycle's own evidence.  It may NOT share verifyGot/verifyPll: a
     * re-entry runs modeVerify, which zeroes verifyBad and overwrites both
     * arrays, so the log would describe the re-entry and call it the revert
     * (codex cross-review 1, confirmed in osrdn_mode.m modeVerify). */
    unsigned long   revertGot[OSRDN_SNAP_MMIO_COUNT];
    unsigned long   revertPll[OSRDN_SNAP_PLL_COUNT];
    int             revertBad;          /* MMIO + PLL words that came back wrong */
    int             revertVgaBad;       /* MISC, SEQ, CRTC, GR, ATTR bytes wrong */
    int             revertPaletteBad;   /* palette entries wrong */
    int             revertChecked;      /* the read-back ran at all */
    int             revertCheckWhy;     /* why it did not */

    /* The separating measurement (docs/R2C_REVERT_PLAN.md 13-2).  Read BEFORE
     * the wait and before any re-entry, so the record can tell "the revert's
     * update completed" from "the re-entry overwrote it". */
    unsigned long   revertOffsetFirst[2];   /* CRTC_OFFSET, CRTC_OFFSET_CNTL, unwaited */
    unsigned long   revertOffsetTurns;      /* turns until the trigger bit cleared */
    int             revertOffsetPending;    /* it never cleared inside the bounds */
    int             revertVerdict;          /* 0 clean, 1 pending (offset words only,
                                               each differing by exactly bit 30), 2 real */

    /* WHICH VGA bytes came back wrong.  A count alone cannot be acted on: the
     * first cycle that waited for the offset trigger reported two wrong bytes
     * and the log could not say which (2026-09-16). */
#define OSRDN_VGA_NAMED         6
    unsigned char   revertVgaKind[OSRDN_VGA_NAMED];   /* 1 MISC 2 SEQ 3 CRTC 4 GR 5 ATTR */
    unsigned char   revertVgaIndex[OSRDN_VGA_NAMED];
    unsigned char   revertVgaWant[OSRDN_VGA_NAMED];
    unsigned char   revertVgaGot[OSRDN_VGA_NAMED];
    unsigned long   cycleCount;
    int             cycleWhy;

    /* inputs the caller sets before a sequence */
    int             noSleep;            /* wait with IODelay, not IOSleep */
    int             skipShow;           /* no operator look, and NO TEST PATTERN.  The cycle sets
                                           it: a mode change does not clear the framebuffer, so
                                           not painting is what brings the desktop back.  The
                                           first cycle on the machine painted over the desktop
                                           and the window server, having nothing to redraw for,
                                           left the pattern on screen until the next login
                                           (2026-09-16, operator saw it). */
    int             wantRevertCheck;    /* read the whole snapshot back after the revert.  OFF on
                                           the shutdown path on purpose: that path is what the
                                           machine has already proved, and the check reads 256
                                           palette entries and leaves the palette index where a
                                           snapshot leaves it. */

    /* R3b-2b: the transfer table and the brightness (docs/R3_MULTIMODE_PLAN.md
     * 24).  Stored first, applied under the claim; a zero-filled state means
     * no table and FULL brightness (dim = 64 - level, 24-9 B3). */
    unsigned char   xferRgb[OSRDN_SNAP_PALETTE * 3];
    int             xferCount;          /* 0: no table */
    int             dim;                /* 64 - brightness level, 0..64 */
    int             grayLevels;         /* "Gray Levels": 0 (256), 16, 4 or 2; BW:8 only */
    int             lutPending;         /* a stored change not yet on the card */
    unsigned long   xferCalls, brightCalls;
    unsigned long   lutApplied, lutDeferred, lutStored;
    int             applyLutBad, applyLutIndex;     /* the read-back after the last apply */
    unsigned long   applyLutGot, applyLutWant;

    /* one flag for every sequence, not one per entry point */
    int             inSequence;
    int             kernelRevertSeen;   /* the kernel reverted while a cycle held the card */

    /* which oracle row this boot's refdiv selected */
    unsigned long   refdiv;
    unsigned long   div3;
} osrdn_mode_state;

/* step 10: the test pattern for the chosen resolution and format, into the
   framebuffer the class mapped; it writes nothing past memorySize */
void osrdn_mode_pattern(const osrdn_mode_state *mode, vm_address_t fb);

/* R3b-2b results of osrdn_mode_set_transfer / osrdn_mode_set_brightness */
#define MODE_LUT_IGNORED        0       /* bad arguments, or no resolution chosen yet */
#define MODE_LUT_APPLIED        1       /* on the card now */
#define MODE_LUT_STORED         2       /* kept; no live mode (the next entry uses it) */
#define MODE_LUT_DEFERRED       3       /* kept; another sequence holds the card and applies
                                           it when it lets go */

/* the window server's table: count entries, 32-bit packed; BW formats use the
   low byte, the others bytes 31-24 / 23-16 / 15-8 (S3.m:77-90).  base 0 stores only. */
int osrdn_mode_set_transfer(osrdn_mode_state *mode, vm_address_t base,
                            const unsigned int *table, int count);
/* level 0..64 (ev_types.h EV_SCREEN_MAX_BRIGHTNESS); base 0 stores only */
int osrdn_mode_set_brightness(osrdn_mode_state *mode, vm_address_t base, int level);

/* 1 if the mode is live, 0 if it refused or failed (and then reverted) */
int osrdn_mode_enter(osrdn_mode_state *mode, vm_address_t base, vm_address_t fb);

/* always safe to call; does hardware work only when snapshotValid && modeWritten */
void osrdn_mode_revert(osrdn_mode_state *mode, vm_address_t base);

/* revert, read the whole snapshot back, then come back to the mode.  Once per
 * boot, on the operator's word, so the revert can be judged without waiting
 * for a shutdown that cannot log.  1 if the mode is live again. */
int osrdn_mode_cycle(osrdn_mode_state *mode, vm_address_t base, vm_address_t fb);

/* R4 (docs/R4_ENGINE_PLAN.md 12-1, 13 #8): one engine operation under the
 * mode claim.  Claim or return ENG_RC_BUSY without waiting; then noSleep, and
 * every path -- a refusal included -- leaves through modeFinish, so a kernel
 * revert that arrives meanwhile is carried out rather than lost.  The engine
 * may run only while our mode is on the card.  Nothing here logs. */
int osrdn_mode_engine(osrdn_mode_state *mode, vm_address_t base,
                      osrdn_engine_state *eng, int op, unsigned long arg,
                      osrdn_engine_state *copy);

/* R5 (docs/R5_PLAN.md 8): one CP operation under the claim.  STOP and RECORD
   run with or without a live mode; the others need one.  Returns CP_RC_*. */
/* R5: stop the CP under the claim, before anything else reverts the card (the
   kernel's -revertToVGAMode calls it before [super revertToVGAMode]).  If the
   claim is held, the holder's modeFinish runs the owed revert, which stops it. */
void osrdn_mode_cp_stop(osrdn_mode_state *mode, vm_address_t base);

int osrdn_mode_cp(osrdn_mode_state *mode, vm_address_t base, osrdn_cp_state *cp,
                  int engineLatched, int op, unsigned long arg, unsigned long len,
                  osrdn_cp_state *copy, int quiet);
/* G3: one present request, assembled and sent under the claim (docs/G3_PRESENT_PLAN.md 2-1 8);
   the request pointer is the unit's only for that operation.  Quiet: no per-operation lines. */
int osrdn_mode_present(osrdn_mode_state *mode, vm_address_t base, osrdn_cp_state *cp,
                       int engineLatched, const void *req);
/* G3b: one clear request, the same way (docs/G3B_CLEAR_PLAN.md 2-1) */
int osrdn_mode_clear(osrdn_mode_state *mode, vm_address_t base, osrdn_cp_state *cp,
                     int engineLatched, const void *req);
/* copy receives the engine state as it was when the claim was let go, so the
   caller logs one operation's evidence even if another call runs next */
