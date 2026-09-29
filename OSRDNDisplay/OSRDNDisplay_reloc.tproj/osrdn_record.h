/*
 * osrdn_record.h - the R2b-0 record, callable from the OSRDNDisplay class.
 *
 * Plan: docs/R2B0_IMPL_PLAN.md sections 2, 3-1 and 4.  Everything that
 * touches hardware lives behind these functions, in plain C
 * (osrdn_record.m, osrdn_pll.m), so that the host simulator can run it; the
 * class only maps, publishes and forwards.
 */

#import <driverkit/kernelDriver.h>      /* vm_address_t, IOReturn */

#define OSRDN_MAGIC         0x52324230UL        /* "R2B0" */
#define OSRDN_STATE_COUNT   9
#define OSRDN_RECORD_COUNT  2
#define OSRDN_FB_LENGTH     0x800000UL          /* 8 MiB: holds 1600 x 1200 x 4 = 7680000,
                                                   the largest mode (docs/R3_MULTIMODE_PLAN.md
                                                   22-2); was 0x300000 up to R3b-0 */
#define OSRDN_MMIO_LENGTH   0x4000              /* R4: the engine reads RB2D_DSTCACHE_CTLSTAT 0x342c.
                                                   A PCI BAR is a power of two, and the smallest one
                                                   holding 0x342c is 0x4000 -- radeonfb reaches 0x342c
                                                   on this chip, so BAR2 is at least that.  BAR2's size
                                                   itself was never measured (docs/R4_ENGINE_PLAN.md 9-2 #1).
                                                   Was 0x2000 up to R3 (largest offset RBBM_STATUS 0x0e40). */

/* Refusal codes (driverkit/return.h).  None of -704 -705 -711 -727 is used:
 * the kernel and IODevice return those on the set path themselves
 * (docs/R2B0_IMPL_PLAN.md section 2 B 6). */
#define OSRDN_R_INVALID     (-706)              /* IO_R_INVALID_ARG */
#define OSRDN_R_BUSY        (-725)              /* IO_R_BUSY: in progress, or two records this boot */
#define OSRDN_R_LATCHED     (-728)              /* IO_R_NOT_READY: a record stopped; no more */
#define OSRDN_R_KEY_NO      (-729)              /* IO_R_NOT_ATTACHED: "RDN R2B0 Record" is not Yes */

/* lastResult */
#define OSRDN_RESULT_NONE   0
#define OSRDN_RESULT_ENTER  1
#define OSRDN_RESULT_REFUSE 2
#define OSRDN_RESULT_STOP   3

typedef struct {
    unsigned long   nonce;          /* low 32 bits of IOGetTimestamp at init */
    unsigned long   build;
    unsigned long   enterCount;
    unsigned long   revertCount;
    int             bus, dev, fn;   /* getPCIdevice: */
    int             initOk;
    const char     *initWhy;
    unsigned long   bar0;           /* init: BAR0 & ~0xf (the framebuffer) */
    unsigned long   bar2;           /* init: BAR2 & ~0xf (the MMIO map) */
    vm_address_t    mmioBase;       /* the class's mapping, 0 if none */
    int             recordEnabled;  /* "RDN R2B0 Record" = "Yes", read once in init */
    int             cmode;          /* kernel basicConsoleMode at init */
    int             inProgress;
    int             latched;
    int             bootRecords;
    unsigned long   lastRunid;
    unsigned long   lastResult;
    unsigned long   lastLines;
} osrdn_state;

/* +probe:  rc and location from getPCIdevice:; one config read when rc is 0,
 * one log line, no sleep.  Returns 1 to accept. */
int osrdn_probe_accept(int rc, int bus, int dev, int fn);
int osrdn_probe_claim(void);
void osrdn_probe_release(void);

/* init, in order: start (zero, nonce, cmode, location), precheck (config
 * reads only, no line, no sleep), then the class maps and calls line. */
void osrdn_init_start(osrdn_state *st, unsigned long build, int bus, int dev, int fn);
int osrdn_init_precheck(osrdn_state *st);
/* R4: the bridges on the card's path forward [bar0, bar0 + length) -- the
 * engine test block reaches past the 8 MiB framebuffer mapping at 1600x1200x32
 * (docs/R4_ENGINE_PLAN.md 13 #5).  Uses the bridge set precheck captured. */
int osrdn_fb_reach_ok(const osrdn_state *st, unsigned long length);
void osrdn_init_line(const osrdn_state *st);

/* setIntValues "RDNR2b0Record" and getIntValues "RDNR2b0State" */
IOReturn osrdn_record_request(osrdn_state *st, const unsigned *params, unsigned count);
void osrdn_state_words(const osrdn_state *st, unsigned *words);

/* parameter name comparison (no libc) */
int osrdn_name_is(const char *name, const char *want);
