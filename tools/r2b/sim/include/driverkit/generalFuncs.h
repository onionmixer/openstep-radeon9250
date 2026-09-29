/* Host simulation shim.  Prototypes copied from the target header
 * (ref/openstep/headers/NextDeveloper/Headers/driverkit/generalFuncs.h:66,71,88,93;
 * ns_time_t from kernserv/clock_timer.h:16); tools/r2b0/sim_r2b0.py compares
 * them with those headers before building. */
typedef	unsigned long long	ns_time_t;
void IOSleep(unsigned milliseconds);
void IODelay(unsigned microseconds);
void IOGetTimestamp(ns_time_t *nsp);
void IOLog(const char *format, ...)
__attribute__((format(printf, 1, 2)));
