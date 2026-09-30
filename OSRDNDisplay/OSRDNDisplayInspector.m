/*
 * OSRDNDisplayInspector.m - see OSRDNDisplayInspector.h.
 *
 * Lessons carried over from the Matrox inspector (docs/R3_MULTIMODE_PLAN.md
 * 26-2):
 *   - [super setTable:] first, or the stock mode picker is not set up;
 *   - setTable: runs again whenever the operator comes back to this driver,
 *     so it re-reads the table every time and keeps no state of its own;
 *   - the value is stored as an NXCopyStringBuffer and never freed: the
 *     header of NXStringTable does not say whether insertKey:value: copies
 *     or keeps the pointer, and every shipped inspector does exactly this;
 *   - the table here is Configure's NXStringTable, not the kernel's config
 *     table, so the driver's valueForStringKey:/freeString: pairing does not
 *     apply: the value belongs to the table and is not freed.
 */
#import "OSRDNDisplayInspector.h"
#import "osrdn_graypanel.h"
#import "osrdn_hsyncpanel.h"

@implementation OSRDNDisplayInspector

- setTable:(NXStringTable *)instance
{
    [super setTable:instance];
    [grayMatrix selectCellWithTag:
        osrdnGrayTagFor([table valueForStringKey:OSRDN_PANEL_GRAY_KEY])];
    [self showHsync:osrdnHsyncFor([table valueForStringKey:OSRDN_PANEL_HSYNC_KEY])];
    return self;
}

/* the slider and its number show v; the slider's range is the nib's */
- showHsync:(int)v
{
    char buf[4];

    [hsyncSlider setIntValue:v];
    [hsyncValue setStringValue:osrdnHsyncText(v, buf)];
    return self;
}

- grayChanged:sender
{
    [table insertKey:OSRDN_PANEL_GRAY_KEY
               value:NXCopyStringBuffer(osrdnGrayValueForTag([[sender selectedCell] tag]))];
    return self;
}

/* a whole number of pixels, stored as the driver reads it */
- hsyncChanged:sender
{
    char buf[4];
    int  v = osrdnHsyncClamp([sender intValue]);

    [self showHsync:v];
    [table insertKey:OSRDN_PANEL_HSYNC_KEY value:NXCopyStringBuffer(osrdnHsyncText(v, buf))];
    return self;
}

@end
