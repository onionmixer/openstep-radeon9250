/*
 * OSRDNMesaTri.c - see OSRDNMesaTri.h.  Plain C89, no libc and no Mesa headers:
 * the calls it needs are declared here, as the probe's and the surface's are.
 *
 * THE NODE IS A BINARY LATCH.  rdnDevOpen refuses a second open with ENXIO
 * (OSRDNDisplay.m 153) and d_close arrives on the last close only, so this unit
 * opens for the one ioctl and closes again -- exactly as the probe and the
 * surface do.  Holding the descriptor across triangles would be faster and
 * would lock every other unit out of the node; M1d is not the rung that makes
 * anything fast (docs/M1D_PLAN.md 6).
 *
 * The batch window is mapped ONCE.  The mapping outlives the descriptor, which
 * is the same discovery M1c's surface rests on.
 */

#include "OSRDNMesaTri.h"
#include "OSRDNMesaProbe.h"
#include "OSRDNMesaTriTable.h"
#include "osrdn_r7b.h"
#include "OSRDNMesaVerify.h"        /* G4-2 B1: the kernel's verifier, generated */
#include "OSRDNMesaTime.h"          /* G5-0: the frame-budget instrument */

extern int open(const char *, int, ...);
extern int close(int);
extern int ioctl(int, int, char *);
extern int write(int, const void *, unsigned int);     /* G4-6: triTrace only */
extern int fsync(int);
extern long lseek(int, long, int);
extern int ftruncate(int, long);                      /* G5-4: the last stream is cut to its length */
#define TRACE_OPEN_FLAGS  (1 | 01000 | 02000)   /* O_WRONLY | O_CREAT | O_TRUNC, bsd/sys/fcntl.h 35-41 */
extern char *mmap(char *, int, int, int, int, long);
extern int vm_allocate(int, char **, int, int);
extern int task_self(void);
extern char *getenv(const char *);
extern int vm_deallocate(int, char *, int);
/* REL1 B8: the seed's start when RDNMesaSeed is unset.  Its own struct name,
   so a unit that also sees OSRDNMesaTime.c's cannot collide with it. */
struct osrdn_tri_timeval { long sec; long usec; };
extern int gettimeofday(struct osrdn_tri_timeval *, void *);

#define NODE            "/dev/rdnvram0"
#define NODE_RDWR       2           /* bsd/sys/fcntl.h 36 */
#define PROT_RW         3           /* PROT_READ | PROT_WRITE */
#define MAP_SHARED_     1

/* the whole stream: the template, the draw header, VF_CNTL and three vertices.
   The textured one is longer in both parts, so the buffer bound is its. */
#define TRI_VERTS       3
#define TRI_WORDS       (OSRDN_TRI_PROLOGUE_WORDS + 1 + 1 + \
                         (TRI_VERTS * OSRDN_TRI_VERTEX_WORDS))
#define TEX_WORDS       (OSRDN_TEX_PROLOGUE_WORDS + 1 + 1 + \
                         (TRI_VERTS * OSRDN_TEX_VERTEX_WORDS))
#define MAX_WORDS       ((TEX_WORDS > TRI_WORDS) ? TEX_WORDS : TRI_WORDS)

/*
 * The ring in the header says 3 * 5 because it may not include the generated
 * table.  If the generated vertex width ever stops being 5, this line stops the
 * build instead of letting the log silently hold a different shape.
 */
typedef char osrdnTriSentFits[(3 * OSRDN_TRI_VERTEX_WORDS == 15) ? 1 : -1];
/* the sent-log ring holds the WIDEST vertex, or a textured triangle would be
   recorded short and the host would predict from half of it */
typedef char osrdnTexSentFits[(3 * OSRDN_TEX_VERTEX_WORDS <= OSRDN_TRI_LOG_WORDS)
                              ? 1 : -1];
/* M3d: the failed-stream copy holds a whole batch */
typedef char osrdnTriFailFits[(OSRDN_TRI_FAIL_WORDS == OSRDN_BATCH_MAX_WORDS) ? 1 : -1];

static osrdn_tri_counts triCounts;
static osrdn_tri_sent   triSent;
static osrdn_tri_failed triFailed;     /* M3d */
static unsigned long   *triWindow;      /* the mapped batch page */
/*
 * M1p: WHERE THE WORDS ARE BUILT.
 *
 * Either the mapped window (cache-inhibited, 69 ns a word) or this process's
 * own cached buffer (the driver copies it in).  Everything that lays out a
 * stream writes through this, so the two paths share one builder and cannot
 * drift apart -- the picture must be identical whichever is chosen, and the
 * gate checks exactly that.
 */
static unsigned long   *triDest;

/*
 * M1p: the client's own cached buffer, and the switch that chooses it.
 *
 * `triCopyinOn` is deliberately NOT a read-once latch: M1n measured a 620 us
 * drift between one arm of a run and the next, which is larger than the effect
 * this knob is meant to show.  The only way round that is to alternate the two
 * paths inside ONE process, so the caller must be able to change it.
 */
static int triCopyinOn = -1;
static unsigned long *triCached;        /* vm_allocate'd, page aligned, touched */

int
osrdn_tri_copyin_enabled(void)
{
    if (triCopyinOn < 0) {
        const char *e = getenv(OSRDN_TRI_COPYIN_ENV);
        const OSRDNMesaProbeCaps *caps = OSRDNMesaProbeGetCaps();

        if (e != 0 && (e[0] == '0' || e[0] == '1') && e[1] == 0)
            triCopyinOn = (e[0] == '1');
        else
            /* G4-3 K4: the driver's limit outgrew its one-page window, so the path that carries a
               full batch is the copyin one -- unless the environment says otherwise */
            triCopyinOn = (caps != 0 && caps->bytes != 0UL && caps->maxWords > caps->bytes / 4UL) ? 1 : 0;
    }
    return triCopyinOn;
}

void
osrdn_tri_set_copyin(int on)
{
    triCopyinOn = on ? 1 : 0;
}

/*
 * The cached buffer.  Allocated once and TOUCHED once: a first-touch fault
 * inside a timed block would be charged to the path being measured, and the
 * review named exactly that.  vm_allocate returns page-aligned memory, which
 * is the other half of that warning.
 */
static int
triCachedReady(void)
{
    char *addr = 0;
    unsigned long i;

    if (triCached != 0)
        return 1;
    if (vm_allocate(task_self(), &addr, (int)(OSRDN_BATCH_MAX_WORDS * 4), 1) != 0)
        return 0;
    triCached = (unsigned long *)addr;
    for (i = 0UL; i < (unsigned long)OSRDN_BATCH_MAX_WORDS; i++)
        triCached[i] = 0UL;             /* prefault every page, once */
    return 1;
}

static unsigned long    triBytes;
static unsigned long    triSeed;        /* never 0, never the same twice */
static int              triSeedDone;    /* the base is read once */

/*
 * M1k: THE BATCH IN HAND.
 *
 * It lives in the mapped window, not in a buffer of its own: the prologue goes
 * down once when the first triangle arrives and the vertices are appended after
 * the two packet words, which are rewritten with the real count at flush.  So a
 * batch costs no copy and no memory, and the stream that goes out is word for
 * word the one a single triangle would have made with more vertices in it.
 */
typedef struct {
    unsigned long colourByteOff;
    int           pitchPixels;
    int           width;
    int           height;
    int           smooth;
    int           blend;
    int           tex;
    int           depth;
    unsigned long alpha;        /* G4-3 K2: the alpha code the batch was opened with */
    unsigned long texOff;       /* G4-1b: the texture the batch was opened with */
    int           texW, texH, texMag, texMin, texLevels;
    unsigned long pn;           /* prologue words -- where the first packet's words are */
    unsigned long vw;           /* words per vertex of the CURRENT segment, 5 or 7 */
    unsigned long vf;           /* and the VF_CNTL flags its prologue wants */
    unsigned long tris;         /* how many are waiting, all segments */
    /* G4-2 B2 (docs/G4_2_BATCH_PLAN.md 4): the stream is segments -- register
       pairs that differ from what the stream last wrote, a draw header, the
       triangles -- and these bound it in WORDS, the only bound the kernel has */
    unsigned long nseg;         /* segments open (the first is the prologue's) */
    unsigned long end;          /* the word after the last vertex */
    unsigned long room;         /* how many words this batch may reach */
} osrdn_tri_batch;

static osrdn_tri_batch triB;

/* G4-2 B2: one segment of the stream */
typedef struct {
    unsigned long diffAt;       /* its register pairs start here (== hdrAt for the first) */
    unsigned long hdrAt;        /* its draw header, two words */
    unsigned long tris;
    unsigned long vw, vf;
    int smooth, blend, tex, depth;      /* what the sent-log records for its triangles */
    unsigned long alpha, texOff;        /* and the rest of the state key, for a truncation */
    int texW, texH, texMag, texMin, texLevels;
} osrdn_tri_seg;

static osrdn_tri_seg triSeg[OSRDN_TRI_SEGS];
static unsigned long triScratch[OSRDN_TEX_PROLOGUE_WORDS];   /* a candidate prologue, never sent */
static void triBatchReset(void);

/* G4-1b: the current texture (OSRDNMesaTri.h osrdn_tri_texture_set).  The defaults are M1g's one
   8 x 8 texture at the window's fixed texel offset, nearest -- so a program that never sets it
   draws what M1g drew. */
static struct {
    unsigned long byteOff;
    int w, h;
    int magLinear, minCode, levels;     /* G4-4 K5: the MIN code and the resident level count */
} triTex = { OSRDN_TEX_BYTE_OFF, OSRDN_TEX_W, OSRDN_TEX_H, 0, OSRDN_TRI_MIN_NEAREST, 1 };

static unsigned long triAlpha;      /* G4-3 K2: 0 = the test is off (the template's words) */

void
osrdn_tri_alpha_set(unsigned long code)
{
    triAlpha = code;
}

void
osrdn_tri_texture_set(unsigned long byteOff, int w, int h, int magLinear, int minCode, int levels)
{
    triTex.byteOff = byteOff;
    triTex.w = w;
    triTex.h = h;
    triTex.magLinear = magLinear ? 1 : 0;
    triTex.minCode = (minCode >= 0 && minCode < OSRDN_TRI_MIN_CODES) ? minCode : -1;
    triTex.levels = levels;
}

/* G4-4 K5: the MIN field for a code, as r200SetTexFilter maps the GL filters (r200_tex.c 206-231);
   ~0 for a code this unit does not know, which the prologue refuses */
static unsigned long
triMinField(int code)
{
    switch (code) {
    case OSRDN_TRI_MIN_NEAREST:                return 0UL;
    case OSRDN_TRI_MIN_LINEAR:                 return OSRDN_TEX_TXFILTER_MIN_LINEAR;
    case OSRDN_TRI_MIN_NEAREST_MIPMAP_NEAREST: return OSRDN_TEX_TXFILTER_MIN_NEAREST_MIP_NEAREST;
    case OSRDN_TRI_MIN_NEAREST_MIPMAP_LINEAR:  return OSRDN_TEX_TXFILTER_MIN_LINEAR_MIP_NEAREST;
    case OSRDN_TRI_MIN_LINEAR_MIPMAP_NEAREST:  return OSRDN_TEX_TXFILTER_MIN_NEAREST_MIP_LINEAR;
    case OSRDN_TRI_MIN_LINEAR_MIPMAP_LINEAR:   return OSRDN_TEX_TXFILTER_MIN_LINEAR_MIP_LINEAR;
    default:                                   return ~0UL;
    }
}

static int triMipOn = -1;

/* G4-10 (docs/G4_10_MIP_SUBSTITUTE_PLAN.md 2-1): THE CODE THE CARD IS SENT.  The two level-BLENDING
   modes hang this card (docs/G4_8_REPLAY_PLAN.md 15: hw MIN 6 and 7 freeze the machine within a
   few submissions; the level-selecting modes never did in 436), so unless the knob is "all" they
   go out as the level-selecting mode with the same texel filter -- NEAREST_MIPMAP_LINEAR as
   NEAREST_MIPMAP_NEAREST, LINEAR_MIPMAP_LINEAR as LINEAR_MIPMAP_NEAREST -- a documented
   approximation, as Matrox M12 10-1 decision 2 opened its blending pair.  triTex.minCode keeps
   the GL code: level count, batch joins and the trace are about what GL asked. */
static int
triMinSent(int code)
{
    if (osrdn_tri_mip_mode() == OSRDN_TRI_MIP_ALL)
        return code;                    /* the blend values themselves: the freeze reproducer */
    if (code == OSRDN_TRI_MIN_NEAREST_MIPMAP_LINEAR)
        return OSRDN_TRI_MIN_NEAREST_MIPMAP_NEAREST;
    if (code == OSRDN_TRI_MIN_LINEAR_MIPMAP_LINEAR)
        return OSRDN_TRI_MIN_LINEAR_MIPMAP_NEAREST;
    return code;
}

int
osrdn_tri_mip_mode(void)
{
    if (triMipOn < 0) {
        const char *e = getenv(OSRDN_TRI_MIP_ENV);

        if (e != 0 && e[0] == '0' && e[1] == 0)
            triMipOn = OSRDN_TRI_MIP_OFF;
        else if (e != 0 && e[0] == 'a' && e[1] == 'l' && e[2] == 'l' && e[3] == 0)
            triMipOn = OSRDN_TRI_MIP_ALL;
        else
            triMipOn = OSRDN_TRI_MIP_MEASURED;
    }
    return triMipOn;
}

static unsigned long
triLog2(int v)
{
    unsigned long n = 0UL;
    while (v > 1) {
        v >>= 1;
        n++;
    }
    return n;
}

const osrdn_tri_counts *
OSRDNMesaTriCounts(void)
{
    return &triCounts;
}

const osrdn_tri_sent *
OSRDNMesaTriSent(void)
{
    return &triSent;
}

const osrdn_tri_failed *
OSRDNMesaTriFailed(void)
{
    return &triFailed;
}

/* M3d: keep the first failed stream.  Called right after triSubmit refused and
   BEFORE anything resets the batch, so triDest still holds what the kernel was
   offered (docs/M3D_PLAN.md 2). */
static void
triKeepFailed(unsigned long n, int w, unsigned long tris, unsigned long vw,
              int batch)
{
    unsigned long i;

    triFailed.failures++;
    if (triFailed.n != 0UL || triDest == 0 || n == 0UL)
        return;
    if (n > (unsigned long)OSRDN_TRI_FAIL_WORDS)
        n = (unsigned long)OSRDN_TRI_FAIL_WORDS;
    for (i = 0UL; i < n; i++)
        triFailed.w[i] = triDest[i];
    triFailed.reason = (unsigned long)w;
    triFailed.tris = tris;
    triFailed.vw = vw;
    triFailed.batch = (unsigned long)batch;
    triFailed.seed = triCounts.seed;
    triFailed.why = triCounts.lastWhy;
    triFailed.at = triCounts.lastAt;
    triFailed.word = triCounts.lastWord;
    triFailed.status = triCounts.lastStatus;
    triFailed.n = n;
}

const char *
OSRDNMesaTriWhyName(int why)
{
    static const char *names[OSRDN_TRI_REASONS] = {
        "-", "NO_ACCEL", "NOT_RUNNING", "NO_WINDOW", "ARGS",
        "IOCTL", "REFUSED", "NOT_DRAWN", "BATCH_OPEN"
    };

    if (why < 0 || why >= OSRDN_TRI_REASONS)
        return "?";
    return names[why];
}

/*
 * Open the node for one call.  Every caller closes it again before returning,
 * because the driver's latch lets exactly one holder exist at a time.
 */
static int triHoldOn = -1;
static int triHeldFd = -1;
static int triHoldProg;                 /* G3: held by PresentMode(1), not by the environment */

int
osrdn_tri_hold_enabled(void)
{
    if (triHoldOn < 0) {
        const char *e = getenv(OSRDN_TRI_HOLD_ENV);

        triHoldOn = (e != 0 && e[0] == '1' && e[1] == 0) ? 1 : 0;
    }
    return triHoldOn || triHoldProg;
}

/* G3 (docs/G3_PRESENT_PLAN.md 2-2): the present rows and the triangles share
   ONE descriptor while a frame is being stamped -- the driver logs every open
   and admits one holder (OSRDNDisplay.m 176-216).  Off closes what was held,
   unless the environment holds it too. */
void
osrdn_tri_hold_set(int on)
{
    triHoldProg = on ? 1 : 0;
    if (!on && triHoldOn != 1 && triHeldFd >= 0) {
        (void)close(triHeldFd);
        triHeldFd = -1;
    }
}

static int
triOpen(void)
{
    int fd;

    if (osrdn_tri_hold_enabled() && triHeldFd >= 0)
        return triHeldFd;               /* already ours; opens is not bumped */
    fd = open(NODE, NODE_RDWR);
    if (fd >= 0) {
        triCounts.opens++;
        if (osrdn_tri_hold_enabled())
            triHeldFd = fd;
    }
    return fd;
}

/* the other half: a held descriptor is not closed until the surface goes */
static void
triClose(int fd)
{
    if (fd < 0)
        return;
    if (osrdn_tri_hold_enabled() && fd == triHeldFd)
        return;
    (void)close(fd);
}

/* the present path's way in: the same open, the same hold */
int
osrdn_tri_device_open(void)
{
    return triOpen();
}

void
osrdn_tri_device_close(int fd)
{
    triClose(fd);
}

/*
 * G5-2 (docs/G5_2_ASYNC_SUBMIT_PLAN.md 2-4).  Asked once: RETIRE is the probe as well as
 * the wait -- a kernel without it answers ENOTTY and this process stays synchronous.  The
 * mapped-window path (SUBMIT) is not affected; only the copyin path has a SUBMIT3.
 */
static int triAsyncOn = -1;
static int triInflight;

static int
triRetireIoctl(osrdn_r7b_retire *rb)
{
    int fd, rc;

    rb->magic = OSRDN_RETIRE_MAGIC;
    rb->version = OSRDN_RETIRE_VERSION;
    rb->status = ~0UL;
    rb->us = 0UL;
    rb->lost = 0UL;
    if ((fd = triOpen()) < 0)
        return -1;
    rc = ioctl(fd, (int)OSRDN_R7B_IOC_RETIRE, (char *)rb);
    triClose(fd);
    return (rc == 0 && rb->status == 0UL) ? 0 : -1;
}

int
osrdn_tri_async(void)
{
    if (triAsyncOn < 0) {
        const char *e = getenv(OSRDN_TRI_SYNC_ENV);
        osrdn_r7b_retire rb;

        triAsyncOn = 0;
        if (!(e != 0 && e[0] == '1' && e[1] == 0) && osrdn_tri_copyin_enabled() &&
            triRetireIoctl(&rb) == 0)
            triAsyncOn = 1;
        triCounts.async = (unsigned long)triAsyncOn;
    }
    return triAsyncOn;
}

int
osrdn_tri_retire_if_inflight(void)
{
    osrdn_r7b_retire rb;
    int ok;

    if (!triInflight) {
        triCounts.retiresSkipped++;
        return 1;
    }
    ok = (triRetireIoctl(&rb) == 0);
    /* either way nothing of ours is in flight any more: drawn, or thrown away by the
       kernel's recovery (which the next submission's refusal will also say) */
    triInflight = 0;
    triCounts.retires++;
    triCounts.retireUs += rb.us;
    triCounts.lost = rb.lost;
    if (!ok)
        triCounts.retireFailed++;
    return ok;
}

/* Map the batch window.  Once, ever: the counter is what the gate reads. */
static int
triMap(void)
{
    const OSRDNMesaProbeCaps *caps = OSRDNMesaProbeGetCaps();
    char *addr = 0;
    int fd;

    if (triWindow != 0)
        return 1;
    if (caps->bytes == 0UL || caps->maxWords < (unsigned long)MAX_WORDS)
        return 0;
    if ((fd = triOpen()) < 0)
        return 0;
    /* 4.2BSD mmap has no MAP_FIXED: the place is taken first (R4c, and the
       Matrox probe records the same discovery). */
    if (vm_allocate(task_self(), &addr, (int)caps->bytes, 1) != 0) {
        triClose(fd);
        return 0;
    }
    if (mmap(addr, (int)caps->bytes, PROT_RW, MAP_SHARED_, fd,
             (long)caps->window) == (char *)-1) {
        triClose(fd);
        return 0;
    }
    triClose(fd);
    triWindow = (unsigned long *)addr;
    triBytes = caps->bytes;
    triCounts.maps++;
    return 1;
}

void
osrdn_tri_release(void)
{
    /* The mapping is left in place and forgotten, as the surface's is: this
       system's mmap put it over memory we vm_allocated and a later triangle may
       want the same window.  What the gate counts is that only one was ever
       made. */
    if (triHeldFd >= 0) {
        (void)close(triHeldFd);
        triHeldFd = -1;
    }
    triWindow = 0;
    triBytes = 0UL;
    /* M1k: a batch that outlived its window would append through a null
       pointer.  Dropping it here is safe because the only caller releases at
       the end of a surface's life, when nothing is waiting. */
    triBatchReset();
}

/*
 * Lay the stream into the window.  Returns the word count, or 0 if the
 * arguments cannot be expressed -- which is a refusal, not a silent clamp.
 */
/* Choose the destination for the stream about to be built.  0 if neither is
   available, which the caller turns into a refusal rather than a silent skip. */
static int
triPick(void)
{
    if (osrdn_tri_copyin_enabled()) {
        if (!triCachedReady())
            return 0;
        triDest = triCached;
        return 1;
    }
    if (!triMap())
        return 0;
    if ((unsigned long)MAX_WORDS * 4UL > triBytes)
        return 0;
    triDest = triWindow;
    return 1;
}

static unsigned long
triPrologueTo(unsigned long *dst, unsigned long colourByteOff, int pitchPixels,
              int width, int height, int smooth, int blend, int tex, int depth)
{
    const OSRDNMesaProbeCaps *caps = OSRDNMesaProbeGetCaps();
    const unsigned long *pro = tex ? osrdnTexPrologue : osrdnTriPrologue;
    const unsigned char *slt = tex ? osrdnTexSlot : osrdnTriSlot;
    unsigned long pn = tex ? (unsigned long)OSRDN_TEX_PROLOGUE_WORDS
                           : (unsigned long)OSRDN_TRI_PROLOGUE_WORDS;
    unsigned long n = 0UL;
    unsigned long i;

    if (width <= 0 || height <= 0 || width > 0x4000 || height > 0x4000)
        return 0UL;
    if (pitchPixels <= 0 || pitchPixels > 0x1ff8)
        return 0UL;
    /*
     * M3h: THE WINDOW IS LAID OUT FOR THE LARGEST SURFACE (docs/M3H_PLAN.md 4),
     * colour at 0, depth at OSRDN_TRI_DEPTH_BYTE_OFF, the texels after it --
     * so a surface is taken when it fits that layout and refused as ARGS (the
     * hook draws it in software) when it does not.  M3a refused any depth-tested
     * surface past 64 x 64, because the depth pitch was fixed at 64.
     *
     * The pitch goes to the card masked to whole 8-pixel steps (R200's
     * COLORPITCH_MASK), so a pitch that is not one would be drawn at a different
     * stride than the rows were laid out with.  The kernel refuses a clip wider
     * than the pitch; ours is the surface width, which the pitch is.
     *
     * HERE and not in the classifier, for the reasons M3a found
     * (docs/M3A_PLAN.md 11): every send, single or batched, comes through this
     * function with the size and depth of the moment it draws, and a refusal
     * here refuses every triangle of the frame, so it stays on one side.
     */
    if (width > OSRDN_TRI_SURF_MAX_W || height > OSRDN_TRI_SURF_MAX_H ||
        pitchPixels > OSRDN_TRI_SURF_MAX_W || (pitchPixels & 7) != 0 ||
        width > pitchPixels)
        return 0UL;
    if (colourByteOff > (unsigned long)OSRDN_TRI_DEPTH_BYTE_OFF -
                        (unsigned long)pitchPixels * 4UL * (unsigned long)height)
        return 0UL;
    if (caps->winStart == 0UL)
        return 0UL;
    if (caps->winStart > 0xffffffffUL - colourByteOff)
        return 0UL;

    for (i = 0UL; i < pn; i++) {
        switch (slt[i]) {
        case OSRDN_TRI_SLOT_COLOROFFSET:
            dst[n] = caps->winStart + colourByteOff;
            break;
        case OSRDN_TRI_SLOT_COLORPITCH:
            dst[n] = (unsigned long)pitchPixels;
            break;
        case OSRDN_TRI_SLOT_WIDTH_HEIGHT:
            dst[n] = (((unsigned long)height - 1UL) << 16) |
                           ((unsigned long)width - 1UL);
            break;
        case OSRDN_TRI_SLOT_TOP_LEFT:
            dst[n] = 0UL;
            break;
        case OSRDN_TRI_SLOT_SE_CNTL:
            dst[n] = smooth ? OSRDN_TRI_SE_CNTL_GOURAUD
                                  : OSRDN_TRI_SE_CNTL_FLAT;
            break;
        case OSRDN_TRI_SLOT_RB3D_CNTL:
            dst[n] = (blend ? OSRDN_TRI_RB3D_CNTL_BLEND
                                  : OSRDN_TRI_RB3D_CNTL_PLAIN) |
                           (depth ? OSRDN_TRI_RB3D_CNTL_Z : 0UL);
            break;
        case OSRDN_TRI_SLOT_BLENDCNTL:
            /* G4-1a: the pair by its code (OSRDNMesaClass.c osrdn_class_blend_code) */
            dst[n] = (blend == OSRDN_TRI_BLEND_SRCA) ? OSRDN_TRI_BLENDCNTL_SRCA
                       : (blend == OSRDN_TRI_BLEND_ZERO_OMSC) ? OSRDN_TRI_BLENDCNTL_ZERO_OMSC
                       : (blend == OSRDN_TRI_BLEND_ONE_ONE) ? OSRDN_TRI_BLENDCNTL_ONE_ONE
                       : OSRDN_TRI_BLENDCNTL_OFF;
            break;
        case OSRDN_TRI_SLOT_TXCBLEND:
            dst[n] = (tex == OSRDN_TRI_TEX_MODULATE) ? OSRDN_TEX_TXCBLEND_MODULATE
                                                         : OSRDN_TEX_TXCBLEND_REPLACE;
            break;
        case OSRDN_TRI_SLOT_TXABLEND:
            dst[n] = (tex == OSRDN_TRI_TEX_MODULATE) ? OSRDN_TEX_TXABLEND_MODULATE
                                                         : OSRDN_TEX_TXABLEND_REPLACE;
            break;
        case OSRDN_TRI_SLOT_TXOFFSET:
            dst[n] = caps->winStart + triTex.byteOff;      /* G4-1b: the resident image's place */
            break;
        case OSRDN_TRI_SLOT_TXFORMAT:
            dst[n] = OSRDN_TEX_TXFORMAT_ARGB |
                         (triLog2(triTex.w) << OSRDN_TEX_TXFORMAT_WIDTH_SHIFT) |
                         (triLog2(triTex.h) << OSRDN_TEX_TXFORMAT_HEIGHT_SHIFT);
            break;
        case OSRDN_TRI_SLOT_TXFILTER:
            /* G4-4 K5: the MIN field from the code, and MAX_MIP_LEVEL = levels - 1 (r200_texstate.c
               338-339); a mip code with one level, an unknown code, or more levels than the field
               holds is refused at the prologue (0 words), never sent half right */
            if (tex && (triMinField(triMinSent(triTex.minCode)) == ~0UL || triTex.levels < 1 ||
                        triTex.levels > OSRDN_TEX_MAX_LEVELS ||
                        (triTex.minCode >= OSRDN_TRI_MIN_MIP_FIRST && triTex.levels < 2)))
                return 0UL;
            dst[n] = OSRDN_TEX_TXFILTER_WRAP_NEAREST |
                         (triTex.magLinear ? OSRDN_TEX_TXFILTER_MAG_LINEAR : 0UL) |
                         triMinField(triMinSent(triTex.minCode)) |        /* G4-10: blend -> select */
                         (((unsigned long)triTex.levels - 1UL) << OSRDN_TEX_TXFILTER_MAX_MIP_SHIFT);
            break;
        case OSRDN_TRI_SLOT_TXSIZE:
            dst[n] = ((unsigned long)triTex.w - 1UL) | (((unsigned long)triTex.h - 1UL) << 16);
            break;
        case OSRDN_TRI_SLOT_TXPITCH:
            dst[n] = (unsigned long)triTex.w * 4UL - 32UL;     /* rows are w x 4 bytes; w >= 8 */
            break;
        /* G4-3 K2: the alpha test -- the template's PP_CNTL word with the enable bit when a code is
           set, and PP_MISC as r200AlphaFunc writes it (ref byte | compare << 8) */
        case OSRDN_TRI_SLOT_PP_CNTL:
            dst[n] = pro[i] | (triAlpha ? OSRDN_ALPHA_ENABLE : 0UL);
            break;
        case OSRDN_TRI_SLOT_PP_MISC:
            dst[n] = triAlpha ? (OSRDN_TRI_ALPHA_REF(triAlpha) |
                                     (OSRDN_TRI_ALPHA_OP(triAlpha) << OSRDN_ALPHA_OP_SHIFT)) : 0UL;
            break;
        /*
         * M1i.  The driver's prefix has already pointed the depth buffer at its
         * own offset, which for a client stream is 0 -- on top of the colour
         * surface (docs/M1D_PLAN.md 4d).  These three words come AFTER that
         * prefix in the same submission, so they are what moves it and turns it
         * on.  Depth OFF is the table's own literal, so a stream built with
         * depth = 0 is word for word the one M1d..M1h sent.
         */
        case OSRDN_TRI_SLOT_ZSTENCILCNTL:
            /* G4-1a: the measured LESS word with its compare field and write bit replaced by the
               code's (OSRDN_TRI_DEPTH_ZTEST / _WRITE); every other bit -- the 16-bit format, the
               stencil fields -- stays what R6 measured */
            dst[n] = depth ? ((OSRDN_TRI_ZSTENCIL_LESS &
                                   ~(OSRDN_TRI_ZSTENCIL_TEST_MASK | OSRDN_TRI_ZSTENCIL_WRITE)) |
                                  (OSRDN_TRI_DEPTH_ZTEST(depth) << OSRDN_TRI_ZSTENCIL_TEST_SHIFT) |
                                  (OSRDN_TRI_DEPTH_WRITE(depth) ? OSRDN_TRI_ZSTENCIL_WRITE : 0UL))
                               : OSRDN_TRI_ZSTENCIL_OFF;
            break;
        case OSRDN_TRI_SLOT_DEPTHOFFSET:
            dst[n] = caps->winStart + OSRDN_TRI_DEPTH_BYTE_OFF;
            break;
        case OSRDN_TRI_SLOT_DEPTHPITCH:
            /* M3h: the surface width in whole 32-pixel tiles, as the
               reference sizes a tiled depth buffer and the kernel requires */
            dst[n] = ((unsigned long)width + 31UL) & ~31UL;
            break;
        default:
            dst[n] = pro[i];
            break;
        }
        n++;
    }

    return n;
}

static unsigned long
triPrologue(unsigned long colourByteOff, int pitchPixels, int width, int height,
            int smooth, int blend, int tex, int depth)
{
    return triPrologueTo(triDest, colourByteOff, pitchPixels, width, height,
                         smooth, blend, tex, depth);
}

/*
 * The whole stream for ONE triangle: the prologue, then a draw packet with
 * three vertices in it.  M1k's batch builds the same thing with more vertices
 * in the one packet, which is why the packet words are written in one place.
 */
static void
triDrawPacket(unsigned long pn, unsigned long vf, unsigned long vw,
              unsigned long tris)
{
    unsigned long nv = tris * 3UL;

    triDest[pn] = OSRDN_TRI_DRAW_HDR_BASE | ((nv * vw) << 16);
    triDest[pn + 1UL] = vf | (nv << 16);
}

static unsigned long
triBuild(unsigned long colourByteOff, int pitchPixels, int width, int height,
         const unsigned long *vtx, int smooth, int blend, int tex, int depth)
{
    unsigned long vw = tex ? (unsigned long)OSRDN_TEX_VERTEX_WORDS
                           : (unsigned long)OSRDN_TRI_VERTEX_WORDS;
    unsigned long vf = tex ? OSRDN_TEX_VF_CNTL_FLAGS : OSRDN_TRI_VF_CNTL_FLAGS;
    unsigned long n = triPrologue(colourByteOff, pitchPixels, width, height,
                                  smooth, blend, tex, depth);
    unsigned long i;

    if (n == 0UL)
        return 0UL;
    triDrawPacket(n, vf, vw, 1UL);          /* one triangle */
    n += 2UL;
    for (i = 0UL; i < (unsigned long)TRI_VERTS * vw; i++)
        triDest[n++] = vtx[i];
    return n;
}

void
osrdn_tri_vertex(unsigned long *vtx, int i, int tex,
                 unsigned long x, unsigned long y, unsigned long z,
                 unsigned long w, unsigned long col,
                 unsigned long s, unsigned long t)
{
    unsigned long *v;

    if (vtx == 0 || i < 0 || i >= TRI_VERTS)
        return;
    /* M1t: the slots are spelled out in ONE place now -- the header's macro --
       because the hook's inline path writes the same ones. */
    v = OSRDN_TRI_VERTEX_AT(vtx, i, tex);
    OSRDN_TRI_VERTEX_PUT(v, tex, x, y, z, w, col, s, t);
}


/*
 * Seed, submit, read the verdict.  Returns OSRDN_TRI_OK or the reason.
 *
 * Nothing here knows how many triangles rode in the stream: one and a hundred
 * are the same ioctl, which is the whole of M1k on this side.
 */
static int triPoisonOn = -1;

int
osrdn_tri_poison_enabled(void)
{
    if (triPoisonOn < 0) {
        const char *e = getenv(OSRDN_TRI_POISON_ENV);

        triPoisonOn = (e != 0 && e[0] == '1' && e[1] == 0) ? 1 : 0;
    }
    return triPoisonOn;
}

/*
 * G4-6: the submission trace (OSRDNMesaTri.h, OSRDN_TRI_TRACE_ENV).  The ONLY function in the
 * accelerated sources that calls write(): it writes to the two files the environment names and
 * to nothing else, and only when they are named (check_hook: g46-trace).
 *
 * A summary line is hex words: seq, stream words, triangles, segments, depth code, blend code, then
 * five per segment -- texture offset, (w << 16) | h, the MIN code, the levels, the triangles.  THE
 * MIN CODE IS GL's (osrdn_class_min_code), NOT WHAT THE CARD GOT: under the default knob the two
 * blended mip codes 4 and 5 go to the card as 2 and 3 (triMinSent, G4-10); only RDNMesaMip=all
 * sends them as they are.  (G5-4 8f: G4-10 said this note lived in a `cpdec.py` that was never
 * committed; this is where a reader of the trace looks.)
 */
static int triTraceFd = -2, triTraceLastFd = -2;
static unsigned long triTraceSeq;

static int
triTraceHex(char *p, unsigned long v)
{
    static const char hx[] = "0123456789abcdef";
    int i;

    for (i = 7; i >= 0; i--)
        p[7 - i] = hx[(v >> (i * 4)) & 15UL];
    p[8] = ' ';
    return 9;
}

static int triTraceDepthOnly = 0;

static void
triTrace(unsigned long n)
{
    char line[9 * (6 + 5 * 24) + 2];
    int k = 0;
    unsigned long g;

    if (triTraceFd == -2) {
        const char *e = getenv(OSRDN_TRI_TRACE_ENV), *l = getenv(OSRDN_TRI_TRACE_LAST_ENV);

        triTraceFd = (e != 0 && e[0] != 0) ? open(e, TRACE_OPEN_FLAGS, 0644) : -1;
        triTraceLastFd = (l != 0 && l[0] != 0) ? open(l, TRACE_OPEN_FLAGS, 0644) : -1;
        triTraceDepthOnly = (getenv("RDNMesaTraceLastDepth") != 0) ? 1 : 0;
    }
    if (triTraceFd >= 0) {
        k += triTraceHex(line + k, ++triTraceSeq);
        k += triTraceHex(line + k, n);
        k += triTraceHex(line + k, triB.tris);
        k += triTraceHex(line + k, triB.nseg);
        k += triTraceHex(line + k, (unsigned long)triB.depth);    /* G4-10: the batch's depth code (0 = off) */
        k += triTraceHex(line + k, (unsigned long)triB.blend);    /* G4-10: and its blend code */
        for (g = 0UL; g < triB.nseg && g < 24UL; g++) {
            k += triTraceHex(line + k, triSeg[g].tex ? triSeg[g].texOff : 0UL);
            k += triTraceHex(line + k, ((unsigned long)triSeg[g].texW << 16) | (unsigned long)triSeg[g].texH);
            k += triTraceHex(line + k, (unsigned long)triSeg[g].texMin);
            k += triTraceHex(line + k, (unsigned long)triSeg[g].texLevels);
            k += triTraceHex(line + k, triSeg[g].tris);
        }
        line[k++] = '\n';
        (void) write(triTraceFd, line, (unsigned int)k);
        (void) fsync(triTraceFd);
    }
    /* G4-10 diagnosis: with RDNMesaTraceLastDepth set, only a submission whose batch has a depth code is
       kept as the last stream -- the last stream of a frame is otherwise the 2D pass */
    if (triTraceLastFd >= 0 && triDest != 0 && (triTraceDepthOnly == 0 || triB.depth != 0)) {
        (void) lseek(triTraceLastFd, 0L, 0);
        (void) write(triTraceLastFd, (const void *)triDest, (unsigned int)(n * 4UL));
        /* G5-4 (docs/G5_4_READPIX_AND_CLEANUP_PLAN.md 2-1): and cut to it -- a shorter stream over a
           longer one left the old tail behind (trace-g411-last.bin: 4,064 words, the stream 4,057) */
        (void) ftruncate(triTraceLastFd, (long)(n * 4UL));
        (void) fsync(triTraceLastFd);
    }
}

static int
triSubmit(unsigned long n)
{
    osrdn_r7b_submit sb;
    int w = OSRDN_TRI_OK;
    int fd, rc;

    /* M1m Q3: make the kernel refuse at word 0, so the submission carries the
       driver's fixed path and its log and nothing else. */
    if (osrdn_tri_poison_enabled() && triDest != 0)
        triDest[0] = 0xffffffffUL;

    /* A repeated seed would let a stale read-back pass for a fresh one, so the
       kernel refuses one (CP_WHY_SEED).  Zero is not a seed either, and neither
       is a counter that restarts at 1 in every process -- see the header. */
    if (!triSeedDone) {
        const char *e = getenv(OSRDN_TRI_SEED_ENV);

        triSeedDone = 1;
        if (e != 0) {
            while (*e >= '0' && *e <= '9') {
                triSeed = triSeed * 10UL + (unsigned long)(*e - '0');
                e++;
            }
        } else {
            /*
             * REL1 B8 (docs/REL1_PACKAGING_PLAN.md 16): unset -- which is every
             * program a user runs -- the start comes from the clock, not 0.  The
             * kernel refuses only a seed EQUAL to the previous submission's, and
             * two processes that both counted from 1 met exactly there whenever
             * the first had submitted once.  Kept between 65536 and 1000065535
             * (below 2^30) so the increment below cannot wrap to 0 and back to
             * 1 in any process.  Decimal on purpose: a long hex constant in this
             * unit reads as a card address to check_hook's m1d-tri-pure.
             */
            struct osrdn_tri_timeval tv;

            tv.sec = 0L;
            tv.usec = 0L;
            (void)gettimeofday(&tv, 0);
            triSeed = 65536UL + ((((unsigned long)tv.sec * 1000003UL) ^ (unsigned long)tv.usec)
                                 % 1000000000UL);
        }
    }
    triSeed++;
    if (triSeed == 0UL)
        triSeed = 1UL;
    triCounts.seed = triSeed;

    triTrace(n);                            /* G4-6: on the host before the card sees it */
    if (osrdn_tri_copyin_enabled()) {
        osrdn_r7b_submit2 s2;

        s2.magic = OSRDN_R7B_MAGIC;
        s2.version = OSRDN_R7B_VERSION;
        s2.nwords = n;
        s2.seed = triSeed;
        s2.words = (unsigned long)triDest;      /* our own cached buffer */
        s2.status = 0UL;
        s2.why = 0UL;
        s2.at = 0UL;
        s2.word = 0UL;
        s2.drawn = 0UL;
        {
            int async = osrdn_tri_async();      /* G5-2: asks RETIRE once, before the node is ours here */

            if ((fd = triOpen()) < 0)
                return OSRDN_TRI_IOCTL;
            {
            osrdn_time_stamp t;
            int timed = osrdn_time_on();        /* G5-0: the ioctl alone */

            if (timed)
                osrdn_time_now(&t);
            rc = ioctl(fd, async ? (int)OSRDN_R7B_IOC_SUBMIT3 : (int)OSRDN_R7B_IOC_SUBMIT2, (char *)&s2);
            if (timed) {
                osrdn_time_add(OSRDN_TIME_SUBMIT, &t);
                osrdn_time_count(OSRDN_TIME_SUBMIT, n);
            }
            }
            triClose(fd);
            /* G5-2: an accepted batch is on the ring until a RETIRE; a failure while one is
               there may have taken it with it (the kernel counts which, `lost`) */
            if (async) {
                if (rc == 0 && s2.status == 0UL && s2.why == 0UL && s2.drawn != 0UL) {
                    triInflight = 1;
                    triCounts.asubmits++;
                } else if (triInflight) {
                    triCounts.lateLatch++;
                    triInflight = 0;
                }
            }
        }
        triCounts.words = n;
        if (rc != 0) {
            triCounts.lastWhy = ~0UL;
            triCounts.lastAt = ~0UL;
            triCounts.lastWord = 0UL;
            triCounts.lastStatus = ~0UL;
            return OSRDN_TRI_IOCTL;
        }
        triCounts.lastWhy = s2.why;
        triCounts.lastAt = s2.at;
        triCounts.lastWord = s2.word;
        triCounts.lastStatus = s2.status;
        if (s2.status != 0UL || s2.why != 0UL)
            return OSRDN_TRI_REFUSED;
        if (s2.drawn == 0UL)
            return OSRDN_TRI_NOT_DRAWN;
        return OSRDN_TRI_OK;
    }

    sb.magic = OSRDN_R7B_MAGIC;
    sb.version = OSRDN_R7B_VERSION;
    sb.nwords = n;
    sb.seed = triSeed;
    sb.status = 0UL;
    sb.why = 0UL;
    sb.at = 0UL;
    sb.word = 0UL;
    sb.drawn = 0UL;

    if ((fd = triOpen()) < 0)
        return OSRDN_TRI_IOCTL;
    {
        osrdn_time_stamp t;
        int timed = osrdn_time_on();            /* G5-0: the ioctl alone */

        if (timed)
            osrdn_time_now(&t);
        rc = ioctl(fd, (int)OSRDN_R7B_IOC_SUBMIT, (char *)&sb);
        if (timed) {
            osrdn_time_add(OSRDN_TIME_SUBMIT, &t);
            osrdn_time_count(OSRDN_TIME_SUBMIT, n);
        }
    }
    triClose(fd);

    triCounts.words = n;

    /*
     * A 4.3BSD ioctl copies the block back only when the handler returns zero
     * (osrdn_r7b.h).  So on a non-zero rc the answer fields still hold what WE
     * put there -- all zeroes -- and copying them into the counters would log
     * "why=0", which reads as "no refusal".  The first draft of this function
     * did exactly that.  Record a sentinel instead, and only believe the block
     * when the kernel actually wrote it.
     */
    if (rc != 0) {
        triCounts.lastWhy = ~0UL;
        triCounts.lastAt = ~0UL;
        triCounts.lastWord = 0UL;
        triCounts.lastStatus = ~0UL;
        w = OSRDN_TRI_IOCTL;
    } else {
        triCounts.lastWhy = sb.why;
        triCounts.lastAt = sb.at;
        triCounts.lastWord = sb.word;
        triCounts.lastStatus = sb.status;
        if (sb.status != 0UL || sb.why != 0UL)
            w = OSRDN_TRI_REFUSED;
        else if (sb.drawn == 0UL)
            w = OSRDN_TRI_NOT_DRAWN;
    }
    return w;
}

/*
 * Write down ONE triangle that has really gone.  Called once per triangle, so
 * `submitted` and the sent ring count triangles whether they rode alone or in a
 * batch -- which is why every equality the host gates on survives M1k.
 *
 * A triangle that was refused was never drawn by the card, and putting it in
 * this ring would make the host predict a picture nobody asked for.
 */
static int triSentLogOn = -1;

int
osrdn_tri_sentlog_enabled(void)
{
    if (triSentLogOn < 0) {
        const char *e = getenv(OSRDN_TRI_SENTLOG_ENV);

        triSentLogOn = (e != 0 && e[0] == '0' && e[1] == 0) ? 0 : 1;
    }
    return triSentLogOn;
}

static int triGroupOn = -1;

int
osrdn_tri_group_enabled(void)
{
    if (triGroupOn < 0) {
        const char *e = getenv(OSRDN_TRI_GROUP_ENV);

        triGroupOn = (e != 0 && e[0] == '1' && e[1] == 0) ? 1 : 0;
    }
    return triGroupOn;
}

static int triInlineOn = -1;

int
osrdn_tri_inline_enabled(void)
{
    if (triInlineOn < 0) {
        const char *e = getenv(OSRDN_TRI_INLINE_ENV);

        triInlineOn = (e != 0 && e[0] == '1' && e[1] == 0) ? 1 : 0;
    }
    return triInlineOn;
}

static int triNullSendOn = -1;

int
osrdn_tri_nullsend_enabled(void)
{
    if (triNullSendOn < 0) {
        const char *e = getenv(OSRDN_TRI_NULLSEND_ENV);

        triNullSendOn = (e != 0 && e[0] == '1' && e[1] == 0) ? 1 : 0;
    }
    return triNullSendOn;
}

static void
triRecord(const unsigned long *v, unsigned long vw, int smooth, int blend,
          int tex, int depth)
{
    unsigned long nw = 3UL * vw;
    int i;

    /*
     * M1r.  Twenty-one words a triangle, and nothing outside a gate run reads
     * them.  THE COUNTERS BELOW STILL RUN -- they are what the gates count --
     * so turning the ring off changes what is REMEMBERED, never what is sent.
     * With it off `triSent.n` stays 0, so `sent()` prints no rows and a judge
     * that wants vertices fails instead of reading a stale ring.
     */
    if (osrdn_tri_sentlog_enabled()) {
        for (i = 0; i < OSRDN_TRI_LOG_WORDS; i++)
            triSent.v[triSent.n % (unsigned long)OSRDN_TRI_LOG][i] =
                ((unsigned long)i < nw) ? v[i] : 0UL;
        triSent.words = nw;
        triSent.n++;
    }

    triCounts.submitted++;
    if (smooth)
        triCounts.smoothSent++;
    if (blend)
        triCounts.blendSent++;
    if (tex)
        triCounts.texSent++;
    if (depth)
        triCounts.depthSent++;
}

int
osrdn_tri_send(unsigned long colourByteOff, int pitchPixels,
               int width, int height, const unsigned long *vtx,
               int smooth, int blend, int tex, int depth, int *why)
{
    unsigned long n = 0UL;
    int w = OSRDN_TRI_OK;

    triCounts.entered++;

    if (OSRDNMesaProbeRun() != OSRDN_PROBE_HARDWARE)
        /* The probe folds "the CP is not running" into its own verdict, so a
           NOT_RUNNING of ours would only ever be reached if that changed. */
        w = OSRDN_TRI_NO_ACCEL;
    else if (vtx == 0)
        w = OSRDN_TRI_ARGS;
    else if (triB.tris != 0UL)
        /* the window already holds a batch; writing over it would lose every
           triangle in it silently */
        w = OSRDN_TRI_BATCH_OPEN;
    else if (!triPick())
        w = OSRDN_TRI_NO_WINDOW;
    else if ((n = triBuild(colourByteOff, pitchPixels, width, height, vtx,
                           smooth, blend, tex, depth)) == 0UL)
        w = OSRDN_TRI_ARGS;

    if (w != OSRDN_TRI_OK) {
        triCounts.refused[w]++;
        if (why != 0)
            *why = w;
        return 0;
    }

    w = triSubmit(n);
    if (w != OSRDN_TRI_OK) {
        triKeepFailed(n, w, 1UL, tex ? (unsigned long)OSRDN_TEX_VERTEX_WORDS
                                     : (unsigned long)OSRDN_TRI_VERTEX_WORDS, 0);
        triCounts.refused[w]++;
        if (why != 0)
            *why = w;
        return 0;
    }
    triRecord(vtx, tex ? (unsigned long)OSRDN_TEX_VERTEX_WORDS
                       : (unsigned long)OSRDN_TRI_VERTEX_WORDS,
              smooth, blend, tex, depth);
    if (why != 0)
        *why = OSRDN_TRI_OK;
    return 1;
}

/*
 * How many WORDS a batch may reach.
 *
 * NOT a constant out of the header: the header's number sizes the arrays, and
 * the real bound is whatever the DRIVER says it will take (caps->maxWords) and
 * whatever the window is big enough for, whichever is smaller.  A number typed
 * here would be a second opinion about the kernel's limit, and the two would
 * drift.  G4-2 B2 made it words rather than triangles: with segments of two
 * vertex widths in one stream there is no one triangle count to bound.
 */
static long triBatchCap = -1L;             /* G5-5: -1 not read yet, 0 none, else the cap */

static unsigned long
triRoomWords(void)
{
    const OSRDNMesaProbeCaps *caps = OSRDNMesaProbeGetCaps();
    unsigned long room = caps->maxWords;

    /* G4-4 K8 (docs/G4_4_KERNEL_PLAN.md 2): the copyin path takes maxWords whole -- the
       version 2 kernel copies it in chunks through its page (a version 1 kernel refused a
       stream past the page as "count" while advertising 4068, which G4-2's first hardware run
       found; the probe refuses any other version, so this unit never meets one).  The mapped
       window path sends FROM the page, so the page bounds it, and so does our own mapping. */
    if (!osrdn_tri_copyin_enabled() && triBytes / 4UL < room)
        room = triBytes / 4UL;              /* what we mapped is the page it sends from */
    /* G5-5 (docs/G5_5_BATCH_SIZE_PLAN.md 2): RDNMesaBatchWords=N makes batches smaller so more than
       one fits in the ring.  Only ever LOWER; below 256 words (the largest first triangle is
       60 + 2 + 3 x 7 = 83) it is ignored and says so in RDN-A */
    if (triBatchCap < 0L) {
        const char *e = getenv(OSRDN_TRI_BATCH_WORDS_ENV);
        unsigned long v = 0UL;

        while (e != 0 && *e >= '0' && *e <= '9' && v < 100000UL) {
            v = v * 10UL + (unsigned long)(*e - '0');
            e++;
        }
        triBatchCap = (v >= 256UL) ? (long) v : 0L;
        triCounts.batchCap = (unsigned long) triBatchCap;
        triCounts.batchCapIgnored = (v != 0UL && v < 256UL) ? v : 0UL;
    }
    if (triBatchCap > 0L && (unsigned long) triBatchCap < room)
        room = (unsigned long) triBatchCap;
    return room;
}

static void
triBatchReset(void)
{
    triB.tris = 0UL;
    triB.nseg = 0UL;
    triB.end = 0UL;
    triB.room = 0UL;
}

/*
 * M1l.  Read once: getenv on every triangle would put a libc call in the path
 * being measured, which is the mistake the Matrox work recorded as "the
 * instrument taxes whichever arm it is heavier on".
 */
static int triBatchOn = -1;

int
osrdn_tri_batch_enabled(void)
{
    if (triBatchOn < 0) {
        const char *e = getenv(OSRDN_TRI_BATCH_ENV);

        triBatchOn = (e != 0 && e[0] == '0' && e[1] == 0) ? 0 : 1;
    }
    return triBatchOn;
}

unsigned long
osrdn_tri_batch_count(void)
{
    return triB.tris;
}

/*
 * G4-2 B2: THE STATE KEY.  Every field picks a word in the prologue (see
 * triPrologueTo), so two states with different keys are two different
 * prologues.  The SURFACE fields (colourByteOff, pitch, width, height) are not
 * here: the verifier judges the surface registers once, by their LAST value
 * in the stream (osrdn_cp.m cpR7Verify, after the loop), so a stream never
 * changes them -- a different surface is a different batch.
 */
static int
triSameState(int smooth, int blend, int tex, int depth)
{
    return (triB.smooth == smooth && triB.blend == blend &&
            triB.tex == tex && triB.depth == depth && triB.alpha == triAlpha &&
            (tex == 0 || (triB.texOff == triTex.byteOff && triB.texW == triTex.w && triB.texH == triTex.h &&
                          triB.texMag == triTex.magLinear && triB.texMin == triTex.minCode &&
                          triB.texLevels == triTex.levels))) ? 1 : 0;
}

static int
triSameSurface(unsigned long colourByteOff, int pitchPixels, int width, int height)
{
    return (triB.colourByteOff == colourByteOff && triB.pitchPixels == pitchPixels &&
            triB.width == width && triB.height == height) ? 1 : 0;
}

static void
triKeepState(int smooth, int blend, int tex, int depth)
{
    triB.smooth = smooth;
    triB.blend = blend;
    triB.tex = tex;
    triB.depth = depth;
    triB.alpha = triAlpha;
    triB.texOff = triTex.byteOff;
    triB.texW = triTex.w;
    triB.texH = triTex.h;
    triB.texMag = triTex.magLinear;
    triB.texMin = triTex.minCode;
    triB.texLevels = triTex.levels;
    triB.vw = tex ? (unsigned long)OSRDN_TEX_VERTEX_WORDS : (unsigned long)OSRDN_TRI_VERTEX_WORDS;
    triB.vf = tex ? OSRDN_TEX_VF_CNTL_FLAGS : OSRDN_TRI_VF_CNTL_FLAGS;
}

static void
triSegOpen(unsigned long diffAt, unsigned long hdrAt)
{
    osrdn_tri_seg *g = &triSeg[triB.nseg];

    g->diffAt = diffAt;
    g->hdrAt = hdrAt;
    g->tris = 0UL;
    g->vw = triB.vw;
    g->vf = triB.vf;
    g->smooth = triB.smooth;
    g->blend = triB.blend;
    g->tex = triB.tex;
    g->depth = triB.depth;
    g->alpha = triB.alpha;
    g->texOff = triB.texOff;
    g->texW = triB.texW;
    g->texH = triB.texH;
    g->texMag = triB.texMag;
    g->texMin = triB.texMin;
    g->texLevels = triB.texLevels;
    triB.nseg++;
    triB.end = hdrAt + 2UL;
}

/* the state key is the last segment's again -- after a truncation or a trim,
   so joins() answers for the stream as it now is */
static void
triSegRestore(void)
{
    const osrdn_tri_seg *g = &triSeg[triB.nseg - 1UL];

    triB.smooth = g->smooth;
    triB.blend = g->blend;
    triB.tex = g->tex;
    triB.depth = g->depth;
    triB.alpha = g->alpha;
    triB.texOff = g->texOff;
    triB.texW = g->texW;
    triB.texH = g->texH;
    triB.texMag = g->texMag;
    triB.texMin = g->texMin;
    triB.texLevels = g->texLevels;
    triB.vw = g->vw;
    triB.vf = g->vf;
}

/*
 * A segment that was opened (reserve) and never committed has a draw header
 * that counts no vertex, which the verifier refuses (VF) -- so before anything
 * is judged, sent, or built on, such a segment goes whole, pairs and header.
 * The two-phase form allows a caller to change its mind (see the header); this
 * is what that costs with segments.  A batch left with no segment is empty.
 */
static void
triSegTrim(void)
{
    while (triB.nseg > 0UL && triSeg[triB.nseg - 1UL].tris == 0UL) {
        triB.nseg--;
        triB.end = triSeg[triB.nseg].diffAt;
    }
    if (triB.nseg == 0UL)
        triBatchReset();
    else
        triSegRestore();
}

/*
 * What this stream last wrote to a register -- read from the STREAM, not from
 * a table kept beside it, so there is one source of truth: the prologue's
 * pairs, then every later segment's pairs, in order.  A pair is a PACKET0
 * header naming one register and its value (the templates are nothing else).
 */
static int
triStreamLast(unsigned long hdr, unsigned long *val)
{
    unsigned long i, k;
    int found = 0;

    for (i = 0UL; i + 1UL < triB.pn; i += 2UL)
        if (triDest[i] == hdr) {
            *val = triDest[i + 1UL];
            found = 1;
        }
    for (k = 1UL; k < triB.nseg; k++)
        for (i = triSeg[k].diffAt; i + 1UL < triSeg[k].hdrAt; i += 2UL)
            if (triDest[i] == hdr) {
                *val = triDest[i + 1UL];
                found = 1;
            }
    return found;
}

/*
 * G4-2 B2: the pairs a new state needs -- those of ITS prologue whose value is
 * not what the stream last wrote (r200 sends its dirty atoms the same way,
 * r200_cmdbuf.c 216-230; here "dirty" is computed against the stream itself).
 * Returns how many pairs, and writes them to `out` when it is not null; ~0 if
 * the state cannot be expressed at all.  Pure: it touches only the scratch
 * buffer and `out`.
 */
static unsigned long
triSegDiff(unsigned long colourByteOff, int pitchPixels, int width, int height,
           int smooth, int blend, int tex, int depth, unsigned long *out)
{
    unsigned long pn = triPrologueTo(triScratch, colourByteOff, pitchPixels, width, height,
                                     smooth, blend, tex, depth);
    unsigned long i, d = 0UL, last = 0UL;

    if (pn == 0UL)
        return ~0UL;
    for (i = 0UL; i + 1UL < pn; i += 2UL) {
        if (triStreamLast(triScratch[i], &last) && last == triScratch[i + 1UL])
            continue;
        if (out != 0) {
            out[2UL * d] = triScratch[i];
            out[2UL * d + 1UL] = triScratch[i + 1UL];
        }
        d++;
    }
    return d;
}

int
osrdn_tri_batch_joins(unsigned long colourByteOff, int pitchPixels,
                      int width, int height, int smooth, int blend,
                      int tex, int depth)
{
    unsigned long vw = tex ? (unsigned long)OSRDN_TEX_VERTEX_WORDS
                           : (unsigned long)OSRDN_TRI_VERTEX_WORDS;
    unsigned long d;

    if (triB.tris == 0UL)
        return 1;
    if (triB.tris >= (unsigned long)OSRDN_BATCH_MAX_TRIS)
        return 0;
    if (!triSameSurface(colourByteOff, pitchPixels, width, height))
        return 0;
    if (triSameState(smooth, blend, tex, depth))
        return (triB.end + 3UL * vw <= triB.room) ? 1 : 0;
    /* a different state: a segment, if the stream has room for its pairs, its
       header and this triangle, and the table has a row */
    if (triB.nseg >= (unsigned long)OSRDN_TRI_SEGS)
        return 0;
    d = triSegDiff(colourByteOff, pitchPixels, width, height, smooth, blend, tex, depth, 0);
    if (d == ~0UL)
        return 0;
    return (triB.end + 2UL * d + 2UL + 3UL * vw <= triB.room) ? 1 : 0;
}

unsigned long *
osrdn_tri_batch_reserve(unsigned long colourByteOff, int pitchPixels,
                        int width, int height, int smooth, int blend,
                        int tex, int depth, int *why)
{
    unsigned long at;
    int w = OSRDN_TRI_OK;

    triCounts.entered++;

    if (OSRDNMesaProbeRun() != OSRDN_PROBE_HARDWARE)
        w = OSRDN_TRI_NO_ACCEL;
    else if (!osrdn_tri_batch_joins(colourByteOff, pitchPixels, width, height,
                                    smooth, blend, tex, depth))
        /* the caller is supposed to have flushed; refusing is safe -- it draws
           this one itself and the batch in hand still goes out whole */
        w = OSRDN_TRI_BATCH_OPEN;
    else if (!triPick())
        w = OSRDN_TRI_NO_WINDOW;

    if (w == OSRDN_TRI_OK && triB.tris == 0UL) {
        unsigned long pn = triPrologue(colourByteOff, pitchPixels, width,
                                       height, smooth, blend, tex, depth);
        unsigned long room = triRoomWords();

        triB.nseg = 0UL;
        triKeepState(smooth, blend, tex, depth);
        if (pn == 0UL)
            w = OSRDN_TRI_ARGS;
        else if (room < pn + 2UL + 3UL * triB.vw)
            w = OSRDN_TRI_NO_WINDOW;
        else {
            triB.colourByteOff = colourByteOff;
            triB.pitchPixels = pitchPixels;
            triB.width = width;
            triB.height = height;
            triB.pn = pn;
            triB.room = room;
            triSegOpen(pn, pn);
        }
    } else if (w == OSRDN_TRI_OK && !triSameState(smooth, blend, tex, depth)) {
        /* G4-2 B2: a new segment -- joins() said its pairs, its header and
           this triangle fit, and the words are laid where it said.  An open
           segment nobody committed goes first (its pairs would be judged
           against, and its header refused). */
        unsigned long d;

        triSegTrim();
        d = triSegDiff(colourByteOff, pitchPixels, width, height,
                       smooth, blend, tex, depth, triDest + triB.end);
        triKeepState(smooth, blend, tex, depth);
        triSegOpen(triB.end, triB.end + 2UL * d);
        triCounts.segments++;
        triCounts.segWords += 2UL * d;
    }

    if (w != OSRDN_TRI_OK) {
        triCounts.refused[w]++;
        if (why != 0)
            *why = w;
        return 0;
    }
    at = triB.end;
    if (why != 0)
        *why = OSRDN_TRI_OK;
    return triDest + at;
}

unsigned long
osrdn_tri_batch_commit(void)
{
    triB.tris++;
    triSeg[triB.nseg - 1UL].tris++;
    triB.end += 3UL * triB.vw;
    triCounts.batched++;
    return triB.tris;
}

/*
 * The one-call form, which is what every caller used before M1r and what the
 * hook still uses when RDNMesaDirect is off.  IT IS WRITTEN IN TERMS OF THE
 * TWO-PHASE FORM so there is ONE decision path: a rule that lived only here
 * would be a rule the direct path does not have.
 */
unsigned long
osrdn_tri_batch_add(unsigned long colourByteOff, int pitchPixels,
                    int width, int height, const unsigned long *vtx,
                    int smooth, int blend, int tex, int depth, int *why)
{
    unsigned long *p;
    unsigned long i;

    if (vtx == 0) {
        triCounts.entered++;
        triCounts.refused[OSRDN_TRI_ARGS]++;
        if (why != 0)
            *why = OSRDN_TRI_ARGS;
        return 0UL;
    }
    p = osrdn_tri_batch_reserve(colourByteOff, pitchPixels, width, height,
                                smooth, blend, tex, depth, why);
    if (p == 0)
        return 0UL;
    for (i = 0UL; i < 3UL * triB.vw; i++)
        p[i] = vtx[i];
    return osrdn_tri_batch_commit();
}

/* every segment's draw header, as the stream will be sent; the words after
   the last vertex are the stream's length */
static unsigned long
triSegHeaders(void)
{
    unsigned long k;

    for (k = 0UL; k < triB.nseg; k++)
        triDrawPacket(triSeg[k].hdrAt, triSeg[k].vf, triSeg[k].vw, triSeg[k].tris);
    return triB.end;
}

unsigned long
osrdn_tri_batch_flush(int *why)
{
    unsigned long tris = triB.tris;
    unsigned long i, k, n;
    int w;

    if (why != 0)
        *why = OSRDN_TRI_OK;
    if (tris == 0UL) {
        triSegTrim();                   /* a reserved, uncommitted segment is not a batch */
        return 0UL;
    }
    triSegTrim();
    n = triSegHeaders();
    w = triSubmit(n);
    if (w != OSRDN_TRI_OK) {
        /* M3d: keep the stream the kernel refused, THEN empty the batch.  The
           caller now draws all `tris` of them, which is what the promise at the
           top of this file costs when a batch fails. */
        triKeepFailed(n, w, tris, triB.vw, 1);
        triCounts.refused[w]++;
        triCounts.flushFailed++;
        triBatchReset();
        if (why != 0)
            *why = w;
        return 0UL;
    }

    for (k = 0UL; k < triB.nseg; k++)
        for (i = 0UL; i < triSeg[k].tris; i++)
            triRecord(&triDest[triSeg[k].hdrAt + 2UL + i * 3UL * triSeg[k].vw], triSeg[k].vw,
                      triSeg[k].smooth, triSeg[k].blend, triSeg[k].tex, triSeg[k].depth);
    triCounts.flushes++;
    triBatchReset();
    return tris;
}

/* G4-2 B1 (docs/G4_2_BATCH_PLAN.md 2): see the header. */
static int triSpanOn = -1;

int
osrdn_tri_span_enabled(void)
{
    if (triSpanOn < 0) {
        const char *e = getenv(OSRDN_TRI_SPAN_ENV);

        triSpanOn = (e != 0 && e[0] == '0' && e[1] == 0) ? 0 : 1;
    }
    return triSpanOn;
}

unsigned long
osrdn_tri_batch_verify(unsigned long winBytes, unsigned long *at,
                       unsigned long *word)
{
    const OSRDNMesaProbeCaps *caps = OSRDNMesaProbeGetCaps();
    unsigned long n, why, a = 0UL, wd = 0UL, winEnd;

    if (triB.tris == 0UL || triDest == 0)
        why = CP_R7_WHY_EMPTY;
    else {
        /* the headers the flush writes, so the verifier reads the stream the
           flush would send -- the flush writes them again, identically */
        triSegTrim();
        n = triSegHeaders();
        winEnd = (winBytes > 0xffffffffUL - caps->winStart)
                 ? 0xffffffffUL : caps->winStart + winBytes;
        why = osrdn_r7_verify(caps->winStart, winEnd,
                              caps->winStart + OSRDN_R7V_DEF_COLOR_OFF,
                              caps->winStart + OSRDN_R7V_DEF_DEPTH_OFF,
                              OSRDN_R7V_DEF_PITCH, triDest, n, &a, &wd);
    }
    triCounts.verifies++;
    if (why != CP_R7_WHY_OK)
        triCounts.verifyRefused++;
    if (at != 0)
        *at = a;
    if (word != 0)
        *word = wd;
    return why;
}

unsigned long
osrdn_tri_batch_truncate(unsigned long keep)
{
    unsigned long before = 0UL, k;
    osrdn_tri_seg *g;

    if (keep >= triB.tris)
        return triB.tris;
    triCounts.truncated += triB.tris - keep;
    if (keep == 0UL) {
        triBatchReset();
        return 0UL;
    }
    /* the segment the boundary falls in keeps what is before it and the ones
       after it go; a segment left with no triangle is trimmed like any other */
    for (k = 0UL; k < triB.nseg; k++) {
        g = &triSeg[k];
        if (before + g->tris >= keep) {
            g->tris = keep - before;
            triB.nseg = k + 1UL;
            triB.end = g->hdrAt + 2UL + g->tris * 3UL * g->vw;
            break;
        }
        before += g->tris;
    }
    triB.tris = keep;
    triSegTrim();
    return triB.tris;
}
