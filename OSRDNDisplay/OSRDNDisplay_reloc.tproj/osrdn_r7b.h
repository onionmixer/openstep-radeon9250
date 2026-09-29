/*
 * osrdn_r7b.h - R7b: the character device's ioctl interface (docs/R7_PLAN.md 10).
 *
 * R7a carried the client's CP words through setIntValues, which needs
 * IODeviceMaster, which is Objective-C.  The Mesa acceleration library cannot
 * link Objective-C, so it has to reach the same verifier through the node it
 * must open for mmap anyway.  That is all this header is: the two commands and
 * the two blocks, in plain C, so a client needs nothing else.
 *
 * The words never travel in a block.  They are written into the page the client
 * maps at OSRDN_R7B_WINDOW_OFF, and SUBMIT says how many of them to take -- the
 * kernel then copies them into its own buffer before judging them, so what runs
 * is a copy the client can no longer reach.
 *
 * The outcome travels in `status`, not in the ioctl's return: a 4.3BSD ioctl
 * copies its block back only when the handler returns zero (bsd/sys/ioctl.h and
 * the Matrox precedent's submit), so refusing would throw away the explanation.
 */

#ifndef OSRDN_R7B_H
#define OSRDN_R7B_H

#define OSRDN_R7B_MAGIC         0x52374230UL    /* "R7B0" */
#define OSRDN_R7B_VERSION       2UL     /* G4-4 K8: SUBMIT2 takes maxWords, chunked through the page */

/* the batch window, as d_mmap offers it (osrdn_vmap.h, OSRDN_VMAP_BATCH_BASE) */
#define OSRDN_R7B_WINDOW_OFF    0x40000000UL
#define OSRDN_R7B_WINDOW_BYTES  8192UL
#define OSRDN_R7B_MAX_WORDS     4068UL          /* CP_R7_BATCH_MAX: what a submission may carry.  G4-4 K8: true of the
                                                   copyin path (SUBMIT2 copies in chunks through the page); the mapped
                                                   window path is bounded by the page it sends from, OSRDN_R7B_WINDOW_WORDS,
                                                   and the client knows that from CAPS `bytes`.  Version 1 kernels refused
                                                   a copyin past the page as "count" while advertising this -- hence 2. */
#define OSRDN_R7B_WINDOW_WORDS  (OSRDN_R7B_WINDOW_BYTES / 4UL)

/* what CAPS answers (9 words = 36 bytes, well under the 128 the encoding allows) */
typedef struct {
    unsigned long magic;
    unsigned long version;
    unsigned long window;       /* the mmap offset to ask for */
    unsigned long bytes;        /* its length */
    unsigned long maxWords;     /* the most one submission may carry (the copyin path takes it whole, K8) */
    unsigned long build;        /* which driver this is */
    unsigned long ready;        /* 1 when the batch path exists: a page and a window.
                                   It does NOT mean the CP is running -- that is cpRunning,
                                   and a client may legitimately ask CAPS before it is. */
    unsigned long cpRunning;    /* 1 when a submission would reach the ring */
    unsigned long winStart;     /* the offscreen window's card address: a client forms its
                                   surface addresses from this, and has no other way to
                                   learn it without Objective-C */
} osrdn_r7b_caps;

/* what SUBMIT takes and answers (the same size, for the same reason) */
typedef struct {
    unsigned long magic;        /* in */
    unsigned long version;      /* in */
    unsigned long nwords;       /* in: how many words of the page to take */
    unsigned long seed;         /* in: non-zero, and not the one the last operation used.
                                   The kernel refuses a repeat (CP_WHY_SEED) because the
                                   marker pattern is derived from it, and a repeated seed
                                   would let a stale read-back pass for a fresh one.  A
                                   client's run id serves, as it does for R7a's tool. */
    unsigned long status;       /* out: 0, or an errno */
    unsigned long why;          /* out: CP_R7_WHY_*, the verifier's verdict */
    unsigned long at;           /* out: the word it stopped at */
    unsigned long word;         /* out: that word */
    unsigned long drawn;        /* out: 1 if the stream reached the ring */
} osrdn_r7b_submit;

/*
 * M1p: THE SAME SUBMISSION, WITH THE WORDS IN THE CLIENT'S OWN MEMORY.
 *
 * The mapped window is CACHE-INHIBITED (it is a d_mmap of kernel pages), so a
 * client writing 15 words a triangle into it pays 69 ns a word -- measured,
 * 1.03 us a triangle, 54% of the per-triangle cost.  The reference stack never
 * does this: the DRI client builds its command buffer in an ordinary cached
 * array (r200_context.h:712-717) and the kernel reads it with copy_from_user,
 * for the same TOCTOU reason this driver already copies (radeon_state.c
 * 2858-2863).  The zero-copy alternative exists there too and is root-only and
 * labelled insecure (radeon_state.c 2479-2484).
 *
 * So: `words` is a pointer into the CLIENT's cached memory and the driver
 * copyins it -- before it takes the hardware claim, because a fault may sleep.
 * The old block and the old window stay, so a run can alternate between the
 * two paths and price the difference without an arm-order confound.
 */
typedef struct {
    unsigned long magic;        /* in */
    unsigned long version;      /* in */
    unsigned long nwords;       /* in: bounded before it is multiplied */
    unsigned long seed;         /* in */
    unsigned long words;        /* in: the client's own address, cached memory */
    unsigned long status;       /* out */
    unsigned long why;          /* out */
    unsigned long at;           /* out */
    unsigned long word;         /* out */
    unsigned long drawn;        /* out */
} osrdn_r7b_submit2;

/*
 * The encoding is this target's, read out of its own <sys/ioctl.h> rather than
 * remembered from a later BSD: IOCPARM_MASK is 0x7f here (ioctl.h:166), so a
 * block must stay under 128 bytes or the kernel silently truncates the copy.
 * Written out so that a pure-C client needs only this file.
 */
#define OSRDN_R7B_IOC_OUT       0x40000000UL
#define OSRDN_R7B_IOC_IN        0x80000000UL
#define OSRDN_R7B_IOC_PARM_MASK 0x7fUL
#define OSRDN_R7B_IOC_GROUP     'R'

#define OSRDN_R7B_IOC_CAPS      ((unsigned long)(OSRDN_R7B_IOC_OUT | \
    ((sizeof(osrdn_r7b_caps) & OSRDN_R7B_IOC_PARM_MASK) << 16) | \
    ((unsigned long)OSRDN_R7B_IOC_GROUP << 8) | 1UL))

#define OSRDN_R7B_IOC_SUBMIT    ((unsigned long)(OSRDN_R7B_IOC_IN | OSRDN_R7B_IOC_OUT | \
    ((sizeof(osrdn_r7b_submit) & OSRDN_R7B_IOC_PARM_MASK) << 16) | \
    ((unsigned long)OSRDN_R7B_IOC_GROUP << 8) | 2UL))

#define OSRDN_R7B_IOC_SUBMIT2   ((unsigned long)(OSRDN_R7B_IOC_IN | OSRDN_R7B_IOC_OUT | \
    ((sizeof(osrdn_r7b_submit2) & OSRDN_R7B_IOC_PARM_MASK) << 16) | \
    ((unsigned long)OSRDN_R7B_IOC_GROUP << 8) | 3UL))

/*
 * THE SIZE FIELD WRAPS AT 128 AND SAYS NOTHING.
 *
 * `(sizeof(x) & 0x7f) << 16` encodes 128 as ZERO, and a 4.3BSD dispatcher then
 * copies no structure at all -- it puts the raw argument pointer where the
 * first field should be and calls the handler, which reads a pointer as
 * `magic` and garbage after it.  Nothing warns.  These refuse to compile
 * instead; a cross-review named this exact failure and it costs two lines.
 */
typedef char osrdn_r7b_caps_fits[(sizeof(osrdn_r7b_caps) <
                                  OSRDN_R7B_IOC_PARM_MASK) ? 1 : -1];
typedef char osrdn_r7b_submit_fits[(sizeof(osrdn_r7b_submit) <
                                    OSRDN_R7B_IOC_PARM_MASK) ? 1 : -1];
typedef char osrdn_r7b_submit2_fits[(sizeof(osrdn_r7b_submit2) <
                                     OSRDN_R7B_IOC_PARM_MASK) ? 1 : -1];

/*
 * G5-2 (docs/G5_2_ASYNC_SUBMIT_PLAN.md 2): SUBMIT3 IS SUBMIT2 ACCEPTED, NOT WAITED FOR.
 *
 * The same block and the same staging; the kernel verifies the words exactly as
 * for SUBMIT2 and puts on the ring exactly the words SUBMIT2 puts there, then
 * returns after the doorbell.  `drawn` keeps its meaning -- verified and on the
 * ring -- which was all it ever promised: SUBMIT2 also sets it before any
 * read-back could disagree.  A client that uses SUBMIT3 must ask RETIRE before
 * its CPU reads or writes anything the card may still be drawing into or from.
 *
 * NEW NUMBERS, not a new version.  CAPS, SUBMIT2 and their version stay as they
 * are, so every binary built against version 2 keeps working; a kernel without
 * these two answers ENOTTY, which is how a client learns there is no
 * acceptance to be had (it asks RETIRE once, at start).
 */
#define OSRDN_R7B_IOC_SUBMIT3   ((unsigned long)(OSRDN_R7B_IOC_IN | OSRDN_R7B_IOC_OUT | \
    ((sizeof(osrdn_r7b_submit2) & OSRDN_R7B_IOC_PARM_MASK) << 16) | \
    ((unsigned long)OSRDN_R7B_IOC_GROUP << 8) | 6UL))

#define OSRDN_RETIRE_MAGIC      0x52545230UL    /* "RTR0" */
#define OSRDN_RETIRE_VERSION    1UL
typedef struct {
    unsigned long magic;        /* in */
    unsigned long version;      /* in */
    unsigned long status;       /* out: 0 when everything accepted is drawn; else an errno */
    unsigned long waited;       /* out: 1 if the kernel still had a submission in flight */
    unsigned long us;           /* out: how long this RETIRE took */
    unsigned long asubmits;     /* out: sticky, accepted submissions this boot */
    unsigned long lost;         /* out: sticky, recoveries that threw accepted work away (events, not submissions) */
    unsigned long rc;           /* out: the CP unit's return code (CP_RC_*, as a two's complement) */
} osrdn_r7b_retire;
#define OSRDN_R7B_IOC_RETIRE    ((unsigned long)(OSRDN_R7B_IOC_IN | OSRDN_R7B_IOC_OUT | \
    ((sizeof(osrdn_r7b_retire) & OSRDN_R7B_IOC_PARM_MASK) << 16) | \
    ((unsigned long)OSRDN_R7B_IOC_GROUP << 8) | 7UL))
typedef char osrdn_r7b_retire_fits[(sizeof(osrdn_r7b_retire) <
                                    OSRDN_R7B_IOC_PARM_MASK) ? 1 : -1];

/*
 * G3 (docs/G3_PRESENT_PLAN.md 2-1): PUT A RECTANGLE OF THE CLIENT'S SURFACE ON
 * THE SCREEN.  The kernel builds the blit itself (the reference's
 * radeon_cp_dispatch_swap, radeon_state.c 1343-1400) and sends it down the
 * same ring as everything else; nothing of the client's is interpreted as a
 * packet.  srcOrg is an offset INTO THE WINDOW (card address winStart +
 * srcOrg), srcStride is in pixels, dst is in screen pixels from the top left.
 * The verdict numbers are the Matrox driver's (OpenStepMGAHW3D.h 1414-1421):
 * SDL's stamp loop reads 3 (DST) and 5 (BUSY) by value.
 */
#define OSRDN_PRESENT_MAGIC     0x50525330UL    /* "PRS0" */
#define OSRDN_PRESENT_VERSION   1UL
#define OSRDN_PRESENT_OK        0UL
#define OSRDN_PRESENT_E_MAGIC   1UL     /* wrong magic or version */
#define OSRDN_PRESENT_E_SRC     2UL     /* the source rectangle leaves the window */
#define OSRDN_PRESENT_E_DST     3UL     /* the destination leaves the screen */
#define OSRDN_PRESENT_E_GEOM    4UL     /* zero or oversized, or a stride the engine cannot encode */
#define OSRDN_PRESENT_E_BUSY    5UL     /* the card is claimed; try again */
#define OSRDN_PRESENT_E_LATCH   6UL     /* the CP failed under this request (latched or recovered) */
#define OSRDN_PRESENT_E_MODE    7UL     /* no mode, no CP, or not a 32 bpp screen */
#define OSRDN_PRESENT_VERDICTS  8
typedef struct {
    unsigned long magic;        /* in */
    unsigned long version;      /* in */
    unsigned long srcOrg;       /* in: window offset of the surface, 64-byte aligned */
    unsigned long srcStride;    /* in: pixels a surface row holds (x 4 must be a multiple of 64) */
    unsigned long srcX, srcY;   /* in: pixels into the surface */
    unsigned long w, h;         /* in: pixels */
    unsigned long dstX, dstY;   /* in: screen pixels, top-left origin */
    unsigned long status;       /* out: 0, or an errno */
    unsigned long verdict;      /* out: OSRDN_PRESENT_* */
} osrdn_r7b_present;
#define OSRDN_R7B_IOC_PRESENT   ((unsigned long)(OSRDN_R7B_IOC_IN | OSRDN_R7B_IOC_OUT | \
    ((sizeof(osrdn_r7b_present) & OSRDN_R7B_IOC_PARM_MASK) << 16) | \
    ((unsigned long)OSRDN_R7B_IOC_GROUP << 8) | 4UL))
typedef char osrdn_r7b_present_fits[(sizeof(osrdn_r7b_present) <
                                     OSRDN_R7B_IOC_PARM_MASK) ? 1 : -1];
/* what the kernel hands the CP unit with the block: the screen it may write */
typedef struct {
    osrdn_r7b_present *blk;
    unsigned long modeW, modeH;     /* the mode's pixels */
    unsigned long rowBytes;         /* the screen's pitch */
    unsigned long bytesPerPixel;    /* 4, or the request is refused */
    unsigned long verdict;          /* out: the unit's verdict, copied under the claim */
} osrdn_cp_present_req;

/*
 * G3b (docs/G3B_CLEAR_PLAN.md 2-1): CLEAR THE CLIENT'S COLOUR AND/OR DEPTH ON THE
 * CARD -- the reference's radeon_cp_dispatch_clear (radeon_state.c 852-1262):
 * a 2D solid fill for the colour, the precedent's depth rectangle for the
 * depth.  Offsets are into the window; pitches in pixels; depthZ is the IEEE
 * float bits of the clear depth in [0, 1] (the rectangle's vertex z, which
 * the card writes as floor(z * 2^16), R6f).  The verdicts are the present's.
 */
#define OSRDN_CLEAR_MAGIC       0x434c5230UL    /* "CLR0" */
#define OSRDN_CLEAR_VERSION     1UL
#define OSRDN_CLEAR_COLOUR      1UL
#define OSRDN_CLEAR_DEPTH       2UL
typedef struct {
    unsigned long magic;        /* in */
    unsigned long version;      /* in */
    unsigned long flags;        /* in: OSRDN_CLEAR_COLOUR | OSRDN_CLEAR_DEPTH */
    unsigned long colourOff;    /* in: window offset of the colour surface, 1 KiB aligned */
    unsigned long colourPitch;  /* in: pixels a row holds (x 4 a multiple of 64) */
    unsigned long colourValue;  /* in: ARGB8888 */
    unsigned long depthOff;     /* in: window offset of the depth buffer, 32-byte aligned */
    unsigned long depthPitch;   /* in: pixels a depth row holds (a multiple of 32) */
    unsigned long depthZ;       /* in: float bits, 0.0 .. 1.0 */
    unsigned long w, h;         /* in: pixels */
    unsigned long status;       /* out: 0, or an errno */
    unsigned long verdict;      /* out: OSRDN_PRESENT_* */
} osrdn_r7b_clear;
#define OSRDN_R7B_IOC_CLEAR     ((unsigned long)(OSRDN_R7B_IOC_IN | OSRDN_R7B_IOC_OUT | \
    ((sizeof(osrdn_r7b_clear) & OSRDN_R7B_IOC_PARM_MASK) << 16) | \
    ((unsigned long)OSRDN_R7B_IOC_GROUP << 8) | 5UL))
typedef char osrdn_r7b_clear_fits[(sizeof(osrdn_r7b_clear) <
                                   OSRDN_R7B_IOC_PARM_MASK) ? 1 : -1];
typedef struct {
    osrdn_r7b_clear *blk;
    unsigned long bytesPerPixel;    /* 4, or the request is refused */
    unsigned long verdict;          /* out: the unit's verdict, copied under the claim */
} osrdn_cp_clear_req;

#endif /* OSRDN_R7B_H */
