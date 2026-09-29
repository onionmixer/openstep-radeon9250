/*
 * cpsize.m - how big is the struct the driver copies on EVERY submission?
 *
 *   cc -o cpsize cpsize.m ; ./cpsize
 *
 * `osrdn_mode_cp` ends with `*copy = *cp;` (osrdn_mode.m:1443) -- an
 * unconditional whole-struct copy, done while the mode claim is held, whose
 * only reader is `osrdn_cp_lines`.  Under `quiet` nobody reads it at all.  The
 * fixed cost of a submission is 530 us and 366 us of that is inside the kernel
 * operation, so a copy worth measuring is worth knowing the size of.
 *
 * It must be built ON THE TARGET: vm_address_t and the pointers are 32-bit
 * there and 64-bit on the host, so a host build would report the wrong number.
 */
/* The userland kernelDriver.h does not bring vm_address_t in -- the driver is
   built with the kernel CFLAGS.  It is a 32-bit address on this machine either
   way, which is all the struct needs it for. */
typedef unsigned long vm_address_t;
#import "osrdn_cp.h"

/* the header wants these two only for prototypes it does not use here */
typedef int IOReturn;

int printf(const char *, ...);

int
main(void)
{
    printf("CPSIZE state=%lu bytes words=%lu digest=%lu\n",
           (unsigned long) sizeof(osrdn_cp_state),
           (unsigned long) sizeof(osrdn_cp_state) / 4UL,
           (unsigned long) sizeof(osrdn_cp_digest));
    return 0;
}
