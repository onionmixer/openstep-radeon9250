#
# RDNR1Probe - R1 interrogation of a PCI Radeon 9250 (docs/R1_INTERROGATION_PLAN.md).
# A bare loadable bundle: no DriverKit matching, loaded by kl_util, run once.
#

NAME = RDNR1Probe

PROJECTVERSION = 0.1
LANGUAGE = English

LOCAL_RESOURCES = Localizable.strings
GLOBAL_RESOURCES = Default.table
TOOLS = RDNR1Probe_reloc.tproj

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
