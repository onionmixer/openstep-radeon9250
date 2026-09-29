#
# RDNR1Probe_reloc - the kernel-loadable body of the R1 probe.
#

NAME = RDNR1Probe_reloc

PROJECTVERSION = 0.1
LANGUAGE = English

CLASSES = RDNR1Probe.m
HFILES =
OTHERSRCS = Makefile Makefile.preamble Makefile.postamble\
            Makefile.driver_preamble Load_Commands.sect Unload_Commands.sect

MAKEFILEDIR = /NextDeveloper/Makefiles/app
MAKEFILE = tool.make
SOURCEMODE = 444

-include Makefile.preamble
include $(MAKEFILEDIR)/$(MAKEFILE)
-include Makefile.postamble
-include Makefile.dependencies
