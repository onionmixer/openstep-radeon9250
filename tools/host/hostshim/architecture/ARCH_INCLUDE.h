/* host shim: modern cpp cannot build an #include path by pasting string
   literals.  ARCH_INCLUDE(driverkit/, driverTypes.h) becomes the string
   "driverkit//i386/driverTypes.h" -- the doubled slash is harmless and
   keeps the prefix, which mdh10's shim dropped (harmless there, but
   bsd/i386 and architecture/i386 both have cpu.h and table.h). */
#ifndef _ARCH_INCLUDE_H_
#define _ARCH_INCLUDE_H_
#define ARCH_STR_(x) #x
#define ARCH_INCLUDE(prefix, suffix) ARCH_STR_(prefix/i386/suffix)
#endif
