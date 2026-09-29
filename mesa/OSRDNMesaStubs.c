/*
 * OSRDNMesaStubs.c - the hooks that still decline (docs/M1C_PLAN.md 7).
 *
 * M1b had nine here.  M1c moved six of them into OSRDNMesaHook.c, where they
 * work; what is left are the ones this rung deliberately does NOT turn on --
 * the depth surface, its copy-back, and the clear word.  Turning colour, depth
 * and texture on together is the mistake the precedent names outright.
 *
 * Every one of them counts and then returns the value osmesa.c's own comments
 * call "leave it to the caller":
 *
 *   Buffer, DepthBuffer, AppBuffer  null   -- leave the caller's buffer alone
 *   BoundTo, CopyDepth              0      -- declined
 *   Stride                          0
 *   ReleaseBuffer, Mirror, ClearPixel      -- nothing to return; do nothing
 *
 * Declining is not the same as not being called, which is why each has its own
 * counter.  A rung whose evidence was "the picture is unchanged" would be
 * satisfied by a library whose hooks were never reached at all.
 *
 * NOTHING here writes through a pointer argument or touches any global but its
 * own counter, and tools/mesa/check_hook.py holds that as a rule with a
 * mutation.  No Mesa headers: every parameter these take is void * or a plain
 * integer, so this unit needs none.
 */

#include "OSRDNMesaHook.h"



void *
OpenStepMesaAccelDepthBuffer(void *ctx, int width, int height, int bytesPerValue)
{
    (void)ctx; (void)width; (void)height; (void)bytesPerValue;
    osrdn_hook_count(OSRDN_HOOK_DEPTH_BUFFER);
    return 0;
}



int
OpenStepMesaAccelCopyDepth(void *dst, int width, int height, int bytesPerValue)
{
    (void)dst; (void)width; (void)height; (void)bytesPerValue;
    osrdn_hook_count(OSRDN_HOOK_COPY_DEPTH);
    /* Zero is "declined", and the caller then has the uninitialised buffer it
       would have had anyway -- which is correct here, because we never gave it
       a depth buffer of ours to copy back from. */
    return 0;
}



void
OpenStepMesaAccelClearPixel(void *ctx, unsigned long word)
{
    (void)ctx; (void)word;
    osrdn_hook_count(OSRDN_HOOK_CLEAR_PIXEL);
}
