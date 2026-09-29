/*
 * osrdn_engine.h - R4a/R4b: the 2D engine on offscreen VRAM, over MMIO only.
 *
 * docs/R4_ENGINE_PLAN.md 12 (the spec) and 13 (its review).  One operation
 * per call, each judged by reading the result back through an uncached alias
 * of the test block and comparing every pixel with arithmetic:
 *
 *   RECORD  read the engine's state; no engine write (the PLL index byte is
 *           written to select and then put back);
 *   FILL    a solid rectangle in surface S0;
 *   BLIT    one copy per call: case 0 between surfaces, 1-8 overlapping
 *           moves inside S1, 9-12 the moves of 5-8 with the direction bit
 *           deliberately wrong (does this hardware decide the direction?);
 *   UBLIT   R4c (docs/R4C_VMAP_PLAN.md 11-2): case 0, but the source is what a
 *           user task wrote through its mapping of the window, U(seed, off) over
 *           the whole block.  The kernel first reads the whole block and refuses
 *           unless every word is U -- that shows the user's 32 pages land on the
 *           right card pages, as the CPU sees them; only the engine's copy into
 *           S2 shows the user's writes reached VRAM (plan 10-1 E3).
 *
 * Rules that shape the code:
 *   - nothing is written unless every gate holds (the gates read status
 *     first and 2D registers only once the engine is idle);
 *   - every wait is bounded by time AND by turns, spins with IODelay (the
 *     caller holds the mode claim with noSleep set), and a wait that ends on
 *     a bound BEFORE the trigger writes nothing;
 *   - a wait that ends on a bound AFTER the trigger latches the engine off
 *     for the rest of the boot -- latch first, in RAM, then read one status
 *     word for the log; no clean-up writes, no fallback, no reset
 *     (docs/R4_ENGINE_PLAN.md 1-4, PLAN.md prohibition 8);
 *   - the engine is never reset, and SURFACE_CNTL, RBBM_SOFT_RESET and
 *     HOST_PATH_CNTL are never written; RB3D_CNTL is written, to 0 only, at
 *     the head of each batch, as the references do (docs/R4_ENGINE_PLAN.md 17);
 *   - nothing here logs: osrdn_modelog.m prints the result afterwards.
 *
 * Only this file touches the engine registers, through the RDNR2aMMIO
 * accessors, and only the test block through the alias.
 *
 * "Alias": IOMapPhysicalIntoIOTask builds its PTEs with the same pmap_enter
 * call, and the same cache bits, as a user mapping (IDA, docs/R4C_VMAP_PLAN.md
 * 1 F5 F6) -- it is not uncached by its PTE.  R4a/R4b's readings stand as a
 * measurement: on this range the alias did see the engine's writes.
 *
 * With "RDN VRAM Mmap" also on, the block is the first 256 KiB of the window
 * a user task may map, and every operation here overwrites it: a boot with
 * both keys is a test boot (docs/R4C_VMAP_PLAN.md 2).
 */

#ifndef OSRDN_ENGINE_H
#define OSRDN_ENGINE_H

#import <driverkit/kernelDriver.h>      /* vm_address_t */

/* the test block, card addresses relative to winStart (docs/R4_ENGINE_PLAN.md 12-2).
   tools/r4/check_tool_r4map.py holds the user tool's copies to these. */
#define ENG_ALIAS_BYTES         0x40000UL       /* 256 KiB */
#define ENG_S0_OFF              16384UL         /* 256 x 64, pitch 1024 */
#define ENG_S0_W                256UL
#define ENG_S0_H                64UL
#define ENG_S1_OFF              98304UL         /* 128 x 128, pitch 512 */
#define ENG_S1_W                128UL
#define ENG_S1_H                128UL
#define ENG_S2_OFF              180224UL        /* 128 x 64, pitch 512 */
#define ENG_S2_W                128UL
#define ENG_S2_H                64UL
#define ENG_D_OFF               229376UL        /* 64 x 64, pitch 256: the decoy */
#define ENG_D_W                 64UL
#define ENG_D_H                 64UL

/* what the block holds around a result, and the fill's rectangle in S0 */
#define ENG_MARK                0x5a5a5a5aUL
#define ENG_FILL_X              16UL
#define ENG_FILL_Y              8UL
#define ENG_FILL_W              200UL
#define ENG_FILL_H              40UL

/* UBLIT: the user's word at block offset off (off / 4 < 65536 in the block),
   and the seeds the kernel takes: low 16 bits clear, top byte not the
   marker's, the pattern's or the tool's fill colour's (plan 10-2 B9) */
#define ENG_USER_VALUE(seed, off) ((seed) | ((off) >> 2))
#define ENG_SEED_LOW_MASK       0x0000ffffUL
#define ENG_SEED_BAD_TOP_1      0x5aUL
#define ENG_SEED_BAD_TOP_2      0xffUL
#define ENG_SEED_BAD_TOP_3      0x96UL

/* operations; setIntValues "RDNR4Engine" {magic, op, arg} */
#define ENG_MAGIC               0x52344530UL    /* "R4E0" */
#define ENG_OP_RECORD           1
#define ENG_OP_FILL             2
#define ENG_OP_BLIT             3
#define ENG_OP_UBLIT            4       /* R4c: case 0 from the user's words; arg = seed */
#define ENG_BLIT_CASES          13              /* 0..12 */

/* results */
#define ENG_RC_RAN              0       /* the operation ran; the counts judge it */
#define ENG_RC_REFUSED          1       /* a gate held: nothing written (why) */
#define ENG_RC_PRE_TIMEOUT      2       /* FIFO never had room: nothing written */
#define ENG_RC_POST_TIMEOUT     3       /* after the trigger: latched */
#define ENG_RC_BUSY             4       /* the mode claim was held (wrapper) */
#define ENG_RC_NOT_LIVE         5       /* no mode on the card (wrapper) */
#define ENG_RC_CP               6       /* the CP holds the card or is latched (R5, wrapper) */

/* why a gate refused */
#define ENG_WHY_NONE            0
#define ENG_WHY_KEY             1       /* "RDN Engine Test" is not Yes */
#define ENG_WHY_NO_ALIAS        2
#define ENG_WHY_LATCHED         3
#define ENG_WHY_BAD_OP          4
#define ENG_WHY_FIFO            5       /* RBBM_STATUS FIFO not 64 */
#define ENG_WHY_ACTIVE          6       /* RBBM_ACTIVE set */
#define ENG_WHY_CPMODE          7       /* CP_CSQ_CNTL mode not 0 */
#define ENG_WHY_DC2_BUSY        8
#define ENG_WHY_DC3_BUSY        9
#define ENG_WHY_RB3D            10      /* no longer used: RB3D_CNTL is written to 0 (docs 17) */
#define ENG_WHY_SURFACE         11      /* aperture byte swapping on */
#define ENG_WHY_REACH           12      /* CONFIG_MEMSIZE or APER_SIZE below the block */
#define ENG_WHY_MARKER          13      /* the CPU's marker did not read back */
#define ENG_WHY_PATTERN         14      /* the CPU's pattern did not read back */
#define ENG_WHY_MARK_COLOUR     15      /* a fill with the marker colour could not fail */
#define ENG_WHY_USER            16      /* UBLIT: words not U(seed) at this physical block (value = count) */
#define ENG_WHY_SEED            17      /* UBLIT: the seed is the last one used (a leftover could pass) */

/* RECORD's words, in this order (the log prints them as named) */
#define ENG_REC_RBBM_STATUS     0
#define ENG_REC_CP_CSQ_CNTL     1
#define ENG_REC_RB2D_DC         2
#define ENG_REC_RB3D_DC         3
#define ENG_REC_DSTCACHE        4       /* 0x1714 */
#define ENG_REC_RB2D_DC_MODE    5
#define ENG_REC_RB3D_CNTL       6
#define ENG_REC_DEFAULT_OFFSET  7
#define ENG_REC_DEFAULT_PITCH   8
#define ENG_REC_DEFAULT_SC_BR   9
#define ENG_REC_SC_TOP_LEFT     10
#define ENG_REC_SC_BOTTOM_RIGHT 11
#define ENG_REC_AUX_SC_CNTL     12
#define ENG_REC_DP_DATATYPE     13
#define ENG_REC_GMC             14
#define ENG_REC_DP_CNTL         15
#define ENG_REC_WRITE_MASK      16
#define ENG_REC_DST_PO          17
#define ENG_REC_SRC_PO          18
#define ENG_REC_BRUSH           19
#define ENG_REC_SURFACE_CNTL    20
#define ENG_REC_SCLK_CNTL       21
#define ENG_REC_SCLK_MORE_CNTL  22
#define ENG_REC_CLK_PWRMGT_CNTL 23
#define ENG_REC_COUNT           24

typedef struct {
    unsigned long   evals;      /* times the condition was evaluated */
    unsigned long   us;         /* elapsed */
    int             limit;      /* 1 if a bound ended it */
} osrdn_engine_wait;

typedef struct {
    /* set once by the class */
    int             keyOn;
    vm_address_t    alias;          /* alias of card [winStart, winStart + 256 KiB) (see above) */
    unsigned long   winStart;       /* card address of the block (osrdn_window_start) */

    /* sticky for the boot */
    int             latched;        /* a wait ran out after a trigger */
    unsigned long   ops;
    int             seedUsed;       /* UBLIT: lastSeed is valid */
    unsigned long   lastSeed;       /* the seed of the last UBLIT that reached its preparation */

    /* the last operation's evidence */
    int             op;
    unsigned long   arg;
    int             rc;
    int             why;
    unsigned long   gateValue;      /* the register that refused */
    unsigned long   rec[ENG_REC_COUNT];
    unsigned long   inBad;          /* destination pixels wrong */
    unsigned long   notBad;         /* ... of which still hold the pre-op value */
    unsigned long   outBad;         /* pixels outside the destination changed */
    unsigned long   decoyBad;       /* decoy surface changed: DEFAULT_OFFSET was used */
    unsigned long   guardBad;       /* guard bands changed: pitch/offset wrong */
    long            first;          /* byte offset in the block of the first bad word, -1 none */
    unsigned long   f64;            /* bad words in the first 64 bytes of the destination RECTANGLE
                                       (its top-left, where Matrox 3-18 saw stale reads) */
    unsigned long   reread;         /* bad words after one more read (rereadDone says it ran) */
    int             rereadDone;
    osrdn_engine_wait wFifo, wIdle, wDc2, wDc3, wIdle2, wRestore;
    unsigned long   dc2Pre, dc3Pre; /* the cache control words before the flush */
    unsigned long   defaultSaved;   /* DEFAULT_OFFSET before the decoy */
    int             defaultLeft;    /* 1: the decoy stayed (post-trigger timeout) */
    unsigned long   postStatus;     /* RBBM_STATUS read after a post-trigger timeout */
    unsigned long   elapsedUs;      /* the whole operation */
} osrdn_engine_state;

/* One operation.  The caller holds the mode claim with noSleep set and a mode
   on the card (osrdn_mode_engine).  Returns ENG_RC_*. */
int osrdn_engine_run(osrdn_engine_state *e, vm_address_t base, int op, unsigned long arg);

/* the numbers the checkers hold the code to */
unsigned long osrdn_engine_pitch_offset(unsigned long card, unsigned long pitchBytes);

/* CONFIG_MEMSIZE and CONFIG_APER_SIZE, raw (reads only; the gate here and the
   R4c registration both use it, docs/R4C_VMAP_PLAN.md 3-2, 10-3) */
void osrdn_engine_vram_reach(vm_address_t base, unsigned long *memsize, unsigned long *aperSize);

#endif /* OSRDN_ENGINE_H */
