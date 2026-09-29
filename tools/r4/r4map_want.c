/*
 * r4map_want.c - what rdnr4map expects to read back through its mapping of
 * the engine's test block, and how it sorts a wrong word
 * (docs/R4C_VMAP_PLAN.md 11-4).  Plain C89, no header: rdnr4map.m includes
 * it on the target, and tools/r4/sim/world4.c includes it on the host, where
 * every one of the block's 65 536 words is compared with what the driver and
 * the fake engine actually left in VRAM -- the Matrox probe's own arithmetic
 * was wrong once (docs S4A 10-3), so this is tested, not trusted.
 *
 * The numbers are copies of osrdn_engine.h's (the tool is built on the target
 * and does not share the kernel header); tools/r4/check_tool_r4map.py holds
 * each copy to its original.
 */

#define R4M_BLOCK       0x40000UL       /* ENG_ALIAS_BYTES */
#define R4M_S0_OFF      16384UL         /* ENG_S0_OFF, 256 x 64, pitch 1024 */
#define R4M_S0_PITCH    1024UL
#define R4M_S0_H        64UL
#define R4M_S1_OFF      98304UL         /* ENG_S1_OFF, 128 x 128, pitch 512 */
#define R4M_S1_PITCH    512UL
#define R4M_S1_H        128UL
#define R4M_S2_OFF      180224UL        /* ENG_S2_OFF, 128 x 64, pitch 512 */
#define R4M_S2_PITCH    512UL
#define R4M_S2_H        64UL
#define R4M_MARK        0x5a5a5a5aUL    /* ENG_MARK */
#define R4M_FILL_X      16UL            /* ENG_FILL_X .. _H */
#define R4M_FILL_Y      8UL
#define R4M_FILL_W      200UL
#define R4M_FILL_H      40UL
#define R4M_C0_SX       32UL            /* engCases[0]: S1 (32,32) 64 x 64 onto S2 (8,0) */
#define R4M_C0_SY       32UL
#define R4M_C0_DX       8UL
#define R4M_C0_DY       0UL
#define R4M_C0_W        64UL
#define R4M_C0_H        64UL

/* the classes of a word read back */
#define R4M_OK          0
#define R4M_STALE       1       /* the user's own earlier word at this place */
#define R4M_MARKED      2       /* the marker where the engine's result belongs */
#define R4M_OTHER       3

/* ENG_USER_VALUE: the user's word at block offset off */
static unsigned long
r4mUser(unsigned long seed, unsigned long off)
{
    return seed | (off >> 2);
}

/* 1 and (x, y) if off lies in a surface */
static int
r4mIn(unsigned long off, unsigned long soff, unsigned long pitch, unsigned long h,
      unsigned long *x, unsigned long *y)
{
    if (off < soff || off - soff >= pitch * h)
        return 0;
    *y = (off - soff) / pitch;
    *x = ((off - soff) % pitch) / 4UL;
    return 1;
}

/* 1 if off lies in the UBLIT result: case 0's destination rectangle in S2 */
static int
r4mUblitSpot(unsigned long off, unsigned long *srcOff)
{
    unsigned long x, y;

    if (!r4mIn(off, R4M_S2_OFF, R4M_S2_PITCH, R4M_S2_H, &x, &y))
        return 0;
    if (x < R4M_C0_DX || x >= R4M_C0_DX + R4M_C0_W || y < R4M_C0_DY || y >= R4M_C0_DY + R4M_C0_H)
        return 0;
    *srcOff = R4M_S1_OFF + (R4M_C0_SY + (y - R4M_C0_DY)) * R4M_S1_PITCH +
              (R4M_C0_SX + (x - R4M_C0_DX)) * 4UL;
    return 1;
}

/* 1 if off lies in the FILL result: the rectangle in S0 */
static int
r4mFillSpot(unsigned long off)
{
    unsigned long x, y;

    if (!r4mIn(off, R4M_S0_OFF, R4M_S0_PITCH, R4M_S0_H, &x, &y))
        return 0;
    return x >= R4M_FILL_X && x < R4M_FILL_X + R4M_FILL_W && y >= R4M_FILL_Y && y < R4M_FILL_Y + R4M_FILL_H;
}

/* the block after UBLIT seed: S1 keeps the user's words, the destination holds
   their copy, the rest is the marker */
static unsigned long
r4mWantUblit(unsigned long seed, unsigned long off)
{
    unsigned long x, y, src;

    if (r4mUblitSpot(off, &src))
        return r4mUser(seed, src);
    if (r4mIn(off, R4M_S1_OFF, R4M_S1_PITCH, R4M_S1_H, &x, &y))
        return r4mUser(seed, off);
    return R4M_MARK;
}

/* the block after FILL colour */
static unsigned long
r4mWantFill(unsigned long colour, unsigned long off)
{
    return r4mFillSpot(off) ? colour : R4M_MARK;
}

/* sort a word: old is what the user itself wrote there before the operation,
   spot says whether the engine's result belongs there */
static int
r4mClass(unsigned long got, unsigned long want, unsigned long old, int spot)
{
    if (got == want)
        return R4M_OK;
    if (got == old)
        return R4M_STALE;
    if (spot && got == R4M_MARK)
        return R4M_MARKED;
    return R4M_OTHER;
}
