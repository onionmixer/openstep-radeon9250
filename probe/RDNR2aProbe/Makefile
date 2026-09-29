#
# RDNR2aProbe - R2a MMIO and PLL snapshot of a PCI Radeon 9250 (docs/R1C_R2A_IMPL_PLAN.md).
# A bare loadable bundle: no DriverKit matching, loaded by kl_util, run once.
#

NAME = RDNR2aProbe

PROJECTVERSION = 0.1
LANGUAGE = English

LOCAL_RESOURCES = Localizable.strings
GLOBAL_RESOURCES = Default.table
TOOLS = RDNR2aProbe_reloc.tproj

OTHERSRCS = Makefile Makefile.preamble Makefile.postamble

MAKEFILEDIR = /NextDeveloper/Makefiles/app
MAKEFILE = bundle.make
INSTALLDIR = /private/Devices
INSTALLFLAGS = -c -s -m 755
SOURCEMODE = 444
BUNDLE_EXTENSION = config

-include Makefile.preamble
include $(MAKEFILEDIR)/$(MAKEFILE)
-include Makefile.postamble
-include Makefile.dependencies
