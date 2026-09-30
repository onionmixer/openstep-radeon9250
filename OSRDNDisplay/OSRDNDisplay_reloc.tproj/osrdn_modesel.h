/*
 * osrdn_modesel.h - which resolution and pixel format this boot drives.
 *
 * docs/R3_MULTIMODE_PLAN.md 23-2 and 23-9.  Plain C: no hardware, no log, no
 * driverkit header, so tools/r3 can compile and test it on the host as it is.
 * The rule is the Matrox replacement driver's (operator decision: depth
 * follows Matrox), re-implemented here rather than linked:
 *
 *   resolution  "Height:" n "Width:" n "Refresh:" n "Hz" [ "ColorSpace:" x ],
 *               spaces and tabs skipped between the parts, keys case-sensitive,
 *               height and width 1..65535, refresh 1..4294967 and NOT compared;
 *               the table row with that width and height, else the default
 *               (edid/OpenStepMGAEDID.c:269-321, OpenStepMGAReplacementDisplay.m:4568-4577)
 *   format      the first format token, in table order, found ANYWHERE in the
 *               string, whether or not the resolution parsed; else the default
 *               (OpenStepMGAReplacementDisplay.m:4579-4583)
 *   pair        a pair whose frame does not fit the mapping, or whose width is
 *               not a whole number of the CRTC's 8-pixel units, is replaced
 *               WHOLE by the default pair (OpenStepMGAReplacementDisplay.m:4608-4627)
 *
 * The kernel's own -selectMode:count:valid: is not used (23-2).
 */

#import "osrdn_mode_expect.h"

typedef struct {
    int     res;            /* index into the resolution table */
    int     fmt;            /* index into the format table */
    int     resDefault;     /* 1: no row matched, the default resolution is used */
    int     fmtDefault;     /* 1: no token matched, the default format is used */
    int     pairDefault;    /* 1: the chosen pair was replaced whole */
} osrdn_modesel;

/* choose from the "Display Mode" text (0 when the key is absent); mapped is
   the framebuffer length the class maps */
void osrdn_modesel_choose(const char *displayMode, unsigned long mapped, osrdn_modesel *sel);

/* "Gray Levels" (docs/R3_MULTIMODE_PLAN.md 24-5): exactly "256", "16", "4" or
   "2" (OpenStepMGAReplacementDisplay.m:4545-4561); 0 means 256.  Anything else
   is 256 with *refused = 1.  An absent key (0) is 256, not refused. */
int osrdn_modesel_gray(const char *text, int *refused);

/* "RDN HSync Adjust" (docs/REL3_DISPLAY_FIX_PLAN.md 3-2 4): an optional '+' or
   '-' then one to three decimal digits and nothing else, in
   OSRDN_HSYNC_MIN..OSRDN_HSYNC_MAX pixels.  Anything else is the default with
   *refused = 1; an absent key (0) is the default, not refused.  The per-row
   bound is osrdn_mode_hsync_word's, applied when the word is written. */
#define OSRDN_HSYNC_MIN         (-16L)  /* 640x480's front porch, the smallest (python, plan 3-2) */
#define OSRDN_HSYNC_MAX         48L     /* 640x480's back porch */
#define OSRDN_HSYNC_DEFAULT     7L      /* set on the machine, 800x600 RGB:888/32 (plan 7):
                                           0 left a black band left, 13 one right */
long osrdn_modesel_hsync(const char *text, int *refused);

/* the rows; 0 for an index outside the table */
const osrdn_res_row *osrdn_res(int index);
const osrdn_fmt_row *osrdn_fmt(int index);
