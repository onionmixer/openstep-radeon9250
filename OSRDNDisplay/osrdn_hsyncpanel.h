/*
 * osrdn_hsyncpanel.h - what the Configure inspector stores for "RDN HSync
 * Adjust", and which slider position a stored value shows.
 *
 * docs/REL3_DISPLAY_FIX_PLAN.md 3-2 and 3-4.  Plain C89: no AppKit, no
 * driverkit, no libc, so tools/rel3/test_inspector_hsync.py compiles THIS
 * file on the host -- the same bytes the bundle compiles -- and holds it to
 * the driver's rule (osrdn_modesel_hsync() in the reloc) through the oracle.
 *
 * The driver's rule, for reference: an optional '+' or '-' and one to three
 * digits, -16..48; anything else is the default (7) and is logged as
 * refused.  The panel shows what the driver will use: a value it refuses
 * shows the default, and saving writes the slider's value.
 *
 * Imported by exactly one unit, OSRDNDisplayInspector.m, hence the statics.
 */
#ifndef OSRDN_HSYNCPANEL_H
#define OSRDN_HSYNCPANEL_H

#define OSRDN_PANEL_HSYNC_KEY       "RDN HSync Adjust"
#define OSRDN_PANEL_HSYNC_MIN       (-16)
#define OSRDN_PANEL_HSYNC_MAX       48
#define OSRDN_PANEL_HSYNC_DEFAULT   7

/* the value a stored string gives: its own when the driver takes it, else
   the default -- absent included */
static int
osrdnHsyncFor(const char *value)
{
    int v = 0, sign = 1, digits = 0;

    if (value == 0)
        return OSRDN_PANEL_HSYNC_DEFAULT;
    if (*value == '+' || *value == '-') {
        if (*value == '-')
            sign = -1;
        value++;
    }
    while (*value >= '0' && *value <= '9' && digits < 4) {
        v = v * 10 + (*value - '0');
        digits++;
        value++;
    }
    v *= sign;
    if (*value != '\0' || digits == 0 || digits > 3 ||
        v < OSRDN_PANEL_HSYNC_MIN || v > OSRDN_PANEL_HSYNC_MAX)
        return OSRDN_PANEL_HSYNC_DEFAULT;
    return v;
}

/* the slider's value made one the driver takes: clamped into the range */
static int
osrdnHsyncClamp(int v)
{
    if (v < OSRDN_PANEL_HSYNC_MIN)
        return OSRDN_PANEL_HSYNC_MIN;
    if (v > OSRDN_PANEL_HSYNC_MAX)
        return OSRDN_PANEL_HSYNC_MAX;
    return v;
}

/* the string stored for v (clamped first): "-16" .. "48", no '+', at most
   three characters and the terminator, so buf needs 4 bytes */
static const char *
osrdnHsyncText(int v, char buf[4])
{
    int n = 0, a;

    v = osrdnHsyncClamp(v);
    a = (v < 0) ? -v : v;
    if (v < 0)
        buf[n++] = '-';
    if (a >= 10)
        buf[n++] = (char)('0' + a / 10);
    buf[n++] = (char)('0' + a % 10);
    buf[n] = '\0';
    return buf;
}

#endif /* OSRDN_HSYNCPANEL_H */
