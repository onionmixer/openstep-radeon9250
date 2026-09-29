/*
 * OSRDNMesaTri.h - M1d: one triangle, to the card or to the software function
 * (docs/M1D_PLAN.md).
 *
 * This unit owns the BATCH window and the SUBMIT ioctl.  It knows nothing about
 * Mesa: the caller hands it three vertices already in the card's form, because
 * only OSRDNMesaHook.c may include Mesa's headers.
 *
 * Its one promise, and the reason the rung exists: A TRIANGLE IS NEVER LOST.
 * Every path that cannot submit says so and returns 0, and the caller then draws
 * it with the software function it saved.  The precedent lost a whole process's
 * acceleration twice by getting this the other way round.
 */

#ifndef OSRDN_MESA_TRI_H
#define OSRDN_MESA_TRI_H

/* Why a triangle did not reach the card.  Counting only "not submitted" would
   make a gate unable to tell "the card is busy" from "we built a bad stream". */
#define OSRDN_TRI_OK            0
#define OSRDN_TRI_NO_ACCEL      1   /* the probe did not say HARDWARE */
#define OSRDN_TRI_NOT_RUNNING   2   /* CAPS says the CP is not running */
#define OSRDN_TRI_NO_WINDOW     3   /* the batch window could not be mapped */
#define OSRDN_TRI_ARGS          4   /* a size or pitch we cannot express */
#define OSRDN_TRI_IOCTL         5   /* the ioctl itself failed */
#define OSRDN_TRI_REFUSED       6   /* the kernel's verifier said no */
#define OSRDN_TRI_NOT_DRAWN     7   /* it was accepted but did not reach the ring */
/* M1k: a batch is waiting in the window, so a single send would write over it.
   The caller is supposed to flush first; this refuses rather than corrupt, and
   having its own reason means the gate can tell it from a card refusal. */
#define OSRDN_TRI_BATCH_OPEN    8
/* G4-1a: the `depth` argument is a CODE from osrdn_class_depth_code -- 0 off, else
   1 | ztest << 1 | write << 4; `blend` and `tex` are OSRDN_TRI_BLEND_* / OSRDN_TRI_TEX_* */
/* G4-1b: the texture the next textured triangles sample -- its arena byte offset inside the
   window, its size (POT, 8..512) and its two filters.  Set by the hook once it has the image
   resident; read by the prologue's TXOFFSET/TXFORMAT/TXFILTER/TXSIZE/TXPITCH slots and by the
   batch key, so a change of texture closes the batch. */
/* G4-4 K5: the MIN filter as a CODE (GL's six, named as GL names them; the Tri unit maps them onto
   the card's field the way r200SetTexFilter does), and how many levels of the chain are resident
   (1 = the base alone).  A code >= OSRDN_TRI_MIN_MIP_FIRST with levels == 1 is a contradiction
   the unit refuses (OSRDN_TRI_ARGS) rather than sends. */
/* the codes OSRDN_TRI_MIN_* are in the generated OSRDNMesaTriTable.h, beside OSRDN_TRI_TEX_* */
void osrdn_tri_texture_set(unsigned long byteOff, int w, int h, int magLinear, int minCode, int levels);

/*
 * G4-5 (docs/G4_5_MIP_PLAN.md 2-3): THE MIP KNOB.  Three answers:
 *   OSRDN_TRI_MIP_OFF       "0"   every mipmap MIN filter stays in software
 *   OSRDN_TRI_MIP_MEASURED  unset or anything else: all four mip modes go to the card, the two
 *                                  level-BLENDING ones SUBSTITUTED by the level-selecting mode with
 *                                  the same texel filter (OSRDNMesaTri.c triMinSent; G4-10) -- the
 *                                  blending path hangs this card (docs/G4_8_REPLAY_PLAN.md 15)
 *   OSRDN_TRI_MIP_ALL       "all" the four with their own values -- THIS FREEZES THE MACHINE within
 *                                  a few submissions on this card; it exists as the reproducer only
 */
#define OSRDN_TRI_MIP_ENV       "RDNMesaMip"

/*
 * G4-6 (docs/G4_6_GLQUAKE_PLAN.md 8): THE SUBMISSION TRACE, for a stream that freezes the machine.
 * RDNMesaTrace=<file>: one line per submission, written and fsynced BEFORE the ioctl (sequence,
 * words, triangles, and per segment the texture offset, size, MIN code and level count).
 * RDNMesaTraceLast=<file>: the whole stream, rewritten from offset 0 and fsynced before each
 * ioctl -- after a freeze it holds the stream the card was executing.  One fd each, kept open
 * (tools/nxbreadcrumb.c: reopening per record keeps only the last record).  Unset: nothing.
 */
#define OSRDN_TRI_TRACE_ENV      "RDNMesaTrace"
#define OSRDN_TRI_TRACE_LAST_ENV "RDNMesaTraceLast"
/* OSRDN_TRI_MIP_OFF / _MEASURED / _ALL are in the generated OSRDNMesaTriTable.h (the classifier
   reads them and includes only the table) */

int osrdn_tri_mip_mode(void);
/* G4-3 K2: the alpha test the next triangles draw with -- a code from osrdn_class_alpha_code
   (1 | op << 1 | ref << 4), or 0 for off.  Read by the PP_CNTL and PP_MISC slots and by the batch
   key, so a change closes the batch. */
void osrdn_tri_alpha_set(unsigned long code);
#define OSRDN_TRI_ALPHA_OP(c)     ((unsigned long)((c) >> 1) & 7UL)
#define OSRDN_TRI_ALPHA_REF(c)    ((unsigned long)((c) >> 4) & 0xffUL)
#define OSRDN_TRI_DEPTH_ZTEST(c)  ((unsigned long)((c) >> 1) & 7UL)
#define OSRDN_TRI_DEPTH_WRITE(c)  ((unsigned long)((c) >> 4) & 1UL)
#define OSRDN_TRI_REASONS       9

typedef struct {
    unsigned long entered;      /* our triangle function was called */
    unsigned long submitted;    /* and the triangle reached the ring */
    /* "delegated" is NOT counted here.  The promise of this rung is that the
       CALLER drew every triangle this unit refused, and a number this unit
       wrote could only ever say what it intended.  OSRDNMesaHook.c counts the
       delegations, and the gate compares the two: sum(refused) == delegated,
       or a triangle was lost. */
    unsigned long refused[OSRDN_TRI_REASONS];
    unsigned long maps;         /* batch-window mappings (must never exceed 1) */
    unsigned long opens;        /* node opens: one per submission, then closed */
    unsigned long lastWhy;      /* the verifier's verdict on the last submission */
    unsigned long lastAt;       /* the word it stopped at */
    unsigned long lastWord;
    unsigned long lastStatus;
    unsigned long words;        /* how many words the last stream was */
    unsigned long seed;         /* the last seed sent -- see OSRDN_TRI_SEED_ENV */
    unsigned long smoothSent;   /* submissions that carried the Gouraud shade value */
    unsigned long blendSent;    /* and this many carried the blend unit switched on */
    unsigned long texSent;      /* and this many carried the texture unit */
    unsigned long depthSent;    /* M1i: and this many carried the depth test */
    /*
     * M1k.  `submitted` stays what it always was -- TRIANGLES that reached the
     * ring -- so every equality M1d..M1j gates on survives batching unchanged.
     * These three are about the SUBMISSIONS those triangles rode in:
     */
    unsigned long batched;      /* triangles taken into a batch */
    unsigned long flushes;      /* batches that reached the ring (one ioctl each) */
    unsigned long flushFailed;  /* batches the card would not take */
    /* G4-2 B1: the client-side verdicts (osrdn_tri_batch_verify), and the
       triangles a truncation dropped from the stream (drawn by the caller) */
    unsigned long verifies;
    unsigned long verifyRefused;
    unsigned long truncated;
    /* G4-2 B2: segments opened after a batch's first (a state change inside
       the stream), and the register-pair words they cost */
    unsigned long segments;
    unsigned long segWords;
    /* G5-2 (docs/G5_2_ASYNC_SUBMIT_PLAN.md 2-4): accepted submissions and their retirement */
    unsigned long async;        /* 1 when SUBMIT3 is in use (the kernel answered RETIRE at start) */
    unsigned long asubmits;     /* batches the kernel accepted without waiting */
    unsigned long retires;      /* RETIRE ioctls that ran (a submission was in flight) */
    unsigned long retiresSkipped;   /* retire points reached with nothing in flight: no ioctl */
    unsigned long retireFailed; /* RETIREs the kernel could not complete (the CP failed or recovered) */
    unsigned long retireUs;     /* the kernel's own microseconds for the RETIREs that ran */
    unsigned long lateLatch;    /* a submission failed while an earlier accepted one was in flight */
    unsigned long lost;         /* the kernel's count of recoveries that threw accepted work away (events) */
    unsigned long batchCap;     /* G5-5: RDNMesaBatchWords in force (0 = the driver's own limit) */
    unsigned long batchCapIgnored;  /* G5-5: a value below 256 that was ignored */
} osrdn_tri_counts;

/*
 * What was actually SENT, kept so the host can judge without guessing.
 *
 * The picture the card draws is predicted by tools/r6/tri_oracle.py's
 * cover(pts, MEASURED) -- but only if the host knows which vertices reached the
 * card, and those are Mesa's window coordinates after a transform this side
 * cannot reproduce.  So they are recorded here and printed, and the prediction
 * is made from what went out rather than from what the test meant to draw.
 *
 * A ring, because a scene has more triangles than anyone wants to read.
 */
#define OSRDN_TRI_LOG   8
/* the WIDEST vertex, not the plain one: a textured triangle is 3 x 7 words and
   recording it short would have the host predict from half a triangle */
#define OSRDN_TRI_LOG_WORDS (3 * 7)

typedef struct {
    unsigned long n;                                    /* how many were sent in all */
    unsigned long words;                                /* how wide the last one was */
    unsigned long v[OSRDN_TRI_LOG][OSRDN_TRI_LOG_WORDS];
} osrdn_tri_sent;

const osrdn_tri_sent *OSRDNMesaTriSent(void);

/*
 * M3d: the FIRST stream the card did not take, word for word (docs/M3D_PLAN.md).
 *
 * The ring above records only what succeeded, so when the CP latched on a
 * two-triangle batch nothing said what those two triangles were.  This keeps
 * the whole stream of the first failed submission -- the words exactly as the
 * kernel was offered them -- and the verdict that came back with it.  Later
 * failures do not overwrite it: after a latch every submission fails, and the
 * one that matters is the first.
 *
 * The size is the batch limit, which lives in the generated table;
 * OSRDNMesaTri.c stops the build if the two ever differ.
 */
#define OSRDN_TRI_FAIL_WORDS 4068

typedef struct {
    unsigned long n;            /* words held; 0 = nothing has failed */
    unsigned long failures;     /* how many submissions failed in all */
    unsigned long reason;       /* OSRDN_TRI_* from triSubmit */
    unsigned long tris;         /* triangles in it */
    unsigned long vw;           /* words per vertex */
    unsigned long batch;        /* 1 = a batch flush, 0 = a single send */
    unsigned long seed;         /* the seed it went with */
    unsigned long why, at, word, status;   /* the kernel's answer, as triCounts */
    unsigned long w[OSRDN_TRI_FAIL_WORDS];
} osrdn_tri_failed;

const osrdn_tri_failed *OSRDNMesaTriFailed(void);

/*
 * Put one vertex in the buffer.
 *
 * The caller passes the vertex NUMBER and whether the triangle is textured, and
 * this decides the stride -- once, in one place.  The hook used to write both
 * shapes itself, the five-word slots first and the seven-word ones after, and
 * for i = 2 the five-word writes landed inside vertex 1's seven-word block: the
 * card got 28.0 where a colour belonged and a texture coordinate where a w
 * belonged.  Every host check passed; the picture came back unjudgeable.
 *
 * `vtx` must have room for 3 * OSRDN_TEX_VERTEX_WORDS.  s and t are ignored
 * when tex is 0, which is why they may be anything there.
 */
void osrdn_tri_vertex(unsigned long *vtx, int i, int tex,
                      unsigned long x, unsigned long y, unsigned long z,
                      unsigned long w, unsigned long col,
                      unsigned long s, unsigned long t);

/*
 * M1t: THE LAYOUT, WRITTEN ONCE.
 *
 * The comment above records what happens when it is written twice -- five-word
 * writes landing inside a seven-word block, the card reading 28.0 where a
 * colour belonged.  So the hook's inline path (RDNMesaInline) and the function
 * above BOTH expand these, and neither spells the slots out again.
 *
 * No argument check here: the one caller runs `for (i = 0; i < 3; i++)` over a
 * local array, so `vtx != 0` and `0 <= i < 3` are structural.  The function
 * keeps its own check for callers that are not that loop.
 */
#define OSRDN_TRI_VERTEX_AT(vtx, i, tex)                                      \
    ((vtx) + (long)(i) * (long)((tex) ? OSRDN_TEX_VERTEX_WORDS                \
                                      : OSRDN_TRI_VERTEX_WORDS))

#define OSRDN_TRI_VERTEX_PUT(q, tex, x, y, z, w, col, s, t)                   \
    do {                                                                      \
        (q)[0] = (x);                                                         \
        (q)[1] = (y);                                                         \
        (q)[2] = (z);                                                         \
        (q)[3] = (w);                                                         \
        (q)[4] = (col);                                                       \
        if (tex) {                                                            \
            (q)[5] = (s);                                                     \
            (q)[6] = (t);                                                     \
        }                                                                     \
    } while (0)

/*
 * M1t: the hook's inline path.  Default OFF.  It changes no value and no slot
 * -- only how many calls a word crosses on its way into vtx[] (docs/M1T_PLAN.md).
 */
#define OSRDN_TRI_INLINE_ENV "RDNMesaInline"

int osrdn_tri_inline_enabled(void);

/*
 * WHERE THE SEED COMES FROM.
 *
 * The kernel refuses a repeated seed (CP_WHY_SEED): the marker pattern is
 * derived from it, and a repeat would let a stale read-back pass for a fresh
 * one.  A counter starting at 1 inside the library therefore works ONCE per
 * boot and is refused every run after that -- measured, boot ed7bef6a: the
 * first run drew and the second was refused with why=13.
 *
 * So the base comes from the environment, as R7a's tool takes it from its run
 * id.  The seed that was used is reported either way, so a collision is
 * legible instead of looking like a refusal with no reason.
 *
 * Unset -- every program a user runs -- the base used to be 0, and a process
 * whose predecessor had submitted exactly once had its first submission
 * refused (the kernel refuses a seed equal to the previous one).  From REL1
 * (docs/REL1_PACKAGING_PLAN.md 16, B8) the unset base comes from
 * gettimeofday, kept between 65536 and 1000065535 (below 2^30).
 */
#define OSRDN_TRI_SEED_ENV  "RDNMesaSeed"

/*
 * M1l: THE BATCH KNOB.
 *
 * "0" turns batching off and every triangle goes alone -- the path M1d..M1j
 * used and the hardware proved.  It exists so the cost of a submission can be
 * measured against itself in one boot: the same scene, the same pixels, a
 * different number of ioctls.
 *
 * Anything else, including unset, leaves batching on.  A knob that could be
 * mistyped into a third behaviour would make a measurement unreadable.
 */
#define OSRDN_TRI_BATCH_ENV "RDNMesaBatch"

/* 1 when batching is allowed.  Read from the environment once, then cached. */
int osrdn_tri_batch_enabled(void);

/*
 * M1l: HOLD THE DESCRIPTOR.
 *
 * This unit opens the node for one ioctl and closes it again, because the
 * driver's latch lets exactly one holder exist and other units want the node
 * too.  Within ONE process that is a policy, not a requirement: the latch
 * refuses a SECOND open, not a long first one.
 *
 * "1" holds it from the first submission until osrdn_tri_release().  It exists
 * to split the 13.56 ms fixed cost M1l measured: if open/close is the bulk,
 * this removes it, and if it is not, the number will not move.  Default off --
 * holding locks the surface and the probe out of the node, and that is a real
 * cost outside a measurement.
 */
#define OSRDN_TRI_HOLD_ENV  "RDNMesaHold"

int osrdn_tri_hold_enabled(void);
void osrdn_tri_hold_set(int on);        /* G3: programmatic hold (docs/G3_PRESENT_PLAN.md 2-2) */
int osrdn_tri_device_open(void);        /* G3: the present rows use the triangle path's open */
void osrdn_tri_device_close(int fd);

/*
 * M1l/M1m: POISON THE STREAM (a measurement knob, never a shipping one).
 *
 * "1" corrupts the FIRST word of every stream just before the ioctl, so the
 * kernel's verifier refuses it at word 0 (measured on the host oracle: word 0
 * = 0xffffffff gives why=6, "packet3 opcode 0xff00").  The submission then
 * costs the ioctl, the driver's fixed path and its 25 log lines -- and NONE of
 * the per-word verification, the ring copy or the drawing.
 *
 * It is how the 13.56 ms fixed cost is split WITHOUT changing the driver: if a
 * refused submission costs the same, the cost is not the work.
 *
 * The picture stays right: every refused triangle comes back to the hook and
 * the software function draws it, which is the promise at the top of this file
 * and which the counters prove (flushFailed and replayed both rise).
 */
#define OSRDN_TRI_POISON_ENV "RDNMesaPoison"

int osrdn_tri_poison_enabled(void);

/*
 * M1p: WHERE THE CLIENT BUILDS THE STREAM.
 *
 * 0 (the default) builds it in the mapped window, which is CACHE-INHIBITED --
 * 69 ns a word, measured, 1.03 us a triangle.  1 builds it in this process's
 * own cached memory and the driver copies it in, which is what the DRI
 * reference does (r200_context.h:712-717 is a plain array; the kernel reads it
 * with copy_from_user).
 *
 * THIS ONE IS A SETTER, NOT A LATCH.  The other knobs are read once because
 * they choose a path for a whole run; this one has to be switchable BETWEEN
 * blocks of one run, because the only way to price the two paths without the
 * arm-order drift that ruined M1n is to alternate them inside one process.
 * The environment gives the starting value; the caller may change it.
 */
#define OSRDN_TRI_COPYIN_ENV "RDNMesaCopyin"

int osrdn_tri_copyin_enabled(void);
void osrdn_tri_set_copyin(int on);

/*
 * M1r: THE SENT-TRIANGLE RING, WHICH IS PURE INSTRUMENTATION AND IS NOT FREE.
 *
 * `triRecord` copies OSRDN_TRI_LOG_WORDS -- twenty-one -- into a ring for EVERY
 * triangle, with a conditional and a modulo, whether or not anything will read
 * them.  M1q left 1.20 us a triangle in userland and priced the hook's whole
 * arithmetic at 50 ns of it, so the copies are where the time is; this knob
 * prices this one.
 *
 * DEFAULT ON: the ring is what the M1d..M1k gates predict the picture from.
 * With it off, `n` is reported as ZERO rather than as a count with the previous
 * run's rows behind it -- a judge that wants the vertices then FAILS instead of
 * reading something that is not this run's.
 */
#define OSRDN_TRI_SENTLOG_ENV "RDNMesaSentLog"

int osrdn_tri_sentlog_enabled(void);

/*
 * M1s: THE BISECTION KNOB.
 *
 * M1p and M1r both predicted a cost from "operations counted in the source x a
 * rate from a microbenchmark" and both were wrong -- once by a factor of fifty,
 * once by 1.7.  So the remaining userland microsecond is not estimated again;
 * it is BISECTED.
 *
 * With this on, the hook does everything it does now -- classify, read the
 * state, assemble the three vertices -- and then does NOT call this unit at
 * all: the triangle goes to Mesa's software function, exactly as a declined one
 * does.  So
 *
 *     nullsend - stock   = what the HOOK costs a triangle
 *     poison   - nullsend = what this UNIT and the ioctl cost
 *
 * with one software draw on both sides of each subtraction, cancelling.
 *
 * The witness is `submitted`, which the transcript already prints: in this arm
 * it must be ZERO while the hook's `triangles` is not.
 */
#define OSRDN_TRI_NULLSEND_ENV "RDNMesaNullSend"

int osrdn_tri_nullsend_enabled(void);

/*
 * M1v: THE WHOLE-GROUP HOOK.  Default OFF.
 *
 * With it on, the hook installs its own copy of Mesa's raw render table with
 * the GL_TRIANGLES slot replaced, so a whole begin/end group arrives in one
 * call and the state work happens once for the group instead of once for every
 * triangle (docs/M1V_PLAN.md).  It draws the same words; the gate is that the
 * sent words and the picture do not move.
 */
#define OSRDN_TRI_GROUP_ENV "RDNMesaGroup"

int osrdn_tri_group_enabled(void);

/*
 * G5-2 (docs/G5_2_ASYNC_SUBMIT_PLAN.md 2-4): SUBMISSIONS ARE ACCEPTED, NOT WAITED FOR.
 *
 * When the driver answers RETIRE (asked once, at the first submission), batches go
 * by SUBMIT3: the kernel puts them on the ring and returns while the card draws.
 * Anything that then reads or writes the window with the CPU -- a texture upload,
 * the mirror, the depth read, Mesa's own software paths -- calls
 * osrdn_tri_retire_if_inflight() first.  It costs nothing when no batch went out
 * since the last one, and one ioctl when one did.  RDNMesaSync=1 keeps SUBMIT2.
 */
#define OSRDN_TRI_SYNC_ENV  "RDNMesaSync"
/* G5-5 (docs/G5_5_BATCH_SIZE_PLAN.md): the most words a batch may reach, if lower than the driver's;
   256 and up, read once */
#define OSRDN_TRI_BATCH_WORDS_ENV "RDNMesaBatchWords"
int osrdn_tri_async(void);
int osrdn_tri_retire_if_inflight(void);

const osrdn_tri_counts *OSRDNMesaTriCounts(void);
const char *OSRDNMesaTriWhyName(int why);

/*
 * Send one triangle.  `vtx` is 3 * OSRDN_TRI_VERTEX_WORDS words, already in the
 * card's order (x, y, z, w as IEEE bits, then the packed colour).  Returns 1 if
 * the triangle reached the ring and 0 otherwise -- and 0 means the caller must
 * draw it itself.  *why is set either way; it may be null.
 *
 * The surface is named by its byte offset INSIDE the window: the window's card
 * address comes from the probe's CAPS, and no address is written in this file.
 *
 * `tex` picks the whole PROLOGUE, not just a register: a textured draw needs
 * the texture unit on, six texture registers, and -- the part that is easy to
 * miss -- SEVEN-word vertices (x, y, z, w, colour, s, t) instead of five,
 * because SE_VTX_FMT_1 asks for two components on unit 0 and the kernel checks
 * that the data count matches (osrdn_cp.m 2031).  So `vtx` is 3 * 5 words when
 * tex is 0 and 3 * 7 when it is 1, and the caller must agree.
 *
 * `blend` picks the blend unit: 0 leaves it off, 1 is
 * SRC_ALPHA / ONE_MINUS_SRC_ALPHA / ADD_CLAMP.  BLENDCNTL is written EITHER WAY
 * -- the reference driver requires a defined value there even when blending is
 * disabled, or at least GL_MIN and GL_FUNC_REVERSE_SUBTRACT go wrong
 * (r200_state.c 197-200).  Our stream never wrote that register before M1f, so
 * it carried whatever the last operation left; now it does not.
 *
 * `smooth` picks the shade control: 0 sends the flat value, non-zero the Gouraud
 * one.  Both are generated (OSRDNMesaTriTable.h), and the Gouraud one is the
 * value R6e measured its interpolation rule under -- sending a different one
 * would make the host's prediction belong to a state the card was never in
 * (docs/M1E_PLAN.md 3).  The per-vertex colours are already in `vtx`; with
 * `smooth` 0 the caller puts the same colour in all three.
 */
int osrdn_tri_send(unsigned long colourByteOff, int pitchPixels,
                   int width, int height, const unsigned long *vtx,
                   int smooth, int blend, int tex, int depth, int *why);

/*
 * M1k: THE BATCH.  One prologue, one draw packet, many triangles.
 *
 * A batch is the same stream osrdn_tri_send() builds, with more vertices in the
 * one draw packet -- the shape the R6 ladder measured with
 * (tools/r6/tri_oracle.py:143).  Nothing about the picture changes; only the
 * number of ioctls does.
 *
 * WHY THE CALLER MUST STILL BE ABLE TO DRAW THEM.  The promise at the top of
 * this file does not bend for speed: if the flush fails, the caller draws every
 * triangle in that batch itself.  That is only correct while the vertices the
 * caller kept are still the ones Mesa would read, which is true inside one
 * render pass and NOT after it -- see docs/M1K_PLAN.md 8 and 10.  So the caller
 * batches only between Driver.RenderStart and Driver.RenderFinish, and flushes
 * there; outside it, it calls osrdn_tri_send() as before.
 *
 * osrdn_tri_batch_joins() answers "may this triangle go in the batch in hand?"
 * -- 0 when the batch is full or holds a different state, and then the caller
 * flushes first.  It asks nothing of the card and changes nothing.
 */
int osrdn_tri_batch_joins(unsigned long colourByteOff, int pitchPixels,
                          int width, int height, int smooth, int blend,
                          int tex, int depth);

/*
 * Take one triangle into the batch.  Returns the batch's new triangle count
 * (never 0 on success) or 0 if it was refused, with *why set as
 * osrdn_tri_send() sets it.  A refusal here means the caller must draw that
 * triangle itself, exactly as a refused send does.
 */
/*
 * M1r: THE TWO-PHASE FORM.
 *
 * `reserve` runs every rule `add` ran and hands back where the three vertices
 * go, or 0 with *why set.  `commit` counts the triangle.  Between them the
 * caller writes 3 * vw words; a caller that changes its mind writes into a part
 * of the window the flush never sends, because the draw packet's count and the
 * ioctl's length both come from the triangle count that only `commit` moves.
 *
 * `add` is written in terms of these two, so there is ONE decision path.
 */
unsigned long *osrdn_tri_batch_reserve(unsigned long colourByteOff,
                                       int pitchPixels, int width, int height,
                                       int smooth, int blend, int tex,
                                       int depth, int *why);
unsigned long osrdn_tri_batch_commit(void);

unsigned long osrdn_tri_batch_add(unsigned long colourByteOff, int pitchPixels,
                                  int width, int height,
                                  const unsigned long *vtx,
                                  int smooth, int blend, int tex, int depth,
                                  int *why);

/* How many triangles are waiting.  The caller keeps the same number of vertex
   triples for the replay, and a disagreement is a bug, not a state. */
unsigned long osrdn_tri_batch_count(void);

/*
 * Send the batch.  Returns how many triangles reached the ring; 0 means either
 * there was nothing waiting (*why is OSRDN_TRI_OK) or the card refused the
 * whole batch (*why says which), and in THAT case the caller must draw all of
 * them itself.  The batch is empty when this returns, either way.
 */
unsigned long osrdn_tri_batch_flush(int *why);

/* Give the batch window back.  Safe with nothing mapped, and safe twice. */
void osrdn_tri_release(void);

/*
 * G4-2 B1: A BATCH MAY OUTLIVE THE RENDER BRACKET (docs/G4_2_BATCH_PLAN.md 2-3).
 *
 * The promise above rested on the caller being able to redraw a refused batch,
 * which needs the vertices Mesa handed it to still be there -- true inside one
 * render bracket and not after.  B1 keeps a batch open across brackets, so the
 * promise is kept differently: BEFORE a bracket ends, the caller asks the same
 * verifier the kernel runs (mesa/OSRDNMesaVerify.c, generated from the kernel's
 * text) whether the stream in hand would be refused.  Refused: it is drawn now,
 * while the vertices are alive.  Accepted: it stays open, and the only way it
 * can then fail is a card that does not answer (EIO), which is counted by the
 * caller as lost -- the one hole, named, not hidden.
 *
 * osrdn_tri_batch_verify() writes the draw header exactly as the flush would,
 * runs the verifier over the words that would be sent, and returns its verdict
 * (CP_R7_WHY_OK, or the rule; *at and *word say where).  No ioctl, no change
 * to the batch.  winBytes is how far the caller's surface mapping reaches: the
 * verifier's window bound is [winStart, winStart + winBytes), never larger than
 * the kernel's own, so a stream this accepts is one the kernel accepts for the
 * same reason, and a stream the kernel would accept past this bound is merely
 * refused here (drawn in software: slower, never wrong).
 *
 * osrdn_tri_batch_truncate(keep) drops every triangle after the first `keep`
 * from the stream -- the caller uses it when a bracket's tail is refused but
 * the prefix a previous bracket verified must still go out whole.  Returns the
 * count now in hand; 0 empties the batch without sending.
 *
 * The knob: "0" restores the M1k shape (every batch is flushed at RenderFinish,
 * nothing is ever kept open), so the two can be measured against each other in
 * one boot.  Anything else, including unset, keeps batches open.
 */
#define OSRDN_TRI_SPAN_ENV  "RDNMesaSpan"

/*
 * G4-2 B2: SEGMENTS (docs/G4_2_BATCH_PLAN.md 4).  A state change no longer
 * closes the batch: the pairs of the new state's prologue whose value differs
 * from what the stream last wrote are appended, then a new draw header, then
 * its triangles -- the r200 shape (dirty atoms as raw register writes before
 * the draw, r200_cmdbuf.c 216-230).  osrdn_tri_batch_joins() says whether the
 * pairs, the header and the triangle fit; a SURFACE change still closes the
 * batch, because the verifier judges the surface once, by its last value.
 * This many segments a stream may have; past it the caller flushes (F1).
 */
#define OSRDN_TRI_SEGS      256

int osrdn_tri_span_enabled(void);
unsigned long osrdn_tri_batch_verify(unsigned long winBytes, unsigned long *at,
                                     unsigned long *word);
unsigned long osrdn_tri_batch_truncate(unsigned long keep);

#endif /* OSRDN_MESA_TRI_H */
