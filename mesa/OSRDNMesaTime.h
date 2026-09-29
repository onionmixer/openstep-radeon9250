/*
 * OSRDNMesaTime.h - G5-0: the frame-budget instrument (docs/G5_0_PERF_MEASURE_PLAN.md 2).
 *
 * WHAT IT IS.  Seven sites in the library are bracketed by two reads of the
 * CPU's cycle counter, and every interval lands in one of three bins by WHERE
 * it happened: outside any render bracket, inside a bracket but outside the
 * triangle hook, or inside the triangle hook.  The bins are what make the
 * arithmetic honest: an upload made by the hook (texture residency at draw
 * time) or a submission made by the hook (batch full) is inside the hook's
 * own interval, so adding "hook + upload + submit" would count it twice.  The
 * judge (build/g50/judge_g50.py) subtracts by the tags; this file only counts.
 *
 * WHAT IT COSTS.  Nothing when RDNMesaTime is not in the environment: every
 * site asks osrdn_time_on() once, a static int.  When it is on, a site costs
 * two rdtsc reads (a few dozen cycles) and a handful of adds.  The report
 * prints raw 64-bit cycle counts as two hex words and the run's own
 * calibration (wall microseconds from gettimeofday against the cycles the
 * same span took); the conversion is python's job, not C's.
 *
 * WHY rdtsc AND NOT gettimeofday.  The triangle hook runs 1,400-4,300 times a
 * frame; a system call at each end would cost more than what it measures.
 * The counter is read with the two-byte opcode rather than the mnemonic, so
 * the target's assembler needs to know nothing (osrdn_cpu.m does the same for
 * wbinvd by name because that one it knows).
 */
#ifndef OSRDN_MESA_TIME_H
#define OSRDN_MESA_TIME_H

#define OSRDN_TIME_TRI      0   /* the triangle hook, state preparation included (Hook.c) */
#define OSRDN_TIME_BRACKET  1   /* RenderStart .. RenderFinish, everything inside */
#define OSRDN_TIME_VERIFY   2   /* the host verifier at the bracket's end */
#define OSRDN_TIME_SUBMIT   3   /* one SUBMIT / SUBMIT2 ioctl; units = words */
#define OSRDN_TIME_PRESENT  4   /* one PRESENT ioctl = one row */
#define OSRDN_TIME_CLEAR    5   /* one CLEAR ioctl */
#define OSRDN_TIME_UPLOAD   6   /* one texture level upload, the leaf; units = bytes */
#define OSRDN_TIME_QUERY    7   /* G5-1c: one window-server round trip for the window's frame */
#define OSRDN_TIME_SITES    8

#define OSRDN_TIME_OUT      0   /* outside any bracket */
#define OSRDN_TIME_BR       1   /* inside a bracket, outside the triangle hook */
#define OSRDN_TIME_HOOK     2   /* inside the triangle hook */
#define OSRDN_TIME_TAGS     3

typedef struct {
    unsigned long n;            /* intervals */
    unsigned long lo, hi;       /* cycles, 64 bits as two words */
    unsigned long max;          /* the longest interval that fit a word */
    unsigned long huge;         /* intervals of 2^32 cycles or more (1.6 s): counted, not maxed */
} osrdn_time_acc;

typedef struct { unsigned long lo, hi; } osrdn_time_stamp;

/* the state the hook keeps current: they decide the bin of every interval */
extern int osrdn_time_in_render;
extern int osrdn_time_in_hook;

int  osrdn_time_on(void);                                   /* RDNMesaTime set: read once; starts the clock */
void osrdn_time_now(osrdn_time_stamp *t);                   /* rdtsc */
void osrdn_time_add(int site, const osrdn_time_stamp *t0);  /* now - t0, into the bin of the moment */
void osrdn_time_count(int site, unsigned long units);       /* words, bytes, triangles */
void osrdn_time_frame_present(unsigned long dstY);          /* one row: a frame starts when dstY goes back up */
void osrdn_time_frame_clear(void);
void osrdn_time_report(void);                               /* the RDN-T lines on stderr (also at exit) */
void osrdn_time_at_exit(void (*fn)(void));                  /* G5-1b: one more reporter, called after the RDN-T lines */
/* G5-1b: the reporter writes its own line through the same formatter (no stdio in
   the accelerated sources: judge_m1b B3): begin("RDN-C"), put("key", v)..., end() */
void osrdn_time_line_begin(const char *prefix);
void osrdn_time_line_put(const char *key, unsigned long value);
void osrdn_time_line_end(void);

/* for the Matrox-named statistics the port prints (test/mgashim): whole
   microseconds by this run's own calibration, all bins together */
unsigned long osrdn_time_calls(int site);
unsigned long osrdn_time_us(int site);
unsigned long osrdn_time_units(int site);

#endif
