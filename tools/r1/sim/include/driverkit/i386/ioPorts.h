/* Host simulation shim.  The target header (driverkit/i386/ioPorts.h) makes
 * these inline `in'/`out' instructions; here they are functions of the fake
 * world.  Type from driverkit/i386/driverTypes.h:12. */
typedef unsigned short IOEISAPortAddress;
unsigned char inb(IOEISAPortAddress port);
unsigned short inw(IOEISAPortAddress port);
unsigned long inl(IOEISAPortAddress port);
void outb(IOEISAPortAddress port, unsigned char data);
void outw(IOEISAPortAddress port, unsigned short data);
void outl(IOEISAPortAddress port, unsigned long data);
