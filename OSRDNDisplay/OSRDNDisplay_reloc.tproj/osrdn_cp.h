/*
 * osrdn_cp.h - R5a-c: the Command Processor over a PCI GART ring
 * (docs/R5_PLAN.md; section 8 is the spec, 9 the operator decisions).
 *
 * One operation per call, each under the mode claim with noSleep:
 *   RECORD  read the CP, GART and MC state; nothing written but the PLL index
 *           byte (selected, then put back)
 *   LOAD    the R200 microcode into ME RAM, once per boot, only with the CP off
 *           and the GUI idle
 *   MAP     fill the 64 KiB block (GART table, guard, spare, ring, canary), flush
 *           the caches, move the AGP aperture away (D3), program the GART and the
 *           ring registers with writeback OFF, then check every register it wrote
 *   RESET   the reference engine reset, verbatim (D4, plan 9-1)
 *   START   the reference start stream; CSQ on
 *   SUBMIT  markers to SCRATCH_REG0..2 through the ring (len words, a seed);
 *           REG1's packet straddles a 1 KiB ring boundary when the span has one
 *   NEGCTL  everything SUBMIT does but the WPTR write: the sentinels must stay
 *   STOP    clean: idle, CSQ off, GART off, AGP back.  Latched: CSQ off, nothing else
 *   INJECT  R5d (docs/R5D_PLAN.md 7): a whole SUBMIT, read-back and all, then --
 *           only if it read back right -- the driver latches as if a wait had run
 *           out.  Behind a second key.  After an injected latch RECORD may still
 *           run; after a real one it is refused and reads nothing
 *
 * Rules that shape the code (docs/R5_PLAN.md 7, 8, 9):
 *   - the GPU only ever READS system memory: RB_NO_UPDATE and SCRATCH_UMSK 0,
 *     and the one address a writeback could reach is the spare page, whose
 *     canary every operation checks;
 *   - every GART entry points into the block, which is never freed, so a stray
 *     fetch always lands on memory that answers; unused entries point at the
 *     guard, filled with PACKET0(SCRATCH_REG5) pairs, so a stray fetch shows;
 *   - every wait is bounded by time and turns; after CSQ is on a bound latches
 *     the CP for the boot, RAM first, then one status read; a latched STOP
 *     writes CSQ_CNTL once and touches neither the GART nor the MC (7-1 E1);
 *   - the table is never changed while translation is on (KMS r100.c 641-646);
 *   - nothing here logs or sleeps: osrdn_modelog.m prints the evidence after the
 *     claim is released.
 */

#ifndef OSRDN_CP_H
#define OSRDN_CP_H

#import <driverkit/kernelDriver.h>      /* vm_address_t */

/* the block (plan 8), offsets from its start */
#define CP_BLOCK_BYTES          0x10000UL
#define CP_TABLE_OFF            0x0000UL        /* 2048 entries */
#define CP_GUARD_OFF            0x2000UL
#define CP_SPARE_OFF            0x3000UL        /* GART entry 4: RPTR_ADDR, SCRATCH_ADDR */
#define CP_RING_OFF             0x4000UL        /* GART entries 0-3 */
#define CP_RING_BYTES           0x4000UL
#define CP_RING_WORDS           4096UL
#define CP_IDLE_RETRY           16UL    /* G4-3 K1: idle rounds before a stall = xorg RADEON_IDLE_RETRY (radeon.h 237) */
#define CP_LATCH_FIFO_WORDS     256UL   /* M3i: the CSQ primary queue (r100.c 2976: entries 0..255) */
#define CP_LATCH_RING_WORDS     64UL    /* M3i: ring words copied around RB_RPTR at a latch */
#define CP_CANARY_OFF           0x8000UL
#define CP_PAGE                 0x1000UL        /* a GART entry */

/* the GART window (plan 1 S5): MC_FB_LOCATION 1fff0000 -> 0x20000000, 8 MiB */
#define CP_GART_BASE            0x20000000UL
#define CP_GART_BYTES           0x800000UL
#define CP_GART_ENTRIES         2048UL
#define CP_RPTR_GPU             (CP_GART_BASE + 4UL * CP_PAGE)
#define CP_SCRATCH_GPU          (CP_RPTR_GPU + 32UL)

/* words */
#define CP_PACKET2              0x80000000UL
#define CP_GUARD_HEAD           0x0000057dUL    /* PACKET0(SCRATCH_REG5 0x15f4), one register */
#define CP_REG5_POISON          0x5a5a0005UL    /* what MAP leaves in REG5; a stray fetch writes 0x80000000 */
#define CP_RB_CNTL_VALUE        0x0804090bUL    /* 16 KiB ring, rptr_update 9, fetch 1, RB_NO_UPDATE */
#define CP_CSQ_ON               0x40000000UL    /* CSQ_PRIBM_INDBM (xf86, KMS) */
#define CP_AGP_OFF              0xffffffc0UL    /* FreeBSD radeon_set_pcigart */
#define CP_ISYNC_VALUE          0x00000033UL

/* operations; setIntValues "RDNR5Cp" {magic, op, arg, len} */
#define CP_MAGIC                0x52354330UL    /* "R5C0" */
#define CP_OP_RECORD            1
#define CP_OP_LOAD              2
#define CP_OP_MAP               3
#define CP_OP_RESET             4
#define CP_OP_START             5
#define CP_OP_SUBMIT            6
#define CP_OP_NEGCTL            7
#define CP_OP_STOP              8
#define CP_OP_INJECT            9       /* R5d */
#define CP_OP_REC3D             10      /* R6a: read the 3D and surface registers (docs/R6_PLAN.md 7) */
#define CP_OP_ZPREP             11      /* R6a: the CPU fills the 256 KiB block with the pattern */
#define CP_OP_ZCLEAR            12      /* R6a: prefix, read-back, the precedent depth clear; len = case */
#define CP_OP_PLANE             13      /* R6e: log 64 words of a stored byte plane; len = lane*4 + chunk (docs/R6E_PLAN.md 13-14) */
/*
 * M1n: TURN THE CLIENT'S SUBMIT LOG OFF, FOR A WHILE.
 *
 * The driver writes 25 lines for every client submission.  Measured (M1l, M1m):
 * about 10 ms a submission while syslogd is still delivering them, about 0.7 ms
 * once it starts dropping -- so the same code times seven times differently
 * depending on how long the machine has been up.  `arg` non-zero turns the log
 * `len` is the LEASE and says everything: N swallows that many submissions and
 * then the log comes back by itself; 0 brings it back now.  A tool that dies mid-run cannot leave the machine
 * quiet for ever, which is the failure a plain flag would have.
 */
#define CP_OP_QUIET             14
/*
 * M1x: read out the accumulated stage times and zero them.  It draws nothing,
 * touches no register and waits for nothing -- it exists so the measurement can
 * happen under `quiet` (where a per-operation line would treble what is being
 * measured) and be reported once afterwards.
 */
#define CP_OP_TDUMP             15
/*
 * M2a (docs/M2A_PLAN.md): skip the WBINVD in the SUBMISSION path only.
 *
 * Every reference does a memory barrier there and no CPU cache operation at all
 * (radeon_cp.c:2094-2130), and leaves the PCI GART entries snooped -- the PCI
 * branch of ati_pcigart.c adds no flag bits, exactly as osrdn_cp_pte does.  On
 * this machine that one instruction was MEASURED at 94.46 us a submission, 47 %
 * of the whole kernel operation.
 *
 * len != 0 turns the skip ON.
 *
 * M2e: THE DEFAULT IS NOW THE SKIP.  It used to be off, because what the
 * references could not show is whether THIS machine's IOMallocLow memory really
 * snoops and only the machine can answer.  The machine has answered: across two
 * runs in one boot the skip saved 221 and 227 us a submission and the drawn
 * picture was identical WORD FOR WORD (docs/M2D_PLAN.md 5).  `nowb 0` puts the
 * WBINVD back without a reboot, and that is this change's rollback path.
 *
 * The six other cpFence call sites are untouched, in particular cpMap's, which
 * is where Linux puts its one wbinvd.
 */
#define CP_OP_NOWB              16
/*
 * M2b: how many extra cpCond polls to make before each IODelay(C_TICK_US).
 *
 * One IODelay throws away 10 us; one cpCond costs 0.83 us (measured).  If the
 * card becomes ready inside that window, polling costs a few us instead of ten.
 * len is the count; 0 (the default) is today's behaviour byte for byte.
 *
 * It does NOT touch either bound: the time check and the turn cap stay where
 * they are.  What it does weaken, and only while the CLOCK IS FROZEN, is how
 * much real time the turn cap allows -- a turn grows from 10 us to
 * 10 + spin*0.83 us (docs/M2B_PLAN.md 2-5).
 */
#define CP_SPIN_MAX             64      /* M2b: bounded here -- the operation holds the
                                           mode claim with noSleep, so an unbounded
                                           spin would hold it unboundedly */
/*
 * M2c (docs/M2C_PLAN.md): the stage instrument, on or off.
 *
 * It was never behind a knob: cpZclear set `timing = 1; c->tOn = 1;` for every
 * client submission, so every client draw paid SEVENTEEN IOGetTimestamp calls --
 * one to start the chain, eight chain marks, and eight inside cpR6Submit.  One
 * call had been measured three ways and the answers disagreed (2.84 .. 4.57 us).
 *
 * M2c THEN MEASURED IT: the same arm with the knob on and off differed by 60 us
 * a submission, so one call is 3.53 us and the instrument was 12 % of the
 * client's fixed cost -- and it buys the client nothing.
 *
 * len != 0 turns it on.  The DEFAULT IS OFF.  The measurement arms turn it on;
 * running the same arm both ways prices the instrument exactly, which is what
 * three disagreeing estimates could not.
 */
#define CP_OP_TIME              18
#define CP_OP_SPIN              17
/*
 * M2g: THE SUBMIT LOG IS OFF BY DEFAULT, and `loud N` turns it on for N
 * submissions, after which it goes quiet by itself.  `loud 0` goes quiet now.
 *
 * The lease moved sides.  CP_OP_QUIET's lease existed because silence was the
 * dangerous state -- a tool that died mid-arm must not leave the machine quiet
 * for ever (above).  With silence the default, the dangerous state is the
 * other one: a machine left loud pays about 1.25 ms a submission, and nothing
 * would notice (docs/M2G_PLAN.md 1, 3).  So the lease is on `loud` now.
 *
 * A NEW NUMBER, not a new meaning for 14.  An old tool that sends `quiet N`
 * gets exactly what it asked for (silence); it is never silently read as
 * something else.  `quiet` of any N now also cancels a `loud` lease: the two
 * are exclusive, so a loud lease cannot hide under a quiet one and come back
 * later in another arm (docs/M2G_PLAN.md 8, C7).
 */
#define CP_OP_LOUD              19
#define CP_OP_PRESENT           20      /* G3: the kernel's own 2D blit of a client rectangle to the screen (docs/G3_PRESENT_PLAN.md 2-1) */
#define CP_OP_CLEAR             21      /* G3b: the reference's clear -- 2D fill for colour, the precedent's rectangle for depth (docs/G3B_CLEAR_PLAN.md 2-1) */
/*
 * G5-2 (docs/G5_2_ASYNC_SUBMIT_PLAN.md 2): A SUBMISSION BECOMES AN ACCEPTANCE.
 *
 * ASUBMIT sends the client's verified stream with the very words ZCLEAR's
 * client case sends -- the prefix, then WAIT_UNTIL + the stream + the tail, as
 * two ring writes -- and returns after the doorbell: no sentinels, no idle
 * gate, no read-backs, no waits.  The card draws while the CPU builds the next
 * batch.  Whoever touches the ring next queues behind it (cpR6Submit waits for
 * SPACE first, the reference's radeon_wait_ring), and whoever touches the
 * window with the CPU asks RETIRE first: the ring caught up, the engine idle,
 * the pixel cache flushed -- the reference's idle path.
 */
#define CP_OP_ASUBMIT           22      /* G5-2: the client's stream, accepted, not waited for */
#define CP_OP_RETIRE            23      /* G5-2: wait for everything accepted (ring, engine, pixel cache) */
#define CP_OP_LAST              23

/* states */
#define CP_ST_NONE              0
#define CP_ST_LOADED            1
#define CP_ST_MAPPED            2       /* GART and ring registers set, CSQ off */
#define CP_ST_RUNNING           3
#define CP_ST_STOPPED           4       /* clean: CSQ off, GART off, AGP back */

/* results */
#define CP_RC_RAN               0
#define CP_RC_REFUSED           1       /* a gate held: nothing written (why) */
#define CP_RC_PRE_TIMEOUT       2       /* a wait ran out before anything was written */
#define CP_RC_LATCHED           3       /* a wait ran out with the CP on: latched for the boot */
#define CP_RC_BUSY              4       /* the mode claim was held (wrapper) */
#define CP_RC_NOT_LIVE          5       /* no mode on the card (wrapper) */
#define CP_RC_CHECK_FAILED      6       /* it ran, and its read-back is wrong (failed set by THIS op) */
#define CP_RC_RECOVERED         8       /* M3j: a wait ran out, the CP was reset and restarted; this submission was not drawn */
#define CP_RC_POST              7       /* a wait or a gate failed AFTER registers were written, with the
                                           CSQ off: not latched, but not "nothing written" either */

/* why */
#define CP_WHY_NONE             0
#define CP_WHY_KEY              1
#define CP_WHY_NO_BLOCK         2
#define CP_WHY_LATCHED          3
#define CP_WHY_BAD_OP           4
#define CP_WHY_STATE            5       /* not the state this operation starts from */
#define CP_WHY_FIFO             6
#define CP_WHY_ACTIVE           7
#define CP_WHY_CPMODE           8       /* CSQ mode not 0 where it must be */
#define CP_WHY_BLOCK            9       /* the block did not read back as written */
#define CP_WHY_MAPGATE          10      /* a register MAP wrote reads back otherwise */
#define CP_WHY_RESETGATE        11      /* the MAP registers changed across RESET */
#define CP_WHY_POISON           12      /* REG5 is not the poison: a stray fetch */
#define CP_WHY_SEED             13      /* zero, or the last seed */
#define CP_WHY_LEN              14
#define CP_WHY_SENTINEL         15      /* the CPU's sentinels did not read back */
#define CP_WHY_NOT_CAUGHT_UP    16      /* RPTR != WPTR before a SUBMIT */
#define CP_WHY_ENGINE           17      /* the 2D engine is latched (R4) */
#define CP_WHY_FAILED           18      /* an earlier SUBMIT read back wrong */
#define CP_WHY_NO_RESET         19      /* START before RESET (operator decision D4) */
#define CP_WHY_BUSMASTER        20      /* BUS_CNTL.BUS_MASTER_DIS is set */
#define CP_WHY_CSQ_QUEUE        21      /* retired (docs/R5_PLAN.md 12-4 B1): CSQ_STAT is a record, never a gate */
#define CP_WHY_INJECTED         22      /* R5d: the latch INJECT set (the waits all held) */
#define CP_WHY_NOT_FRESH        23      /* MAP: the AGP window is already moved or translation is on */
#define CP_WHY_NO_3D            24      /* R6a: the 3D key, or the engine alias, is missing */
#define CP_WHY_SURFACE          25      /* R6a: SURFACE_CNTL is not 0x100 (translation not disabled) */
#define CP_WHY_NOT_PREPPED      26      /* R6a: ZCLEAR without a ZPREP since the last one */
#define CP_WHY_CASE             27      /* R6a: not a case 1 .. CP_R6_CASES */
#define CP_R6_CASES             171     /* R6a A B C, R6b D E, R6c F G H, R6d 9-25 triangles, R6e 26-49 Gouraud, 50-59 its confirmation (docs/R6E_PLAN.md 18),
                                           R6f 60-81 depth values (docs/R6F_PLAN.md 3-1), R6g 82-101 the depth test (docs/R6G_PLAN.md 2-2, 6),
                                           R6h 102-108 the first texture (docs/R6H_PLAN.md 2-2),
                                           R6i 109-124 perspective and bilinear (docs/R6I_PLAN.md 2-2),
                                           R6i-2 125-130 the bilinear weight arithmetic (docs/R6I2_PLAN.md 2-2),
                                           R6i-3 131-135 axis or channel, and the FILTER_ROUND_MODE constants (docs/R6I3_PLAN.md 2-2),
                                           R6j 136-145 the blend unit (docs/R6J_PLAN.md 2-2),
                                           R6k 146-160 the auxiliary scissor (docs/R6K_PLAN.md 4),
                                           R6l 161-165 batching (docs/R6L_PLAN.md 4),
                                           R6m 166-170 buffer reuse (docs/R6M_PLAN.md 4),
                                           R7a 171 the client's own stream (docs/R7_PLAN.md 4) */
#define CP_R6_TEX_OFF           0x20000UL       /* R6h: the texture, clear of both buffers (docs/R6H_PLAN.md X6) */
#define CP_R6_TEX_BYTES         1024UL
#define CP_R6_TRIS              60      /* R6d: the triangle cases' vertex tables (osrdn_cp.m cpR6Tris); R6f 52-56, R6i-2 57, R6j 58, R6k 59-60 */
#define CP_R6_WORDS             4080    /* R6f: cpZclear's word array (a file static, docs/R6F_PLAN.md 3-2);
                                           R6l: the 80-triangle packet needs 1250; G4-3 K4: a full client
                                           submission (CP_R7_BATCH_MAX 4068) plus our WAIT_UNTIL and tail (12)
                                           is 4080 = roundup16 -- and roundup16(B + 12) must stay BELOW
                                           CP_RING_WORDS, or a wrapped submission's target wptr is its start
                                           (build/r7/design3.py derives B from exactly that; the 32-word state
                                           prefix is its own submission) */
#define CP_R6_PLANE_WORDS       256     /* R6e: one lane of the colour buffer's 32 x 32, a byte a pixel */
#define CP_R6_COV_WORDS         64      /* R6d: the coverage map, 2 bits a pixel of the colour buffer's 32 x 32 */
#define CP_WHY_PREFIX           28      /* R6a: a prefix register read back otherwise: nothing drawn */
#define CP_WHY_MARKER           29      /* R6a: a scratch marker did not arrive */
#define CP_WHY_PATTERN          30      /* R6a: ZPREP read back a word it did not write */
#define CP_WHY_NO_PLANE         31      /* R6e: PLANE without a stored plane of that lane, or len >= 16 */
#define CP_WHY_WORDS            32      /* R6f: a submission longer than CP_R6_WORDS: nothing drawn */
#define CP_WHY_PREFILL          33      /* R6g: the CPU's depth prefill did not read back */
#define CP_WHY_R7               34      /* R7a: the verifier refused the client's stream */
#define CP_WHY_SPIN             35      /* M2b: a spin count above CP_SPIN_MAX */
#define CP_WHY_WPTR             36      /* M3i: CP_RB_WPTR did not read back the value just written */
#define CP_WHY_PRESENT          37      /* G3: a present gate held; the value is the OSRDN_PRESENT_* verdict */

/* R6a: the block, card addresses relative to winStart (tools/r6/zclear_oracle.py) */
#define CP_R6_ALIAS_BYTES       0x40000UL

/* ---- R7a: the client's own submission (docs/R7_PLAN.md 4) ---------------------------------- */
#define CP_R7_CASE              171     /* the one case whose words come from the client */
#define CP_R7_BATCH_MAX         4068    /* the longest stream a client may submit: G4-3 K4, derived by
                                           build/r7/design3.py -- roundup16(4068 + 2 + 10) = 4080 < 4096, and
                                           one 16-word step more would not be.  It is the COPYIN path's limit
                                           (SUBMIT2); the mapped window path is bounded by its one page
                                           (OSRDN_R7B_WINDOW_BYTES), which the library honours by choosing
                                           copyin when the window is the smaller (docs/G4_3_KERNEL_PLAN.md 5) */
#define CP_R7_APPEND_MAX        508     /* 512 is the whole setIntValues array (driverTypes.h:153),
                                           so the payload is that less {magic, op, token, nwords} */
#define CP_R7_HEAD              4
#define CP_R7_MAGIC             0x52374130UL    /* "R7A0" */
#define CP_R7_OP_RESET          0       /* drop the staged words, hand out a new token */
#define CP_R7_OP_APPEND         1       /* add words to the staging buffer */
/* why the verifier refused, one code per rule so a boot names which rule fired */
#define CP_R7_WHY_OK            0
#define CP_R7_WHY_TYPE          1       /* packet type 1 or 2: a client may send neither */
#define CP_R7_WHY_TRUNC         2       /* a packet runs off the end of the stream */
#define CP_R7_WHY_P0_COUNT      3       /* PACKET0 count != 1, or ONE_REG_WR set */
#define CP_R7_WHY_P0_REG        4       /* a register outside the measured allow-list */
#define CP_R7_WHY_P0_VALUE      5       /* an allowed register carrying an unmeasured value */
#define CP_R7_WHY_P3_OP         6       /* a packet 3 that is not 3D_DRAW_IMMD_2 */
#define CP_R7_WHY_VF            7       /* VF_CNTL: not TRIANGLES | WALK_RING, or a bad count */
#define CP_R7_WHY_VTX_FMT       8       /* a vertex format field whose width we never measured */
#define CP_R7_WHY_VTX_UNSET     9       /* a draw before the format was set */
#define CP_R7_WHY_COUNT         10      /* header count != vertex words x vertex count */
#define CP_R7_WHY_SURFACE       11      /* a surface footprint leaves the client's window */
#define CP_R7_WHY_WORDS         12      /* longer than CP_R7_BATCH_MAX */
#define CP_R7_WHY_EMPTY         13      /* nothing staged, or the stream draws nothing */
#define CP_R6_DEPTH_OFF         0x00000UL
#define CP_R6_COLOR_OFF         0x3c000UL
#define CP_R6_PITCH             64UL
#define CP_R6_BUF_WORDS         4096UL          /* 64 x 64 x 4 bytes */
/*
 * M1m: HOW WIDE THE CLIENT'S DIGEST IS.
 *
 * The R6 cases digest the whole 4096-word buffer twice, which is 16,384
 * uncached reads through the VRAM alias -- measured at 826-867 ns each, so
 * 13.5 ms, and that was the WHOLE fixed cost of a client submission (M1l).
 * The client's own judges never read a digest; they read the picture through
 * their own mapping.  So the client SAMPLES instead of scanning.
 *
 * It is not zero on purpose.  Two passes over a few words still (a) touch the
 * aperture, which is the fence the flush-and-idle sequence has never been
 * proved to make unnecessary, and (b) catch a buffer that changes between two
 * reads.  Both were raised in review and both are kept, at 1/64 the cost.
 */
#define CP_R7_DIGEST_WORDS      64UL
#define CP_R6_REC_COUNT         72              /* REC3D's registers (osrdn_cp.m cpR3Regs); a multiple of 4:
                                                   the log prints four a line (docs/R6C_PLAN.md 8) */
#define CP_R6_PRE_COUNT         12              /* the prefix registers read back (cpR6PreRegs); G4-7 added two, G4-9 one at the end */

/*
 * M1x: the checkpoints on the client path.  Nine marks, eight intervals:
 *   0 just after cpR7Verify   (where t-poison turns back, so the intervals
 *                              cover exactly the 366 us bucket)
 *   1 after the gates         (idle, caught up, poison canary, SURFACE_CNTL)
 *   2 after the preamble      (FIFO wait, two scratch writes, idle wait, reads)
 *   3 after stage 1's ring submit
 *   4 after stage 1's read-backs (SCRATCH_REG0 + CP_R6_PRE_COUNT registers)
 *   5 after stage 2's words are assembled
 *   6 after stage 2's ring submit
 *   7 after the pixcache flush and its read-back
 *   8 the end of the operation
 */
#define CP_T_MARKS              9
#define CP_T_CHAIN              (CP_T_MARKS - 1)        /* intervals between the checkpoints */
/*
 * M1z (docs/M1Z_PLAN.md 5-1): two more accumulators that are NOT links in that
 * chain.  They are totals gathered inside cpR6Submit, which runs TWICE in a
 * ZCLEAR, so they cannot be intervals between checkpoints of one walk.  They
 * ride in the same tAcc array -- cpTDump copies and zeroes all CP_T_STAGES of
 * them -- at indices above the chain's, and cpTMark refuses anything at or
 * above CP_T_CHAIN so a chain mark can never land on one.
 */
#define CP_T_FENCE              CP_T_CHAIN              /* 8: cpFence, both submits summed */
#define CP_T_WAIT               (CP_T_CHAIN + 1)        /* 9: the two cpWaits, both summed */
/* M2b: the cpPut loops.  What was left of the ring stages after the fence and
   the waits was 44.12 us that nobody had measured -- a subtraction, and this
   project has named six of those wrong. */
#define CP_T_PUT                (CP_T_CHAIN + 2)        /* 10 */
#define CP_T_STAGES             (CP_T_CHAIN + 3)
#define CP_R6_PRE_GATE          0x10fUL         /* the ones that place writes (offsets, pitches, DEPTHXY): the
                                                   other four are recorded, never gated (docs/R6_PLAN.md 8-2 m1) */

typedef struct {
    unsigned long   xr, wsum, changed, ixor, isum;
    unsigned long   vals[4];
    int             nvals;
} osrdn_cp_digest;

/* RECORD's words, in this order */
#define CP_REC_RBBM_STATUS      0
#define CP_REC_CSQ_CNTL         1
#define CP_REC_CSQ_MODE         2
#define CP_REC_CSQ_STAT         3
#define CP_REC_RB_BASE          4
#define CP_REC_RB_CNTL          5
#define CP_REC_RB_RPTR          6
#define CP_REC_RB_WPTR          7
#define CP_REC_RB_RPTR_ADDR     8
#define CP_REC_RB_WPTR_DELAY    9
#define CP_REC_SCRATCH_UMSK     10
#define CP_REC_SCRATCH_ADDR     11
#define CP_REC_SCRATCH_REG0     12
#define CP_REC_SCRATCH_REG1     13
#define CP_REC_SCRATCH_REG2     14
#define CP_REC_SCRATCH_REG5     15
#define CP_REC_AIC_CNTL         16
#define CP_REC_AIC_STAT         17
#define CP_REC_AIC_PT_BASE      18
#define CP_REC_AIC_LO           19
#define CP_REC_AIC_HI           20
#define CP_REC_MC_AGP_LOCATION  21
#define CP_REC_AGP_BASE         22
#define CP_REC_AGP_BASE_2       23
#define CP_REC_BUS_CNTL         24
#define CP_REC_ISYNC_CNTL       25
#define CP_REC_GEN_INT_CNTL     26
#define CP_REC_GEN_INT_STATUS   27
#define CP_REC_RB3D_COLOROFFSET 28
#define CP_REC_RB3D_DEPTHOFFSET 29
#define CP_REC_ME_RAM_ADDR      30
#define CP_REC_MC_FB_LOCATION   31
#define CP_REC_SCLK_CNTL        32      /* PLL, read only (D9) */
#define CP_REC_MCLK_CNTL        33      /* PLL */
#define CP_REC_RBBM_SOFT_RESET  34
#define CP_REC_AGP_COMMAND      35      /* last: never read on this machine before (plan 7-2 B17) */
#define CP_REC_COUNT            36

/* the MAP gate's read-backs (docs/R5_PLAN.md 12-5 G1): every one is read on every
   gate call; the first 13 are judged (bit k of mgBad), the last two are a record */
#define CP_MG_RB_CNTL           0
#define CP_MG_UMSK              1
#define CP_MG_PT_BASE           2
#define CP_MG_LO                3
#define CP_MG_HI                4
#define CP_MG_AIC_CNTL          5
#define CP_MG_RB_BASE           6
#define CP_MG_RPTR_ADDR         7
#define CP_MG_RPTR              8
#define CP_MG_WPTR              9
#define CP_MG_INT_CNTL          10
#define CP_MG_AGP_LOCATION      11
#define CP_MG_REG5              12
#define CP_MG_JUDGED            13
#define CP_MG_AGP_COMMAND       13      /* record only */
#define CP_MG_AIC_STAT          14      /* record only */
#define CP_MG_COUNT             15

typedef struct {
    unsigned long   evals;
    /*
     * M2b (docs/M2B_PLAN.md 2-4): the OUTER turns, counted apart from evals.
     *
     * Until M2b the two were the same number and `evals - 1` was the count of
     * IODelay sleeps.  The spin knob asks cpCond extra times before sleeping, so
     * evals stops meaning turns -- and a log written with the knob on could not
     * be read at all without this.  evals is "how often we asked", turns is "how
     * often we slept".  Each number means one thing.
     */
    unsigned long   turns;
    unsigned long   us;
    int             limit;
    /* G4-3 K1 (docs/G4_3_KERNEL_PLAN.md 2): resets = how often a W_RPTR wait saw the read pointer
       move and restarted its clock (radeon_wait_ring: head != last_head -> i = 0); retries = how
       many whole C_IDLE_US rounds an idle wait needed beyond the first (xorg RADEON_IDLE_RETRY). */
    unsigned long   resets;
    unsigned long   retries;
} osrdn_cp_wait;

typedef struct {
    /* set once by the class */
    int             keyOn;
    vm_address_t    block;          /* IOMallocLow, 64 KiB, never freed */
    unsigned long   phys;           /* its physical address, checked contiguous */
    int             blockOk;
    int             injectKey;      /* R5d: "RDN CP Inject" = "Yes" */
    int             key3d;          /* R6a: "RDN 3D Test" = "Yes" */
    vm_address_t    alias;          /* R6a: the engine's uncached alias of [winStart, +256 KiB), or 0 */
    unsigned long   winStart;       /* R6a: its card address */
    unsigned long   winEnd;         /* M3h: the end of the window a client may map, or 0 */
    /* G3 (docs/G3_PRESENT_PLAN.md 2-1): the present request, set by the claim
       holder for the duration of one CP_OP_PRESENT and cleared after */
    const void     *presentReq;     /* an osrdn_cp_present_req, or 0 */
    unsigned long   presentVerdict; /* this operation's OSRDN_PRESENT_* */
    unsigned long   presentOk;      /* sticky counters, per verdict */
    unsigned long   presentRefused[8];
    /* G3b (docs/G3B_CLEAR_PLAN.md 2-1): the clear request, the same way */
    const void     *clearReq;       /* an osrdn_cp_clear_req, or 0 */
    unsigned long   clearVerdict;
    unsigned long   clearOk;
    unsigned long   clearRefused[8];

    /* sticky for the boot */
    int             state;
    int             latched;
    int             resetDone;
    int             failed;         /* a SUBMIT read back wrong: no more SUBMITs */
    int             latchInjected;  /* R5d: the latch is INJECT's, not a wait's */
    unsigned long   injectCount;
    unsigned long   ops;
    unsigned long   wptr;           /* ring words */
    int             seedUsed;
    unsigned long   lastSeed;
    int             agpSaved;
    unsigned long   agpLocation;    /* MC_AGP_LOCATION before MAP */
    unsigned long   agpCommand;

    /* the last operation's evidence */
    int             op;
    unsigned long   arg;
    unsigned long   len;
    int             rc;
    int             why;
    unsigned long   gateValue;      /* the value read (a gate), or what refused */
    unsigned long   gateReg;        /* the register a read-back gate refused on, or 0 */
    unsigned long   rec[CP_REC_COUNT];
    int             mgDone;         /* the MAP gate ran in this operation */
    unsigned long   mgBad;          /* bit k: CP_MG_k read back otherwise */
    unsigned long   mg[CP_MG_COUNT];
    unsigned long   digestWords;    /* M1m: how wide this operation's digest was */
    int             quiet;          /* M1n: swallow the client submit log */
    unsigned long   quietBudget;    /* ... for this many more submissions */
    unsigned long   quietSwallowed; /* how many it has swallowed in all */
    unsigned long   qTouch[2];      /* M1o: the two words a quiet submission still reads */
    unsigned long   loudBudget;     /* M2g: speak for this many more submissions; 0 = quiet */
    int             subQuiet;       /* M2g: THIS operation is a quiet client submission.
                                       Set and cleared by osrdn_mode_cp while it holds
                                       the claim, never outside it (docs/M2G_PLAN.md 10) */
    unsigned long   marker[3];
    unsigned long   sentinel[3];
    unsigned long   got[3];         /* SCRATCH_REG0..2 after */
    unsigned long   reg5;
    unsigned long   rptrBefore, rptrAfter, wptrAfter;
    unsigned long   rptrOff, wptrOff;   /* STOP: both pointers after the CSQ is off (a record) */
    int             straddle;       /* REG1's packet crossed a 1 KiB ring boundary */
    unsigned long   boundary;       /* which one (ring words), or 0 */
    unsigned long   tableBad, guardBad, spareBad, canaryBad, ringBad;
    unsigned long   pteSum, pteXor; /* over the table as read back */
    unsigned long   mclkBefore, mclkForced, mclkAfter;
    unsigned long   indexBefore, indexAfter;
    unsigned long   softBefore, softAfter;
    unsigned long   postStatus;     /* RBBM_STATUS read once after a latch */
    /*
     * M3i (docs/M3I_PLAN.md 3): WHAT THE CP ITSELF SAYS AT A LATCH -- the registers
     * Linux's r100_debugfs_cp_ring_info / _csq_fifo read, taken the moment the
     * wait runs out, and printed again by the RECORD the latch refuses.  Four
     * latches were judged on RBBM_STATUS alone; this is the rest of the story.
     */
    int             latchRead;      /* the block below was filled by cpLatch */
    unsigned long   cpStat;         /* CP_STAT (0x7c0): no bit layout in any reference; raw */
    unsigned long   rbRptr, rbWptr; /* CP_RB_RPTR, CP_RB_WPTR as the card reports them */
    unsigned long   csqMode;        /* CP_CSQ_MODE */
    unsigned long   wptrRead;       /* every submission: CP_RB_WPTR read back right after the write */
    unsigned long   fifo[CP_LATCH_FIFO_WORDS];      /* the CSQ primary queue, CSQ_ADDR/CSQ_DATA */
    unsigned long   ringNear[CP_LATCH_RING_WORDS];  /* the ring in RAM from rbRptr - 16 */
    unsigned long   ringNearAt;     /* the ring word ringNear[0] is */
    unsigned long   ringNearBad;    /* of those, how many differ from the shadow */
    /* M3i D3: the reference's kick (r100_gpu_is_lockup -> radeon_ring_force_activity): 16 NOPs at
       wptr, WPTR written again, and did rptr move within C_KICK_US?  Taken after the dump. */
    unsigned long   kickWptr;       /* the WPTR the kick wrote */
    unsigned long   kickWptrRead;   /* ... read back */
    unsigned long   kickRptr;       /* RB_RPTR after the kick's wait */
    int             kickMoved;      /* 1 if it differs from rbRptr (the dump's) */
    osrdn_cp_wait   wKick;          /* the kick's wait, like the others */
    unsigned long   kickSkipped;    /* G5-2: sticky: kicks not sent because fewer than 16 ring words were free
                                       (16 NOPs there would overwrite unfetched words or make a full ring read empty) */
    /* M3j (docs/M3J_PLAN.md 5): the reference's recovery instead of a boot-long latch */
    int             recoverKind;    /* this op: 0 none/failed, 1 the kick alone, 2 reset and restart */
    unsigned long   recovers;       /* sticky: how many submissions this boot recovered from */
    unsigned long   csqStat;        /* CP_CSQ_STAT after the operation (record only) */
    unsigned long   csq2Stat;       /* CP_CSQ2_STAT after the operation (record only) */
    unsigned long   aicStat;        /* AIC_STAT after the operation (record only, R5d D2) */
    int             csqRead;        /* the three above were read in this operation */
    unsigned long   ioRd, ioWr;     /* MMIO reads and writes this unit made in the operation (R5d 7) */

    /* R6a (docs/R6_PLAN.md 7) */
    int             zprepped;       /* sticky: a ZPREP since the last ZCLEAR */
    int             restSkipped;    /* M1h: the whole-alias scan was not run (client stream),
                                       so restChanged 0 means "not looked at", not "nothing" */
    unsigned long   r3[CP_R6_REC_COUNT];    /* REC3D */
    unsigned long   surfaceCntl;
    int             zcase, zstage;  /* ZCLEAR: the case, and how far it got (1 prefix, 2 draw, 3 read) */
    unsigned long   pfBad;          /* R6g: depth words the prefill wrote that did not read back */
    unsigned long   prefixBad;      /* bit k: cpR6PreRegs[k] read back otherwise */
    unsigned long   pre[CP_R6_PRE_COUNT];
    unsigned long   zreg0, zreg2;   /* the scratch markers as read back */
    unsigned long   prepBad;        /* ZPREP: words that read back otherwise */
    osrdn_cp_digest dDepth[2], dColor[2];   /* two passes over the block */
    unsigned long   restChanged[2], restFirst, restFirstVal;
    /* R6m (docs/R6M_PLAN.md 4-5): where this case's three surfaces were, as the driver
       itself resolved them, and what the texture surface held AFTER the draw */
    unsigned long   zColorOff, zDepthOff, zTexOff;
    unsigned long   texPost, texPostAt, texPostVal;
    /* R7a (docs/R7_PLAN.md 4): the client's staged stream and the verifier's verdict */
    unsigned long   subWords;       /* how many words are staged */
    unsigned long   subToken;       /* whose they are; an append with another token is refused */
    unsigned long   subDropped;     /* appends refused since the last RESET (a record) */
    unsigned long   r7Why, r7At;    /* the verifier's code and the word it stopped at */
    unsigned long   r7Word;         /* and the word itself -- a rule that fires on the wrong
                                       word looks exactly like one that fires on the right
                                       word unless the word is on the record */
    unsigned long   r7WinStart, r7WinEnd;   /* the card addresses a client's surfaces may use */
    int             covValid;       /* R6d: a triangle case filled cov[] in this operation */
    int             planeValid;     /* R6e: plane[] holds the last successful Gouraud ZCLEAR's planes -- cleared
                                       by every ZPREP or ZCLEAR request, set only when a ZCLEAR succeeds */
    unsigned long   planeZop;       /* R6e: that ZCLEAR's operation number (ops) */
    int             planeZcase;     /* R6e: and its case (zcase is reset every operation) */
    unsigned long   planeChunk;     /* R6e: PLANE: the lane*4 + chunk this operation logs */
    unsigned long   planeLanes;     /* R6e: bit l (0 B, 1 G, 2 R, 3 A): plane[l] was read */
    unsigned long   planeSrc;       /* R6f: where the planes came from: 0 the colour buffer, 1 the 24-bit depth
                                       (mba_z32, lanes 0-2 = depth bytes), 2 the 16-bit depth (mba_z16, lanes 0-1) */
    unsigned long   laneOff[4];     /* R6e: covered pixels whose constant lane l is not the case's constant */
    unsigned long   plane[4][CP_R6_PLANE_WORDS];    /* R6e: pixel i = y*32+x at word i/4, bits 8*(i%4); 0 where uncovered
                                                       (colour); R6f depth: every pixel, what the buffer holds */
    unsigned long   cov[CP_R6_COV_WORDS];   /* R6d: pixel i = y*32+x at word i/16, bits 2*(i%16): 0 pattern,
                                               1 / 2 the case's two map colours, 3 anything else */
    osrdn_cp_wait   wFifo, wIdle, wRptr, wIdle2, wDc;
    /* G5-2 (docs/G5_2_ASYNC_SUBMIT_PLAN.md 2): the accepted submission and its retirement */
    int             noWait;         /* THIS cpR6Submit returns after the doorbell.  Set and cleared by cpAsubmit
                                       around its two writes, and cleared again at every operation's entry */
    int             inflight;       /* 1 from an accepted submission until a wait saw the ring and engine drain */
    osrdn_cp_wait   wSpace;         /* the last space wait (cpWaitSpace) */
    unsigned long   spaceWaits;     /* sticky: space waits that had to wait at all */
    unsigned long   spaceUs;        /* sticky: their microseconds */
    unsigned long   asubmits;       /* sticky: accepted submissions */
    unsigned long   retires;        /* sticky: RETIRE operations that ran */
    unsigned long   retireWaited;   /* sticky: ... of them with a submission in flight */
    unsigned long   retireUs;       /* sticky: their microseconds (ring + idle + pixel cache) */
    unsigned long   retireLastUs;   /* this RETIRE's */
    unsigned long   retireMarkBad;  /* sticky: RETIREs that found SCRATCH_REG2 != ~lastSeed after idle (a record) */
    unsigned long   lostInflight;   /* sticky: recoveries or latches that threw away accepted work (EVENTS: `inflight`
                                       is a flag, so two accepted submissions lost together count once) */
    unsigned long   elapsedUs;
    /*
     * M1x: WHERE THE KERNEL'S 366 us GOES, accumulated and reported ONCE.
     *
     * A client submission costs 530 us of fixed cost, of which 366 us is inside
     * the kernel operation, and the two things the source can name -- the whole
     * state copy and the MMIO accesses -- are at most 15 % of it (the driver
     * already counts the MMIO: ioRd is 37..40 an operation, 2.2 % at 830 ns).
     *
     * NOT LOGGED PER OPERATION.  The log costs about 1,085 us a submission and
     * would treble what is being measured -- the same operation reads 1,440 us
     * with the log on and 366 us without.  So the stages ACCUMULATE here and are
     * read once, after a quiet run, through the state parameter.
     *
     * tAcc[k] is the microseconds spent between checkpoint k and k+1, summed
     * over tAccN operations.  An unsigned long holds 4,295 seconds; a run is
     * 2,160 submissions x 366 us = 0.79 s, so there is 5,400x of headroom.
     */
    unsigned long   tAcc[CP_T_STAGES];
    unsigned long   tAccN;
    /* what CP_OP_TDUMP handed back, so the log prints a snapshot and not a
       live sum that the next operation has already moved */
    unsigned long   tDump[CP_T_STAGES];
    unsigned long   tDumpN;
    /* M2a: 1 when the submission path skips the WBINVD.  Not a lease like
       `quiet`: an arm turns it on, runs, and turns it off. */
    /*
     * M2e: 1 = DO the submission WBINVD.  The sense is this way round on
     * purpose.  The state is cleared byte by byte at init (OSRDNDisplay.m:291),
     * so whatever means "fast" has to be ZERO -- then no initialiser can be
     * forgotten, and no clear anyone adds later can undo it.  The knob keeps its
     * outside name: `nowb 1` means "do not write back" and sets this to 0.
     */
    int             doWb;
    unsigned int    spin;       /* M2b: the extra polls in force, for the log */
    /* M2c: 1 when the stage instrument may run.  It lives HERE, beside doWb and
       spin, and NOT in the per-operation clear -- tOn is the per-operation one
       and takes its value from this. */
    int             timeOn;
    /* M1z: cpZclear's `timing` used to be a local, but cpR6Submit has to see it
       to fill CP_T_FENCE and CP_T_WAIT.  Set where `timing` is set -- just after
       cpR7Verify, the point t-poison turns back from -- and cleared per operation. */
    int             tOn;
} osrdn_cp_state;

/* One operation.  The caller holds the mode claim with noSleep set.  engineLatched
   is the R4 engine's latch (plan 7-2 B10).  Returns CP_RC_*. */
/* R7a (docs/R7_PLAN.md 3): stage the client's CP words.  Takes NO mode claim and touches no
   hardware -- it only copies into the driver's own buffer, which is the whole point: the words the
   verifier judges at ZCLEAR time are words the client can no longer reach.  Returns 1 if the words
   were taken. */
int osrdn_cp_stage(osrdn_cp_state *c, unsigned long op, unsigned long token,
                   unsigned long nwords, const unsigned *words);

/* M1n: 1 when THIS client submission's log is to be swallowed.  Call once per
   submission: it spends the lease and hands the log back when it runs out. */
int osrdn_cp_quiet_take(osrdn_cp_state *c);

int osrdn_cp_run(osrdn_cp_state *c, vm_address_t base, int op, unsigned long arg,
                 unsigned long len, int engineLatched);

/* Before any revert: a clean STOP if the CP holds the card, a latched STOP if
   latched (plan 8).  Caller holds the claim. */
void osrdn_cp_quiesce(osrdn_cp_state *c, vm_address_t base);

/* 1 when a mode change or an R4 engine operation may run: NONE, LOADED or a clean
   STOPPED, and not latched (plan 7-2 B3 B10) */
int osrdn_cp_allows_mode(const osrdn_cp_state *c);

/* the GART entry for index e, from the block's physical address (host checkers
   recompute the same) */
unsigned long osrdn_cp_pte(unsigned long phys, unsigned long e);

/* R6a: the registers REC3D reads, in order */
extern const unsigned short osrdnCpR3Regs[CP_R6_REC_COUNT];

/* the SUBMIT markers from a seed (the log judge recomputes them) */
unsigned long osrdn_cp_marker(unsigned long seed, int k);

#endif /* OSRDN_CP_H */
