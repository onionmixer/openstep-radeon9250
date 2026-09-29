/*
 * OSRDNDisplay.h - R2b-0 record build of the PCI Radeon 9250 display driver.
 *
 * Plan: docs/R2B0_IMPL_PLAN.md sections 2 and 3-1.  This build owns the
 * display on an activation boot and writes no mode register: enterLinearMode
 * refuses, revertToVGAMode only tells the superclass, and the hardware
 * record runs after boot when a root tool sets "RDNR2b0Record".  The class
 * makes no port or MMIO access of its own; everything that touches hardware
 * is the plain C in osrdn_record.m and osrdn_pll.m.
 */

#import <driverkit/IOFrameBufferDisplay.h>
#import "osrdn_record.h"
#import "osrdn_mode.h"
#import "osrdn_r7b.h"           /* R7b: the ioctl blocks the switch functions hand over */

@interface OSRDNDisplay : IOFrameBufferDisplay
{
    osrdn_state     rdnState;
    osrdn_mode_state rdnMode;
    osrdn_engine_state rdnEngine;   /* R4 (docs/R4_ENGINE_PLAN.md 12) */
    int             vmapKey;        /* R4c: "RDN VRAM Mmap" (docs/R4C_VMAP_PLAN.md 3-2) */
    osrdn_cp_state  rdnCp;          /* R5 (docs/R5_PLAN.md 8) */
    BOOL            mmioMapped;
    vm_address_t    mmioBase;
    vm_address_t    fbBase;
}

+ (BOOL)probe:deviceDescription;
- initFromDeviceDescription:deviceDescription;
- (void)enterLinearMode;
- (void)revertToVGAMode;
- (IOReturn)getIntValues:(unsigned *)parameterArray
            forParameter:(IOParameterName)parameterName
                   count:(unsigned *)count;
- (IOReturn)setIntValues:(unsigned *)parameterArray
            forParameter:(IOParameterName)parameterName
                   count:(unsigned)count;
- setTransferTable:(const unsigned int *)table count:(int)count;
- setBrightness:(int)level token:(int)token;
- (vm_address_t)lutBase;
- (void)engineAliasAt:(unsigned long)start ceiling:(unsigned long)ceiling;
- (void)registerVmap:deviceDescription start:(unsigned long)start ceiling:(unsigned long)ceiling;
- (void)cpBlock;
/* R7b (docs/R7_PLAN.md 10): the batch page, and the two things d_ioctl asks of
   the instance.  Declared here because the switch functions are plain C that
   messages an id, and a selector it cannot see is a selector it cannot send. */
- (void)r7bBlock;
- (void)r7bCaps:(osrdn_r7b_caps *)cb;
- (void)r7bSubmit:(osrdn_r7b_submit *)sb;
- (void)r7bRun:(osrdn_r7b_submit *)sb words:(unsigned long)n staged:(int)staged op:(int)op;   /* G4-4 K8: the shared tail */
/* M1p: the same submission with the words copied in from the client */
- (void)r7bSubmit2:(osrdn_r7b_submit2 *)sb op:(int)op;   /* G5-2: CP_OP_ZCLEAR (SUBMIT2) or CP_OP_ASUBMIT (SUBMIT3) */
- (void)r7bRetire:(osrdn_r7b_retire *)rb;       /* G5-2: docs/G5_2_ASYNC_SUBMIT_PLAN.md 2-3 */
- (int)r7bCloseRetire;                          /* G5-2: 2-5, the last close's backstop */
- (void)r7bAutoStart;                           /* REL1 B7: the first client brings the CP up */
- (void)r7bPresent:(osrdn_r7b_present *)pb;     /* G3: docs/G3_PRESENT_PLAN.md 2-1 */
- (void)r7bClear:(osrdn_r7b_clear *)cb;         /* G3b: docs/G3B_CLEAR_PLAN.md 2-1 */
- (unsigned int)displayModeCount;
- free;

@end
