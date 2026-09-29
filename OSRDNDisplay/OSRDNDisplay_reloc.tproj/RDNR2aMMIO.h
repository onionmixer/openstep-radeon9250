/*
 * RDNR2aMMIO.h - the only way RDNR2aProbe.m reaches the Radeon's MMIO.
 *
 * Plan: docs/R1C_R2A_IMPL_PLAN.md section 2-1.  The three functions live in
 * their own compilation unit, RDNR2aMMIO.m, so that cc 2.7.2.1 cannot inline
 * them into the probe (it has no cross-unit optimisation) and they stay
 * visible as symbols in the target-built reloc, where tools/r2a/check_reloc.py
 * disassembles them: rdnMmioWrite8 must store one byte, rdnMmioWrite32 four,
 * rdnMmioRead32 nothing.  The host simulator (tools/r2a/sim) supplies its own
 * implementation of the same three prototypes.
 */

#import <driverkit/kernelDriver.h>      /* vm_address_t */

unsigned long rdnMmioRead32(vm_address_t base, unsigned int offset);
void rdnMmioWrite8(vm_address_t base, unsigned int offset, unsigned char value);
void rdnMmioWrite32(vm_address_t base, unsigned int offset, unsigned long value);
