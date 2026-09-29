/* Host simulation shim.  Prototypes copied from the target header
 * (ref/openstep/headers/NextDeveloper/Headers/kernserv/i386/spl.h:23,49);
 * tools/r2a/sim_r2a.py compares them with that header before building. */
extern int splhigh(void);
extern int splx(int ipl);
