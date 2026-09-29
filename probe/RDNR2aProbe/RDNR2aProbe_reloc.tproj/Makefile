#
# RDNR2aProbe_reloc - the kernel-loadable body of the R2a probe.
#

NAME = RDNR2aProbe_reloc

PROJECTVERSION = 0.1
LANGUAGE = English

CLASSES = RDNR2aProbe.m RDNR2aMMIO.m
HFILES = RDNR2aMMIO.h
OTHERSRCS = Makefile Makefile.preamble Makefile.postamble\
            Makefile.driver_preamble Load_Commands.sect Unload_Commands.sect

MAKEFILEDIR = /NextDeveloper/Makefiles/app
MAKEFILE = tool.make
SOURCEMODE = 444

-include Makefile.preamble
include $(MAKEFILEDIR)/$(MAKEFILE)
-include Makefile.postamble
-include Makefile.dependencies
