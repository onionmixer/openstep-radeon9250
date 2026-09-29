/*
 * osrdn_graypanel.h - what the Configure inspector stores for "Gray Levels",
 * and which radio cell a stored value selects.
 *
 * docs/R3_MULTIMODE_PLAN.md 25-3 and 26-3.  Plain C89: no AppKit, no
 * driverkit, no libc, so tools/r3/test_inspector_gray.py compiles THIS file
 * on the host -- the same bytes the bundle compiles -- and holds it to the
 * driver's rule (osrdn_modesel_gray() in the reloc) through the oracle.
 *
 * The driver's rule, for reference: exactly "256", "16", "4" or "2";
 * anything else is 256 grey levels and is logged as refused.  The panel
 * cannot show "refused": a value it does not know selects the 256 cell,
 * because 256 is what the driver will actually use for it, and saving then
 * writes "256".  It never leaves the matrix without a selection -- nothing
 * establishes what selectCellWithTag: does with a tag no cell has (the
 * Matrox inspector's rule).
 *
 * Imported by exactly one unit, OSRDNDisplayInspector.m, hence the statics.
 */
#ifndef OSRDN_GRAYPANEL_H
#define OSRDN_GRAYPANEL_H

#define OSRDN_PANEL_GRAY_KEY    "Gray Levels"

/* cell tags, in the order the nib lays the cells out left to right */
#define OSRDN_GRAY_COUNT        4
static const char * const osrdnGrayValues[OSRDN_GRAY_COUNT] = { "256", "16", "4", "2" };

static int
osrdnGraySame(const char *a, const char *b)
{
    while (*a != '\0' && *a == *b) {
        a++;
        b++;
    }
    return *a == '\0' && *b == '\0';
}

/* the cell a stored value selects: its own, else 0 (256) -- absent included */
static int
osrdnGrayTagFor(const char *value)
{
    int tag;

    if (value == 0)
        return 0;
    for (tag = 0; tag < OSRDN_GRAY_COUNT; tag++)
        if (osrdnGraySame(value, osrdnGrayValues[tag]))
            return tag;
    return 0;
}

/* the value a cell stores; a tag no cell has stores "256" */
static const char *
osrdnGrayValueForTag(int tag)
{
    if (tag < 0 || tag >= OSRDN_GRAY_COUNT)
        tag = 0;
    return osrdnGrayValues[tag];
}

#endif /* OSRDN_GRAYPANEL_H */
