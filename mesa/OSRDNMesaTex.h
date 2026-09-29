/*
 * OSRDNMesaTex.h - M1g: the texels, and getting them into the card's window
 * (docs/M1G_PLAN.md).
 *
 * This unit knows nothing about Mesa.  The caller hands it a rectangle of
 * finished pixel words; deciding which textures are drawable is the
 * classifier's, and reading them out of GLcontext is OSRDNMesaHook.c's.
 *
 * TWO THINGS ARE EASY TO GET WRONG HERE AND BOTH ARE MEASURED:
 *
 *  1. THE ROW STRIDE IS THE HARDWARE'S, NOT THE IMAGE'S.  The texture unit
 *     reads rows max(width * 4, 32) bytes apart whatever the CPU did.  R6h's
 *     case XF wrote a 4-wide texture with 16-byte rows and the picture came out
 *     shuffled in a way only a 32-byte stride explained (16 and 64 both wrong,
 *     32 exact).  OSRDN_TEX_STRIDE is that number, generated.
 *
 *  2. A TEXEL IS NOT A VERTEX COLOUR.  The vertex colour goes through the
 *     card's interpolator and comes out with bytes 0 and 2 exchanged, so
 *     OSRDNMesaHook.c swaps it (M1d).  A TEXEL does not: R6h measured "the
 *     texel value becomes the pixel, zero byte swaps".  So the word written
 *     here is exactly the word the application wants to read back, and swapping
 *     it would put red where blue goes -- in a picture that otherwise looks
 *     perfectly plausible.
 */

#ifndef OSRDN_MESA_TEX_H
#define OSRDN_MESA_TEX_H

#define OSRDN_TEX_OK            0
#define OSRDN_TEX_NO_WINDOW     1   /* the mapping does not reach the texels */
#define OSRDN_TEX_ARGS          2   /* not the one size this rung uploads */
#define OSRDN_TEX_READBACK      3   /* what we wrote is not what is there */
#define OSRDN_TEX_REASONS       4

typedef struct {
    unsigned long uploads;      /* images written */
    unsigned long texels;       /* and how many words that was */
    unsigned long readBad;      /* words that did not read back */
    unsigned long verifyWords;  /* G5-1a: words read back and compared (4 a level by default,
                                   w x h under RDNMesaTexVerify) */
    unsigned long refused[OSRDN_TEX_REASONS];
    unsigned long lastWord;     /* the first texel, for the log line */
} osrdn_tex_counts;

const osrdn_tex_counts *OSRDNMesaTexCounts(void);

/*
 * The last image that went in, w * h words, row-major and tightly packed.
 *
 * The texels are the one input to a textured picture that is NOT in the CP
 * stream -- they go in by store -- so without this the host would have to
 * predict from what the TEST meant to upload.  This is what the upload unit
 * actually wrote and then read back out of video memory.
 */
const unsigned long *OSRDNMesaTexImage(void);
const char *OSRDNMesaTexWhyName(int why);

/*
 * Put one image in the window and read it back.  `argb` is w * h words in the
 * application's own packing, row-major, TIGHTLY packed (the caller's rows are
 * w words apart; this unit re-spaces them to the hardware's stride).
 *
 * Returns 1 when the image is there and verified, 0 otherwise; *why may be null.
 *
 * MUST be called AFTER any ZPREP: that operation fills the whole 256 KiB window
 * with a pattern, texels included (docs/M1_NEXT_DECISION.md H4).  Inside one
 * process that is automatic -- the runner's ZPREP happens before the process
 * starts -- but it is why this is a call and not a one-time initialiser.
 */
int osrdn_tex_upload(const unsigned long *argb, int w, int h, int *why);
/* G4-1b (docs/G4_GLQUAKE_PLAN.md 5 T1): an image of Mesa's bytes -- comps 3 (R,G,B) or 4 (R,G,B,A),
   w x h texels, w in [8, 512] -- written at byteOff inside the window as ARGB8888 words in the
   application's packing (the shifts), rows w x 4 bytes apart (the pitch the prologue says), then
   read back.  byteOff must be 32-byte aligned and the rows must fit the mapping. */
int osrdn_tex_upload_at(const unsigned char *px, int comps, int w, int h, unsigned long byteOff,
                        int rs, int gs, int bs, int as, int *why);
/* G4-4 K5: one level of a mip chain -- any w x h from 1 to OSRDN_TEX_MAX_DIM, its rows rowBytes
   apart (a multiple of 32 no smaller than w x 4: the R200's level rows, r200_texstate.c 272).
   osrdn_tex_upload_at is this with rowBytes = w x 4, which for w >= 8 is the same thing. */
int osrdn_tex_upload_level(const unsigned char *px, int comps, int w, int h, unsigned long byteOff,
                           unsigned long rowBytes, int rs, int gs, int bs, int as, int *why);

#endif /* OSRDN_MESA_TEX_H */
