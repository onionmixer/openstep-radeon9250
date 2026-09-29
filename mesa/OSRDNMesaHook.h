/*
 * OSRDNMesaHook.h - M1b: what the ten hooks have done so far (docs/M1B_PLAN.md).
 *
 * In M1b only UpdateState does anything, and what it does is LOOK: it asks the
 * gate once, reads the state, classifies it and counts.  Nothing is installed,
 * nothing is drawn, no pixel is written.  Gate B3 holds that to more than a
 * promise -- the undefined symbols of this object are an allow-list that has no
 * way to draw in it.
 *
 * The counters are the other half of the rung's evidence.  A picture identical
 * to the software one proves nothing on its own: the hooks might never have
 * been called.  So the gate wants both, from one run.
 */

#ifndef OSRDN_MESA_HOOK_H
#define OSRDN_MESA_HOOK_H

#include "OSRDNMesaClass.h"

/*
 * One counter per hook, so that "never called" and "called and declined" are
 * different readings.  The order is the order osmesa.c declares them in.
 */
#define OSRDN_HOOK_UPDATE_STATE     0
#define OSRDN_HOOK_BUFFER           1
#define OSRDN_HOOK_DEPTH_BUFFER     2
#define OSRDN_HOOK_RELEASE_BUFFER   3
#define OSRDN_HOOK_BOUND_TO         4
#define OSRDN_HOOK_APP_BUFFER       5
#define OSRDN_HOOK_COPY_DEPTH       6
#define OSRDN_HOOK_MIRROR           7
#define OSRDN_HOOK_STRIDE           8
#define OSRDN_HOOK_CLEAR_PIXEL      9
#define OSRDN_HOOKS                10

/*
 * G4-2 B1: what closed a batch.  Each is one line of docs/G4_2_BATCH_PLAN.md 3
 * (F1-F10) or one of the two the M1k shape already had.  A gate reads the
 * table to see WHICH events fired, and a batching change that closes batches
 * from a place not on this list is a change nobody reviewed.
 */
#define OSRDN_FLUSH_OUTSIDE     0   /* M1k: a hook outside the bracket (Finish, RenderStart with the span knob off) */
#define OSRDN_FLUSH_BRACKET     1   /* M1k: RenderFinish, span knob off */
#define OSRDN_FLUSH_STATE       2   /* F1: the next triangle would not join (limit, or a different state) */
#define OSRDN_FLUSH_CTX         3   /* another context's triangle */
#define OSRDN_FLUSH_REFUSED     4   /* F2: RenderFinish, the verifier refused the stream */
#define OSRDN_FLUSH_POINTS      5   /* F3: software points about to be drawn */
#define OSRDN_FLUSH_LINES       6   /* F3: software lines */
#define OSRDN_FLUSH_DELEGATE    7   /* F4: a triangle about to be drawn in software */
#define OSRDN_FLUSH_LEAVE       8   /* F5: UpdateState declined the new state */
#define OSRDN_FLUSH_CLEAR       9   /* F6 */
#define OSRDN_FLUSH_GLFLUSH     10  /* F6: glFlush */
#define OSRDN_FLUSH_READPIX     11  /* F7 */
#define OSRDN_FLUSH_COPYPIX     12
#define OSRDN_FLUSH_DRAWPIX     13
#define OSRDN_FLUSH_BITMAP      14
#define OSRDN_FLUSH_TEXUPLOAD   15  /* F8: texels about to be written */
#define OSRDN_FLUSH_TEXDROP     16  /* F8: a resident block about to be freed */
#define OSRDN_FLUSH_SURFACE     17  /* F9: the surface is being taken */
#define OSRDN_FLUSH_RELEASE     18  /* F9: the surface is going away */
#define OSRDN_FLUSH_ALONE       19  /* a triangle outside any bracket goes alone; the batch first */
#define OSRDN_FLUSH_REASONS     20

typedef struct {
    unsigned long hook[OSRDN_HOOKS];        /* calls, per hook */
    unsigned long cls[OSRDN_CLASSES];       /* UpdateState's verdicts */
    unsigned long why[OSRDN_WHY_REASONS];   /* and why it declined */
    unsigned long rowLength;                /* the last ones seen, for the log line */
    unsigned long yUp;
    /*
     * M1c's first question, answered by measurement rather than guessed: which
     * raster bits are actually set when we decline for RASTER.  M1b found that
     * EVERY decline was RASTER, so the common OSMesa state has bits we do not
     * know -- and which ones cannot be reasoned out, only read.
     */
    unsigned long rasterSeen;               /* every bit ever seen, OR-ed */
    unsigned long rasterDeclined;           /* the bits in states we declined */
    /*
     * And the mask of the MOST RECENT state.  The OR above can only grow, so a
     * question like "is ALPHABUF_BIT gone now" is unanswerable from it -- once
     * set it is set forever.  Measured the hard way: the M1c judge asked that
     * of the accumulated mask and it could never have said yes.
     */
    unsigned long rasterLast;
    unsigned long verdict;                  /* what the gate said, once */
    unsigned long asked;                    /* 1 once the gate has been asked */
    /* M1d */
    unsigned long installs;                 /* times our triangle function went in */
    unsigned long leaves;                   /* times we left Mesa's choice alone */
    unsigned long triangles;                /* times it was CALLED (not the same thing) */
    unsigned long delegated;                /* and handed to the software function */
    unsigned long culled;                   /* M3b: back faces we dropped ourselves */
    unsigned long finishes;                 /* M3g: glFinish calls that reached us */
    unsigned long finishMirrors;            /* M3g: ... and copied the surface back */
    unsigned long finishStoodDown;          /* G3: ... or did not, because a present was on */
    unsigned long codeGap;                  /* G4-1a: a feature on with no code -- classifier and hook disagree (must stay 0) */
    unsigned long colourClears;             /* G3b: colour clears the card did (the bit taken from Mesa) */
    unsigned long colourClearBad;           /* G3b: ... refused, Mesa cleared its array instead */
    unsigned long finishForeign;            /* M3g: Driver.Finish held someone else's */
    unsigned long notUp;                    /* M3g: states declined for Y_UP false */
    unsigned long noSoftware;               /* delegated with nothing saved -- must stay 0 */
    unsigned long notBound;                 /* delegated WITHOUT asking the card: the surface
                                               was not ours, so the tri unit never saw it and
                                               never counted a refusal.  Without this the
                                               'refused == delegated' check cannot close. */
    unsigned long slotsFull;                /* contexts we could not remember */
    unsigned long caps;                     /* the last ctx->TriangleCaps seen */
    unsigned long shade;                    /* the last ctx->Light.ShadeModel seen */
    unsigned long blend;                    /* M1f: 0, or the last blend src factor seen */
    unsigned long tex;                      /* M1g: the last ctx->Texture.ReallyEnabled */
    unsigned long texAbsent;                /* G4-1b: draws refused because the image could not be made resident */
    unsigned long texUploads;               /* images this hook put in the window */
    unsigned long texUploadBad;             /* and the ones that would not read back */
    unsigned long texProjective;            /* textured triangles with more than s and t */
    /* the LAST RasterMask, kept because a decline for RASTER otherwise names
       no value and the next step is a guess -- M1g spent a run learning that
       TEXTURE_BIT is 0x1000 from the Mesa source instead of from the log */
    unsigned long rmask;
    unsigned long depthClears;              /* M1i: depth buffers filled */
    unsigned long depthClearBad;            /* and the ones that would not read back */
    unsigned long clearInstalls;            /* M1j: our Clear went in (once) */
    unsigned long clearCalls;               /* and was called this many times */
    unsigned long clearPassed;              /* and passed bits on this many times */
    /*
     * M1k: the batch.
     *
     * `batchAdds` are triangles this file put in a batch and `flushed` are the
     * ones a batch really delivered; the two differ exactly when a flush fails,
     * and then `replayed` says how many were drawn by the software function
     * instead.  Nothing is allowed to fall between them -- see the gate.
     */
    unsigned long renderStarts;             /* Driver.RenderStart came in */
    unsigned long renderFinishes;           /* and Driver.RenderFinish */
    unsigned long renderInstalls;           /* the two were installed this often */
    unsigned long batchAdds;                /* triangles taken into a batch */
    unsigned long flushes;                  /* batches sent */
    unsigned long flushed;                  /* triangles those batches delivered */
    unsigned long flushFailed;              /* batches the card would not take */
    unsigned long replayed;                 /* triangles the software drew after one */
    /*
     * OUTSIDE THE BRACKET.  Batching is only safe between RenderStart and
     * RenderFinish, because only there are the vertex indices still the ones
     * Mesa would read (docs/M1K_PLAN.md 8).  A triangle that arrives outside is
     * sent ALONE, exactly as M1d..M1j sent every triangle -- correct, just not
     * batched.  The gate wants this at 0: not because a non-zero is unsafe, but
     * because a non-zero means there is a path into the triangle function that
     * the reading did not find.
     */
    unsigned long outsideRender;
    unsigned long flushOutside;             /* flushes forced by the other hooks */
    unsigned long batchDesync;              /* our count and the unit's disagreed -- must stay 0 */
    /* M1v: the whole-group path.  `groupsLost` must stay 0 -- it counts a group
       we declined with nothing to hand it back to, which would lose triangles. */
    unsigned long groups;                   /* groups that came to our table slot */
    unsigned long groupsDeclined;           /* handed back to Mesa's own entry */
    unsigned long groupsLost;               /* declined with no fallback -- MUST be 0 */
    unsigned long groupTris;                /* triangles drawn through the group path */
    unsigned long groupInstalls;            /* times we put our table in */
    /* M1l: triangles sent alone because RDNMesaBatch=0, not because they
       arrived outside the bracket.  A measurement run has this non-zero and
       outsideRender still zero. */
    unsigned long batchOff;
    /* G4-2 B1 (docs/G4_2_BATCH_PLAN.md 2-3): batches live across brackets.
       prevalidated: a RenderFinish found the batch acceptable and left it open;
       prevalidateRefused: it would have been refused, so the fresh part was
       drawn in software there (the verified prefix, if any, went out alone:
       prefixFlushed); lostAtFlush: triangles a failed flush could NOT redraw
       because their bracket had ended -- the promise's one hole, counted;
       unfinished: a bracket ended without RenderFinish (its triangles are
       marked unreplayable); flushWhy[]: which event closed each batch. */
    unsigned long prevalidated;
    unsigned long prevalidateRefused;
    unsigned long prevalidateWhy;           /* the last refusing rule, and where */
    unsigned long prevalidateAt;
    unsigned long prevalidateWord;
    unsigned long prefixFlushed;
    unsigned long lostAtFlush;
    unsigned long unfinished;
    unsigned long multipass;                /* states with a MultipassFunc: not batched */
    unsigned long pointRuns;                /* the point and line wrappers were called */
    unsigned long lineRuns;
    unsigned long primNoSoftware;           /* and had nothing to call -- MUST be 0 */
    unsigned long glFlushes;                /* glFlush came in */
    unsigned long flushWhy[OSRDN_FLUSH_REASONS];
    unsigned long texChains;                /* G4-4 K5: chains (more than the base) made resident */
    unsigned long texWhy[OSRDN_TEXWHY_CLAUSES];     /* G4-6: TEXTURE declines by clause (osrdn_class_tex_why) */
    unsigned long texWhyVal[OSRDN_TEXWHY_CLAUSES];  /* and the last offending value of each */
    /* G5-4 (docs/G5_4_READPIX_AND_CLEANUP_PLAN.md 1): glReadPixels from the top-down (present
       mode) surface: answered by the flipped reader, or declined to Mesa (which reads it upside
       down -- so this must stay 0) */
    unsigned long readpixFlipped;
    unsigned long leavesUnbound;    /* leaves decided while this context had no card surface bound */
    unsigned long rendersWhileLeft; /* render passes begun while the last decision was a leave */
    unsigned long leavesWatched;    /* leaves made with our RenderStart in place (so the count above sees them) */
    unsigned long readpixFlipDeclined;
} osrdn_hook_counts;

/* Read-only; never null.  A caller prints it, it does not reset it: a counter a
   test can zero is a counter a test can zero at the wrong moment. */
const osrdn_hook_counts *OSRDNMesaHookCounts(void);
const char *OSRDNMesaFlushName(int why);    /* G4-2 B1: a name for flushWhy[why] */

/* Counting, shared with the stub unit.  The stubs have no business seeing the
   rest of the hook unit, and a second copy of the counters would mean a stub
   incrementing a table nobody prints. */
void osrdn_hook_count(int hook);

/* The name of a hook, for a log line; never null. */
const char *OSRDNMesaHookName(int hook);

#endif /* OSRDN_MESA_HOOK_H */
