/*
 * OSRDNDisplay.m - R2b build of the PCI Radeon 9250 display driver: the first
 * mode set.
 *
 * Plan: docs/R2B_IMPL_PLAN.md (R2b-0's contract, docs/R2B0_IMPL_PLAN.md
 * sections 2 A, 3 and 3-1, still holds for probe, init and the opt-in key).
 *
 * On this boot the class:
 *   - accepts at +probe: only the location getPCIdevice: gave (PCIBus has
 *     already matched Auto Detect IDs, S25) and only if its ID reads RV280;
 *   - at init runs R2a's PCI checks without a line, reads the opt-in key
 *     once, publishes the oracle's mode (osrdn_mode_expect.h), maps the MMIO
 *     aperture (0x4000 since R4) and the framebuffer the way the Matrox replacement
 *     driver does (S3);
 *   - at enterLinearMode, WITH the opt-in key, runs osrdn_mode_enter: the
 *     snapshot, then CRTC, PLL, FIFO, DAC, palette and a test pattern.  A
 *     refused gate or a failed verify leaves the entry reverting itself,
 *     because enterLinearMode returns nothing and cannot report a failure;
 *   - at revertToVGAMode calls the superclass first, then osrdn_mode_revert,
 *     which puts back exactly what the snapshot read;
 *   - hands every parameter name that is not its own to the superclass, so
 *     the window server's IO_Framebuffer_* and IOGetDisplayInfo still work
 *     (S1, S22).
 *
 * This file makes no port and no MMIO access of its own: every hardware write
 * goes through osrdn_mode.m and osrdn_snap.m, and the evidence lines come
 * from osrdn_modelog.m AFTER the sequence has finished (the mode module may
 * not log, docs/R2B_IMPL_PLAN.md 12-9).  tools/r2b0/check_r2b0_src.py and
 * tools/r2b/check_r2b_src.py hold it to that.
 */

#import <driverkit/generalFuncs.h>
#import <driverkit/kernelDriver.h>
#import <driverkit/i386/kernelDriver.h>
/*
 * M1p: copyin is DECLARED HERE, not imported.
 *
 * <kernserv/prototypes.h> looked like the right header -- it is where copyin
 * is declared -- but it redefines current_task(), current_thread() and
 * ASSERT(), and it imports <bsd/dev/m68k/autoconf.h>: an m68k header, into an
 * i386 build, ahead of every driver header this file uses.  A display flicker
 * appeared on the boot that first carried it.  One extern costs nothing and
 * cannot reach anything else.
 */
extern int copyin(const void *from, void *to, unsigned int n);
#import <driverkit/IODeviceDescription.h>
#import <driverkit/IOConfigTable.h>
#import <driverkit/i386/IOPCIDeviceDescription.h>
#import <bsd/dev/ev_types.h>            /* EV_SCREEN_MIN/MAX_BRIGHTNESS */
#import <mach/vm_param.h>               /* PAGE_SIZE: the kernel's page_size (8192 here) */
#import <bsd/sys/mman.h>                /* PROT_READ, PROT_WRITE (R4c) */
#import <bsd/sys/errno.h>               /* ENXIO, ENODEV (R4c) */
#import "OSRDNDisplay.h"         /* brings osrdn_mode.h and osrdn_modesel.h */
#import "osrdn_modelog.h"        /* the evidence lines, printed after the sequence */
#import "osrdn_window.h"         /* where the offscreen window starts (R4, Matrox rule) */
#import "osrdn_vmap.h"           /* the character device's d_mmap decision (R4c) */
#import "osrdn_r7b.h"            /* the character device's ioctl interface (R7b) */

/* Provenance: tools/r2b0/target-build-r2b0.sh passes -DOSRDN_BUILD=0x<stamp>.
 * 0 means unstamped, and the host parser refuses such a log. */
#ifndef OSRDN_BUILD
#define OSRDN_BUILD         0x00000000
#endif

#define OSRDN_RECORD_KEY    "RDN R2B0 Record"
#define OSRDN_MODE_KEY      "Display Mode"          /* what Configure writes (R3b-2) */
#define OSRDN_GRAY_KEY      "Gray Levels"           /* BW:8 only (R3b-2b, docs/R3_MULTIMODE_PLAN.md 24-5) */
#define OSRDN_BRIGHT_LINES  8UL                     /* brightness lines logged per boot: autodim
                                                       repeats the call (24-5) */
#define OSRDN_RECORD_PARAM  "RDNR2b0Record"
#define OSRDN_STATE_PARAM   "RDNR2b0State"
#define OSRDN_CYCLE_PARAM   "RDNR2bCycle"
#define OSRDN_CYCLE_MAGIC   0x52324358U      /* "R2CX" -- one word, so a stray
                                               setIntValues cannot start a cycle */
#define OSRDN_ENGINE_KEY    "RDN Engine Test"       /* R4: off unless "Yes" (PLAN.md 4) */
#define OSRDN_ENGINE_PARAM  "RDNR4Engine"           /* {ENG_MAGIC, op, arg} */
#define OSRDN_VMAP_KEY      "RDN VRAM Mmap"         /* R4c: off unless "Yes" (docs/R4C_VMAP_PLAN.md 3-2) */
#define OSRDN_CP_KEY        "RDN CP Test"           /* R5: off unless "Yes" (docs/R5_PLAN.md 8) */
#define OSRDN_CP_INJECT_KEY "RDN CP Inject"         /* R5d: off unless "Yes" (docs/R5D_PLAN.md 7) */
#define OSRDN_3D_KEY        "RDN 3D Test"           /* R6a: off unless "Yes" (docs/R6_PLAN.md 7) */

/* R6a: ZPREP and ZCLEAR index the engine's alias by the CP's length (8-2 m4) */
typedef char osrdnR6AliasIsTheEngines[(CP_R6_ALIAS_BYTES == ENG_ALIAS_BYTES) ? 1 : -1];

/* the evidence copies, off the 4 KiB kernel stack (docs/R6_PLAN.md 8-2 M2: the CP state is
   ~1 KiB and setIntValues' frame held both copies).  The mode claim serialises the
   operations; a second caller racing the first can only garble a log line. */
static osrdn_cp_state rdnCpCopy;
static osrdn_engine_state rdnEngCopy;
/* M3e (docs/M3E_PLAN.md 2): the FIRST failure on the card, kept whole.  Twice
   the latch's record went out of the 4 KB message buffer before syslogd read
   it.  This copy is printed again by a RECORD refused for the latch -- memory
   only, the card is not read (osrdn_cp.m's RECORD rule stands). */
static osrdn_cp_state rdnCpKept;
static int            rdnCpKeptRc = 0;
static unsigned long  rdnCpKeptSub = 0UL;       /* 0 = nothing kept */
static unsigned long  rdnCpKeptPrints = 0UL;    /* M3i: odd prints the record, even the fifo words */
#define OSRDN_CP_PARAM      "RDNR5Cp"               /* {CP_MAGIC, op, arg, len} */
#define OSRDN_R7_PARAM      "RDNR7Sub"              /* R7a: {R7_MAGIC, op, token, nwords, words...} */
#define OSRDN_CP_COUNT      4
#define OSRDN_VMAP_PARAM    "RDNR4Vmap"             /* getIntValues, 7 words */
#define OSRDN_VMAP_COUNT    7
#define OSRDN_VMAP_MAGIC    0x52344D30U             /* "R4M0" */
#define OSRDN_VMAP_OFF      0                       /* the key is not Yes */
#define OSRDN_VMAP_ON       1                       /* registered */
#define OSRDN_VMAP_REFUSED  2                       /* a gate held: no device */

/* The format table carries IOBitsPerPixel and IOColorSpace as plain numbers
 * (the generator checks them against displayDefs.h, docs/R3_MULTIMODE_PLAN.md
 * 23-9 E5).  This only pins the enum constants that check relies on. */
typedef char osrdn_enums_are_the_generators[(IO_8BitsPerPixel == 1 && IO_15BitsPerPixel == 3 &&
                                             IO_24BitsPerPixel == 4 && IO_OneIsWhiteColorSpace == 1 &&
                                             IO_RGBColorSpace == 2) ? 1 : -1];

/* d_mmap's refusal test compares prot with this number; it must be mman.h's */
typedef char osrdn_prot_rw_is_mmans[(OSRDN_VMAP_PROT_RW == (PROT_READ | PROT_WRITE)) ? 1 : -1];

/* R7b: the window the client maps is exactly one kernel page, because d_mmap
   answers in pages.  PAGE_SIZE is a kernel VARIABLE here, not a constant, so
   that one is a gate in -r7bBlock ("pagesize") rather than a compile-time pin;
   the rest are constants and are pinned here. */
typedef char osrdn_r7b_page_within_the_limit[(OSRDN_R7B_WINDOW_WORDS <= OSRDN_R7B_MAX_WORDS) ? 1 : -1];   /* G4-3 K4: the window path submits at most its page */
typedef char osrdn_r7b_max_is_the_cps[(OSRDN_R7B_MAX_WORDS == (unsigned long)CP_R7_BATCH_MAX) ? 1 : -1];
typedef char osrdn_r7b_window_is_the_vmaps[(OSRDN_R7B_WINDOW_OFF == OSRDN_VMAP_BATCH_BASE) ? 1 : -1];
typedef char osrdn_r7b_blocks_fit_a_parameter[(sizeof(osrdn_r7b_caps) <= OSRDN_R7B_IOC_PARM_MASK &&
                                               sizeof(osrdn_r7b_submit) <= OSRDN_R7B_IOC_PARM_MASK) ? 1 : -1];

/*
 * R4c: the character device (docs/R4C_VMAP_PLAN.md 3-2, 11-3).  The switch
 * functions are plain C and see no instance, so what they need is here, set
 * once by -registerVmap:start:ceiling: before the device exists.
 *
 * d_mmap is osrdn_vmap_pfn and nothing else: the kernel asks it twice per
 * page and trusts the second answer (plan 1 F3), so it must not look at
 * anything that can change.  d_open and d_close run in the caller's open()
 * and close() system calls, where a log line is safe (Matrox osmgaDevOpen).
 * d_close arrives on the LAST close only and a mapping outlives it, so the
 * counts are observations, not ownership (Matrox 3-35, plan 10-2 B8).
 *
 * THE DRIVER MUST NOT BE UNLOADED once this is registered: the cdevsw slot
 * points into this module's text.  A display driver is loaded at boot and
 * never unloaded; Unload_Commands.sect says so too (plan 10-1 E8).
 */
static int              rdnVmapState = OSRDN_VMAP_OFF;
static int              rdnVmapMajor = -1;
static unsigned long    rdnVmapNonce = 0;
static unsigned long    rdnVmapOpens = 0;
static unsigned long    rdnVmapRefused = 0;
static unsigned long    rdnVmapCloses = 0;

/* R7b (docs/R7_PLAN.md 10): the batch page, and the one client that may submit.
 * The switch functions see no instance, so the instance is kept here and set by
 * -registerVmap: before the device exists -- the same shape R4c uses for the
 * window.  IOPhysicalFromVirtual may block (driverkit/kernelDriver.h:78), so it
 * is called once at init and never from d_mmap or d_ioctl. */
#define R7B_HW_PAGE             4096UL          /* the MMU's page: the step the walk takes */
#define R7B_ALLOC_BYTES         ((int)(OSRDN_R7B_WINDOW_BYTES + R7B_HW_PAGE))

static id               rdnR7bInstance = nil;
static unsigned long    rdnCloseRetires;    /* G5-2: last closes that found a submission in flight and retired it */
/* REL1 B7 (docs/REL1_PACKAGING_PLAN.md 16): the CP is brought up by the first
   client's open, not by a privileged tool.  Attempts are capped so a CP that
   will not come up cannot put a log line on every open of every submission;
   the evidence copy is static for the reason rdnCpCopy is (the 4 KiB stack). */
#define OSRDN_AUTOSTART_TRIES   8
static unsigned long    rdnAutoTries = 0UL;
static osrdn_cp_state   rdnAutoCopy;
static vm_address_t     rdnR7bAlloc = 0;        /* what IOMallocLow gave back */
static vm_address_t     rdnR7bVirt = 0;         /* the aligned page inside it */
static unsigned long    rdnR7bPhys = 0UL;
static int              rdnR7bHeld = 0;         /* the binary latch: 0 free, 1 held */
static unsigned long    rdnR7bSubmits = 0UL;
static unsigned long    rdnR7bDenied = 0UL;

static int
rdnDevOpen(int dev, int flag, int devtype)
{
    (void)flag;
    (void)devtype;
    if ((dev & 0xFF) != 0 || rdnVmapState != OSRDN_VMAP_ON || rdnR7bHeld) {
        /* R7b: a binary latch, not a count.  d_close arrives on the LAST close
           only, so opens minus closes is not how many hold it (plan 10-1 V6). */
        rdnVmapRefused++;
        IOLog("RDN-R4 open boot=%08x dev=%04x minor=%d refused opens=%u refused=%u closes=%u\n",
              (unsigned int)rdnVmapNonce, (unsigned int)(dev & 0xFFFF), dev & 0xFF,
              (unsigned int)rdnVmapOpens, (unsigned int)rdnVmapRefused, (unsigned int)rdnVmapCloses);
        return ENXIO;
    }
    rdnVmapOpens++;
    rdnR7bHeld = 1;                     /* last: a refusal above changes nothing */
    /* REL1 B7: bring the CP up for this client if nobody has (it returns at
       once when the CP is not in CP_ST_NONE or the attempts are spent) */
    if (rdnR7bInstance != nil)
        [rdnR7bInstance r7bAutoStart];
    /*
     * M2f TRIED PUTTING THIS LINE BEHIND THE QUIET KNOB, AND IT WAS REVERTED.
     *
     * The reasoning was good: a client that does not hold the node opens and
     * closes once a SUBMISSION, so this line and the close's were written 2,160
     * times an arm, outside the gate the submit log has had since M1n.
     *
     * The MEASUREMENT said no.  With the guard in, the seven arms that must
     * cost the same (quiet, instrument on, WBINVD on, knobs that touch nothing
     * measurable) split into two clusters 210 us apart, and which arm landed in
     * which changed between two runs of the same boot.  Without it they agree
     * to 2.5 us.  Runs: 790202535 (no guard, 2.5), 790215947 and 790216462
     * (guard, 210 and 213).  docs/M2F_PLAN.md 8.
     *
     * Whatever the guard costs, it is not worth a bimodal machine: every pair
     * that straddles the split reports the split as its knob's price, and that
     * is exactly what happened three times before the spread gate caught it.
     */
    IOLog("RDN-R4 open boot=%08x dev=%04x minor=%d ok opens=%u refused=%u closes=%u\n",
          (unsigned int)rdnVmapNonce, (unsigned int)(dev & 0xFFFF), dev & 0xFF,
          (unsigned int)rdnVmapOpens, (unsigned int)rdnVmapRefused, (unsigned int)rdnVmapCloses);
    return 0;
}

static int
rdnDevClose(int dev, int flag, int devtype)
{
    (void)flag;
    (void)devtype;
    rdnVmapCloses++;
    /* G5-2 (docs/G5_2_ASYNC_SUBMIT_PLAN.md 2-5): a client that died without RETIRE leaves its
       last accepted submission on the ring; the last close waits it out, as the reference's
       lastclose idles the engine.  Only when one is in flight: otherwise this touches nothing. */
    if (rdnR7bInstance != nil && [rdnR7bInstance r7bCloseRetire])
        rdnCloseRetires++;
    rdnR7bHeld = 0;
    IOLog("RDN-R4 close boot=%08x dev=%04x minor=%d opens=%u refused=%u closes=%u retires=%u\n",
          (unsigned int)rdnVmapNonce, (unsigned int)(dev & 0xFFFF), dev & 0xFF,
          (unsigned int)rdnVmapOpens, (unsigned int)rdnVmapRefused, (unsigned int)rdnVmapCloses,
          (unsigned int)rdnCloseRetires);
    return 0;
}

static int
rdnDevMmap(int dev, int offset, int prot)
{
    return osrdn_vmap_pfn(&osrdn_vmap_window, dev, offset, prot);
}

/* R7b: the pure-C way in (docs/R7_PLAN.md 10-3).  Both commands return ZERO
 * whatever happened, because a 4.3BSD ioctl copies its block back only on a
 * zero return -- refusing would throw away the answer the caller came for.  The
 * outcome is in the block's `status`. */
static int
rdnDevIoctl(int dev, int cmd, caddr_t data, int flag)
{
    (void)flag;
    if ((dev & 0xFF) != 0 || rdnVmapState != OSRDN_VMAP_ON)
        return ENXIO;
    if (data == 0 || rdnR7bInstance == nil)
        return ENXIO;
    /* int against int, one comparison per statement.  A wide unsigned constant
       is what this compiler read wrongly in R7a's first boot, and SUBMIT's
       number has the top bit set (docs/R7_PLAN.md 9-2). */
    if (cmd == (int)OSRDN_R7B_IOC_CAPS) {
        [rdnR7bInstance r7bCaps:(osrdn_r7b_caps *)data];
        return 0;
    }
    if (cmd == (int)OSRDN_R7B_IOC_SUBMIT2) {
        [rdnR7bInstance r7bSubmit2:(osrdn_r7b_submit2 *)data op:CP_OP_ZCLEAR];
        return 0;
    }
    if (cmd == (int)OSRDN_R7B_IOC_SUBMIT3) {        /* G5-2: the same stream, accepted */
        [rdnR7bInstance r7bSubmit2:(osrdn_r7b_submit2 *)data op:CP_OP_ASUBMIT];
        return 0;
    }
    if (cmd == (int)OSRDN_R7B_IOC_RETIRE) {         /* G5-2: everything accepted is drawn */
        [rdnR7bInstance r7bRetire:(osrdn_r7b_retire *)data];
        return 0;
    }
    if (cmd == (int)OSRDN_R7B_IOC_PRESENT) {
        [rdnR7bInstance r7bPresent:(osrdn_r7b_present *)data];
        return 0;
    }
    if (cmd == (int)OSRDN_R7B_IOC_CLEAR) {
        [rdnR7bInstance r7bClear:(osrdn_r7b_clear *)data];
        return 0;
    }
    if (cmd == (int)OSRDN_R7B_IOC_SUBMIT) {
        [rdnR7bInstance r7bSubmit:(osrdn_r7b_submit *)data];
        return 0;
    }
    /* a command nobody recognises leaves the number behind: a refusal with no
       value is a refusal that cannot be diagnosed */
    IOLog("RDN-R7B ioctl boot=%08x cmd=%08x unknown caps=%08x submit=%08x\n",
          (unsigned int)rdnVmapNonce, (unsigned int)cmd, (unsigned int)OSRDN_R7B_IOC_CAPS,
          (unsigned int)OSRDN_R7B_IOC_SUBMIT);
    return ENOTTY;
}

/* the unused slots refuse rather than leave a NULL behind (Matrox) */
static int
rdnDevNotSupported(void)
{
    return ENODEV;
}

@implementation OSRDNDisplay

+ (BOOL)probe:deviceDescription
{
    unsigned char dev = 0xff, fn = 0xff, bus = 0xff;
    IOReturn rc = IO_R_NO_DEVICE;

    if ([deviceDescription respondsTo:@selector(getPCIdevice:function:bus:)])
        rc = [deviceDescription getPCIdevice:&dev function:&fn bus:&bus];
    if (!osrdn_probe_accept((int)rc, (int)bus, (int)dev, (int)fn))
        return NO;
    if (!osrdn_probe_claim())
        return NO;                 /* a second instance for the one card */
    if ([super probe:deviceDescription])
        return YES;
    osrdn_probe_release();
    return NO;
}

- initFromDeviceDescription:deviceDescription
{
    unsigned char dev = 0xff, fn = 0xff, bus = 0xff;
    IOReturn rc = IO_R_NO_DEVICE;
    IOConfigTable *table;
    const char *key;
    IODisplayInfo *info;
    IORange ranges[3];
    vm_address_t fb;
    osrdn_modesel sel;
    const osrdn_res_row *res;
    const osrdn_fmt_row *fmt;
    int k, grayRefused;
    unsigned long winStart, winCeiling;

    mmioMapped = NO;
    mmioBase = 0;
    /* by hand, not trusting a zero-filled instance: -free unmaps rdnEngine.alias
       when it is not 0, and every early failure below goes through -free
       (code review 1) */
    rdnEngine.keyOn = 0;
    rdnEngine.alias = 0;
    rdnEngine.winStart = 0;
    rdnEngine.latched = 0;
    rdnEngine.ops = 0;
    rdnEngine.seedUsed = 0;
    rdnEngine.lastSeed = 0;
    vmapKey = 0;
    /* by hand, every byte: the CP state holds a block pointer the free path
       must be able to trust (it is never freed, but it is tested) */
    {
        unsigned char *z = (unsigned char *)&rdnCp;
        unsigned int zi;

        for (zi = 0; zi < sizeof rdnCp; zi++)
            z[zi] = 0;
    }
    rdnMode.cp = &rdnCp;
    /* nil, NOT [super free].  This is the CONSERVATIVE choice and its old
     * justification is withdrawn (it rested on a decompilation this project
     * does not treat as a source; plan 15-5).  If the superclass already freed
     * the object, [super free] here would be a second free of kernel memory;
     * if it did not, this path leaks one object on a failure that ends the
     * driver anyway.  The Matrox replacement driver carries the same
     * construct; it has never been reached there. */
    if ([super initFromDeviceDescription:deviceDescription] == nil)
        return nil;

    if ([deviceDescription respondsTo:@selector(getPCIdevice:function:bus:)])
        rc = [deviceDescription getPCIdevice:&dev function:&fn bus:&bus];
    osrdn_init_start(&rdnState, (unsigned long)OSRDN_BUILD, (int)bus, (int)dev, (int)fn);

    /* the opt-in key, read once here and cached (docs/R2B0_IMPL_PLAN.md 2 A) */
    table = [deviceDescription configTable];
    key = (table == nil) ? 0 : [table valueForStringKey:OSRDN_RECORD_KEY];
    rdnState.recordEnabled = osrdn_name_is(key, "Yes");
    if (key != 0)
        [table freeString:key];
    key = (table == nil) ? 0 : [table valueForStringKey:OSRDN_ENGINE_KEY];
    rdnEngine.keyOn = osrdn_name_is(key, "Yes");
    if (key != 0)
        [table freeString:key];
    key = (table == nil) ? 0 : [table valueForStringKey:OSRDN_VMAP_KEY];
    vmapKey = osrdn_name_is(key, "Yes");
    if (key != 0)
        [table freeString:key];
    key = (table == nil) ? 0 : [table valueForStringKey:OSRDN_CP_KEY];
    rdnCp.keyOn = osrdn_name_is(key, "Yes");
    if (key != 0)
        [table freeString:key];
    key = (table == nil) ? 0 : [table valueForStringKey:OSRDN_CP_INJECT_KEY];
    rdnCp.injectKey = rdnCp.keyOn && osrdn_name_is(key, "Yes");
    if (key != 0)
        [table freeString:key];
    key = (table == nil) ? 0 : [table valueForStringKey:OSRDN_3D_KEY];
    rdnCp.key3d = rdnCp.keyOn && osrdn_name_is(key, "Yes");
    if (key != 0)
        [table freeString:key];

    /* the resolution and format, once per boot (docs/R3_MULTIMODE_PLAN.md 23-2).
       The string is used only inside the call and freed right after: what
       survives is two indexes, and the log names the table's own token. */
    key = (table == nil) ? 0 : [table valueForStringKey:OSRDN_MODE_KEY];
    osrdn_modesel_choose(key, OSRDN_FB_LENGTH, &sel);
    if (key != 0)
        [table freeString:key];
    key = (table == nil) ? 0 : [table valueForStringKey:OSRDN_GRAY_KEY];
    rdnMode.grayLevels = osrdn_modesel_gray(key, &grayRefused);
    if (key != 0)
        [table freeString:key];
    rdnMode.res = sel.res;
    rdnMode.fmt = sel.fmt;
    rdnMode.selected = 1;
    res = osrdn_res(sel.res);
    fmt = osrdn_fmt(sel.fmt);

    if (rc != IO_R_SUCCESS) {
        rdnState.initWhy = "no-location";
        osrdn_init_line(&rdnState);
        return [self free];
    }
    if (!osrdn_init_precheck(&rdnState)) {
        osrdn_init_line(&rdnState);
        return [self free];
    }

    /* the chosen row, as the Matrox replacement driver publishes its own
       (OpenStepMGAReplacementDisplay.m:4000-4035), with the hardware LUT
       advertised: setTransferTable:count: is implemented below, and the
       window server sends no table without this flag (TEST_STATUS.md:84) */
    info = [self displayInfo];
    info->width = res->width;
    info->height = res->height;
    info->totalWidth = res->width;
    info->rowBytes = res->width * fmt->bytes;
    info->refreshRate = 60;
    info->frameBuffer = 0;
    info->bitsPerPixel = (IOBitsPerPixel)fmt->ioBpp;
    info->colorSpace = (IOColorSpace)fmt->ioColorSpace;
    for (k = 0; k + 1 < IO_MAX_PIXEL_BITS && fmt->encoding[k] != '\0'; k++)
        info->pixelEncoding[k] = fmt->encoding[k];
    info->pixelEncoding[k] = '\0';
    info->flags = IO_DISPLAY_HAS_TRANSFER_TABLE;
    info->memorySize = res->width * fmt->bytes * res->height;  /* the mode, not the aperture */
    info->scanRate = 60;
    /* The realized pixel clock at refdiv 12, from tools/oracle/radeon_modeset.py
     * through the generated table (the refdiv is only known at entry, so a
     * refdiv 6 boot differs by up to 0.44 %, docs/R3_MULTIMODE_PLAN.md 18-2). */
    info->dotClockRate = (int)res->dotClock;
    info->screenWidth = res->width;
    info->screenHeight = res->height;

    if (IOMapPhysicalIntoIOTask((unsigned)rdnState.bar2, OSRDN_MMIO_LENGTH, &mmioBase) != IO_R_SUCCESS ||
        mmioBase == 0) {
        rdnState.initWhy = "mmio-map";
        mmioBase = 0;
        osrdn_init_line(&rdnState);
        return [self free];
    }
    mmioMapped = YES;
    rdnState.mmioBase = mmioBase;

    ranges[0].start = (unsigned int)rdnState.bar0;
    ranges[0].size = (unsigned int)OSRDN_FB_LENGTH;
    ranges[1].start = 0xa0000;
    ranges[1].size = 0x20000;
    ranges[2].start = 0xc0000;
    ranges[2].size = 0x10000;
    [deviceDescription setMemoryRangeList:ranges num:3];

    fb = [self mapFrameBufferAtPhysicalAddress:(unsigned int)rdnState.bar0 length:(int)OSRDN_FB_LENGTH];
    if (fb == 0) {
        rdnState.initWhy = "fb-map";
        rdnState.mmioBase = 0;
        osrdn_init_line(&rdnState);
        return [self free];
    }
    info->frameBuffer = (void *)fb;
    fbBase = (vm_address_t)fb;

    /* what step 0 compares the card against: the aperture this class mapped
       (docs/R2_CLOSEOUT.md 11).  mappedLength is the MAPPED length, not the
       mode's memorySize. */
    rdnMode.bar0 = rdnState.bar0;
    rdnMode.mappedLength = OSRDN_FB_LENGTH;

    osrdn_init_line(&rdnState);
    /* the offscreen window, once: the engine's block and the R4c device use
       the same two numbers (docs/R4C_VMAP_PLAN.md 3-2) */
    winStart = osrdn_window_start((unsigned long)res->width, (unsigned long)res->height,
                                  (unsigned long)fmt->bytes, (unsigned long)PAGE_SIZE);
    winCeiling = osrdn_window_ceiling(OSRDN_WIN_VRAM, (unsigned long)PAGE_SIZE);
    [self engineAliasAt:winStart ceiling:winCeiling];
    rdnCp.alias = rdnEngine.alias;          /* R6a: the same block, through the same alias */
    rdnCp.winStart = rdnEngine.winStart;
    /* M3h: the client's drawing window is the one it may map (docs/M3H_PLAN.md 4-1) */
    rdnCp.winEnd = (rdnEngine.winStart != 0UL) ? winCeiling : 0UL;
    [self cpBlock];
    [self r7bBlock];
    IOLog("RDN-R3 select boot=%08x res=%ux%u fmt=%s rdflt=%d fdflt=%d pdflt=%d gray=%d gbad=%d\n",
          (unsigned int)rdnState.nonce, res->width, res->height, fmt->token,
          sel.resDefault, sel.fmtDefault, sel.pairDefault, rdnMode.grayLevels, grayRefused);
    /* LAST: nothing after this may fail, because a registered device's slot
       outlives any object that init gives back (docs/R4C_VMAP_PLAN.md 3-2) */
    [self registerVmap:deviceDescription start:winStart ceiling:winCeiling];
    return self;
}

- (void)enterLinearMode
{
    int live;
    unsigned long ran;

    rdnState.enterCount++;
    /* the same opt-in key as the record build: without it this driver owns the
       display but drives nothing, which is the R2b-0 behaviour */
    if (!rdnState.recordEnabled || !mmioMapped) {
        IOLog("RDN-R2B enter boot=%08x n=%u refused key=%d mapped=%d\n",
              (unsigned int)rdnState.nonce, (unsigned int)rdnState.enterCount,
              rdnState.recordEnabled, mmioMapped);
        return;
    }
    ran = rdnMode.enterCount;
    live = osrdn_mode_enter(&rdnMode, mmioBase, fbBase);
    IOLog("RDN-R2B enter boot=%08x n=%u live=%d\n",
          (unsigned int)rdnState.nonce, (unsigned int)rdnState.enterCount, live);
    osrdn_mode_lines(&rdnMode);        /* the evidence, after the sequence */
    /* the extended read-back, only if THIS call's entry reached it: a busy
       refusal returns before the entry body and leaves the last one's values */
    if (rdnMode.enterCount != ran && rdnMode.step >= 12)
        osrdn_verify_line(&rdnMode);
}

- (void)revertToVGAMode
{
    rdnState.revertCount++;
    /* R5: the CP stops before anything reverts the card (docs/R5_PLAN.md 7-2 B2,
       code review 3); modeRevertBody stops it again if a claim holder owed it */
    osrdn_mode_cp_stop(&rdnMode, mmioBase);
    [super revertToVGAMode];
    osrdn_mode_revert(&rdnMode, mmioBase);
    IOLog("RDN-R2B revert boot=%08x n=%u written=%d snap=%d\n",
          (unsigned int)rdnState.nonce, (unsigned int)rdnState.revertCount,
          rdnMode.modeWritten, rdnMode.snapshotValid);
    osrdn_mode_lines(&rdnMode);
}

- (IOReturn)getIntValues:(unsigned *)parameterArray
            forParameter:(IOParameterName)parameterName
                   count:(unsigned *)count
{
    if (osrdn_name_is(parameterName, OSRDN_VMAP_PARAM)) {
        /* R4c: what the tool needs to aim its mappings (docs/R4C_VMAP_PLAN.md 3-2) */
        if (parameterArray == 0 || count == 0 || *count != OSRDN_VMAP_COUNT)
            return IO_R_INVALID_ARG;
        parameterArray[0] = OSRDN_VMAP_MAGIC;
        parameterArray[1] = (unsigned)rdnVmapState;
        parameterArray[2] = (unsigned)osrdn_vmap_window.start;
        parameterArray[3] = (unsigned)osrdn_vmap_window.end;
        parameterArray[4] = (unsigned)osrdn_vmap_window.page;
        parameterArray[5] = (unsigned)rdnVmapMajor;
        parameterArray[6] = (unsigned)rdnEngine.winStart;
        *count = OSRDN_VMAP_COUNT;
        return IO_R_SUCCESS;
    }
    if (!osrdn_name_is(parameterName, OSRDN_STATE_PARAM))
        return [super getIntValues:parameterArray forParameter:parameterName count:count];
    if (parameterArray == 0 || count == 0 || *count != OSRDN_STATE_COUNT)
        return IO_R_INVALID_ARG;
    osrdn_state_words(&rdnState, parameterArray);
    *count = OSRDN_STATE_COUNT;
    /* One line per State read, through IOLog: the kernel facility is the only
     * one this machine's syslog.conf routes to /usr/adm/messages (the R1c run
     * measured that a logger marker never arrives, docs/R1C_RESULT.md fact 5).
     * tools/r2b0/target-run-r2b0.sh reads State once before the record, so this
     * line proves in-boot syslog delivery before anything touches hardware, and
     * tools/r2b0/parse_r2b0.py requires it ahead of the record's begin line. */
    IOLog("RDN-R2B0 state boot=%08x build=%08x records=%u last=%u flags=%08x cmode=%d loc=%02x:%02x.%x\n",
          (unsigned int)rdnState.nonce, (unsigned int)rdnState.build,
          (unsigned int)rdnState.bootRecords, (unsigned int)rdnState.lastRunid,
          (unsigned int)parameterArray[8], rdnState.cmode,
          (unsigned int)(rdnState.bus & 0xff), (unsigned int)(rdnState.dev & 0xff),
          (unsigned int)(rdnState.fn & 0xff));
    return IO_R_SUCCESS;
}

- (IOReturn)setIntValues:(unsigned *)parameterArray
            forParameter:(IOParameterName)parameterName
                   count:(unsigned)count
{
    int live;
    int keptNow = 0;              /* M3j */

    if (osrdn_name_is(parameterName, OSRDN_CYCLE_PARAM)) {
        /* R2c: revert, read the whole snapshot back, come back to the mode.
         * The judgement of the revert lives here because the revert otherwise
         * runs only at shutdown, where IOLog never reaches the disk
         * (docs/R2C_REVERT_PLAN.md section 1).  Every refusal is a return
         * code and touches no hardware. */
        if (parameterArray == 0 || count != 1)
            return IO_R_INVALID_ARG;
        if (parameterArray[0] != OSRDN_CYCLE_MAGIC)
            return IO_R_INVALID_ARG;
        if (!rdnState.recordEnabled || !mmioMapped)
            return IO_R_UNSUPPORTED;
        live = osrdn_mode_cycle(&rdnMode, mmioBase, fbBase);
        IOLog("RDN-R2B cycled boot=%08x live=%d\n", (unsigned int)rdnState.nonce, live);
        osrdn_revert_lines(&rdnMode);
        osrdn_wait_lines(&rdnMode);
        return live ? IO_R_SUCCESS : IO_R_IO;
    }
    if (osrdn_name_is(parameterName, OSRDN_ENGINE_PARAM)) {
        /* R4 (docs/R4_ENGINE_PLAN.md 12-3): one engine operation under the mode
         * claim; the result line is printed after the claim is released. */
        if (parameterArray == 0 || count != 3)
            return IO_R_INVALID_ARG;
        if (parameterArray[0] != (unsigned)ENG_MAGIC)
            return IO_R_INVALID_ARG;
        if (!rdnState.recordEnabled || !mmioMapped)
            return IO_R_UNSUPPORTED;
        live = osrdn_mode_engine(&rdnMode, mmioBase, &rdnEngine, (int)parameterArray[1],
                                 (unsigned long)parameterArray[2], &rdnEngCopy);
        if (live == ENG_RC_BUSY || live == ENG_RC_NOT_LIVE) {
            /* the engine did not run: its state belongs to another call */
            IOLog("RDN-R4 skip boot=%08x op=%u arg=%08x rc=%d\n", (unsigned int)rdnState.nonce,
                  parameterArray[1], parameterArray[2], live);
        } else {
            osrdn_engine_line(&rdnEngCopy, rdnState.nonce, live);
        }
        if (live == ENG_RC_RAN)
            return IO_R_SUCCESS;
        return (live == ENG_RC_BUSY) ? IO_R_BUSY : IO_R_IO;
    }
    if (osrdn_name_is(parameterName, OSRDN_R7_PARAM)) {
        /* R7a (docs/R7_PLAN.md 3): the client stages its own CP words here.  This call NEVER
         * touches the hardware -- it only copies into the driver's buffer, which is what makes
         * the words the verifier judges the same words that run.  Drawing them is a ZCLEAR of
         * case CP_R7_CASE, which goes through the ordinary mode claim like every other case. */
        unsigned nwords;

        if (parameterArray == 0 || count < (unsigned)CP_R7_HEAD)
            return IO_R_INVALID_ARG;
        if (parameterArray[0] != (unsigned)CP_R7_MAGIC)
            return IO_R_INVALID_ARG;
        if (!rdnState.recordEnabled || !mmioMapped)
            return IO_R_UNSUPPORTED;
        nwords = parameterArray[3];
        if (count != (unsigned)CP_R7_HEAD + nwords)
            return IO_R_INVALID_ARG;
        live = osrdn_cp_stage(&rdnCp, (unsigned long)parameterArray[1], (unsigned long)parameterArray[2],
                             (unsigned long)nwords, parameterArray + CP_R7_HEAD);
        IOLog("RDN-R7 stage boot=%08x op=%u token=%08x n=%u staged=%u dropped=%u ok=%d\n",
              (unsigned int)rdnState.nonce, parameterArray[1], parameterArray[2], nwords,
              (unsigned int)rdnCp.subWords, (unsigned int)rdnCp.subDropped, live);
        return live ? IO_R_SUCCESS : IO_R_INVALID_ARG;
    }
    if (osrdn_name_is(parameterName, OSRDN_CP_PARAM)) {
        /* R5 (docs/R5_PLAN.md 8, 9-2): one CP operation under the mode claim.
           The begin line goes out BEFORE the claim, so a hang can be placed
           offline; the evidence after the claim is released. */

        if (parameterArray == 0 || count != OSRDN_CP_COUNT)
            return IO_R_INVALID_ARG;
        if (parameterArray[0] != (unsigned)CP_MAGIC)
            return IO_R_INVALID_ARG;
        if (!rdnState.recordEnabled || !mmioMapped)
            return IO_R_UNSUPPORTED;
        IOLog("RDN-R5 begin boot=%08x op=%u arg=%08x len=%u\n", (unsigned int)rdnState.nonce,
              parameterArray[1], parameterArray[2], parameterArray[3]);
        live = osrdn_mode_cp(&rdnMode, mmioBase, &rdnCp, rdnEngine.latched, (int)parameterArray[1],
                             (unsigned long)parameterArray[2], (unsigned long)parameterArray[3], &rdnCpCopy,
                             0);         /* M2g: a diagnostic always computes and speaks */
        /* M3e: a RECORD the latch refused re-prints the kept failure; M3j: so does a RECORD
           that RAN once something is kept -- after a recovery the CP is not latched, and the
           kept record would otherwise never come out (in place of RECORD's own lines, which
           would not fit the 4 KB buffer beside it) */
        keptNow = (parameterArray[1] == (unsigned)CP_OP_RECORD && rdnCpKeptSub != 0UL &&
                   (live == CP_RC_RAN || (live == CP_RC_REFUSED && rdnCpCopy.why == CP_WHY_LATCHED)));
        if (live == CP_RC_BUSY || live == CP_RC_NOT_LIVE)
            IOLog("RDN-R5 skip boot=%08x op=%u rc=%d\n", (unsigned int)rdnState.nonce, parameterArray[1], live);
        else if (!keptNow)
            osrdn_cp_lines(&rdnCpCopy, rdnState.nonce, live);
        if (keptNow) {
            /* M3i: the record and the 40 fifo/ring lines would not share one 4 KB message
               buffer, so they take turns: the first refused RECORD prints the record, the
               second the words, and so on (docs/M3I_PLAN.md 5) */
            rdnCpKeptPrints++;
            if (rdnCpKeptPrints & 1UL) {
                IOLog("RDN-R5 kept boot=%08x subs=%u rc=%d\n", (unsigned int)rdnState.nonce,
                      (unsigned int)rdnCpKeptSub, rdnCpKeptRc);
                osrdn_cp_lines(&rdnCpKept, rdnState.nonce, rdnCpKeptRc);
            } else
                osrdn_cp_latch_words(&rdnCpKept, rdnState.nonce);
        }
        if (live == CP_RC_RAN)
            return IO_R_SUCCESS;
        return (live == CP_RC_BUSY) ? IO_R_BUSY : IO_R_IO;
    }
    if (!osrdn_name_is(parameterName, OSRDN_RECORD_PARAM))
        return [super setIntValues:parameterArray forParameter:parameterName count:count];
    return osrdn_record_request(&rdnState, parameterArray, count);
}

/* R3b-2b (docs/R3_MULTIMODE_PLAN.md 24).  Both arrive on kernel threads: the
 * table through the superclass's setIntValues, which has already checked the
 * count for the depth, the brightness from the event driver with its lock
 * held (24-9 A1).  The hardware work is the mode module's, under its claim;
 * with no MMIO or without the opt-in key it only stores. */
- setTransferTable:(const unsigned int *)table count:(int)count
{
    int result;

    result = osrdn_mode_set_transfer(&rdnMode, [self lutBase], table, count);
    osrdn_xfer_line(&rdnMode, table, count, result);
    return self;
}

- setBrightness:(int)level token:(int)token
{
    int result;

    if (level < EV_SCREEN_MIN_BRIGHTNESS || level > EV_SCREEN_MAX_BRIGHTNESS) {
        IOLog("RDN-R3 bright level=%d refused\n", level);      /* as S3.m:48-51 */
        return nil;
    }
    result = osrdn_mode_set_brightness(&rdnMode, [self lutBase], level);
    if (rdnMode.brightCalls <= OSRDN_BRIGHT_LINES)
        osrdn_bright_line(&rdnMode, level, result);
    return self;
}

- (vm_address_t)lutBase
{
    return (mmioMapped && rdnState.recordEnabled) ? mmioBase : 0;
}

/*
 * No mode list.  Answering 0 makes every index invalid, whatever the
 * superclass would have defaulted to, so "IOGetDisplayModeInfo:<n>" cannot be
 * served from a list this build does not have.  The earlier reasoning about
 * the superclass's own defaults is withdrawn: it rested on a decompilation
 * this project does not treat as a source (plan 15-5).  This is the
 * conservative answer either way.
 */
- (unsigned int)displayModeCount
{
    return 0;
}

/* R4 (docs/R4_ENGINE_PLAN.md 12-1, 13 #5 #14): the alias of the engine's
 * test block (same PTE as a user mapping, docs/R4C_VMAP_PLAN.md 1 F6), made
 * once, after the framebuffer is mapped so a failed init cannot leave it
 * behind.  The block starts where the Matrox rule puts the offscreen window
 * for THIS mode -- init computes it once for this and for the R4c device --
 * and must stay under the window ceiling and inside what the bridges forward.
 * Any refusal leaves alias 0 and every engine operation then refuses
 * (ENG_WHY_NO_ALIAS). */
- (void)engineAliasAt:(unsigned long)start ceiling:(unsigned long)ceiling
{
    vm_address_t alias = 0;
    const char *why = "ok";

    rdnEngine.alias = 0;
    rdnEngine.winStart = 0;
    if (!rdnEngine.keyOn)
        return;
    if (start == 0UL || start > ceiling || ceiling - start < ENG_ALIAS_BYTES)
        why = "window";
    else if (!osrdn_fb_reach_ok(&rdnState, start + ENG_ALIAS_BYTES))
        why = "bridge";
    else if (IOMapPhysicalIntoIOTask((unsigned)(rdnState.bar0 + start), (unsigned)ENG_ALIAS_BYTES,
                                     &alias) != IO_R_SUCCESS || alias == 0)
        why = "map";
    if (why[0] == 'o') {
        rdnEngine.winStart = start;
        rdnEngine.alias = alias;
    }
    IOLog("RDN-R4 alias boot=%08x win=%08x ceiling=%08x page=%u len=%08x %s\n",
          (unsigned int)rdnState.nonce, (unsigned int)start, (unsigned int)ceiling,
          (unsigned int)PAGE_SIZE, (unsigned int)ENG_ALIAS_BYTES, why);
}

/* R5 (docs/R5_PLAN.md 1 S6, 7-2 B12, 8): the CP's 64 KiB, once, at init and only
 * with the key on.  IOMallocLow is a bump allocator on the conventional-memory
 * arena (physically contiguous by construction, Matrox S5 3-2) -- measured here
 * anyway, page by page, before anything is told the address: contiguous, 64 KiB
 * aligned, below 640 KiB.  A block that fails is handed straight back, since
 * nothing has seen it; one that passes is never freed (a bus master may still
 * reach it). */
- (void)cpBlock
{
    vm_address_t va = 0;
    unsigned int p = 0, p0 = 0;
    unsigned long off;
    const char *why = "ok";

    /* the keys and the build, one line per boot, for the R5d judge (7) */
    IOLog("RDN-R5 keys boot=%08x test=%d inject=%d 3d=%d build=%08x\n", (unsigned int)rdnState.nonce, rdnCp.keyOn,
          rdnCp.injectKey, rdnCp.key3d, (unsigned int)OSRDN_BUILD);
    if (!rdnCp.keyOn)
        return;
    if (!mmioMapped || !rdnState.recordEnabled)
        why = "mode";
    else if ((va = (vm_address_t)IOMallocLow((int)CP_BLOCK_BYTES)) == 0)
        why = "alloc";
    else {
        for (off = 0; off < CP_BLOCK_BYTES; off += CP_PAGE) {
            if (IOPhysicalFromVirtual(IOVmTaskSelf(), va + off, &p) != IO_R_SUCCESS) {
                why = "phys";
                break;
            }
            if (off == 0)
                p0 = p;
            else if ((unsigned long)p != (unsigned long)p0 + off) {
                why = "contig";
                break;
            }
        }
        if (why[0] == 'o' && (p0 & 0xffffU) != 0U)
            why = "align";
        if (why[0] == 'o' && (unsigned long)p0 + CP_BLOCK_BYTES > 0xa0000UL)
            why = "above640k";
        if (why[0] == 'o') {
            rdnCp.block = va;
            rdnCp.phys = (unsigned long)p0;
            rdnCp.blockOk = 1;
        } else {
            IOFreeLow((void *)va, (int)CP_BLOCK_BYTES);
        }
    }
    IOLog("RDN-R5 block boot=%08x va=%08x phys=%08x len=%08x %s\n", (unsigned int)rdnState.nonce,
          (unsigned int)va, (unsigned int)p0, (unsigned int)CP_BLOCK_BYTES, why);
}

/* R7b (docs/R7_PLAN.md 10-6): the page the client maps, once, at init and only
 * with the 3D key on.  d_mmap answers in whole pages, so the eight kilobytes
 * behind the answer must be ONE physical run at a page boundary -- nothing in
 * the headers promises that of a heap allocation, so it is measured here, the
 * way cpBlock measures the CP block, before anything is told the address.  The
 * request is one page larger than the window (build/r7/design6.py) so that an
 * aligned run can be FOUND rather than hoped for.
 *
 * This page is NOT carved out of the CP block: the GART maps that block to the
 * card, and a client that could write any of it could write the ring. */
- (void)r7bBlock
{
    vm_address_t va = 0;
    unsigned int p = 0, p0 = 0;
    unsigned long off = 0UL, o = 0UL;
    const char *why = "ok";

    if (!rdnCp.key3d)
        return;                         /* no line: the key is off */
    if (!rdnState.recordEnabled || !mmioMapped)
        why = "mode";
    else if (!rdnCp.blockOk)
        why = "noblock";                /* without the CP there is nothing to submit to */
    else if ((unsigned long)PAGE_SIZE != OSRDN_R7B_WINDOW_BYTES)
        why = "pagesize";               /* the header's window is not this kernel's page */
    else if ((va = (vm_address_t)IOMallocLow(R7B_ALLOC_BYTES)) == 0)
        why = "alloc";
    else {
        for (off = 0UL; off < (unsigned long)R7B_ALLOC_BYTES; off += R7B_HW_PAGE) {
            if (IOPhysicalFromVirtual(IOVmTaskSelf(), va + off, &p) != IO_R_SUCCESS) {
                why = "phys";
                break;
            }
            if (off == 0UL)
                p0 = p;
            else if ((unsigned long)p != (unsigned long)p0 + off) {
                why = "contig";
                break;
            }
        }
        if (why[0] == 'o') {
            /* the first offset whose PHYSICAL address starts a kernel page */
            while (o + OSRDN_R7B_WINDOW_BYTES <= (unsigned long)R7B_ALLOC_BYTES &&
                   (((unsigned long)p0 + o) & (OSRDN_R7B_WINDOW_BYTES - 1UL)) != 0UL)
                o += R7B_HW_PAGE;
            if (o + OSRDN_R7B_WINDOW_BYTES > (unsigned long)R7B_ALLOC_BYTES)
                why = "align";
        }
        if (why[0] == 'o' && (unsigned long)p0 + (unsigned long)R7B_ALLOC_BYTES > 0xa0000UL)
            why = "above640k";
        if (why[0] == 'o') {
            rdnR7bAlloc = va;
            rdnR7bVirt = va + o;
            rdnR7bPhys = (unsigned long)p0 + o;
        } else {
            IOFreeLow((void *)va, R7B_ALLOC_BYTES);     /* nothing has seen it yet */
            va = 0;
        }
    }
    IOLog("RDN-R7B page boot=%08x va=%08x phys=%08x len=%08x skip=%08x %s\n",
          (unsigned int)rdnState.nonce, (unsigned int)rdnR7bVirt, (unsigned int)rdnR7bPhys,
          (unsigned int)R7B_ALLOC_BYTES, (unsigned int)o, why);
}

/* what a pure-C client has to be told before it can map anything */
- (void)r7bCaps:(osrdn_r7b_caps *)cb
{
    cb->magic = OSRDN_R7B_MAGIC;
    cb->version = OSRDN_R7B_VERSION;
    cb->window = OSRDN_R7B_WINDOW_OFF;
    cb->bytes = OSRDN_R7B_WINDOW_BYTES;
    cb->maxWords = OSRDN_R7B_MAX_WORDS;
    cb->build = (unsigned long)OSRDN_BUILD;
    cb->ready = (rdnR7bVirt != 0 && osrdn_vmap_window.bfixed) ? 1UL : 0UL;
    cb->cpRunning = (rdnCp.state == CP_ST_RUNNING) ? 1UL : 0UL;
    cb->winStart = rdnCp.winStart;
}

/* R7b: take the words out of the mapped page and run them.  The staging is
 * R7a's, unchanged and already proved on hardware -- which is the point: the
 * verifier, the buffer and the draw are the same ones, and only the way in is
 * new.  The copy happens HERE, so the words the verifier judges are words the
 * client can no longer reach. */
/*
 * M1p: THE SAME SUBMISSION, WITH THE WORDS COPIED IN FROM THE CLIENT.
 *
 * Everything after the copy is the path above, unchanged -- that is the point.
 * The only new thing is where the words came from: the client's own cached
 * memory instead of the cache-inhibited window, which is what the reference
 * stack does and for the same reason (r200_context.h:712-717 builds the
 * command buffer in a plain array; radeon_state.c 2858-2863 copies it in).
 *
 * copyin HAPPENS HERE, BEFORE THE CLAIM.  A page fault may sleep, and sleeping
 * with the hardware claim held is how this driver would hang.  The claim is
 * taken further down, inside osrdn_mode_cp.  A cross-review named this as the
 * one condition that makes the design sound, and it is why this method exists
 * instead of a copy inside the old one.
 */
/* G3 (docs/G3_PRESENT_PLAN.md 2-1): one rectangle of the client's surface onto the
 * screen.  The unit gates and builds the blit under the claim; this only names
 * the screen and translates the outcome.  Said once per verdict, never per
 * call: SDL presents a frame a row at a time. */
static unsigned long rdnPresentOk = 0UL, rdnPresentRefused = 0UL, rdnPresentSaid = 0UL;

- (void)r7bPresent:(osrdn_r7b_present *)pb
{
    osrdn_cp_present_req q;
    const osrdn_res_row *res = osrdn_res(rdnMode.res);
    const osrdn_fmt_row *fmt = osrdn_fmt(rdnMode.fmt);
    int live = CP_RC_NOT_LIVE;

    pb->status = (unsigned long)EINVAL;
    pb->verdict = OSRDN_PRESENT_E_MODE;
    q.verdict = OSRDN_PRESENT_E_MODE;
    if (mmioMapped && rdnState.recordEnabled && res != 0 && fmt != 0) {
        q.blk = pb;
        q.modeW = (unsigned long)res->width;
        q.modeH = (unsigned long)res->height;
        q.rowBytes = (unsigned long)[self displayInfo]->rowBytes;
        q.bytesPerPixel = (unsigned long)fmt->bytes;
        live = osrdn_mode_present(&rdnMode, mmioBase, &rdnCp, rdnEngine.latched, &q);
    }
    if (live == CP_RC_RAN) {
        pb->status = 0UL;
        pb->verdict = OSRDN_PRESENT_OK;
        rdnPresentOk++;
    } else if (live == CP_RC_BUSY) {
        pb->status = (unsigned long)EBUSY;
        pb->verdict = OSRDN_PRESENT_E_BUSY;
    } else if (live == CP_RC_NOT_LIVE) {
        pb->status = (unsigned long)ENODEV;
        pb->verdict = OSRDN_PRESENT_E_MODE;
    } else if (live == CP_RC_REFUSED) {
        pb->status = (unsigned long)EINVAL;
        pb->verdict = q.verdict;
    } else {
        pb->status = (unsigned long)EIO;      /* latched, recovered, post: the CP failed under it */
        pb->verdict = OSRDN_PRESENT_E_LATCH;
    }
    if (pb->status != 0UL)
        rdnPresentRefused++;
    if (pb->verdict < 32UL && !(rdnPresentSaid & (1UL << pb->verdict))) {
        rdnPresentSaid |= (1UL << pb->verdict);
        IOLog("RDN-G3 present boot=%08x rc=%d verdict=%u src=%u,%u %ux%u stride=%u org=%08x dst=%u,%u ok=%u refused=%u\n",
              (unsigned int)rdnState.nonce, live, (unsigned int)pb->verdict,
              (unsigned int)pb->srcX, (unsigned int)pb->srcY, (unsigned int)pb->w, (unsigned int)pb->h,
              (unsigned int)pb->srcStride, (unsigned int)pb->srcOrg,
              (unsigned int)pb->dstX, (unsigned int)pb->dstY,
              (unsigned int)rdnPresentOk, (unsigned int)rdnPresentRefused);
    }
}

/* G3b (docs/G3B_CLEAR_PLAN.md 2-1): the client's colour and depth cleared on the
 * card, once a frame.  Said once per verdict, as the present is. */
static unsigned long rdnClearOk = 0UL, rdnClearRefused = 0UL, rdnClearSaid = 0UL;

/*
 * G5-2 (docs/G5_2_ASYNC_SUBMIT_PLAN.md 2-3): wait until everything SUBMIT3 accepted is drawn.
 * Quiet when it works, as a submission is; a failure on the card speaks with the whole record,
 * a refusal with its head line (M3c's split).  Also the probe: a kernel without it answers
 * ENOTTY and the client stays synchronous.
 */
- (void)r7bRetire:(osrdn_r7b_retire *)rb
{
    int live = CP_RC_NOT_LIVE;

    rb->status = (unsigned long)EINVAL;
    rb->waited = 0UL;
    rb->us = 0UL;
    if (rb->magic != OSRDN_RETIRE_MAGIC || rb->version != OSRDN_RETIRE_VERSION)
        return;
    rb->waited = rdnCp.inflight ? 1UL : 0UL;        /* a hint read outside the claim; the wait itself is under it */
    if (mmioMapped && rdnState.recordEnabled)
        live = osrdn_mode_cp(&rdnMode, mmioBase, &rdnCp, rdnEngine.latched, CP_OP_RETIRE,
                             0UL, 0UL, &rdnCpCopy, 1);
    rb->rc = (unsigned long)live;
    if (live == CP_RC_RAN) {
        rb->status = 0UL;
        rb->us = rdnCpCopy.retireLastUs;
    } else if (live == CP_RC_BUSY)
        rb->status = (unsigned long)EBUSY;
    else if (live == CP_RC_NOT_LIVE)
        rb->status = (unsigned long)ENODEV;
    else
        rb->status = (unsigned long)EIO;
    rb->asubmits = rdnCpCopy.asubmits;
    rb->lost = rdnCpCopy.lostInflight;
    if (live == CP_RC_REFUSED)
        osrdn_cp_head(&rdnCpCopy, rdnState.nonce, live);
    else if (live != CP_RC_RAN && live != CP_RC_BUSY && live != CP_RC_NOT_LIVE)
        osrdn_cp_lines(&rdnCpCopy, rdnState.nonce, live);
}

/* G5-2: the last close's backstop -- 1 if a submission was in flight and RETIRE ran */
- (int)r7bCloseRetire
{
    osrdn_r7b_retire rb;

    if (!rdnCp.inflight)
        return 0;
    rb.magic = OSRDN_RETIRE_MAGIC;
    rb.version = OSRDN_RETIRE_VERSION;
    [self r7bRetire:&rb];
    return 1;
}

/*
 * REL1 B7 (docs/REL1_PACKAGING_PLAN.md 16): BRING THE CP UP FOR THE FIRST CLIENT.
 *
 * Every measurement brought the CP up with the privileged tool rdnr5cp, six ops
 * in this order (build/g3c/run_g3c.sh); an ordinary user cannot (IODeviceMaster
 * answers IO_R_PRIVILEGE), so an installed driver never accelerated.  The same
 * six ops, in the same order, through the same osrdn_mode_cp, with quiet = 0 as
 * the tool's path passes -- only the per-op log lines are replaced by one.
 *
 * Only from CP_ST_NONE: an operator's tool may already have run it (RUNNING), and
 * after a STOP the LOAD is refused anyway (one cycle a boot).  A chain that stops
 * before LOAD leaves NONE and the next open tries again; one that stops after it
 * leaves the CP out of NONE and is not repeated, as the tool's runner did not.
 * Nothing is sent unless the keys are on and the mode is written: RECORD and
 * REC3D pass the mode gate and RECORD writes the clock-index byte back
 * (osrdn_mode.m 1456, osrdn_cp.m 907).
 */
- (void)r7bAutoStart
{
    static const int ops[6] = { CP_OP_RECORD, CP_OP_REC3D, CP_OP_LOAD,
                                CP_OP_MAP, CP_OP_RESET, CP_OP_START };
    int k, live = CP_RC_NOT_LIVE;

    if (rdnCp.state != CP_ST_NONE || rdnAutoTries >= (unsigned long)OSRDN_AUTOSTART_TRIES)
        return;
    if (!mmioMapped || !rdnState.recordEnabled || !rdnCp.keyOn || !rdnCp.key3d ||
        !rdnMode.modeWritten || !rdnMode.snapshotValid)
        return;
    rdnAutoTries++;
    for (k = 0; k < 6; k++) {
        live = osrdn_mode_cp(&rdnMode, mmioBase, &rdnCp, rdnEngine.latched, ops[k],
                             0UL, 0UL, &rdnAutoCopy, 0);
        if (live != CP_RC_RAN)
            break;
    }
    IOLog("RDN-R5 autostart boot=%08x try=%u ran=%d rc=%d why=%u val=%08x state=%u\n",
          (unsigned int)rdnState.nonce, (unsigned int)rdnAutoTries, k, live,
          (unsigned int)rdnAutoCopy.why, (unsigned int)rdnAutoCopy.gateValue, (unsigned int)rdnCp.state);
}

- (void)r7bClear:(osrdn_r7b_clear *)cb
{
    osrdn_cp_clear_req q;
    const osrdn_fmt_row *fmt = osrdn_fmt(rdnMode.fmt);
    int live = CP_RC_NOT_LIVE;

    cb->status = (unsigned long)EINVAL;
    cb->verdict = OSRDN_PRESENT_E_MODE;
    q.verdict = OSRDN_PRESENT_E_MODE;
    if (mmioMapped && rdnState.recordEnabled && fmt != 0) {
        q.blk = cb;
        q.bytesPerPixel = (unsigned long)fmt->bytes;
        live = osrdn_mode_clear(&rdnMode, mmioBase, &rdnCp, rdnEngine.latched, &q);
    }
    if (live == CP_RC_RAN) {
        cb->status = 0UL;
        cb->verdict = OSRDN_PRESENT_OK;
        rdnClearOk++;
    } else if (live == CP_RC_BUSY) {
        cb->status = (unsigned long)EBUSY;
        cb->verdict = OSRDN_PRESENT_E_BUSY;
    } else if (live == CP_RC_NOT_LIVE) {
        cb->status = (unsigned long)ENODEV;
        cb->verdict = OSRDN_PRESENT_E_MODE;
    } else if (live == CP_RC_REFUSED) {
        cb->status = (unsigned long)EINVAL;
        cb->verdict = q.verdict;
    } else {
        cb->status = (unsigned long)EIO;
        cb->verdict = OSRDN_PRESENT_E_LATCH;
    }
    if (cb->status != 0UL)
        rdnClearRefused++;
    if (cb->verdict < 32UL && !(rdnClearSaid & (1UL << cb->verdict))) {
        rdnClearSaid |= (1UL << cb->verdict);
        IOLog("RDN-G3 clear boot=%08x rc=%d verdict=%u flags=%u colour=%08x@%08x/%u depth=%08x@%08x/%u %ux%u ok=%u refused=%u\n",
              (unsigned int)rdnState.nonce, live, (unsigned int)cb->verdict, (unsigned int)cb->flags,
              (unsigned int)cb->colourValue, (unsigned int)cb->colourOff, (unsigned int)cb->colourPitch,
              (unsigned int)cb->depthZ, (unsigned int)cb->depthOff, (unsigned int)cb->depthPitch,
              (unsigned int)cb->w, (unsigned int)cb->h, (unsigned int)rdnClearOk, (unsigned int)rdnClearRefused);
    }
}

- (void)r7bSubmit2:(osrdn_r7b_submit2 *)sb op:(int)op
{
    osrdn_r7b_submit old;
    unsigned long n, token;
    const char *why = 0;
    int staged = 0;

    sb->status = (unsigned long)EINVAL;
    sb->why = 0UL;
    sb->at = 0UL;
    sb->word = 0UL;
    sb->drawn = 0UL;
    n = sb->nwords;
    /* BOUNDED BEFORE IT IS MULTIPLIED: n * 4 on a 32-bit word could wrap, and
       the product is what copyin would believe. */
    if (sb->magic != OSRDN_R7B_MAGIC || sb->version != OSRDN_R7B_VERSION)
        why = "magic";
    else if (n == 0UL || n > OSRDN_R7B_MAX_WORDS)
        why = "count";                  /* G4-4 K8: the verifier's limit, not the page's -- see below */
    else if (sb->seed == 0UL)
        why = "seed";
    else if (sb->words == 0UL)
        why = "words";
    else if (rdnR7bVirt == 0 || !osrdn_vmap_window.bfixed || !rdnState.recordEnabled || !mmioMapped)
        why = "nodev";
    if (why == 0) {
        /*
         * G4-4 K8 (docs/G4_4_KERNEL_PLAN.md 2): the stream is copied in CHUNKS of
         * CP_R7_APPEND_MAX words through the one page and staged chunk by chunk,
         * so a submission may carry OSRDN_R7B_MAX_WORDS with a page of 2048.
         * Before this the whole stream was copied at once and anything past
         * the page was refused as "count" while CAPS advertised 4068 (G4-3 K4's
         * mismatch, found by G4-2's first hardware run: 4052 and 2372 words
         * refused).  Every copyin is still BEFORE the claim (osrdn_mode_cp, in
         * r7bRun).  A fault mid-way returns with the staging holding a valid
         * prefix that the next submission's RESET discards; the page holds
         * the last chunk, which is the client's own mapping either way.
         */
        const unsigned *w = (const unsigned *)rdnR7bVirt;
        unsigned long k = 0UL, take;

        token = ((unsigned long)rdnState.nonce | 1UL);
        staged = osrdn_cp_stage(&rdnCp, (unsigned long)CP_R7_OP_RESET, token, 0UL, w);
        while (staged && k < n) {
            take = n - k;
            if (take > (unsigned long)CP_R7_APPEND_MAX)
                take = (unsigned long)CP_R7_APPEND_MAX;
            if (copyin((const void *)(sb->words + k * 4UL), (void *)rdnR7bVirt,
                       (unsigned int)(take * 4UL)) != 0) {
                sb->status = (unsigned long)EFAULT;
                why = "copyin";
                break;
            }
            staged = osrdn_cp_stage(&rdnCp, (unsigned long)CP_R7_OP_APPEND, token, take, w);
            k += take;
        }
    }
    if (why != 0) {
        rdnR7bDenied++;
        if (why[0] == 'n' && why[1] == 'o')
            sb->status = (unsigned long)ENODEV;
        IOLog("RDN-R7B reject2 boot=%08x words=%u %s denied=%u\n",
              (unsigned int)rdnState.nonce, (unsigned int)n, why,
              (unsigned int)rdnR7bDenied);
        return;
    }
    old.magic = sb->magic;
    old.version = sb->version;
    old.nwords = n;
    old.seed = sb->seed;
    old.status = (unsigned long)EINVAL;
    old.why = 0UL;
    old.at = 0UL;
    old.word = 0UL;
    old.drawn = 0UL;
    [self r7bRun:&old words:n staged:staged op:op];
    sb->status = old.status;
    sb->why = old.why;
    sb->at = old.at;
    sb->word = old.word;
    sb->drawn = old.drawn;
}

- (void)r7bSubmit:(osrdn_r7b_submit *)sb
{
    const unsigned *w;
    unsigned long n, k = 0UL, take, token;
    const char *why;
    int staged;

    sb->status = (unsigned long)EINVAL;
    sb->why = 0UL;
    sb->at = 0UL;
    sb->word = 0UL;
    sb->drawn = 0UL;
    n = sb->nwords;
    /* every refusal before the verifier says so and says which one: a submission
       that leaves no line is a submission a judge cannot tell from one that never
       happened (docs/R7_PLAN.md 9-2, the boot that logged no word) */
    why = 0;
    if (sb->magic != OSRDN_R7B_MAGIC || sb->version != OSRDN_R7B_VERSION)
        why = "magic";
    else if (n == 0UL || n > OSRDN_R7B_MAX_WORDS)
        why = "count";
    else if (sb->seed == 0UL)
        why = "seed";                   /* the kernel would refuse it anyway (CP_WHY_SEED) */
    else if (rdnR7bVirt == 0 || !osrdn_vmap_window.bfixed || !rdnState.recordEnabled || !mmioMapped)
        why = "nodev";
    if (why != 0) {
        rdnR7bDenied++;
        if (why[0] == 'n')
            sb->status = (unsigned long)ENODEV;
        IOLog("RDN-R7B reject boot=%08x words=%u %s denied=%u\n", (unsigned int)rdnState.nonce,
              (unsigned int)n, why, (unsigned int)rdnR7bDenied);
        return;
    }
    w = (const unsigned *)rdnR7bVirt;
    token = ((unsigned long)rdnState.nonce | 1UL);
    staged = osrdn_cp_stage(&rdnCp, (unsigned long)CP_R7_OP_RESET, token, 0UL, w);
    while (staged && k < n) {
        take = n - k;
        if (take > (unsigned long)CP_R7_APPEND_MAX)
            take = (unsigned long)CP_R7_APPEND_MAX;
        staged = osrdn_cp_stage(&rdnCp, (unsigned long)CP_R7_OP_APPEND, token, take, w + k);
        k += take;
    }
    [self r7bRun:sb words:n staged:staged op:CP_OP_ZCLEAR];
}

/*
 * G4-4 K8: what BOTH submission paths do once the stream is staged -- the quiet
 * decision, the staging line, the claim and the run, the answer.  One copy:
 * two would drift, and the copyin path's copy of the old tail was the code
 * that could not be reached with a stream longer than the page.
 */
- (void)r7bRun:(osrdn_r7b_submit *)sb words:(unsigned long)n staged:(int)staged op:(int)op
{
    int live, quiet;

    /*
     * M1n: ONE ANSWER FOR THE WHOLE SUBMISSION, taken before the first line.
     *
     * The flag is read here and nowhere else on this path, so every line of
     * this submission is either written or swallowed together -- reading it
     * twice could log the beginning of a submission and not its end.  It is
     * taken AFTER the refusals above, which always speak: a submission that
     * leaves no line at all is one a judge cannot tell from one that never
     * happened (docs/R7_PLAN.md 9-2).
     */
    quiet = osrdn_cp_quiet_take(&rdnCp);
    /*
     * M2g: A FAILED STAGING SPEAKS, quiet or not.  With silence the default,
     * `if (!quiet)` alone would make this failure -- which returns just below,
     * before the submit line -- leave no line at all.  It is rare and it is
     * evidence; only a quiet SUCCESS is swallowed (docs/M2G_PLAN.md 8, C4).
     */
    if (!quiet || !staged)
        IOLog("RDN-R7B stage boot=%08x words=%u staged=%u dropped=%u ok=%d\n",
              (unsigned int)rdnState.nonce, (unsigned int)n, (unsigned int)rdnCp.subWords,
              (unsigned int)rdnCp.subDropped, staged);
    if (!staged) {
        rdnR7bDenied++;
        return;                         /* status is already EINVAL */
    }
    rdnR7bSubmits++;
    /* the begin line goes out BEFORE the claim, so a hang can be placed offline */
    if (!quiet)
        IOLog("RDN-R5 begin boot=%08x op=%u arg=%08x len=%u\n", (unsigned int)rdnState.nonce,
              (unsigned int)op, (unsigned int)sb->seed, (unsigned int)CP_R7_CASE);
    /* G5-2: ZCLEAR's client case waits for the card; ASUBMIT puts the same words on the ring
       and returns (the caller chose by the ioctl) */
    live = osrdn_mode_cp(&rdnMode, mmioBase, &rdnCp, rdnEngine.latched, op,
                         sb->seed, (unsigned long)CP_R7_CASE, &rdnCpCopy, quiet);
    if (live == CP_RC_BUSY || live == CP_RC_NOT_LIVE) {
        /* the operation did not run, so the copy is the PREVIOUS one: reporting
           it would hand the caller another call's evidence.  M3c: one short
           line, quiet or not -- it is a failure and it is rare. */
        IOLog("RDN-R5 skip boot=%08x op=%u rc=%d\n", (unsigned int)rdnState.nonce,
              (unsigned int)op, live);
    } else {
        /*
         * M3c: A FAILURE ON THE CARD SPEAKS, quiet or not.  M2g silenced every
         * line here but the staging failure, and the first latch it met left
         * no record of which wait ran out (docs/M3C_PLAN.md 1).
         *
         * Split by what happened: something on the card (a latch, a failed
         * check -- and PRE_TIMEOUT and POST, which this op cannot return today
         * but would mean the same) gets the whole record, the `RDN-R5 wait`
         * line with it; REFUSED wrote nothing and after a latch EVERY
         * submission is refused, so it gets the head line only -- the full
         * record each time would push the latch's out of the 4 KB buffer
         * (docs/M3C_PLAN.md 2, 4).
         */
        if (live != CP_RC_RAN && live != CP_RC_REFUSED && rdnCpKeptSub == 0UL) {
            rdnCpKept = rdnCpCopy;          /* M3e */
            rdnCpKeptRc = live;
            rdnCpKeptSub = rdnR7bSubmits;
        }
        if (!quiet || (live != CP_RC_RAN && live != CP_RC_REFUSED))
            osrdn_cp_lines(&rdnCpCopy, rdnState.nonce, live);
        else if (live == CP_RC_REFUSED)
            osrdn_cp_head(&rdnCpCopy, rdnState.nonce, live);
        sb->why = rdnCpCopy.r7Why;
        sb->at = rdnCpCopy.r7At;
        sb->word = rdnCpCopy.r7Word;
        sb->drawn = (live == CP_RC_RAN && rdnCpCopy.r7Why == (unsigned long)CP_R7_WHY_OK) ? 1UL : 0UL;
    }
    if (live == CP_RC_RAN)
        sb->status = 0UL;
    else if (live == CP_RC_BUSY)
        sb->status = (unsigned long)EBUSY;
    else
        sb->status = (unsigned long)EIO;
    /* G3b (docs/G3B_CLEAR_PLAN.md 2-2): NOT on the ordinary path.  Measured: with
       syslogd delivering, this one line held every submission 4.2 ms (ioctl
       4,525 us against 290 us with syslogd stopped) -- the reference and the
       Matrox driver log nothing a submission.  A loud lease or a failure speaks. */
    if (!quiet || live != CP_RC_RAN)
        IOLog("RDN-R7B submit boot=%08x words=%u rc=%d why=%u at=%u word=%08x drawn=%u subs=%u denied=%u\n",
              (unsigned int)rdnState.nonce, (unsigned int)n, live, (unsigned int)sb->why,
              (unsigned int)sb->at, (unsigned int)sb->word, (unsigned int)sb->drawn,
              (unsigned int)rdnR7bSubmits, (unsigned int)rdnR7bDenied);
}

/* R4c (docs/R4C_VMAP_PLAN.md 3-2, 11-3): the character device, the last step
 * of init.  Every gate that holds leaves no device and says why; the display
 * is not affected either way.  The window is fixed (write-once) and the
 * d_mmap decision is run over every page with the real page size and BAR0
 * BEFORE the slot exists, and a single wrong answer keeps it from existing. */
- (void)registerVmap:deviceDescription start:(unsigned long)start ceiling:(unsigned long)ceiling
{
    unsigned long mem = 0, aper = 0, cases = 0, allowed = 0, bad = 0, pfn0 = 0, pfnN = 0;
    int fixRc = -1, bwhy = OSRDN_VMAP_BFIRST;
    const char *why = "ok";

    rdnVmapNonce = rdnState.nonce;
    if (!vmapKey)
        return;                         /* no line: the key is off, as before R4c */
    rdnVmapState = OSRDN_VMAP_REFUSED;
    if (!rdnState.recordEnabled)
        why = "record";                 /* this driver does not set the mode */
    else if (!mmioMapped)
        why = "mmio";
    else if (start == 0UL || ceiling == 0UL || start >= ceiling)
        why = "window";
    else if (!osrdn_fb_reach_ok(&rdnState, ceiling))
        why = "bridge";
    else {
        osrdn_engine_vram_reach(mmioBase, &mem, &aper);
        if (mem < ceiling || aper < ceiling)
            why = "reach";
        else if ((fixRc = osrdn_vmap_fix(&osrdn_vmap_window, start, ceiling, rdnState.bar0,
                                         (unsigned long)PAGE_SIZE)) != OSRDN_VMAP_OK)
            why = "fix";
        else {
            /* R7b: the batch window goes in BEFORE the self-test, so the
               self-test judges it too.  A refusal costs the batch window and
               nothing else -- the VRAM window and the device are registered
               either way, and d_mmap then refuses every batch offset. */
            if (rdnR7bPhys != 0UL)
                bwhy = osrdn_vmap_fix_batch(&osrdn_vmap_window, rdnR7bPhys,
                                            OSRDN_R7B_WINDOW_BYTES);
            if ((bad = osrdn_vmap_selftest(&osrdn_vmap_window, &cases, &allowed)) != 0UL)
                why = "self";
            else if (![[self class] addToCdevswFromDescription:deviceDescription
                                                          open:(IOSwitchFunc)rdnDevOpen
                                                         close:(IOSwitchFunc)rdnDevClose
                                                          read:(IOSwitchFunc)rdnDevNotSupported
                                                         write:(IOSwitchFunc)rdnDevNotSupported
                                                         ioctl:(IOSwitchFunc)rdnDevIoctl
                                                          stop:(IOSwitchFunc)rdnDevNotSupported
                                                         reset:(IOSwitchFunc)rdnDevNotSupported
                                                        select:(IOSwitchFunc)rdnDevNotSupported
                                                          mmap:(IOSwitchFunc)rdnDevMmap
                                                          getc:(IOSwitchFunc)rdnDevNotSupported
                                                          putc:(IOSwitchFunc)rdnDevNotSupported])
                why = "cdevsw";
            else {
                rdnVmapMajor = [[self class] characterMajor];
                rdnR7bInstance = self;          /* before the state: d_ioctl reads it */
                rdnVmapState = OSRDN_VMAP_ON;   /* last: d_open refuses until now */
            }
        }
    }
    if (osrdn_vmap_window.fixed) {
        pfn0 = (osrdn_vmap_window.bar0 + osrdn_vmap_window.start) >> osrdn_vmap_window.shift;
        pfnN = (osrdn_vmap_window.bar0 + osrdn_vmap_window.end - osrdn_vmap_window.page) >>
               osrdn_vmap_window.shift;
    }
    IOLog("RDN-R4 vmap boot=%08x start=%08x end=%08x page=%u shift=%u bar0=%08x pfn0=%08x pfnN=%08x "
          "mem=%08x aper=%08x fix=%d self=%u/%u allowed=%u major=%d batch=%d bphys=%08x %s\n",
          (unsigned int)rdnState.nonce, (unsigned int)start, (unsigned int)ceiling,
          (unsigned int)PAGE_SIZE, (unsigned int)osrdn_vmap_window.shift, (unsigned int)rdnState.bar0,
          (unsigned int)pfn0, (unsigned int)pfnN, (unsigned int)mem, (unsigned int)aper, fixRc,
          (unsigned int)cases, (unsigned int)bad, (unsigned int)allowed, rdnVmapMajor, bwhy,
          (unsigned int)osrdn_vmap_window.bphys, why);
    if (rdnVmapState == OSRDN_VMAP_ON)
        IOLog("RDN-R4 vmap boot=%08x the driver must NOT be unloaded: the mappings and the slot outlive it\n",
              (unsigned int)rdnState.nonce);
}

- free
{
    if (rdnEngine.alias != 0) {
        (void)IOUnmapPhysicalFromIOTask(rdnEngine.alias, (unsigned)ENG_ALIAS_BYTES);
        rdnEngine.alias = 0;
    }
    /* only the MMIO aperture: the framebuffer mapping is the superclass's */
    if (mmioMapped) {
        rdnState.mmioBase = 0;
        (void)IOUnmapPhysicalFromIOTask(mmioBase, OSRDN_MMIO_LENGTH);
        mmioMapped = NO;
        mmioBase = 0;
    }
    return [super free];
}

@end
