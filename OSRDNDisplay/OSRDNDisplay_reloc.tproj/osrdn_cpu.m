/*
 * osrdn_cpu.m - see osrdn_cpu.h.  Two functions, one instruction each.
 */

#import "osrdn_cpu.h"

void
osrdn_cpu_wbinvd(void)
{
    __asm__ __volatile__("wbinvd" : : : "memory");
}

void
osrdn_cpu_serialize(void)
{
    static volatile unsigned long w;
    unsigned long v = 1UL;

    __asm__ __volatile__("xchgl %0, %1" : "=r"(v), "=m"(w) : "0"(v), "m"(w) : "memory");
}
