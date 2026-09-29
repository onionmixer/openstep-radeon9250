/* Host simulation shim.  Prototypes copied from the target header
 * (ref/openstep/headers/NextDeveloper/Headers/driverkit/generalFuncs.h:66,71,93);
 * tools/r1/sim_r1.py compares them with that header before building. */
void IOSleep(unsigned milliseconds);
void IODelay(unsigned microseconds);
void IOLog(const char *format, ...)
__attribute__((format(printf, 1, 2)));
