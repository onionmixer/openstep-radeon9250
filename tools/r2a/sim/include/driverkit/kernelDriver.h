/* Host simulation shim.  Types from driverkit/return.h:13,15 and
 * mach/std_types.h:77; prototypes from driverkit/kernelDriver.h:90,100. */
typedef int IOReturn;
#define IO_R_SUCCESS 0
typedef unsigned int vm_address_t;
IOReturn
IOMapPhysicalIntoIOTask(
    unsigned		physicalAddress,
    unsigned		length,
    vm_address_t	*virtualAddress);
IOReturn
IOUnmapPhysicalFromIOTask(
    vm_address_t	virtualAddress,
    unsigned		length);
