#
# OSRDNDisplay - PCI Radeon 9250 (RV280) display driver bundle, R2b-0 record
# build (docs/R2B0_IMPL_PLAN.md section 3).  The kernel driver is the TOOLS
# subproject.
#
# The bundle executable holds the Configure.app inspector
# (OSRDNDisplayInspector, old-AppKit code loaded inside Configure; R3d,
# docs/R3_MULTIMODE_PLAN.md 25-26).  Without CLASSES bundle.make still builds
# that executable, empty ("Building empty bundle"), so what the inspector
# changes is its content, not its presence.  The reloc DOES see this
# makefile's flags -- common.make passes PROJ_CFLAGS down to TOOLS as
# PROPOGATED_CFLAGS -- which is harmless for -I./compat (no such directory
# under the tproj) and is checked on the machine by comparing the reloc's
# compile lines before and after (26-3 H4).
#

NAME = OSRDNDisplay

PROJECTVERSION = 0.1
LANGUAGE = English

LOCAL_RESOURCES = Localizable.strings DisplayInspector.nib
# Display.modes lists all twenty combinations, as the Matrox driver does
# (docs/R3_MULTIMODE_PLAN.md 24-21); tools/r3/check_bundle_modes.py holds it
# to the oracle and to the tables' "Display Mode".
GLOBAL_RESOURCES = Default.table Instance0.table Display.modes
CLASSES = OSRDNDisplayInspector.m
HFILES = OSRDNDisplayInspector.h osrdn_graypanel.h
TOOLS = OSRDNDisplay_reloc.tproj

OTHERSRCS = Makefile Makefile.preamble Makefile.postamble compat

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
