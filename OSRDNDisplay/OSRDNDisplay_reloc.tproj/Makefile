#
# OSRDNDisplay_reloc - the kernel-loadable body of the R2b-0 record build.
#
# All units are .m (the C ones hold no class), as the R2a probe: every unit
# imports the NeXT headers the same way.  osrdn_port.m and RDNR2aMMIO.m are
# separate units on purpose (docs/R2B0_IMPL_PLAN.md 3, 6-4).
#

NAME = OSRDNDisplay_reloc

PROJECTVERSION = 0.1
LANGUAGE = English

CLASSES = OSRDNDisplay.m osrdn_record.m osrdn_mode.m osrdn_modelog.m osrdn_snap.m osrdn_pll.m \
          osrdn_port.m RDNR2aMMIO.m osrdn_modesel.m osrdn_window.m osrdn_vmap.m osrdn_cp.m osrdn_cpu.m osrdn_engine.m
HFILES = OSRDNDisplay.h osrdn_record.h osrdn_mode.h osrdn_modelog.h osrdn_mode_expect.h osrdn_snap.h \
         osrdn_pll.h osrdn_port.h osrdn_expect.h RDNR2aMMIO.h osrdn_modesel.h osrdn_window.h osrdn_vmap.h osrdn_cp.h osrdn_cp_ucode.h osrdn_cpu.h osrdn_engine.h
OTHERSRCS = Makefile Makefile.preamble Makefile.postamble\
            Makefile.driver_preamble Load_Commands.sect Unload_Commands.sect

MAKEFILEDIR = /NextDeveloper/Makefiles/app
MAKEFILE = tool.make
SOURCEMODE = 444

-include Makefile.preamble
include $(MAKEFILEDIR)/$(MAKEFILE)
-include Makefile.postamble
-include Makefile.dependencies
