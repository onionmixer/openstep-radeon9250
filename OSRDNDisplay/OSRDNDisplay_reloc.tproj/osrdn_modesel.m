/*
 * osrdn_modesel.m - see osrdn_modesel.h.  Plain C89; no hardware, no log,
 * no libc (the kernel loadable has none).  The only unit that instantiates
 * the resolution and format tables.
 */

/* before the FIRST import of the header: #import reads a file once */
#define OSRDN_MODE_TABLES_SEL
#import "osrdn_modesel.h"

#define MODESEL_DIM_MAX         65535UL
#define MODESEL_REFRESH_MAX     4294967UL       /* refresh in mHz must fit 32 bits */
#define MODESEL_CRTC_UNIT       8UL             /* CRTC_PITCH counts 8-pixel units */

const osrdn_res_row *
osrdn_res(int index)
{
    if (index < 0 || index >= OSRDN_RES_COUNT)
        return 0;
    return &osrdnResAll[index];
}

const osrdn_fmt_row *
osrdn_fmt(int index)
{
    if (index < 0 || index >= OSRDN_FMT_COUNT)
        return 0;
    return &osrdnFmtAll[index];
}

static const char *
skipBlanks(const char *text)
{
    while (*text == ' ' || *text == '\t')
        text++;
    return text;
}

/* 1 and the cursor moved past `word' if the text starts with it */
static int
takeWord(const char **cursor, const char *word)
{
    const char *text = *cursor;

    while (*word != '\0') {
        if (*text != *word)
            return 0;
        text++;
        word++;
    }
    *cursor = text;
    return 1;
}

/* a decimal number that fits 32 bits; 1 and the cursor moved past it */
static int
takeNumber(const char **cursor, unsigned long *value)
{
    const char     *text = *cursor;
    unsigned long   result = 0, digit;

    if (*text < '0' || *text > '9')
        return 0;
    while (*text >= '0' && *text <= '9') {
        digit = (unsigned long)(*text - '0');
        if (result > (4294967295UL - digit) / 10UL)
            return 0;
        result = result * 10UL + digit;
        text++;
    }
    *cursor = text;
    *value = result;
    return 1;
}

/* 1 with width and height if the text is a well-formed mode string */
static int
parseSize(const char *text, unsigned long *width, unsigned long *height)
{
    unsigned long refresh;

    text = skipBlanks(text);
    if (!takeWord(&text, "Height:"))
        return 0;
    text = skipBlanks(text);
    if (!takeNumber(&text, height) || *height == 0 || *height > MODESEL_DIM_MAX)
        return 0;
    text = skipBlanks(text);
    if (!takeWord(&text, "Width:"))
        return 0;
    text = skipBlanks(text);
    if (!takeNumber(&text, width) || *width == 0 || *width > MODESEL_DIM_MAX)
        return 0;
    text = skipBlanks(text);
    if (!takeWord(&text, "Refresh:"))
        return 0;
    text = skipBlanks(text);
    if (!takeNumber(&text, &refresh) || refresh == 0 || refresh > MODESEL_REFRESH_MAX)
        return 0;
    if (!takeWord(&text, "Hz"))
        return 0;
    text = skipBlanks(text);
    if (*text != '\0') {
        if (!takeWord(&text, "ColorSpace:"))
            return 0;
        text = skipBlanks(text);
        if (*text == '\0')
            return 0;
    }
    return 1;
}

/* 1 if `needle' occurs anywhere in `hay' */
static int
contains(const char *hay, const char *needle)
{
    const char *h, *a, *b;

    for (h = hay; *h != '\0'; h++) {
        a = h;
        b = needle;
        while (*b != '\0' && *a == *b) {
            a++;
            b++;
        }
        if (*b == '\0')
            return 1;
    }
    return 0;
}

static int
pairFits(int res, int fmt, unsigned long mapped)
{
    const osrdn_res_row *r = &osrdnResAll[res];
    const osrdn_fmt_row *f = &osrdnFmtAll[fmt];
    unsigned long rowBytes;

    if (((unsigned long)r->width % MODESEL_CRTC_UNIT) != 0UL)
        return 0;
    rowBytes = (unsigned long)r->width * (unsigned long)f->bytes;
    /* width, height <= 1600 and bytes <= 4: no overflow in 32 bits */
    return rowBytes * (unsigned long)r->height <= mapped;
}

static int
sameText(const char *a, const char *b)
{
    while (*a != '\0' && *a == *b) {
        a++;
        b++;
    }
    return *a == '\0' && *b == '\0';
}

int
osrdn_modesel_gray(const char *text, int *refused)
{
    *refused = 0;
    if (text == 0 || sameText(text, "256"))
        return 0;
    if (sameText(text, "16"))
        return 16;
    if (sameText(text, "4"))
        return 4;
    if (sameText(text, "2"))
        return 2;
    *refused = 1;
    return 0;
}

void
osrdn_modesel_choose(const char *displayMode, unsigned long mapped, osrdn_modesel *sel)
{
    unsigned long   width, height;
    int             k;

    sel->res = OSRDN_RES_DEFAULT;
    sel->fmt = OSRDN_FMT_DEFAULT;
    sel->resDefault = 1;
    sel->fmtDefault = 1;
    sel->pairDefault = 0;

    if (displayMode != 0) {
        if (parseSize(displayMode, &width, &height)) {
            for (k = 0; k < OSRDN_RES_COUNT; k++)
                if ((unsigned long)osrdnResAll[k].width == width &&
                    (unsigned long)osrdnResAll[k].height == height) {
                    sel->res = k;
                    sel->resDefault = 0;
                    break;
                }
        }
        for (k = 0; k < OSRDN_FMT_COUNT; k++)
            if (contains(displayMode, osrdnFmtAll[k].token)) {
                sel->fmt = k;
                sel->fmtDefault = 0;
                break;
            }
    }

    if (!pairFits(sel->res, sel->fmt, mapped)) {
        sel->res = OSRDN_RES_DEFAULT;
        sel->fmt = OSRDN_FMT_DEFAULT;
        sel->pairDefault = 1;
    }
}
