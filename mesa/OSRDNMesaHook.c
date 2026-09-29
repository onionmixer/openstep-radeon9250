/*
 * OSRDNMesaHook.c - M1b: OpenStepMesaAccelUpdateState, for real.
 *
 * This is the ONLY unit that needs Mesa's own headers, and it is deliberately
 * thin: it reads fields out of GLcontext, hands them to OSRDNMesaClass.c as
 * plain integers, and counts.  Everything interesting lives in the unit that
 * needs no headers, because a decision behind Mesa's headers can only be tested
 * on the target (docs/M1B_PLAN.md 3).
 *
 * It installs nothing and draws nothing.  The call site says a back end may
 * replace Mesa's choice "only for states it can draw" and must leave every
 * other one "exactly as it found it" -- in M1b there are no states we draw, so
 * ctx->Driver is not touched at all.  Gate B3 is what holds that to more than
 * a comment: this object's undefined symbols are an allow-list with no way to
 * draw in it.
 */

/* Mesa's own, from -I<mesa>/src.  These are the two osmesa.c reaches for
   outside its PC_HEADER path; taking all.h instead would tie this unit to a
   precompiled-header build it does not need. */
#include "glheader.h"
#include "types.h"
/* M1d: gl_set_triangle_function is how Mesa picks the SOFTWARE triangle
   function.  We call it ourselves, take what it chose, and then put our own in
   its place -- the only way to have a fallback at all, because once ours is
   installed src/triangle.c 1532 returns before Mesa ever chooses one. */
#include "triangle.h"

#include "OSRDNMesaHook.h"
#include "OSRDNMesaClass.h"
#include "OSRDNMesaProbe.h"
#include "OSRDNMesaSurface.h"
#include "OSRDNMesaTime.h"          /* G5-0: the frame-budget instrument */
#include "OSRDNMesaTri.h"
#include "OSRDNMesaTriTable.h"
#include "OSRDNMesaTex.h"
#include "OSRDNMesaTexArena.h"          /* G4-1b: where a resident image lives */
#include "mem.h"                        /* G4-1b: MALLOC/FREE for the residency record */
#include "OSRDNMesaDepth.h"
#include "OSRDNMesaPresent.h"           /* G3: glFinish stands the readback down while stamping */
#include "osrdn_r7b.h"                  /* G5-1c: the present verdicts named in the RDN-P line */
#include "osrdn_r7b.h"                  /* G3b: OSRDN_CLEAR_* */
#include "OSRDNMesaVerify.h"            /* G4-2 B1: CP_R7_WHY_OK */
#include "points.h"                     /* G4-2 B1: gl_set_point_function */
#include "OSRDNMesaReadPix.h"           /* G5-4: glReadPixels from the top-down surface */
#include "lines.h"                      /* G4-2 B1: gl_set_line_function */
#include "macros.h"                     /* G3b: FLOAT_TO_UBYTE for the clear colour */

static osrdn_hook_counts osrdnCounts;
static int osrdnLeft;                   /* the list's item 3: the last state decision was a leave */
static void osrdnFlushFor(int why);     /* G4-2 B1: the one way a hook closes a batch */

/* Counting is shared with the stubs, which have no business seeing the rest of
   this file.  Declared in the private header both include. */
void
osrdn_hook_count(int hook)
{
    if (hook >= 0 && hook < OSRDN_HOOKS)
        osrdnCounts.hook[hook]++;
}

const osrdn_hook_counts *
OSRDNMesaHookCounts(void)
{
    return &osrdnCounts;
}

const char *
OSRDNMesaFlushName(int why)
{
    static const char *names[OSRDN_FLUSH_REASONS] = {
        "outside", "bracket", "state", "ctx", "refused", "points", "lines",
        "delegate", "leave", "clear", "glflush", "readpix", "copypix",
        "drawpix", "bitmap", "texupload", "texdrop", "surface", "release",
        "alone"
    };
    if (why < 0 || why >= OSRDN_FLUSH_REASONS)
        return "?";
    return names[why];
}

const char *
OSRDNMesaHookName(int hook)
{
    static const char *names[OSRDN_HOOKS] = {
        "UpdateState", "Buffer", "DepthBuffer", "ReleaseBuffer", "BoundTo",
        "AppBuffer", "CopyDepth", "Mirror", "Stride", "ClearPixel"
    };

    if (hook < 0 || hook >= OSRDN_HOOKS)
        return "?";
    return names[hook];
}

/*
 * The gate, asked ONCE.  The probe caches its own answer, but asking it once
 * here as well keeps the reading in the counters: a run that never asked and a
 * run that asked and was told no are different runs.
 */
static int
osrdnHookAccel(void)
{
    if (!osrdnCounts.asked) {
        osrdnCounts.verdict = (unsigned long)OSRDNMesaProbeRun();
        osrdnCounts.asked = 1UL;
    }
    return osrdnCounts.verdict == (unsigned long)OSRDN_PROBE_HARDWARE;
}

/*
 * The saved software function, PER CONTEXT.  One global would let a second
 * context be drawn with the first context's state-specific function, which is
 * the same mistake M1c avoided by keeping owner and binding apart.  Four slots
 * is not a limit on contexts -- a context with no slot is simply never
 * installed into, and slotsFull says how often that happened.
 */
#define OSRDN_TRI_SLOTS 4

static struct {
    const GLcontext *ctx;
    /* M1j: the Clear that was there before us.  Unlike TriangleFunc, Mesa does
       NOT reset this every UpdateState (osmesa.c 1991 is the only place it is
       written), so it is saved ONCE -- saving it again after we installed ours
       would save OUR pointer and the chain would call itself. */
    GLbitfield (*clear)(GLcontext *, GLbitfield, GLboolean,
                        GLint, GLint, GLint, GLint);
    triangle_func    sw;
    /* M1k: OSMesa sets neither of these (grep of OSmesa/osmesa.c: 0 hits), so
       these are almost certainly null -- they are saved and chained anyway,
       because "almost certainly" is how a driver loses somebody else's hook. */
    void           (*rstart)(GLcontext *);
    void           (*rfinish)(GLcontext *);
    /* G4-2 B1 F3: Mesa's (or OSMesa's) point and line functions, chosen before
       ours went in front of them -- osmesa.c 2009-2010 resets both every
       UpdateState, so like the triangle function they are saved every time */
    points_func      points;
    line_func        line;
    /* M1v: Mesa's own GL_TRIANGLES entry in the RAW table, saved before ours
       goes in, so a group we cannot take goes back exactly where it came from */
    render_func    rawTri;
} osrdnSaved[OSRDN_TRI_SLOTS];

/*
 * M1v: OUR COPY OF MESA'S RAW TABLE, one slot replaced.
 *
 * Mesa's table is a `static` inside vbrender.c, so it can only be reached
 * through the pointer it installs.  We copy it -- never write through it --
 * because the same array is shared with every other context and with the
 * clipped and culled paths' own tables.
 *
 * Eleven slots: GL_POLYGON+2 (render_tmp.h:279-291), indexed by the GL
 * primitive, so GL_TRIANGLES is its own enum value.
 */
#define OSRDN_RENDER_TAB_SLOTS  11
static render_func osrdnRawTab[OSRDN_TRI_SLOTS][OSRDN_RENDER_TAB_SLOTS];

/*
 * M1k: THE TRIANGLES WAITING IN THE BATCH, as Mesa names them.
 *
 * The tri unit holds their WORDS; this holds their INDICES, because only this
 * file may speak to the software triangle function and that function takes
 * indices.  If a flush fails, these are what draws them instead.
 *
 * They are only valid while ctx->VB still holds what it held when they came in,
 * which is true from RenderStart to RenderFinish and false after
 * (docs/M1K_PLAN.md 10).  That is the whole reason the bracket exists here.
 */
static struct {
    GLcontext    *ctx;
    unsigned long n;
    /* G4-2 B1: the first `stale` entries came in during a bracket that has
       ended.  Their indices are dead: a failed flush counts them as lost
       instead of reading whatever ctx->VB holds now.  They are only ever left
       here after the verifier accepted the stream they are in. */
    unsigned long stale;
    GLuint        v[OSRDN_BATCH_MAX_TRIS][4];   /* v0, v1, v2, pv */
} osrdnPend;

static int osrdnInRender;
static int osrdnMultipass;              /* G4-2 B1 F10: the current state has a MultipassFunc */

static int
osrdnSlotOf(const GLcontext *ctx, int make)
{
    int i, free_ = -1;

    for (i = 0; i < OSRDN_TRI_SLOTS; i++) {
        if (osrdnSaved[i].ctx == ctx)
            return i;
        if (osrdnSaved[i].ctx == 0 && free_ < 0)
            free_ = i;
    }
    if (!make || free_ < 0)
        return -1;
    osrdnSaved[free_].ctx = ctx;
    osrdnSaved[free_].sw = 0;
    return free_;
}

/* the IEEE bits of a float, which is what the card wants in a vertex */
static unsigned long
osrdnBits(GLfloat f)
{
    union { GLfloat f; unsigned long u; } u;

    u.f = f;
    return u.u;
}

/*
 * One vertex colour word, from one Mesa colour.  ONE place does this, because
 * M1e gave the flat and the smooth paths each a reason to build one and a swap
 * that differed between them would be invisible in the flat picture.
 *
 * Measured (R6c): a vertex word r | g<<8 | b<<16 | a<<24 leaves the pixel
 * a<<24 | r<<16 | g<<8 | b -- the card's buffer is ARGB8888.  osmesa wants each
 * channel at the shift it handed to Buffer (osmesa.c 191-194).  Comparing the
 * two: the vertex word is the wanted buffer word with BYTES 0 AND 2 EXCHANGED.
 */
static unsigned long
osrdnWantWord(const GLubyte *c, int rs, int gs, int bs, int as)
{
    return ((unsigned long) c[0] << rs) | ((unsigned long) c[1] << gs) |
           ((unsigned long) c[2] << bs) | ((unsigned long) c[3] << as);
}

/*
 * ONE of these swaps and the other does not, and that asymmetry is measured:
 *
 *   a VERTEX COLOUR goes through the card's interpolator and lands as
 *   a<<24|r<<16|g<<8|b, so the word we send is the wanted one with bytes 0 and
 *   2 exchanged (M1d 4d);
 *
 *   a TEXEL does not go through it -- R6h measured "the texel value becomes the
 *   pixel, zero byte swaps" -- so the word we write IS the wanted one.
 *
 * Swapping the texel too would put red where blue goes in a picture that still
 * looks like a picture.
 */
static unsigned long
osrdnColourWord(const GLubyte *c, int rs, int gs, int bs, int as)
{
    unsigned long want = osrdnWantWord(c, rs, gs, bs, as);

    return (want & 0xff00ff00UL) |
           ((want & 0x000000ffUL) << 16) | ((want >> 16) & 0x000000ffUL);
}

/*
 * G4-1b (docs/G4_GLQUAKE_PLAN.md 5 T1, T2): RESIDENCY.  What the card holds of a texture image
 * lives in gl_texture_image->DriverData (types.h: Mesa never touches it), the way the Matrox
 * library keeps it (OpenStepMGAMesaTexture.c): the arena block, the epoch the block came from,
 * the size it was made for, and whether the texels there are current.  The image is put in the
 * window the first time a triangle draws with it -- not at glTexImage2D, when there may be no
 * window yet and the texture may never be used.
 *
 * The three Mesa hooks that can change it are the OLD-STYLE notification ones, which Mesa
 * 3.4.2 calls after its own storage whatever a TexImage2D hook returned (teximage.c 1557,
 * 2238), and DeleteTexture, which runs before the images are freed (texobj.c 505): TexImage
 * on level 0 drops the record (the size may change), TexSubImage marks it stale, DeleteTexture
 * drops every level's.  Each is chained to whatever was there.  BindTexture is not used --
 * Mesa skips it for a re-bind of the same object (texobj.c 562), and the record does not need
 * it: the object's image is looked at every draw.
 */
typedef struct {
    unsigned long epoch;
    unsigned long origin;               /* byte offset inside the window */
    unsigned long bytes;
    unsigned long w, h;
    unsigned long levels;               /* G4-4 K5: how many levels of the chain the block holds (1 = the base) */
    int valid;                          /* the texels at origin are the image's */
} osrdnTexRes;

static unsigned long osrdnTexEpoch;     /* moves each time the surface is taken */

static void
osrdnTexDrop(struct gl_texture_image *img)
{
    osrdnTexRes *r;

    if (img == 0 || img->DriverData == 0)
        return;
    r = (osrdnTexRes *) img->DriverData;
    osrdnFlushFor(OSRDN_FLUSH_TEXDROP);     /* F8: an open batch may read this block */
    (void) osrdn_texarena_free(r->origin, r->epoch);
    FREE(r);
    img->DriverData = 0;
}

static int
osrdnTexUsable(const struct gl_texture_image *img)
{
    return img != 0 && img->Data != 0 && img->Border == 0 &&
           osrdn_class_tex_dim_ok((unsigned long) img->Width) &&
           osrdn_class_tex_dim_ok((unsigned long) img->Height) &&
           (img->Format == GL_RGBA || img->Format == GL_RGB);
}

/* the image resident, uploading if it is not; 0 with nothing sent when it cannot be */
/*
 * G4-4 K5: `levels` says how much of the chain to keep resident: 1 is the base alone (every
 * caller before K5); more is the base and the next levels - 1 images, laid out as the card reads
 * a chain (osrdn_texarena_chain) in ONE block, each level uploaded at its offset with the card's
 * row stride.  A level that is not usable (no data, a border, another format, the wrong size)
 * makes the whole object non-resident: half a chain is a picture that is wrong.
 */
static int
osrdnTexResident(struct gl_texture_object *to, unsigned long *origin, unsigned long *w, unsigned long *h,
                 unsigned long levels)
{
    struct gl_texture_image *img;
    osrdnTexRes *r;
    unsigned long offs[OSRDN_TEXARENA_MAX_LEVELS], chainBytes = 0UL, i;
    int rs = 0, gs = 8, bs = 16, as = 24, why = 0;

    if (to == 0 || to->BaseLevel != 0 || levels < 1UL || levels > (unsigned long)OSRDN_TEXARENA_MAX_LEVELS)
        return 0;
    img = to->Image[0];
    if (!osrdnTexUsable(img))
        return 0;
    for (i = 1UL; i < levels; i++) {
        const struct gl_texture_image *li = to->Image[i];

        if (li == 0 || li->Data == 0 || li->Border != 0 || li->Format != img->Format ||
            (unsigned long) li->Width != ((unsigned long) img->Width >> i > 0UL ? (unsigned long) img->Width >> i : 1UL) ||
            (unsigned long) li->Height != ((unsigned long) img->Height >> i > 0UL ? (unsigned long) img->Height >> i : 1UL))
            return 0;
    }
    if (!osrdn_texarena_chain((unsigned long) img->Width, (unsigned long) img->Height, levels, offs, &chainBytes))
        return 0;
    r = (osrdnTexRes *) img->DriverData;
    if (r != 0 && (r->epoch != osrdnTexEpoch || r->w != (unsigned long) img->Width ||
                   r->h != (unsigned long) img->Height || r->levels != levels)) {
        osrdnTexDrop(img);
        r = 0;
    }
    if (r == 0) {
        unsigned long org = 0UL;

        if (!osrdn_texarena_alloc(chainBytes, osrdnTexEpoch, &org)) {
            osrdnCounts.texAbsent++;
            return 0;
        }
        r = (osrdnTexRes *) MALLOC(sizeof *r);
        if (r == 0) {
            (void) osrdn_texarena_free(org, osrdnTexEpoch);
            osrdnCounts.texAbsent++;
            return 0;
        }
        r->epoch = osrdnTexEpoch;
        r->origin = org;
        r->bytes = chainBytes;
        r->w = (unsigned long) img->Width;
        r->h = (unsigned long) img->Height;
        r->levels = levels;
        r->valid = 0;
        img->DriverData = r;
    }
    if (!r->valid) {
        osrdn_surf_shifts(&rs, &gs, &bs, &as);
        osrdnFlushFor(OSRDN_FLUSH_TEXUPLOAD);   /* F8: an open batch may read these texels */
        if (!osrdn_tex_upload_at((const unsigned char *) img->Data, img->Format == GL_RGBA ? 4 : 3,
                                 (int) r->w, (int) r->h, r->origin, rs, gs, bs, as, &why)) {
            osrdnCounts.texUploadBad++;
            return 0;
        }
        for (i = 1UL; i < levels; i++) {
            const struct gl_texture_image *li = to->Image[i];

            if (!osrdn_tex_upload_level((const unsigned char *) li->Data, li->Format == GL_RGBA ? 4 : 3,
                                        (int) li->Width, (int) li->Height, r->origin + offs[i],
                                        ((unsigned long) li->Width * 4UL + 31UL) & ~31UL,
                                        rs, gs, bs, as, &why)) {
                osrdnCounts.texUploadBad++;
                return 0;
            }
        }
        r->valid = 1;
        osrdnCounts.texUploads++;
        if (levels > 1UL)
            osrdnCounts.texChains++;
    }
    *origin = r->origin;
    *w = r->w;
    *h = r->h;
    return 1;
}

static void (*osrdnPrevTexImage)(GLcontext *, GLenum, struct gl_texture_object *, GLint, GLint,
                                 const struct gl_texture_image *);
static void (*osrdnPrevTexSubImage)(GLcontext *, GLenum, struct gl_texture_object *, GLint, GLint, GLint,
                                    GLsizei, GLsizei, GLint, const struct gl_texture_image *);
static void (*osrdnPrevDeleteTexture)(GLcontext *, struct gl_texture_object *);

static void
osrdnHookTexImage(GLcontext *ctx, GLenum target, struct gl_texture_object *tObj, GLint level,
                  GLint internalFormat, const struct gl_texture_image *image)
{
    /* G4-5 (docs/G4_5_MIP_PLAN.md 2-1): the record on Image[0] holds the whole chain.  Level 0
       is a new base: the record goes (Mesa reinitialised the same struct, teximage.c 1493-1512).
       Any other level: the chain on the card is stale from that level on, so all of it is copied
       again at the next draw (the Matrox rule; r200 marks the one level, r200_tex.c 701). */
    if (tObj != 0 && level == 0)
        osrdnTexDrop(tObj->Image[0]);
    else if (tObj != 0 && level > 0 && tObj->Image[0] != 0 && tObj->Image[0]->DriverData != 0)
        ((osrdnTexRes *) tObj->Image[0]->DriverData)->valid = 0;
    if (osrdnPrevTexImage != 0)
        (*osrdnPrevTexImage)(ctx, target, tObj, level, internalFormat, image);
}

static void
osrdnHookTexSubImage(GLcontext *ctx, GLenum target, struct gl_texture_object *tObj, GLint level,
                     GLint xoffset, GLint yoffset, GLsizei width, GLsizei height,
                     GLint internalFormat, const struct gl_texture_image *image)
{
    /* G4-5: ANY level -- the record on Image[0] covers the chain (r200_tex.c 749) */
    if (tObj != 0 && level >= 0 && tObj->Image[0] != 0 && tObj->Image[0]->DriverData != 0)
        ((osrdnTexRes *) tObj->Image[0]->DriverData)->valid = 0;
    if (osrdnPrevTexSubImage != 0)
        (*osrdnPrevTexSubImage)(ctx, target, tObj, level, xoffset, yoffset, width, height,
                                internalFormat, image);
}

static void
osrdnHookDeleteTexture(GLcontext *ctx, struct gl_texture_object *tObj)
{
    int i;

    if (tObj != 0)
        for (i = 0; i < MAX_TEXTURE_LEVELS; i++)
            osrdnTexDrop(tObj->Image[i]);
    if (osrdnPrevDeleteTexture != 0)
        (*osrdnPrevDeleteTexture)(ctx, tObj);
}


/* our triangle function, named here because the Clear below asks whether it is
   the one installed and C89 wants to have heard of it first */
/*
 * Send what is waiting, and if the card will not take it, draw it here.
 *
 * The promise M1d made does not bend for M1k: every triangle this file accepted
 * is either on the card or drawn by the function Mesa chose.  A batch makes the
 * failure arrive later, not cheaper.
 */
static void
osrdnFlushBatch(void)
{
    unsigned long want = osrdnPend.n;
    unsigned long stale = osrdnPend.stale;
    unsigned long got;
    triangle_func sw;
    int slot, why = 0;
    unsigned long i;

    if (want == 0UL) {
        /* the unit must agree that there is nothing; if it does not, something
           put words in the window without telling this file */
        if (osrdn_tri_batch_count() != 0UL)
            osrdnCounts.batchDesync++;
        return;
    }
    if (osrdn_tri_batch_count() != want) {
        osrdnCounts.batchDesync++;
        /* fall through: the flush still empties the unit, and the replay below
           still draws everything this file is holding.  A doubled triangle is
           wrong; a missing one is worse, and the counter says it happened. */
    }
    got = osrdn_tri_batch_flush(&why);
    osrdnPend.n = 0UL;
    osrdnPend.stale = 0UL;
    if (got != 0UL) {
        osrdnCounts.flushes++;
        osrdnCounts.flushed += got;
        if (got != want)
            osrdnCounts.batchDesync++;
        return;
    }

    osrdnCounts.flushFailed++;
    slot = osrdnSlotOf(osrdnPend.ctx, 0);
    sw = (slot >= 0) ? osrdnSaved[slot].sw : (triangle_func) 0;
    for (i = 0UL; i < want; i++) {
        if (i < stale) {
            /* G4-2 B1: its bracket has ended, so its indices name nothing.
               The verifier accepted this stream before it was left open, so
               this is a card that did not answer, not a rule -- and it is
               counted, never redrawn from dead indices. */
            osrdnCounts.lostAtFlush++;
            continue;
        }
        if (sw != 0) {
            (*sw)(osrdnPend.ctx, osrdnPend.v[i][0], osrdnPend.v[i][1],
                  osrdnPend.v[i][2], osrdnPend.v[i][3]);
            osrdnCounts.replayed++;
        } else {
            osrdnCounts.noSoftware++;
        }
    }
}

/*
 * G4-2 B1: every hook that closes a batch says why, and the table of whys is
 * the list in docs/G4_2_BATCH_PLAN.md 3.  Nothing to close costs nothing.
 */
/*
 * G5-2 (docs/G5_2_ASYNC_SUBMIT_PLAN.md 1-4, 2-4): WHICH FLUSHES HAND THE WINDOW TO THE CPU.
 *
 * The surface Mesa draws into in software IS the card's window (osrdn_surf_take returns
 * surfBase), so after a flush for one of these reasons the CPU reads or writes what the
 * card may still be drawing -- whether or not this flush had a batch to send: an earlier
 * one can still be in flight.  1 = retire after the flush.  Every reason is named here;
 * check_hook's g52-retire rule refuses a reason added without a verdict.
 */
static const unsigned char osrdnFlushTouches[OSRDN_FLUSH_REASONS] = {
    0,  /* OUTSIDE   a batch closes; Finish mirrors, and the mirror retires itself */
    0,  /* BRACKET   RenderFinish: the next draws are the card's */
    0,  /* STATE     a segment boundary */
    0,  /* CTX       another context's triangle: its own batch, not our window's pixels */
    0,  /* REFUSED   the verified prefix goes; nothing reads */
    1,  /* POINTS    software points into the window */
    1,  /* LINES     software lines into the window */
    1,  /* DELEGATE  a triangle drawn in software */
    1,  /* LEAVE     the state leaves the card: software draws next */
    1,  /* CLEAR     the card's clear is ring-ordered, but a refused one clears in software */
    0,  /* GLFLUSH   no pixel is touched */
    1,  /* READPIX   */
    1,  /* COPYPIX   */
    1,  /* DRAWPIX   */
    1,  /* BITMAP    */
    1,  /* TEXUPLOAD texels written (the upload retires too; this keeps the order visible) */
    0,  /* TEXDROP   allocator bookkeeping only; the next upload retires */
    1,  /* SURFACE   a new surface is taken; the old one is read or reused */
    1,  /* RELEASE   the surface goes away */
    0   /* ALONE     a triangle for the card */
};

static void
osrdnFlushFor(int why)
{
    if (osrdnPend.n != 0UL || osrdn_tri_batch_count() != 0UL) {
        if (why >= 0 && why < OSRDN_FLUSH_REASONS)
            osrdnCounts.flushWhy[why]++;
        osrdnFlushBatch();
    }
    if (why >= 0 && why < OSRDN_FLUSH_REASONS && osrdnFlushTouches[why])
        (void)osrdn_tri_retire_if_inflight();
}

/*
 * G4-2 B1 F2: the end of a bracket.  The last moment the batch can be redrawn
 * from its indices, so the question is asked HERE: would the kernel refuse the
 * stream in hand?  The verifier is the kernel's own text (OSRDNMesaVerify.c).
 *
 *   accepted -> the batch stays open; its entries are marked stale (dead
 *               indices) and the next bracket appends to it
 *   refused  -> the prefix an EARLIER RenderFinish accepted (stale entries)
 *               goes out alone, exactly the stream that was verified; the
 *               fresh tail -- the part that made the stream refusable -- is
 *               drawn by the software function now, while its indices live.
 *               No ioctl is spent on a stream the rule would refuse.
 *
 * With the span knob off this is the M1k flush, unconditionally.
 */
static void
osrdnBracketEnd(void)
{
    unsigned long at = 0UL, word = 0UL, winBytes = 0UL, why, keep, n, i;
    triangle_func sw;
    int slot;

    if (osrdnPend.n == 0UL) {
        osrdnFlushBatch();                  /* nothing, and the unit must agree */
        return;
    }
    if (!osrdn_tri_span_enabled()) {
        osrdnFlushFor(OSRDN_FLUSH_BRACKET);
        return;
    }
    (void) osrdn_surf_window(&winBytes);
    {
        osrdn_time_stamp t;
        int timed = osrdn_time_on();    /* G5-0: the host verifier, by itself */

        if (timed)
            osrdn_time_now(&t);
        why = osrdn_tri_batch_verify(winBytes, &at, &word);
        if (timed)
            osrdn_time_add(OSRDN_TIME_VERIFY, &t);
    }
    if (why == CP_R7_WHY_OK) {
        osrdnCounts.prevalidated++;
        osrdnPend.stale = osrdnPend.n;
        return;
    }
    osrdnCounts.prevalidateRefused++;
    osrdnCounts.prevalidateWhy = why;
    osrdnCounts.prevalidateAt = at;
    osrdnCounts.prevalidateWord = word;
    keep = osrdnPend.stale;
    n = osrdnPend.n;
    (void) osrdn_tri_batch_truncate(keep);
    osrdnPend.n = keep;
    if (keep != 0UL) {
        osrdnCounts.prefixFlushed++;
        osrdnFlushFor(OSRDN_FLUSH_REFUSED); /* the verified prefix; stale, so a failure is counted lost */
    } else {
        osrdnCounts.flushWhy[OSRDN_FLUSH_REFUSED]++;
        osrdnPend.stale = 0UL;
    }
    slot = osrdnSlotOf(osrdnPend.ctx, 0);
    sw = (slot >= 0) ? osrdnSaved[slot].sw : (triangle_func) 0;
    for (i = keep; i < n; i++) {
        if (sw != 0) {
            (*sw)(osrdnPend.ctx, osrdnPend.v[i][0], osrdnPend.v[i][1],
                  osrdnPend.v[i][2], osrdnPend.v[i][3]);
            osrdnCounts.replayed++;
        } else {
            osrdnCounts.noSoftware++;
        }
    }
}

/* Flush from a hook that is NOT RenderFinish.  If the bracket covers every
   triangle these never have anything to do, and the counter says so. */
static void
osrdnFlushOutside(void)
{
    if (osrdnPend.n != 0UL || osrdn_tri_batch_count() != 0UL) {
        osrdnCounts.flushOutside++;
        osrdnFlushFor(OSRDN_FLUSH_OUTSIDE);
    }
}

static void osrdnHookTriangle(GLcontext *ctx, GLuint v0, GLuint v1, GLuint v2,
                              GLuint pv);

/*
 * M1j: OUR glClear, for the depth bit only.
 *
 * Mesa calls Driver.Clear and then clears IN SOFTWARE whatever bits come back
 * (buffers.c 279-281), so a driver claims a buffer by dropping its bit from the
 * return.  We claim DD_DEPTH_BIT when the card owns the depth buffer, and hand
 * everything else to the function that was there before us.
 *
 * Depth was cleared at INSTALL time until this rung.  That was never what GL
 * says happens, and it showed: a scene that did not clear depth drew nothing in
 * the software link and everything in ours (docs/M1I_PLAN.md 11-(3)).
 *
 * Mesa has already dropped the depth bit if Depth.Mask is 0 (buffers.c 267-269),
 * so there is no mask test here -- a clear we are asked for is one that should
 * happen.
 */
static GLbitfield
osrdnHookClear(GLcontext *ctx, GLbitfield mask, GLboolean all,
               GLint x, GLint y, GLint width, GLint height)
{
    GLbitfield left = mask;
    int slot = osrdnSlotOf(ctx, 0);
    GLbitfield (*saved)(GLcontext *, GLbitfield, GLboolean,
                        GLint, GLint, GLint, GLint) =
        (slot >= 0) ? osrdnSaved[slot].clear : 0;

    osrdnCounts.clearCalls++;
    osrdnFlushFor(OSRDN_FLUSH_CLEAR);       /* F6: the clear must land after what was drawn before it */
    /*
     * WE CLEAR THE CARD'S DEPTH AND STILL PASS THE BIT ON.
     *
     * The first draft claimed the bit -- dropped it from the return so Mesa
     * would not clear its own -- and gated that on "are we the one drawing".
     * Two things were wrong with it.
     *
     * It did not fire: this scene clears BEFORE it enables the depth test, so
     * Depth.Test was false at the one glClear that mattered (measured: cli=3
     * clc=1 zclear=0).  A program is free to do that, and to enable depth once
     * at start-up and clear every frame afterwards.
     *
     * And claiming is the risky half.  WHO draws can change between the clear
     * and the triangles -- one declined state and Mesa's software path is
     * testing against a buffer nobody cleared, which is M1i's bug wearing the
     * other hat.  Clearing ours and letting Mesa clear its own costs one
     * software pass over a buffer that is usually unused, and it cannot leave
     * either side stale.  That is the trade this rung takes.
     */
    if ((mask & (DD_DEPTH_BIT | DD_FRONT_LEFT_BIT)) != 0 &&
        osrdn_surf_bound_to((const void *) ctx)) {
        /* The value is Mesa's ClearDepth through the MEASURED conversion --
           floor(z * 2^16) -- and not d * 0xffff, which is what Mesa's own CPU
           side would do and what the card does not do (R6f). */
        unsigned long far = (unsigned long)(ctx->Depth.Clear * 65536.0);
        unsigned long flags = 0UL, colour = 0UL;
        int dwhy = 0, rs, gs, bs, as;
        GLubyte cc[4];

        if (far > 0xffffUL)
            far = 0xffffUL;
        if (mask & DD_DEPTH_BIT)
            flags |= OSRDN_CLEAR_DEPTH;
        if (mask & DD_FRONT_LEFT_BIT) {
            /* G3b (docs/G3B_CLEAR_PLAN.md 2-3): the colour too, packed the way a
               vertex colour is -- Mesa's own clear would only touch the
               application's array, which in present mode nobody looks at */
            cc[0] = FLOAT_TO_UBYTE(ctx->Color.ClearColor[0]);
            cc[1] = FLOAT_TO_UBYTE(ctx->Color.ClearColor[1]);
            cc[2] = FLOAT_TO_UBYTE(ctx->Color.ClearColor[2]);
            cc[3] = FLOAT_TO_UBYTE(ctx->Color.ClearColor[3]);
            osrdn_surf_shifts(&rs, &gs, &bs, &as);
            /* G3d: the PIXEL packing, not the vertex word -- osrdnColourWord swaps R and B for the
               card's COLOR_ORDER_RGBA vertex path; the 2D fill writes its brush word into memory as
               it is, and boot 6 read the background back with R and B exchanged */
            colour = osrdnWantWord(cc, rs, gs, bs, as);
            flags |= OSRDN_CLEAR_COLOUR;
        }
        if (osrdn_card_clear(flags, colour, far, (int) ctx->DrawBuffer->Width,
                             (int) ctx->DrawBuffer->Height, &dwhy)) {
            if (flags & OSRDN_CLEAR_DEPTH)
                osrdnCounts.depthClears++;
            if (flags & OSRDN_CLEAR_COLOUR) {
                osrdnCounts.colourClears++;
                left &= ~DD_FRONT_LEFT_BIT;     /* the card holds the colour now: Mesa's pass is not needed */
            }
        } else {
            if (flags & OSRDN_CLEAR_DEPTH)
                osrdnCounts.depthClearBad++;
            if (flags & OSRDN_CLEAR_COLOUR)
                osrdnCounts.colourClearBad++;   /* the bit stays in `left`: Mesa clears the array as before */
        }
        /* the depth bit is NOT taken out of `left`: Mesa clears its own buffer too */
    }
    osrdnCounts.clearPassed += (unsigned long)(left != 0);
    if (saved != 0)
        return (*saved)(ctx, left, all, x, y, width, height);
    return left;
}


/*
 * Our triangle function.  It either sends the triangle or calls the software
 * one -- never neither.  The counters are what proves that: sum(refused) in the
 * tri unit must equal `delegated` here, and noSoftware must be 0.
 */
/*
 * M1v: THE PART THAT CANNOT CHANGE INSIDE A RENDER PASS.
 *
 * Everything here is read from ctx and from the surface unit, and a GL state
 * change flushes the vertex buffer before it takes effect -- so within one
 * begin/end group these answers are the same for every triangle.  Today they
 * are computed once a TRIANGLE because Mesa calls us once a triangle; the whole
 * point of M1v is to compute them once a GROUP instead.
 *
 * IT BUMPS NO COUNTER.  `notBound` and `texProjective` are per-triangle numbers
 * the gates read, so they are recorded here as flags and bumped by the
 * per-triangle function -- otherwise hoisting this would quietly divide two
 * gated counters by the group size.
 */
typedef struct {
    int ok;                     /* 0: this state cannot be ours */
    int notBound;
    int texProjective;
    int smooth, blend, tex, depth;
    int rs, gs, bs, as;
    int inl;
    int stride, width, height;
} osrdnTriState;

static void
osrdnTriStateOf(GLcontext *ctx, osrdnTriState *s)
{
    struct vertex_buffer *VB = ctx->VB;

    s->ok = 0;
    s->notBound = 0;
    s->texProjective = 0;
    s->smooth = 0;
    s->blend = 0;
    s->tex = 0;
    s->depth = 0;
    s->rs = 0;
    s->gs = 8;
    s->bs = 16;
    s->as = 24;
    s->stride = 0;
    s->width = 0;
    s->height = 0;
    /* M1t: read ONCE, not once a vertex -- a per-vertex accessor would put a
       call back where that rung took three away. */
    s->inl = osrdn_tri_inline_enabled();

    /*
     * The card may only be pointed at a surface we hold.  If the substitution
     * has ended, Mesa is drawing into the application's own buffer and a
     * submission would put the triangle somewhere nobody is looking.
     */
    if (!osrdn_surf_bound_to((const void *) ctx)) {
        s->notBound = 1;
        return;
    }
    /*
     * MORE THAN s AND t IS SOMEONE ELSE'S TRIANGLE.  (The reasoning is in the
     * per-triangle function's history; it is read off the DATA, after texgen
     * and after the matrix, not off any flag.)
     */
    if (ctx->Texture.ReallyEnabled && VB->TexCoordPtr[0]->size > 2) {
        s->texProjective = 1;
        return;
    }
    /*
     * M1e: GL_SMOOTH takes each vertex's own colour, GL_FLAT takes the
     * provoking vertex's three times.  The classifier has already refused
     * anything that is neither, and likewise for blend and depth -- so here
     * "enabled" is enough to pick the one shape we send.
     */
    s->smooth = (ctx->Light.ShadeModel == GL_SMOOTH) ? 1 : 0;
    /* G4-1a: CODES, decided by the classifier's functions (the GL enums live there, not here);
       a feature that is on with a code of 0 is a state the classifier would have refused, so
       it is not sent -- a defence against the two disagreeing, counted so it is seen */
    s->tex = ctx->Texture.ReallyEnabled ? osrdn_class_env_code((unsigned long) ctx->Texture.Unit[0].EnvMode) : 0;
    if (s->tex) {
        /* G4-1b: the image on the card, and its place and shape to the Tri unit; not resident
           (no room, no image, an upload that would not read back) -> this state is not ours */
        unsigned long org = 0UL, tw = 0UL, th = 0UL;
        struct gl_texture_object *to = ctx->Texture.Unit[0].Current;

        /* G4-4 K5: the MIN code the classifier accepted; a mip code keeps M + 1 levels (Mesa's
           M = min(MaxLevel, P) - BaseLevel, types.h 809; BaseLevel is 0 here) */
        int minCode = osrdn_class_min_code((unsigned long) to->MinFilter);
        unsigned long levels = (minCode >= OSRDN_TRI_MIN_MIP_FIRST) ? (unsigned long) (to->M + 0.5f) + 1UL : 1UL;

        if (minCode < 0) {
            osrdnCounts.codeGap++;              /* the classifier accepted a filter this file has no code for */
            return;
        }
        if (!osrdnTexResident(to, &org, &tw, &th, levels))
            return;
        osrdn_tri_texture_set(org, (int) tw, (int) th, to->MagFilter == GL_LINEAR, minCode, (int) levels);
    }
    s->blend = ctx->Color.BlendEnabled ? osrdn_class_blend_code((unsigned long) ctx->Color.BlendSrcRGB, (unsigned long) ctx->Color.BlendDstRGB) : 0;
    s->depth = ctx->Depth.Test ? osrdn_class_depth_code((unsigned long) ctx->Depth.Func, (unsigned long) ctx->Depth.Mask) : 0;
    /* G4-3 K2: the alpha test, as a code the Tri unit turns into PP_CNTL's bit and PP_MISC; a test
       that is on with no code is a state the classifier would have refused */
    {
        unsigned long ac = ctx->Color.AlphaEnabled ?
            (unsigned long) osrdn_class_alpha_code((unsigned long) ctx->Color.AlphaFunc, (unsigned long) ctx->Color.AlphaRef) : 0UL;

        if (ctx->Color.AlphaEnabled && ac == 0UL) {
            osrdnCounts.codeGap++;
            return;
        }
        osrdn_tri_alpha_set(ac);
    }
    if ((ctx->Texture.ReallyEnabled && s->tex == 0) || (ctx->Color.BlendEnabled && s->blend == 0) ||
        (ctx->Depth.Test && s->depth == 0)) {
        osrdnCounts.codeGap++;
        return;
    }
    osrdn_surf_shifts(&s->rs, &s->gs, &s->bs, &s->as);
    /* the disassembly showed osrdn_surf_stride called THREE times a triangle;
       it is as invariant as the rest */
    s->stride = (int) osrdn_surf_stride();
    s->width = (int) ctx->DrawBuffer->Width;
    s->height = (int) ctx->DrawBuffer->Height;
    s->ok = 1;
}

/*
 * One triangle, with the state already in hand.  This is the body the group
 * function and the per-triangle hook BOTH use -- written once, so the two
 * cannot drift apart.
 */
static void
osrdnTriangleWith(GLcontext *ctx, const osrdnTriState *st,
                  GLuint v0, GLuint v1, GLuint v2, GLuint pv)
{
    struct vertex_buffer *VB = ctx->VB;
    unsigned long vtx[3 * OSRDN_TEX_VERTEX_WORDS];   /* the widest shape */
    unsigned long col;
    int rs = st->rs, gs = st->gs, bs = st->bs, as = st->as;
    int smooth = st->smooth, blend = st->blend, tex = st->tex;
    int depth = st->depth;
    GLuint idx[3];
    const GLubyte *c;
    triangle_func sw;
    int i, slot, why = 0;
    int inl = st->inl;
    /* G5-1b: a present-mode surface is drawn top-down (see the vertex loop), and
       the surface is told, so a mirror back to the application reverses rows */
    int flipY = osrdn_present_active();
    GLfloat flipH = flipY ? (GLfloat) OSRDNMesaSurfaceCounts()->height : 0.0F;

    osrdnCounts.triangles++;
    osrdn_surf_set_flipped(flipY);
    idx[0] = v0;
    idx[1] = v1;
    idx[2] = v2;

    /*
     * M3b: WE CULL, because nobody else will.  With culling on and this
     * function installed, Mesa has left culling to the software triangle
     * function (state.c 1127-1130) and that is the function we replaced -- the
     * vertex-buffer stage does not run either (vbcull.c 819).
     *
     * The test is render_triangle's, to the letter: the same GLfloat
     * differences in the same order and the same strict `> 0`
     * (vbrender.c 283-293).  tritemp.h's sorted-vertex form culls exactly the
     * same triangles -- checked in python over 600,000 cases, no disagreement
     * (docs/M3B_PLAN.md 7-1).  backface_sign is 0 when culling is off.
     *
     * A culled triangle is not delegated: the software function would cull it
     * too, so drawing nothing is what both sides do.
     */
    if (ctx->backface_sign != 0.0F) {
        GLfloat (*win)[4] = VB->Win.data;
        GLfloat ex = win[v1][0] - win[v0][0];
        GLfloat ey = win[v1][1] - win[v0][1];
        GLfloat fx = win[v2][0] - win[v0][0];
        GLfloat fy = win[v2][1] - win[v0][1];
        GLfloat cc = ex*fy-ey*fx;

        if (cc * ctx->backface_sign > 0) {
            osrdnCounts.culled++;
            return;
        }
    }

    if (st->notBound) {
        osrdnCounts.notBound++;
        why = -1;
    }
    /*
     * MORE THAN s AND t IS SOMEONE ELSE'S TRIANGLE.
     *
     * We send two components and the card interpolates them affinely.  Mesa
     * keeps the count the application actually supplied (vbxform.c 459-466,
     * from the vertex_sizes table at 437-441) and, when it is four, interpolates
     * the fourth per pixel and divides by it (tritemp.h 462-465).  A projective
     * texture matrix does the same: ENABLE_TEXMAT0 means NOT the identity
     * (types.h 776, set at state.c 949-951) and the transform writes its own
     * size into the destination (stages.c 518-522, xform.h 175).
     *
     * So this is read off the DATA, after texgen and after the matrix -- the
     * pointer we read is the transformed one (texgen_tmp.h 381, stages.c 519) --
     * and not off any flag.  Declining costs a software triangle; accepting
     * would draw a projected texture as a flat one, which looks like a picture.
     *
     * M1v: the test itself now lives in osrdnTriStateOf; the COUNTER stays
     * here, once a triangle, because that is what the gates read.
     */
    else if (st->texProjective) {
        osrdnCounts.texProjective++;
        why = -1;
    }
    else {
        for (i = 0; i < 3; i++) {
            c = VB->ColorPtr->data[smooth ? idx[i] : pv];
            col = osrdnColourWord(c, rs, gs, bs, as);
            /*
             * Window y IS the row index here: with yup set -- and osmesa.c 742
             * ends the substitution when it is not -- rowaddr[i] is
             * origin + i * rowlength (osmesa.c 445-465), and the card lays row
             * y at COLOROFFSET + y * pitch.  No flip, and this is derived from
             * that code rather than guessed at.
             */
            /* The stride is the tri unit's business, not this file's: two
               shapes written here is what put a coordinate in a colour slot.
               Depth is off in M1d, so z and w are 1.0. */
            /*
             * M1i: THE REAL z, not 1.0 -- and in the CARD's units, not Mesa's.
             *
             * Every rung up to M1h sent a constant because depth was off and
             * the value could not matter.
             *
             * Win.data[i][2] is NOT in [0,1]: Mesa has already multiplied by
             * DepthMaxF, so a window z of 0.75 arrives as 49151.25.  The card
             * wants the [0,1] value and floors z * 2^n itself (R6f).  The first
             * hardware run sent the scaled number: every pixel then computed a
             * depth far past 0xffff, clamped there, and failed the compare
             * against a buffer cleared to 0xffff -- two triangles submitted,
             * nothing drawn.  The counters all said yes and the picture was
             * empty.
             *
             * The divide is Mesa's own (feedback.c 171 does exactly this).
             */
            /*
             * M1t: THE WORDS ARE COMPUTED ONCE; ONLY THE CALL DIFFERS.
             *
             * The first draft wrote the argument expressions out twice, once
             * per arm.  That broke a mutation: `check_hook`'s "the vertex z
             * goes out in Mesa's units" patched one copy and the rule still saw
             * the other, so a real defect stopped being catchable.  One copy,
             * in locals, and the two arms differ in exactly one thing -- whether
             * ten arguments cross an object boundary.
             *
             * It also fixes the evaluation order: as arguments their order was
             * unspecified, as statements it is the same for both arms.
             */
            {
                unsigned long wx = osrdnBits(VB->Win.data[idx[i]][0]);
                /* G5-1b (docs/G5_1B_PRESENT_ONE_BLIT_PLAN.md 1): in present mode the
                   surface is drawn top-down -- window y = r + 0.5 goes to row
                   H - 1 - r -- so the screen takes it in ONE blit.  The cull above
                   used Mesa's own y, before this.  flipY is decided once per
                   triangle, outside this loop. */
                unsigned long wy = osrdnBits(flipY ? flipH - VB->Win.data[idx[i]][1]
                                                   : VB->Win.data[idx[i]][1]);
                unsigned long wz = osrdnBits(VB->Win.data[idx[i]][2] /
                                             ctx->Visual->DepthMaxF);
                /*
                 * G4-1b: A TEXTURED VERTEX CARRIES 1/w.  The prologue's SE_VTE_CNTL is
                 * 0x300 (XY and Z already projected, W0_FMT off: W0 is 1/w) and
                 * SE_VAP_CNTL has FORCE_W_TO_ONE off (docs/R6I_PLAN.md Y2, Y11), which is
                 * the reference's projected mode with texture inputs (r200_swtcl.c 248-250):
                 * the card divides s and t by the interpolated 1/w itself.  Mesa's Win[3]
                 * IS 1/w (xform.c 169-170), and its software textured triangle is
                 * perspective-correct (triangle.c 1612, the GL_DONT_CARE default at
                 * context.c 939).  With w = 1 the card interpolated s and t linearly in
                 * screen space: the same texel row read two texels ahead of Mesa in the
                 * middle of a tilted quad and level with it at both ends (G4-1b, sub scene).
                 * An untextured vertex keeps w = 1 -- Mesa's Gouraud is screen-linear and
                 * M1d-M1f measured the pictures against that.
                 */
                unsigned long ww = tex ? osrdnBits(VB->Win.data[idx[i]][3]) : osrdnBits(1.0F);
                unsigned long ws = tex
                    ? osrdnBits(VB->TexCoordPtr[0]->data[idx[i]][0]) : 0UL;
                unsigned long wt = tex
                    ? osrdnBits(VB->TexCoordPtr[0]->data[idx[i]][1]) : 0UL;

                if (inl) {
                    /* the address in a LOCAL: the macro names `q` seven times,
                       so passing the AT() expression would recompute the
                       pointer arithmetic seven times a vertex -- and that is
                       the very kind of hidden work this rung is measuring */
                    unsigned long *q = OSRDN_TRI_VERTEX_AT(vtx, i, tex);

                    OSRDN_TRI_VERTEX_PUT(q, tex, wx, wy, wz, ww, col, ws, wt);
                }
                else
                    osrdn_tri_vertex(vtx, i, tex, wx, wy, wz, ww, col, ws, wt);
            }
        }
        /*
         * M1k: INTO THE BATCH, if we are inside a render pass.
         *
         * Outside one, the vertices this file would keep for the replay may be
         * overwritten before the flush, so the triangle goes alone -- the path
         * every rung up to M1j used.  The counter says how often that happened,
         * and the gate wants it at zero: a non-zero is not a wrong picture, it
         * is a path into this function that the reading did not find.
         */
        /*
         * M1l keeps the two reasons APART.  "outside the render bracket" is a
         * fact about Mesa that the gate wants at zero; "the knob is off" is a
         * choice we made for this run.  Folding them would make the gate fail
         * on a measurement run and mean nothing on either.
         */
        /*
         * M1s: THE BISECTION KNOB, and it sits HERE on purpose.
         *
         * Everything above has already happened -- the classifier, the state
         * reads, the three vertices assembled into vtx -- and everything below
         * is this library's send path.  Falling through from exactly this point
         * leaves the hook's own work in the measurement and takes the unit and
         * the ioctl out of it, which is what makes the subtraction mean
         * something (docs/M1S_PLAN.md).  It is NOT a way to run: `submitted`
         * goes to zero and the picture is Mesa's.
         */
        if (osrdn_tri_nullsend_enabled()) {
            /* nothing: the fall-through below draws it in software */
        }
        else if (!osrdnInRender || !osrdn_tri_batch_enabled() || osrdnMultipass) {
            if (!osrdnInRender)
                osrdnCounts.outsideRender++;
            else
                osrdnCounts.batchOff++;
            osrdnFlushFor(OSRDN_FLUSH_ALONE);   /* B1: what is in hand goes first */
            if (osrdn_tri_send(0UL, st->stride, st->width, st->height,
                               vtx, smooth, blend, tex, depth, &why))
                return;                             /* it reached the ring */
        }
        else {
            unsigned long got;

            /* a different context, a different state or a full batch: what is
               in hand goes out first, and it still has its vertices */
            if (osrdnPend.n != 0UL && osrdnPend.ctx != ctx)
                osrdnFlushFor(OSRDN_FLUSH_CTX);
            else if (osrdnPend.n >= (unsigned long) OSRDN_BATCH_MAX_TRIS ||
                     !osrdn_tri_batch_joins(0UL, st->stride, st->width, st->height,
                                            smooth, blend, tex, depth))
                osrdnFlushFor(OSRDN_FLUSH_STATE);   /* F1 */
            got = osrdn_tri_batch_add(0UL, st->stride, st->width, st->height,
                                      vtx, smooth, blend, tex, depth, &why);
            if (got != 0UL) {
                if (got != osrdnPend.n + 1UL)
                    osrdnCounts.batchDesync++;
                osrdnPend.ctx = ctx;
                osrdnPend.v[osrdnPend.n][0] = v0;
                osrdnPend.v[osrdnPend.n][1] = v1;
                osrdnPend.v[osrdnPend.n][2] = v2;
                osrdnPend.v[osrdnPend.n][3] = pv;
                osrdnPend.n++;
                osrdnCounts.batchAdds++;
                return;                     /* it is ours until the flush */
            }
        }
    }

    osrdnCounts.delegated++;
    slot = osrdnSlotOf(ctx, 0);
    sw = (slot >= 0) ? osrdnSaved[slot].sw : (triangle_func) 0;
    osrdnFlushFor(OSRDN_FLUSH_DELEGATE);    /* F4: the card's triangles go under this one */
    if (sw != 0)
        (*sw)(ctx, v0, v1, v2, pv);
    else
        /* A triangle we neither sent nor drew.  This must stay 0; the gate
           reads it, because "nothing appeared" is the failure this rung is
           most able to cause and least able to see. */
        osrdnCounts.noSoftware++;
}

/*
 * Mesa's per-triangle entry.  It computes the state and calls the body -- the
 * SAME body the group function calls, so the two paths cannot draw differently.
 * When the group hook is off (the default) this is the whole of M1v's change:
 * the same work in the same order, with one struct in between.
 */
static void
osrdnHookTriangle(GLcontext *ctx, GLuint v0, GLuint v1, GLuint v2, GLuint pv)
{
    osrdnTriState st;
    osrdn_time_stamp t;
    /* G5-0: the whole hook, state preparation included -- and NOT when a group
       declined above us and Mesa's raw function is calling us back per
       triangle: that interval is already open (osrdnRenderVBTriangles) */
    int timed = osrdn_time_on() && !osrdn_time_in_hook;

    if (timed) {
        osrdn_time_now(&t);
        osrdn_time_in_hook = 1;
    }
    osrdnTriStateOf(ctx, &st);
    osrdnTriangleWith(ctx, &st, v0, v1, v2, pv);
    if (timed) {
        osrdn_time_in_hook = 0;
        osrdn_time_add(OSRDN_TIME_TRI, &t);
        osrdn_time_count(OSRDN_TIME_TRI, 1UL);
    }
}

/*
 * M1v: ONE BEGIN/END GROUP OF GL_TRIANGLES, in one call.
 *
 * The contract is Mesa's, read from its own default (render_tmp.h:131-146):
 *
 *     for (j = start + 2; j < count; j += 3)
 *         RENDER_TRI( j-2, j-1, j, j, 0 );
 *
 * so `count` is an END INDEX, not a count; `parity` is unused for GL_TRIANGLES;
 * and the raw RENDER_TRI calls ctx->TriangleFunc( ctx, j-2, j-1, j, j )
 * directly, with no VB->Elt indirection (vbrender.c:540-546).
 *
 * WHAT THIS BUYS: the state -- the classifier, the ctx reads, the surface
 * queries -- is computed ONCE for the group instead of once for every triangle.
 * The disassembly said that part is about 260 of the 388 instructions in the
 * per-triangle function (docs/M1U_PLAN.md 0).
 *
 * WHEN WE CANNOT TAKE THE GROUP we hand it to Mesa's saved function unchanged,
 * BEFORE writing anything.  That function calls ctx->TriangleFunc per triangle
 * -- which is our own per-triangle hook -- so declining costs exactly what
 * today costs, and no triangle can be lost or drawn twice.
 */
static void osrdnRenderVBTrianglesBody(struct vertex_buffer *VB, GLuint start, GLuint count,
                                       GLuint parity);

static void
osrdnRenderVBTriangles(struct vertex_buffer *VB, GLuint start, GLuint count,
                       GLuint parity)
{
    osrdn_time_stamp t;
    int timed = osrdn_time_on();        /* G5-0: one interval for the group, state preparation included */

    if (timed) {
        osrdn_time_now(&t);
        osrdn_time_in_hook = 1;
    }
    osrdnRenderVBTrianglesBody(VB, start, count, parity);
    if (timed) {
        osrdn_time_in_hook = 0;
        osrdn_time_add(OSRDN_TIME_TRI, &t);
    }
}

static void
osrdnRenderVBTrianglesBody(struct vertex_buffer *VB, GLuint start, GLuint count,
                           GLuint parity)
{
    GLcontext *ctx = VB->ctx;
    osrdnTriState st;
    GLuint j;
    int slot = osrdnSlotOf(ctx, 0);

    (void) parity;                      /* GL_TRIANGLES does not use it */
    osrdnCounts.groups++;
    osrdnTriStateOf(ctx, &st);
    /*
     * M3b: ONLY WHEN THE TRIANGLE FUNCTION IN FORCE IS OURS.  That says both
     * that the classifier took this state (docs/M3A_PLAN.md 11, D3: the group
     * table outlived a declined state) and that Mesa put no setup function --
     * render_triangle -- in front of us (vbrender.c 758-775), whose culling and
     * colour choice this table would skip.
     */
    if (!st.ok || slot < 0 || ctx->TriangleFunc != osrdnHookTriangle) {
        render_func f = (slot >= 0) ? osrdnSaved[slot].rawTri : (render_func) 0;

        osrdnCounts.groupsDeclined++;
        if (f != 0)
            (*f)(VB, start, count, parity);
        else
            /* nothing to fall back to: the group would vanish.  This must stay
               0, and the gate reads it. */
            osrdnCounts.groupsLost++;
        return;
    }
    for (j = start + 2; j < count; j += 3) {
        osrdnCounts.groupTris++;
        osrdn_time_count(OSRDN_TIME_TRI, 1UL);     /* G5-0: triangles under the group's interval */
        osrdnTriangleWith(ctx, &st, j - 2, j - 1, j, j);
    }
}

/*
 * M1v: INSTALLING THE TABLE, AND WHY IT CANNOT BE DONE IN UpdateState.
 *
 * gl_update_state NULLs Driver.RenderVBRawTab, THEN calls our UpdateState, THEN
 * lets gl_set_render_vb_function put Mesa's defaults in (state.c:1105-1136).  So
 * at UpdateState time there is nothing to copy, and a table installed there
 * would keep Mesa from ever installing its own -- leaving ten NULL slots for
 * every other primitive.
 *
 * RenderStart is called AFTER gl_render_vb has already chosen the table
 * (vbrender.c:667-684, then 699-700), so by then the defaults are in.  We copy,
 * replace one slot, and install; the next group comes to us.  A state change
 * NULLs it again and Mesa re-installs its own, and we re-install at the next
 * RenderStart -- in between, the per-triangle path runs, which draws the same
 * picture.
 */
static void
osrdnInstallGroupTab(GLcontext *ctx)
{
    render_func *tab = ctx->Driver.RenderVBRawTab;
    int slot = osrdnSlotOf(ctx, 1);
    int k;

    if (slot < 0 || tab == 0)
        return;                         /* stay on the per-triangle path */
    if (tab == osrdnRawTab[slot])
        return;                         /* already ours */
    for (k = 0; k < OSRDN_RENDER_TAB_SLOTS; k++)
        osrdnRawTab[slot][k] = tab[k];
    osrdnSaved[slot].rawTri = tab[GL_TRIANGLES];
    osrdnRawTab[slot][GL_TRIANGLES] = osrdnRenderVBTriangles;
    ctx->Driver.RenderVBRawTab = osrdnRawTab[slot];
    osrdnCounts.groupInstalls++;
}

/*
 * M1k: THE BRACKET.
 *
 * Mesa wraps every render pass in these two (vbrender.c:699-700 and 728-729,
 * vbindirect.c:313-314/335-336 and 365-366/392-393), and OSmesa/osmesa.c sets
 * neither.  Between them ctx->VB holds the vertices the triangles came from, so
 * between them -- and only between them -- a batch can be undone.
 */
static osrdn_time_stamp osrdnBracketT0;     /* G5-0: RenderStart's clock, closed by RenderFinish */

/*
 * G5-1b (docs/G5_1B_PRESENT_ONE_BLIT_PLAN.md 1-1): the paths that draw into the
 * surface in software, which in present mode would draw the wrong way up.  Printed
 * after the RDN-T lines when RDNMesaTime is set; the judge requires every one 0.
 */
static void
osrdnCountsReport(void)
{
    const osrdn_surf_counts *sc = OSRDNMesaSurfaceCounts();

    osrdn_time_line_begin("RDN-C");
    osrdn_time_line_put("delegated", osrdnCounts.delegated);
    osrdn_time_line_put("replayed", osrdnCounts.replayed);
    osrdn_time_line_put("points", osrdnCounts.pointRuns);
    osrdn_time_line_put("lines", osrdnCounts.lineRuns);
    osrdn_time_line_put("outside", osrdnCounts.outsideRender);
    osrdn_time_line_put("nosoftware", osrdnCounts.noSoftware);
    osrdn_time_line_put("readpix", osrdnCounts.flushWhy[OSRDN_FLUSH_READPIX]);
    osrdn_time_line_put("copypix", osrdnCounts.flushWhy[OSRDN_FLUSH_COPYPIX]);
    osrdn_time_line_put("drawpix", osrdnCounts.flushWhy[OSRDN_FLUSH_DRAWPIX]);
    osrdn_time_line_put("bitmap", osrdnCounts.flushWhy[OSRDN_FLUSH_BITMAP]);
    osrdn_time_line_put("mirrors", sc->mirrors);
    osrdn_time_line_put("mirrors_flipped", sc->mirrorsFlipped);
    osrdn_time_line_put("readpix_flipped", osrdnCounts.readpixFlipped);         /* G5-4 */
    osrdn_time_line_put("readpix_declined", osrdnCounts.readpixFlipDeclined);   /* G5-4: must be 0 */
    osrdn_time_line_end();
    /* the list's item 3, a line of its own (RDN-C is near the 256-byte line buffer): which Mesa
       RasterMask bits the classifier declined for (the port's "gate refused : Hook.c:5" is
       OSRDN_WHY_RASTER), every bit ever seen (types.h 1449-1462), and whether a declined state drew */
    osrdn_time_line_begin("RDN-G");
    osrdn_time_line_put("raster_declined", osrdnCounts.rasterDeclined);
    osrdn_time_line_put("raster_seen", osrdnCounts.rasterSeen);
    osrdn_time_line_put("leaves", osrdnCounts.leaves);
    osrdn_time_line_put("leaves_unbound", osrdnCounts.leavesUnbound);
    osrdn_time_line_put("leaves_watched", osrdnCounts.leavesWatched);
    osrdn_time_line_put("renders_left", osrdnCounts.rendersWhileLeft);
    osrdn_time_line_end();
    {
        /* G5-2 (docs/G5_2_ASYNC_SUBMIT_PLAN.md 2-4): the accepted submissions and their retirement */
        const osrdn_tri_counts *tc = OSRDNMesaTriCounts();

        osrdn_time_line_begin("RDN-A");
        osrdn_time_line_put("async", tc->async);
        osrdn_time_line_put("asubmits", tc->asubmits);
        osrdn_time_line_put("retires", tc->retires);
        osrdn_time_line_put("skipped", tc->retiresSkipped);
        osrdn_time_line_put("failed", tc->retireFailed);
        osrdn_time_line_put("retire_us", tc->retireUs);
        osrdn_time_line_put("latelatch", tc->lateLatch);
        osrdn_time_line_put("lost", tc->lost);
        osrdn_time_line_put("batchwords", tc->batchCap);               /* G5-5 */
        osrdn_time_line_put("batchwords_ignored", tc->batchCapIgnored);
        osrdn_time_line_end();
    }
    /* G5-1b/1c: how the frames were presented (OSRDNMesaPresent.h) */
    {
        const osrdn_present_counts *pc = OSRDNMesaPresentCounts();

        osrdn_time_line_begin("RDN-P");
        osrdn_time_line_put("rects", pc->rects);
        osrdn_time_line_put("coalesced", pc->coalesced);
        osrdn_time_line_put("covered", pc->covered);
        osrdn_time_line_put("rowfallback", pc->rowFallback);
        osrdn_time_line_put("finds", pc->windowFinds);
        osrdn_time_line_put("lost", pc->windowLost);
        osrdn_time_line_put("calibrations", pc->calibrations);
        osrdn_time_line_put("shifted", pc->shifted);
        osrdn_time_line_put("busy", pc->refused[OSRDN_PRESENT_E_BUSY]);
        osrdn_time_line_put("dst", pc->refused[OSRDN_PRESENT_E_DST]);
        osrdn_time_line_end();
    }
}

static void
osrdnHookRenderStart(GLcontext *ctx)
{
    int slot = osrdnSlotOf(ctx, 0);
    void (*saved)(GLcontext *) = (slot >= 0) ? osrdnSaved[slot].rstart : 0;

    if (osrdnLeft)
        osrdnCounts.rendersWhileLeft++;     /* the list's item 3: a pass drawn under a declined state */

    if (osrdn_time_on()) {
        static int countsRegistered;

        osrdn_time_now(&osrdnBracketT0);
        if (!countsRegistered) {            /* G5-1b: once, the RDN-C line at exit */
            countsRegistered = 1;
            osrdn_time_at_exit(osrdnCountsReport);
        }
    }

    osrdnCounts.renderStarts++;
    if (!osrdn_tri_span_enabled()) {
        /* M1k: nothing should be waiting; if something is, it belongs to a
           pass that ended without a RenderFinish and it goes out now, before
           its vertices stop meaning anything */
        osrdnFlushOutside();
    } else if (osrdnPend.n > osrdnPend.stale) {
        /* G4-2 B1: a bracket ended without RenderFinish (Mesa pairs them; this
           is counted so a run can say it never happened).  Those entries were
           never verified and their indices are dead: they can go out, but
           never be redrawn. */
        osrdnCounts.unfinished++;
        osrdnPend.stale = osrdnPend.n;
    }
    osrdnInRender = 1;
    osrdn_time_in_render = 1;
    /*
     * M1v: the ONLY place the group table can be installed.  By here
     * gl_render_vb has already chosen the table for THIS group, so ours takes
     * effect from the next one -- and by here Mesa's defaults are in, which
     * they are not at UpdateState time (state.c:1105-1136).
     */
    if (osrdn_tri_group_enabled())
        osrdnInstallGroupTab(ctx);
    if (saved != 0)
        (*saved)(ctx);
}

/*
 * M3g: glFinish FILLS THE APPLICATION'S ARRAY (docs/M3G_PLAN.md).
 *
 * The colour surface is ours while the context is bound, and osmesa.c copies
 * it back only when the surface goes or OSMesaGetColorBuffer is asked
 * (osmesa.c 888-895).  An ordinary OSMesa program reads its own array after
 * glFinish -- and saw nothing.  _mesa_Finish calls Driver.Finish when there is
 * one (context.c 2021-2022), and osmesa.c leaves it empty, so this is the
 * copy GetColorBuffer makes, at the moment GL says the picture is done.
 * The Matrox back end does the same from the same hook
 * (OpenStepMGAMesaHook.c, Driver.Finish = osmgaMesaMirror).
 */
static void
osrdnHookFinish(GLcontext *ctx)
{
    osrdnCounts.finishes++;
    if (!osrdn_surf_bound_to((const void *) ctx->DriverCtx) || osrdn_surf_app_buffer() == 0)
        return;
    /* whatever is still in a batch is part of the picture */
    osrdnFlushOutside();
    /* G3 (docs/G3_PRESENT_PLAN.md 2-2): in present mode the picture goes to the
       screen from video memory and the caller's array is declared stale by the
       contract -- ONLY here.  An explicit read (OpenStepMesaAccelMirror) and the
       leave path still copy, so M3g's "the array is the picture" holds the
       moment present mode is off. */
    if (osrdn_present_active()) {
        osrdnCounts.finishStoodDown++;
        return;
    }
    osrdn_surf_mirror();
    osrdnCounts.finishMirrors++;
}

static void
osrdnHookRenderFinish(GLcontext *ctx)
{
    int slot = osrdnSlotOf(ctx, 0);
    void (*saved)(GLcontext *) = (slot >= 0) ? osrdnSaved[slot].rfinish : 0;

    osrdnCounts.renderFinishes++;
    /* M1k: THE flush -- the last moment the software function can draw what
       the card refuses.  G4-2 B1: the question is asked here instead, and the
       batch is flushed only if the answer is "refused" (osrdnBracketEnd). */
    osrdnBracketEnd();
    osrdnInRender = 0;
    osrdn_time_in_render = 0;
    if (saved != 0)
        (*saved)(ctx);
    if (osrdn_time_on())
        osrdn_time_add(OSRDN_TIME_BRACKET, &osrdnBracketT0);      /* G5-0: closed outside, so its bin is "out" */
}

/*
 * G4-2 B1 F3: points and lines.  OSMesa draws its lines straight into the
 * surface with no callback (osmesa.c 1601-1610) and Mesa's points go through
 * the span functions; both must land on top of whatever the card was told to
 * draw before them.  So the batch goes out first, then the function Mesa (or
 * OSMesa) chose runs unchanged.  Installed by the same four steps as the
 * triangle function (docs/M1D_PLAN.md): NULL is what osmesa.c 2009-2010 leaves
 * for points (and for lines when its own does not apply), choose, save,
 * replace; points.c 1333-1346 and lines.c 1071-1084 then leave a non-null
 * function alone.
 */
static void
osrdnHookPoints(GLcontext *ctx, GLuint first, GLuint last)
{
    int slot = osrdnSlotOf(ctx, 0);
    points_func saved = (slot >= 0) ? osrdnSaved[slot].points : (points_func) 0;

    osrdnCounts.pointRuns++;
    osrdnFlushFor(OSRDN_FLUSH_POINTS);
    if (saved != 0)
        (*saved)(ctx, first, last);
    else
        osrdnCounts.primNoSoftware++;
}

static void
osrdnHookLine(GLcontext *ctx, GLuint v1, GLuint v2, GLuint pv)
{
    int slot = osrdnSlotOf(ctx, 0);
    line_func saved = (slot >= 0) ? osrdnSaved[slot].line : (line_func) 0;

    osrdnCounts.lineRuns++;
    osrdnFlushFor(OSRDN_FLUSH_LINES);
    if (saved != 0)
        (*saved)(ctx, v1, v2, pv);
    else
        osrdnCounts.primNoSoftware++;
}

static void
osrdnInstallPrims(GLcontext *ctx, int slot)
{
    if (slot < 0)
        return;                         /* no slot, nothing to save into: Mesa's choice stands */
    if (ctx->Driver.PointsFunc == 0)
        gl_set_point_function(ctx);
    if (ctx->Driver.PointsFunc != osrdnHookPoints) {
        osrdnSaved[slot].points = ctx->Driver.PointsFunc;
        ctx->Driver.PointsFunc = osrdnHookPoints;
    }
    if (ctx->Driver.LineFunc == 0)
        gl_set_line_function(ctx);
    if (ctx->Driver.LineFunc != osrdnHookLine) {
        osrdnSaved[slot].line = ctx->Driver.LineFunc;
        ctx->Driver.LineFunc = osrdnHookLine;
    }
}

/* G4-2 B1 F6/F7: glFlush and the pixel commands read or write the surface;
   the batch goes out first, then whoever was there answers (or GL_FALSE:
   core Mesa does it, dd.h 462-495). */
static void (*osrdnPrevFlush)(GLcontext *);
static GLboolean (*osrdnPrevReadPixels)(GLcontext *, GLint, GLint, GLsizei, GLsizei, GLenum, GLenum,
                                        const struct gl_pixelstore_attrib *, GLvoid *);
static GLboolean (*osrdnPrevCopyPixels)(GLcontext *, GLint, GLint, GLsizei, GLsizei, GLint, GLint, GLenum);
static GLboolean (*osrdnPrevDrawPixels)(GLcontext *, GLint, GLint, GLsizei, GLsizei, GLenum, GLenum,
                                        const struct gl_pixelstore_attrib *, const GLvoid *);
static GLboolean (*osrdnPrevBitmap)(GLcontext *, GLint, GLint, GLsizei, GLsizei,
                                    const struct gl_pixelstore_attrib *, const GLubyte *);

static void
osrdnHookFlush(GLcontext *ctx)
{
    osrdnCounts.glFlushes++;
    osrdnFlushFor(OSRDN_FLUSH_GLFLUSH);
    if (osrdnPrevFlush != 0)
        (*osrdnPrevFlush)(ctx);
}

/*
 * G5-4 (docs/G5_4_READPIX_AND_CLEANUP_PLAN.md 1-2): IN PRESENT MODE THE SURFACE IS TOP-DOWN, and
 * the OSMesa buffer Mesa would read IS that surface -- so Mesa's own read would hand back the
 * picture upside down (GLQuake's `screenshot`).  The reader takes what Mesa's fast path takes,
 * with its clipping, plus the GL alignments; anything else is declined and counted.
 */
static int
osrdnReadFlipped(GLcontext *ctx, GLint x, GLint y, GLsizei width, GLsizei height,
                 GLenum format, GLenum type, const struct gl_pixelstore_attrib *pack, GLvoid *dest)
{
    osrdn_readpix_src s;
    osrdn_readpix_pack p;
    const osrdn_surf_counts *sc = OSRDNMesaSurfaceCounts();

    /* the transfer operations read_fast_rgba_pixels refuses (readpix.c), and the packing it does not do */
    if (ctx->Pixel.ScaleOrBiasRGBA || ctx->Pixel.MapColorFlag || ctx->ColorMatrix.type != MATRIX_IDENTITY ||
        ctx->Pixel.ScaleOrBiasRGBApcm || ctx->Pixel.ColorTableEnabled ||
        ctx->Pixel.PostColorMatrixColorTableEnabled || ctx->Pixel.MinMaxEnabled || ctx->Pixel.HistogramEnabled)
        return 0;
    if (pack == 0 || pack->SwapBytes || pack->LsbFirst || pack->SkipImages != 0)
        return 0;
    if (type != GL_UNSIGNED_BYTE || (format != GL_RGB && format != GL_RGBA))
        return 0;
    if (ctx->DrawBuffer->UseSoftwareAlphaBuffers)
        return 0;                               /* the alpha would come from another buffer */
    if (ctx->ReadBuffer == 0 || (unsigned long) ctx->ReadBuffer->Width != sc->width ||
        (unsigned long) ctx->ReadBuffer->Height != sc->height)
        return 0;                               /* the flip is by the surface's height */
    s.surf = osrdn_surf_base();
    s.rowPixels = osrdn_surf_stride();
    s.width = (long) sc->width;
    s.height = (long) sc->height;
    osrdn_surf_shifts(&s.rs, &s.gs, &s.bs, &s.as);
    s.xmin = ctx->ReadBuffer->Xmin;
    s.xmax = ctx->ReadBuffer->Xmax;
    s.ymin = ctx->ReadBuffer->Ymin;
    s.ymax = ctx->ReadBuffer->Ymax;
    p.alignment = pack->Alignment;
    p.rowLength = pack->RowLength;
    p.skipPixels = pack->SkipPixels;
    p.skipRows = pack->SkipRows;
    return osrdn_readpix_flipped(&s, (long) x, (long) y, (long) width, (long) height,
                                 format == GL_RGBA ? 4 : 3, &p, (unsigned char *) dest);
}

static GLboolean
osrdnHookReadPixels(GLcontext *ctx, GLint x, GLint y, GLsizei width, GLsizei height,
                    GLenum format, GLenum type, const struct gl_pixelstore_attrib *pack, GLvoid *dest)
{
    osrdnFlushFor(OSRDN_FLUSH_READPIX);         /* the batch, and G5-2's retire (table: READPIX 1) */
    if (osrdn_present_active() && osrdn_surf_flipped()) {
        if (osrdnReadFlipped(ctx, x, y, width, height, format, type, pack, dest)) {
            osrdnCounts.readpixFlipped++;
            return GL_TRUE;
        }
        osrdnCounts.readpixFlipDeclined++;
    }
    if (osrdnPrevReadPixels != 0)
        return (*osrdnPrevReadPixels)(ctx, x, y, width, height, format, type, pack, dest);
    return GL_FALSE;
}

static GLboolean
osrdnHookCopyPixels(GLcontext *ctx, GLint srcx, GLint srcy, GLsizei width, GLsizei height,
                    GLint dstx, GLint dsty, GLenum type)
{
    osrdnFlushFor(OSRDN_FLUSH_COPYPIX);
    if (osrdnPrevCopyPixels != 0)
        return (*osrdnPrevCopyPixels)(ctx, srcx, srcy, width, height, dstx, dsty, type);
    return GL_FALSE;
}

static GLboolean
osrdnHookDrawPixels(GLcontext *ctx, GLint x, GLint y, GLsizei width, GLsizei height,
                    GLenum format, GLenum type, const struct gl_pixelstore_attrib *unpack,
                    const GLvoid *pixels)
{
    osrdnFlushFor(OSRDN_FLUSH_DRAWPIX);
    if (osrdnPrevDrawPixels != 0)
        return (*osrdnPrevDrawPixels)(ctx, x, y, width, height, format, type, unpack, pixels);
    return GL_FALSE;
}

static GLboolean
osrdnHookBitmap(GLcontext *ctx, GLint x, GLint y, GLsizei width, GLsizei height,
                const struct gl_pixelstore_attrib *unpack, const GLubyte *bitmap)
{
    osrdnFlushFor(OSRDN_FLUSH_BITMAP);
    if (osrdnPrevBitmap != 0)
        return (*osrdnPrevBitmap)(ctx, x, y, width, height, unpack, bitmap);
    return GL_FALSE;
}

/*
 * Install ours, or leave Mesa's choice exactly as it was.
 *
 * state.c 1100 clears Driver.TriangleFunc before every UpdateState, so this
 * runs every time or not at all -- there is no "already installed".
 */
static void
osrdnHookInstall(GLcontext *ctx, int take)
{
    int slot;

    /*
     * M3g: glFinish copies the surface back.  BEFORE the take test: software
     * draws into the substituted surface too, so a declined state needs it as
     * much as a taken one.  Only where nothing else is -- osmesa.c leaves the
     * field empty -- and a pointer that is not ours is left alone and counted.
     */
    if (ctx->Driver.Finish == 0)
        ctx->Driver.Finish = osrdnHookFinish;
    else if (ctx->Driver.Finish != osrdnHookFinish)
        osrdnCounts.finishForeign++;

    slot = osrdnSlotOf(ctx, take ? 1 : 0);
    if (take && slot < 0) {
        osrdnCounts.slotsFull++;
        take = 0;                       /* no slot: nothing of ours can go in */
    }
    if (!take) {
        osrdnCounts.leaves++;
        osrdnLeft = 1;
        if (ctx->Driver.RenderStart == osrdnHookRenderStart)
            osrdnCounts.leavesWatched++;    /* renders_left can see this leave's passes */
        if (!osrdn_surf_bound_to((const void *) ctx->DriverCtx))
            osrdnCounts.leavesUnbound++;    /* the list's item 3: no surface -- the card could not draw it anyway */
        if (slot >= 0)
            osrdnSaved[slot].sw = 0;
        /* G4-2 B1 F5: everything from here is software, so what the card
           holds goes out first -- and the point/line wrappers below still go
           in, because a batch from an EARLIER state may be open when the next
           software point arrives */
        osrdnFlushFor(OSRDN_FLUSH_LEAVE);
        osrdnInstallPrims(ctx, slot);
        return;                         /* state.c 1124 will choose, as always */
    }
    /* G4-2 B1 F10: a state that renders in passes repeats the bracket; the
       Matrox rule is not to batch it at all (its MultipassFunc is read, never
       written) */
    osrdnMultipass = (ctx->Driver.MultipassFunc != 0) ? 1 : 0;
    if (osrdnMultipass)
        osrdnCounts.multipass++;
    /* Let Mesa choose first, and keep what it chose: with ours already in
       place, triangle.c 1532 returns and there would be nothing to fall back
       to.  gl_set_triangle_function writes this one field and nothing else
       (verified: every assignment in triangle.c 1523-1688 and in
       aatriangle.c 391-420 is to ctx->Driver.TriangleFunc). */
    ctx->Driver.TriangleFunc = 0;
    gl_set_triangle_function(ctx);
    osrdnSaved[slot].sw = ctx->Driver.TriangleFunc;
    ctx->Driver.TriangleFunc = osrdnHookTriangle;
    osrdnLeft = 0;
    /* M1g: the texels go in HERE, not in the triangle function -- once per
       accepted state instead of once per triangle, and always AFTER any ZPREP
       because this runs inside the process (docs/M1_NEXT_DECISION.md H4). */
    /* G4-1b: M1g's one-shot 8 x 8 upload here is gone; osrdnTexResident() puts the current
       texture in the window on the draw path, whatever its size */
    /*
     * M1j: and OUR Clear goes in -- EVERY TIME, like the triangle function.
     *
     * The plan said once, and that was wrong.  `ctx->Driver.Clear = clear` at
     * osmesa.c 1991 is INSIDE osmesa_update_state, not in a one-time setup: the
     * grep found the line and I did not look at which function it sits in.  Our
     * hook is called from the same function twenty lines later (osmesa.c 2013),
     * so the first install survives -- and the SECOND update_state puts Mesa's
     * back, at which point a once-only guard leaves it there.  Measured:
     * cli=1 clc=0, installed and never called.
     *
     * The guard that matters is the OTHER one: never save our own pointer, or
     * the chain calls itself.
     *
     * The depth buffer is no longer wiped here -- glClear does it, which is
     * what GL says and what the software link does too.
     */
    /* G4-1b: the three texture notifications, chained once each */
    if (ctx->Driver.TexImage != osrdnHookTexImage) {
        osrdnPrevTexImage = ctx->Driver.TexImage;
        ctx->Driver.TexImage = osrdnHookTexImage;
    }
    if (ctx->Driver.TexSubImage != osrdnHookTexSubImage) {
        osrdnPrevTexSubImage = ctx->Driver.TexSubImage;
        ctx->Driver.TexSubImage = osrdnHookTexSubImage;
    }
    if (ctx->Driver.DeleteTexture != osrdnHookDeleteTexture) {
        osrdnPrevDeleteTexture = ctx->Driver.DeleteTexture;
        ctx->Driver.DeleteTexture = osrdnHookDeleteTexture;
    }
    if (slot >= 0 && ctx->Driver.Clear != osrdnHookClear) {
        osrdnSaved[slot].clear = ctx->Driver.Clear;
        ctx->Driver.Clear = osrdnHookClear;
        osrdnCounts.clearInstalls++;
    }
    /*
     * M1k: and the bracket.  Same shape as Clear, and for the same reason the
     * guard is on OUR pointer rather than on a "done once" flag -- see above.
     * Unlike Clear these are not reset by Mesa, so after the first install the
     * test is simply false and nothing happens.
     */
    if (ctx->Driver.RenderStart != osrdnHookRenderStart) {
        osrdnSaved[slot].rstart = ctx->Driver.RenderStart;
        ctx->Driver.RenderStart = osrdnHookRenderStart;
        osrdnCounts.renderInstalls++;
    }
    if (ctx->Driver.RenderFinish != osrdnHookRenderFinish) {
        osrdnSaved[slot].rfinish = ctx->Driver.RenderFinish;
        ctx->Driver.RenderFinish = osrdnHookRenderFinish;
    }
    /*
     * G4-2 B1 F6/F7: glFlush and the four pixel commands.  OSMesa sets none of
     * them (grep of OSmesa/osmesa.c: 0 hits), so what is saved is almost
     * certainly null and each wrapper then answers GL_FALSE -- "core Mesa does
     * the job" (dd.h 462-495) -- AFTER the batch has gone out.  Same guard as
     * the texture notifications: never save our own pointer.
     */
    if (ctx->Driver.Flush != osrdnHookFlush) {
        osrdnPrevFlush = ctx->Driver.Flush;
        ctx->Driver.Flush = osrdnHookFlush;
    }
    if (ctx->Driver.ReadPixels != osrdnHookReadPixels) {
        osrdnPrevReadPixels = ctx->Driver.ReadPixels;
        ctx->Driver.ReadPixels = osrdnHookReadPixels;
    }
    if (ctx->Driver.CopyPixels != osrdnHookCopyPixels) {
        osrdnPrevCopyPixels = ctx->Driver.CopyPixels;
        ctx->Driver.CopyPixels = osrdnHookCopyPixels;
    }
    if (ctx->Driver.DrawPixels != osrdnHookDrawPixels) {
        osrdnPrevDrawPixels = ctx->Driver.DrawPixels;
        ctx->Driver.DrawPixels = osrdnHookDrawPixels;
    }
    if (ctx->Driver.Bitmap != osrdnHookBitmap) {
        osrdnPrevBitmap = ctx->Driver.Bitmap;
        ctx->Driver.Bitmap = osrdnHookBitmap;
    }
    osrdnInstallPrims(ctx, slot);
    osrdnCounts.installs++;
}

void
OpenStepMesaAccelUpdateState(GLcontext *ctx, int rowLength, int yUp)
{
    osrdn_class_state s;
    int cls, why = OSRDN_WHY_NONE;

    osrdn_hook_count(OSRDN_HOOK_UPDATE_STATE);

    /* M1k: the state is about to change, and the prologue carries the state.
       Whatever is waiting was built under the OLD one and goes out first.
       G4-2 B2: not any more -- a state change is a SEGMENT of the open batch
       (osrdn_tri_batch_joins decides), and the events that must close it are
       the flush points (a refused state: F5 in the install; a surface: F9).
       The knob restores the M1k shape.  Measured before this guard: every one
       of GHOST_SEG's 150 changes flushed here and no segment was ever made. */
    if (!osrdn_tri_span_enabled())
        osrdnFlushOutside();

    /* The stride and the orientation are handed to us on every call because
       OSMesaPixelStore can turn the buffer over after the context is current
       (the call site says so).  Recorded, not acted on. */
    osrdnCounts.rowLength = (unsigned long)rowLength;
    osrdnCounts.yUp = (unsigned long)yUp;

    /*
     * G4-1b: THE TEXTURE BIT IS TAKEN FROM THE TRUTH, NOT FROM RasterMask.  Mesa 3.4.2
     * recomputes RasterMask only under NEW_RASTER_OPS / NEW_TEXTURE_ENABLE (state.c 991,
     * update_rasterflags at 997, the bit at 817), but Texture.ReallyEnabled moves under
     * NEW_TEXTURING alone (state.c 957) -- a texture that becomes complete through
     * glTexParameter after the enable draws with the bit stale (measured: the first
     * textured scene of ghostprobe_v9, RasterMask 0 with ReallyEnabled 2).  Mesa's own
     * triangle chooser reads ReallyEnabled (triangle.c 1563), so the classifier is given
     * the same word: the bit set exactly when texturing is really on.
     */
    s.rasterMask = ((unsigned long)ctx->RasterMask & ~(unsigned long)TEXTURE_BIT) |
                   (ctx->Texture.ReallyEnabled ? (unsigned long)TEXTURE_BIT : 0UL);
    s.rgba = ctx->Visual->RGBAflag ? 1 : 0;
    s.smooth = ctx->Polygon.SmoothFlag ? 1 : 0;
    s.stipple = ctx->Polygon.StippleFlag ? 1 : 0;
    /*
     * THE VALUE, not a boolean.  The classifier compares this against
     * TEXTURE0_2D (types.h 733) because "textured" is not one state: 1D, 3D and
     * cube all set ReallyEnabled too and none of them is the one the prologue
     * draws.  `? 1 : 0` here made every texture compare unequal to 2 and the
     * card declined every textured triangle -- with `tex=1` in the log, which
     * says texturing was on and says nothing about what was passed on.
     * sim_class could not see it: it drives the classifier with the enum, which
     * is what this line now hands it.
     */
    s.texture = (unsigned long)ctx->Texture.ReallyEnabled;
    s.depthBits = (int)ctx->Visual->DepthBits;
    s.rowLength = rowLength;
    s.yUp = yUp;
    s.shadeModel = (unsigned long)ctx->Light.ShadeModel;
    s.triangleCaps = (unsigned long)ctx->TriangleCaps;
    /* M1f: read, never interpreted here.  The hook carries the state across;
       deciding which blend modes are drawable is the classifier's job, and
       keeping that in one testable integer function is the whole shape of
       this split (docs/M1B_PLAN.md 3). */
    s.blendEnabled = ctx->Color.BlendEnabled ? 1 : 0;
    s.blendSrcRGB = (unsigned long)ctx->Color.BlendSrcRGB;
    s.blendDstRGB = (unsigned long)ctx->Color.BlendDstRGB;
    s.blendSrcA = (unsigned long)ctx->Color.BlendSrcA;
    s.blendDstA = (unsigned long)ctx->Color.BlendDstA;
    s.blendEquation = (unsigned long)ctx->Color.BlendEquation;
    osrdnCounts.shade = s.shadeModel;
    osrdnCounts.caps = s.triangleCaps;
    osrdnCounts.blend = s.blendEnabled ? s.blendSrcRGB : 0UL;

    /*
     * M1g: which texture, not just whether.  Read here, judged there -- the
     * classifier is the one that says whether this is the shape we upload.
     * A null object or a missing level 0 leaves the fields 0, which the
     * classifier refuses; that is the right answer and needs no branch here.
     */
    s.texUnit0 = (unsigned long)ctx->Texture.Unit[0].ReallyEnabled;
    s.texWidth = 0UL; s.texHeight = 0UL; s.texBorder = 0UL; s.texFormat = 0UL;
    s.texMinFilter = 0UL; s.texMagFilter = 0UL;
    s.texWrapS = 0UL; s.texWrapT = 0UL;
    s.texMip = (unsigned long)osrdn_tri_mip_mode(); s.texComplete = 0UL; s.texLodOk = 0UL;   /* G4-4 K5, G4-5 */
    s.texEnvMode = (unsigned long)ctx->Texture.Unit[0].EnvMode;
    s.depthFunc = (unsigned long)ctx->Depth.Func;
    s.depthMask = (unsigned long)ctx->Depth.Mask;
    s.alphaEnabled = ctx->Color.AlphaEnabled ? 1 : 0;            /* G4-3 K2 */
    s.alphaFunc = (unsigned long)ctx->Color.AlphaFunc;
    s.alphaRef = (unsigned long)ctx->Color.AlphaRef;             /* Mesa's byte (alpha.c 57-62) */
    if (ctx->Texture.Unit[0].Current != 0) {
        const struct gl_texture_object *to = ctx->Texture.Unit[0].Current;

        s.texMinFilter = (unsigned long)to->MinFilter;
        s.texMagFilter = (unsigned long)to->MagFilter;
        s.texWrapS = (unsigned long)to->WrapS;
        s.texWrapT = (unsigned long)to->WrapT;
        s.texComplete = to->Complete ? 1UL : 0UL;            /* G4-4 K5 */
        /* G4-5: GL's lambda reaches the whole chain unclamped and unbiased (texobj.c 76-80 are the
           defaults; the unit's LodBias is added to lambda, texture.c 2746-2750); 12 levels is the
           largest chain the log2 fields can name */
        s.texLodOk = (to->BaseLevel == 0 && to->MinLod <= 0.0F && to->MaxLod >= to->M &&
                      ctx->Texture.Unit[0].LodBias == 0.0F && to->M <= 11.0F) ? 1UL : 0UL;
        if (to->Image[0] != 0) {
            s.texWidth = (unsigned long)to->Image[0]->Width;
            s.texHeight = (unsigned long)to->Image[0]->Height;
            s.texBorder = (unsigned long)to->Image[0]->Border;
            s.texFormat = (unsigned long)to->Image[0]->Format;
        }
    }
    osrdnCounts.tex = s.texture;
    osrdnCounts.rmask = s.rasterMask;

    /* record the mask before classifying: what we decline for is the question
       M1c starts from, and a counter that only says "RASTER" cannot answer it */
    osrdnCounts.rasterSeen |= s.rasterMask;
    osrdnCounts.rasterLast = s.rasterMask;

    cls = osrdn_class_of(&s, osrdnHookAccel(), &why);
    if (why == OSRDN_WHY_RASTER)
        osrdnCounts.rasterDeclined |= s.rasterMask;
    if (cls >= 0 && cls < OSRDN_CLASSES)
        osrdnCounts.cls[cls]++;
    if (why >= 0 && why < OSRDN_WHY_REASONS)
        osrdnCounts.why[why]++;
    if (why == OSRDN_WHY_TEXTURE) {                 /* G4-6: which clause, and the value */
        unsigned long tv = 0UL;
        int tk = osrdn_class_tex_why(&s, &tv);

        if (tk >= 0 && tk < OSRDN_TEXWHY_CLAUSES) {
            osrdnCounts.texWhy[tk]++;
            osrdnCounts.texWhyVal[tk] = tv;
        }
    }

    /*
     * M3g: THE CARD DRAWS WITH WINDOW Y AS THE ROW, which is Y_UP.  A context
     * that turned Y_UP off after it was bound is left by osmesa.c 741; one that
     * is made current again with it off is bound without being asked
     * (osmesa.c 561 passes no orientation).  Software still draws right into
     * the surface -- it lays rows out the way the copy back reads them -- so
     * only the card is kept out, as the Matrox back end does
     * (OpenStepMGAMesaHook.c, `if (!yUp || ...)`).  The row length needs no
     * test here: osrdn_surf_take refuses any but the width.
     */
    if (!yUp && cls == OSRDN_CLASS_WOULD_TAKE) {
        osrdnCounts.notUp++;
        cls = -1;
    }

    /* M1d: and now the one thing M1b promised not to do. */
    osrdnHookInstall(ctx, cls == OSRDN_CLASS_WOULD_TAKE);
}

/* ---- M1c: the six that are real now -------------------------------------
 *
 * Each is a thin call into OSRDNMesaSurface.c plus its counter.  The decisions
 * live there because there they are a function of plain integers and can be
 * driven from a table on the host; here there is nothing to get wrong but the
 * order of the arguments, and osmesa.c's declaration fixes that.
 */

void *
OpenStepMesaAccelBuffer(void *ctx, void *buffer, int width, int height,
                        int rshift, int gshift, int bshift,
                        int appRowLength, int *rowLength)
{
    osrdn_hook_count(OSRDN_HOOK_BUFFER);
    osrdnFlushFor(OSRDN_FLUSH_SURFACE);     /* G4-2 B1 F9: a batch aimed at the old surface goes first */
    /*
     * M1g: say how far the ONE mapping has to reach BEFORE it is made.  The
     * texels live past the colour surface, and a reserve that arrived after the
     * mapping would be counted and ignored (surface unit) rather than obeyed --
     * so it has to be here, on the path that leads to the mmap, not later.
     */
    osrdn_surf_reserve(OSRDN_TEX_BYTE_OFF + OSRDN_TEX_ARENA_BYTES);   /* G4-1b: the arena (docs/G4_GLQUAKE_PLAN.md 4-1) */
    {
        void *got = osrdn_surf_take(ctx, buffer, width, height, rshift, gshift, bshift,
                                    appRowLength, rowLength, 0);
        unsigned long winBytes = 0UL;

        /* G4-1b: a (re)taken surface is a new epoch for the arena -- every residency record
           made before it is invalid by its epoch, without a scan; the arena is what the ONE
           mapping reaches past the texels' start, at most OSRDN_TEX_ARENA_BYTES */
        if (got != 0 && osrdn_surf_window(&winBytes) != 0 && winBytes > OSRDN_TEX_BYTE_OFF) {
            unsigned long room = winBytes - OSRDN_TEX_BYTE_OFF;

            osrdnTexEpoch++;
            osrdn_texarena_set(OSRDN_TEX_BYTE_OFF, room > OSRDN_TEX_ARENA_BYTES ? OSRDN_TEX_ARENA_BYTES : room,
                               osrdnTexEpoch);
        }
        return got;
    }
}

int
OpenStepMesaAccelBoundTo(const void *ctx)
{
    osrdn_hook_count(OSRDN_HOOK_BOUND_TO);
    return osrdn_surf_bound_to(ctx);
}

void *
OpenStepMesaAccelAppBuffer(void)
{
    osrdn_hook_count(OSRDN_HOOK_APP_BUFFER);
    return osrdn_surf_app_buffer();
}

unsigned long
OpenStepMesaAccelStride(void)
{
    osrdn_hook_count(OSRDN_HOOK_STRIDE);
    return osrdn_surf_stride();
}

void
OpenStepMesaAccelMirror(void)
{
    osrdn_hook_count(OSRDN_HOOK_MIRROR);
    /* M1k: the application is about to READ the picture (osmesa.c:892 returns
       the buffer immediately after this).  Anything still in a batch would not
       be in it. */
    osrdnFlushOutside();
    /* Safe with nothing bound: the leave path calls this without testing the
       binding (osmesa.c 359-375), so that is an ordinary outcome. */
    osrdn_surf_mirror();
}

void
OpenStepMesaAccelReleaseBuffer(void *ctx)
{
    osrdn_hook_count(OSRDN_HOOK_RELEASE_BUFFER);
    /* M1k: the surface is going away; a batch pointed at it must go first. */
    osrdnFlushFor(OSRDN_FLUSH_RELEASE);
    /* Called from BOTH osmesa_leave_accel (osmesa.c 406) and
       OSMesaDestroyContext (427), so it must be safe twice. */
    osrdn_surf_release(ctx);
}
