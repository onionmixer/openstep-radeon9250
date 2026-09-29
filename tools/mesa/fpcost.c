/*
 * fpcost.c -- what the hook's per-vertex arithmetic costs on THIS machine.
 *
 *   cc -O -o fpcost fpcost.c -lm ; ./fpcost <runid>
 *
 * M1q left 1.20 us a triangle in userland and nothing had priced the pieces.
 * The hook does, per vertex: three union bit-casts, one FLOAT DIVIDE
 * (Win.data[i][2] / Visual->DepthMaxF), one colour word from four channels,
 * and five stores.  A divide on a 486-class FPU is tens of cycles and a
 * multiply is a few, so the divide is the first thing worth pricing -- but
 * pricing is not guessing, so this measures it.
 *
 * TWO WAYS A TIMED LOOP CAN MEASURE NOTHING, both of which this file hit:
 *   1. the operands do not change, so `cc -O` hoists the whole expression out.
 *      Every operand here therefore comes from a table filled from argc.
 *   2. the RESULT is never used -- each loop reset the accumulator, so the
 *      compiler deleted the earlier loops as dead code and the divide read
 *      0.78 ns.  Each step therefore PRINTS its own result, right after timing
 *      it, which is the only thing that makes the loop have to happen.
 *
 * Every line starts "FPCOST ".
 */

#include <sys/time.h>

int printf(const char *, ...);

#define N 200000

static unsigned long
elapsed(struct timeval a, struct timeval b)
{
    return (unsigned long)(b.tv_sec - a.tv_sec) * 1000000UL +
           (unsigned long)(b.tv_usec - a.tv_usec);
}

int
main(int argc, char **argv)
{
    struct timeval t0, t1;
    unsigned long us, i;
    float acc = 0.0F;
    /*
     * EVERY OPERAND COMES FROM THIS TABLE, filled from argc at run time.
     *
     * The first version used two locals that never changed, and `cc -O` hoisted
     * the whole divide out of the loop: it read 1.5 ns for an FDIV, which is
     * not a number any 486-class FPU can produce.  A loop-invariant expression
     * is not a measurement of that expression.
     */
    static float tab[8];
    union { float f; unsigned long u; } u;
    unsigned long bits = 0UL;
    const char *runid = (argc > 1) ? argv[1] : "x";

    for (i = 0; i < 8UL; i++)
        tab[i] = (float)(argc + (int)i) * 1024.0F;
    printf("FPCOST run=%s n=%d argc=%d\n", runid, N, argc);

    gettimeofday(&t0, (struct timezone *)0);
    for (i = 0; i < N; i++)
        acc += tab[i & 7UL];
    gettimeofday(&t1, (struct timezone *)0);
    us = elapsed(t0, t1);
    printf("FPCOST run=%s step=add us=%lu ns_each=%lu acc=%d\n", runid, us,
           us * 1000UL / N, (int)acc);

    acc = 0.0F;
    gettimeofday(&t0, (struct timezone *)0);
    for (i = 0; i < N; i++)
        acc += tab[i & 7UL] * tab[(i + 1UL) & 7UL];
    gettimeofday(&t1, (struct timezone *)0);
    us = elapsed(t0, t1);
    printf("FPCOST run=%s step=mul us=%lu ns_each=%lu acc=%d\n", runid, us,
           us * 1000UL / N, (int)acc);

    acc = 0.0F;
    gettimeofday(&t0, (struct timezone *)0);
    for (i = 0; i < N; i++)
        acc += tab[i & 7UL] / tab[(i + 1UL) & 7UL];
    gettimeofday(&t1, (struct timezone *)0);
    us = elapsed(t0, t1);
    printf("FPCOST run=%s step=div us=%lu ns_each=%lu acc=%d\n", runid, us,
           us * 1000UL / N, (int)acc);

    /* The int-to-float conversion is priced SEPARATELY: on a 486-class FPU an
       FILD is not free, and folding it into the cast step would have blamed the
       cast for it.  (The first version of this file did exactly that and read
       46 ns for "the cast".) */
    acc = 0.0F;
    gettimeofday(&t0, (struct timezone *)0);
    for (i = 0; i < N; i++)
        acc += (float)(i & 1);
    gettimeofday(&t1, (struct timezone *)0);
    us = elapsed(t0, t1);
    printf("FPCOST run=%s step=itof us=%lu ns_each=%lu acc=%d\n", runid, us,
           us * 1000UL / N, (int)acc);

    /* the cast the hook really does: a float into a union, the word out */
    acc = 1.0F;
    gettimeofday(&t0, (struct timezone *)0);
    for (i = 0; i < N; i++) {
        u.f = tab[i & 7UL];
        bits += u.u;
    }
    gettimeofday(&t1, (struct timezone *)0);
    us = elapsed(t0, t1);
    printf("FPCOST run=%s step=cast us=%lu ns_each=%lu bits=%lu\n", runid, us,
           us * 1000UL / N, bits);

    /* and the colour word: four channels shifted and or-ed, which is what
       osrdnColourWord does per vertex */
    gettimeofday(&t0, (struct timezone *)0);
    for (i = 0; i < N; i++)
        bits += ((i & 0xffUL) << 16) | ((i & 0xffUL) << 8) | (i & 0xffUL) |
                ((i & 0xffUL) << 24);
    gettimeofday(&t1, (struct timezone *)0);
    us = elapsed(t0, t1);
    printf("FPCOST run=%s step=colour us=%lu ns_each=%lu bits=%lu\n", runid, us,
           us * 1000UL / N, bits);

    printf("FPCOST run=%s acc=%d bits=%lu\n", runid, (int)(acc * 1000.0F), bits);
    return 0;
}
