/*
 * OSRDNDisplayInspector.h - Configure.app inspector for OSRDNDisplay.
 *
 * docs/R3_MULTIMODE_PLAN.md 25 and 26.  Configure.app is an old-AppKit
 * (libNeXT) application and loads a driver's inspector from the executable
 * of its .config bundle; the kernel driver is the separate TOOLS
 * subproject.  Display drivers get IODisplayInspector, which already owns
 * the resolution and pixel-format picker (it lists Display.modes); this
 * subclass adds the settings a mode string cannot carry: "Gray Levels", and
 * (REL3, docs/REL3_DISPLAY_FIX_PLAN.md 3-4) "RDN HSync Adjust", the picture's
 * horizontal position.
 * 256, 16, 4 and 2 greys are the same BW:8 scanout with the same
 * IODisplayInfo and differ only in the ramp the driver loads, so they are
 * not modes.  The same arrangement as the Matrox replacement driver's
 * OSMGADisplayInspector.
 *
 * The main nib is Configure.app's own DisplayInspector.nib with the File's
 * Owner class renamed and one radio matrix grafted into the displayMode box
 * (tools/r3/build-inspector-nib.py).
 *
 * The driver reads the key once, when it initialises, so the panel writes
 * the table and nothing else; its caption says so.
 */
#ifndef OSRDN_DISPLAY_INSPECTOR_H
#define OSRDN_DISPLAY_INSPECTOR_H

#import <appkit/appkit.h>
#import <driverkit/IODisplayInspector.h>

@interface OSRDNDisplayInspector : IODisplayInspector
{
    id grayMatrix;      /* "Gray Levels": tags 0..3 = 256, 16, 4, 2 */
    id hsyncSlider;     /* "RDN HSync Adjust": -16..48 pixels */
    id hsyncValue;      /* the slider's value, as text */
}

- setTable:(NXStringTable *)instance;
- grayChanged:sender;
- hsyncChanged:sender;
- showHsync:(int)v;

@end

#endif /* OSRDN_DISPLAY_INSPECTOR_H */
