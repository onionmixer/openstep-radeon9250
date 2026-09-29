/*
 * RDNR2aMMIO.m - three MMIO accessors for the R2a probe, and nothing else.
 *
 * See RDNR2aMMIO.h.  No static, no inline: each body is one volatile access
 * whose width is the width of the pointed-to type.  tools/r2a/hostcheck.sh
 * checks this file holds these three functions only.
 */

#import "RDNR2aMMIO.h"

unsigned long
rdnMmioRead32(vm_address_t base, unsigned int offset)
{
    return *(volatile unsigned long *)(base + offset);
}

void
rdnMmioWrite8(vm_address_t base, unsigned int offset, unsigned char value)
{
    *(volatile unsigned char *)(base + offset) = value;
}

void
rdnMmioWrite32(vm_address_t base, unsigned int offset, unsigned long value)
{
    *(volatile unsigned long *)(base + offset) = value;
}
