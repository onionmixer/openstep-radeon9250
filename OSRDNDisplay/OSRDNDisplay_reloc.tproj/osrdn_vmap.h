/*
 * osrdn_vmap.h - R4c: the decision behind the character device's d_mmap.
 * docs/R4C_VMAP_PLAN.md 3-1, 3-3 and 11-1.
 *
 * The kernel asks d_mmap for every page of a request TWICE: once in smmap's
 * validation loop, which refuses the whole mapping on any -1, and again in
 * vm_object_special, which shifts the answer into a physical address WITHOUT
 * looking for -1 (IDA of this machine's kernel, plan 1 F1 and F3).  So the
 * answer for one (dev, offset, prot) must never change: it is pure
 * arithmetic over values fixed once, before the device is registered, and
 * never written again.  Nothing here reads mode state, logs, sleeps, locks or
 * calls anything.
 *
 * What d_mmap cannot defend against, recorded so nobody thinks it does: a
 * request whose length is 2^31 or more skips the validation loop entirely
 * (plan 10-1 E1).  Only who may open the node limits that.
 *
 * Plain C89, no libc, no driverkit: tools/r4/check_vmap.py compiles it on the
 * host and holds it to an independent python oracle.
 */

#ifndef OSRDN_VMAP_H
#define OSRDN_VMAP_H

/* PROT_READ | PROT_WRITE (bsd/sys/mman.h: 0x1 and 0x2); OSRDNDisplay.m pins
   the two to each other at compile time */
#define OSRDN_VMAP_PROT_RW      3

/* why osrdn_vmap_fix refused */
#define OSRDN_VMAP_OK           0
#define OSRDN_VMAP_AGAIN        1       /* already fixed: the values are write-once */
#define OSRDN_VMAP_PAGE         2       /* page size is not a power of two */
#define OSRDN_VMAP_ALIGN        3       /* start, end or bar0 not page aligned */
#define OSRDN_VMAP_EMPTY        4       /* start >= end, or less than a page */
#define OSRDN_VMAP_WRAP         5       /* bar0 + end does not fit 32 bits */
#define OSRDN_VMAP_PFN          6       /* the last PFN does not fit an int */
#define OSRDN_VMAP_RANGE        7       /* end + 2 pages does not fit an int offset */

/* R7b: the batch window's mmap offset (docs/R7_PLAN.md 10-2).  It is a second
   window in the same node, so it lives in the same struct and the same pure
   arithmetic -- d_mmap still reads nothing that can change. */
#define OSRDN_VMAP_BATCH_BASE   0x40000000UL

/* why osrdn_vmap_fix_batch refused */
#define OSRDN_VMAP_BAGAIN       8       /* already fixed: write-once, like the other */
#define OSRDN_VMAP_BFIRST       9       /* the VRAM window is not fixed: no page, no shift */
#define OSRDN_VMAP_BSIZE       10       /* not exactly one page */
#define OSRDN_VMAP_BALIGN      11       /* the physical base is not page aligned */
#define OSRDN_VMAP_BWRAP       12       /* base + bytes does not fit 32 bits */
#define OSRDN_VMAP_BLOW        13       /* not clear of the VRAM window AND of the walk past it */
#define OSRDN_VMAP_BRANGE      14       /* the window does not fit an int offset */
#define OSRDN_VMAP_BPFN        15       /* the PFN does not fit an int */

typedef struct {
    int             fixed;      /* 1 once osrdn_vmap_fix succeeded; never cleared */
    unsigned long   start;      /* card addresses of the window: [start, end) */
    unsigned long   end;
    unsigned long   bar0;       /* the aperture's physical base */
    unsigned long   page;       /* the kernel's page_size */
    unsigned long   shift;      /* log2(page), computed here */
    /* R7b, the batch window: driver memory, so a stored physical base rather
       than an aperture.  IOPhysicalFromVirtual may block (driverkit/kernelDriver.h:78),
       so it is called once at init and never from d_mmap. */
    int             bfixed;     /* 1 once osrdn_vmap_fix_batch succeeded */
    unsigned long   bbase;      /* mmap offset of the batch window */
    unsigned long   bphys;      /* its physical base, page aligned */
    unsigned long   bbytes;     /* exactly one page */
} osrdn_vmap;

/* The one instance d_mmap reads (explicitly initialised, plan 11-1). */
extern osrdn_vmap osrdn_vmap_window;

/* Write-once.  Returns OSRDN_VMAP_OK, or the reason it refused (and then v is
   left as it was). */
int osrdn_vmap_fix(osrdn_vmap *v, unsigned long start, unsigned long end,
                   unsigned long bar0, unsigned long page);

/* d_mmap's answer: the page frame number, or -1.  -1 unless: fixed, the minor
   (dev & 0xFF, never the whole dev: the kernel passes a sign-extended 16-bit
   rdev) is 0, offset >= 0, prot is exactly read+write, start <= offset <=
   end - page (no sum formed), bar0 + offset does not wrap, the physical
   address is page aligned, and the PFN fits an int.  Reads *v only. */
int osrdn_vmap_pfn(const osrdn_vmap *v, int dev, int offset, int prot);

/* Write-once, and only after osrdn_vmap_fix: the batch window is placed at
   OSRDN_VMAP_BATCH_BASE, which must be clear of the VRAM window and of the two
   pages past it that the self-test walks.  Returns OSRDN_VMAP_OK or why it
   refused (and then v is left as it was, VRAM window included). */
int osrdn_vmap_fix_batch(osrdn_vmap *v, unsigned long phys, unsigned long bytes);

/* The boot self-test, before registration: a fixed list of cases, then every
   page from 0 to end + 2 pages, each asked twice.  The expected PFN is derived
   by division and counting, not by the function's own formula.  Returns the
   number of wrong answers; *cases is how many were asked, *allowed how many
   pages the walk accepted. */
unsigned long osrdn_vmap_selftest(const osrdn_vmap *v, unsigned long *cases,
                                  unsigned long *allowed);

#endif /* OSRDN_VMAP_H */
