/*
 * osrdn_port.m - four port accessors for OSRDNDisplay, and nothing else.
 *
 * Plain C in a .m file, as RDNR2aMMIO.m: every unit of the bundle #imports
 * the NeXT headers the same way.  Each body is one statement; the ioPorts.h
 * inline expands here, in this unit only.  tools/r2b0/check_r2b0_src.py
 * checks this file holds these four functions only.
 */

#import <driverkit/i386/ioPorts.h>
#import "osrdn_port.h"

unsigned char
osrdn_inb(IOEISAPortAddress port)
{
    return inb(port);
}

void
osrdn_outb(IOEISAPortAddress port, unsigned char data)
{
    outb(port, data);
}

unsigned long
osrdn_inl(IOEISAPortAddress port)
{
    return inl(port);
}

void
osrdn_outl(IOEISAPortAddress port, unsigned long data)
{
    outl(port, data);
}
