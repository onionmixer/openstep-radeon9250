/*
 * osrdn_port.h - the only way osrdn_record.m reaches an I/O port.
 *
 * Plan: docs/R2B0_IMPL_PLAN.md section 3 (the seam) and 6-4.  The four
 * functions live in their own compilation unit, osrdn_port.m, so that
 * cc 2.7.2.1 cannot inline them into the record code (it has no cross-unit
 * optimisation): they stay visible as symbols in the target-built reloc,
 * where tools/r2b0/check_reloc_r2b0.py requires exactly one port instruction
 * of the right width in each and none anywhere else.  The host simulator
 * (tools/r2b0/sim) supplies its own implementation of the same prototypes.
 */

/* The type only.  ioPorts.h (the inline in/out) is imported by osrdn_port.m
 * alone, so no other unit can expand a port instruction. */
#import <driverkit/i386/driverTypes.h>  /* IOEISAPortAddress */

unsigned char osrdn_inb(IOEISAPortAddress port);
void osrdn_outb(IOEISAPortAddress port, unsigned char data);
unsigned long osrdn_inl(IOEISAPortAddress port);
void osrdn_outl(IOEISAPortAddress port, unsigned long data);
