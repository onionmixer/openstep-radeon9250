/*
 * osrdn_cpu.h - two CPU instructions R5 needs around bus-master memory
 * (docs/R5_PLAN.md 7-2 B8).  Their own unit so the host simulators can supply
 * counting fakes (wbinvd is privileged and cannot run on the host), and so the
 * target reloc shows them as symbols tools/r2b0/check_reloc_r2b0.py can find.
 */

#ifndef OSRDN_CPU_H
#define OSRDN_CPU_H

/* write back and invalidate every cache line (the reference Linux
   drm_ati_pcigart_init does it after writing the table, ati_pcigart.c) */
void osrdn_cpu_wbinvd(void);

/* one locked exchange with memory: orders the CPU's writes before what follows */
void osrdn_cpu_serialize(void);

#endif /* OSRDN_CPU_H */
