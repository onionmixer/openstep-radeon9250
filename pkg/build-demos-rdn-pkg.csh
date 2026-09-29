#!/bin/csh -f
#
# Build the Mesa port's Demos VARIANT that carries the Radeon demos.
#
#   csh -f .../pkg/build-demos-rdn-pkg.csh [mesa-stage-parent] [overlay]
#
# The shape is openstep-matrox-remade's pkg/build-demos-mga-pkg.csh.  The Mesa
# builder reads THREE variables and all three are set here, because none of
# their defaults is right: MESA_STAGE_PARENT (its default /tmp once gave a
# silent exit 2), MESA_DEMO_OVERLAY (the tree pkg/build-demos-overlay.sh
# wrote), and MESA_DEMO_VARIANT, which names the variant RDN -- unset, the
# builder makes the Matrox one.
#
# The builder wipes its dist directory on every run, so collect this
# variant (pkg/collect-release-pkgs.sh) before building another.
#
if ($#argv >= 1) then
    setenv MESA_STAGE_PARENT "$argv[1]"
else
    setenv MESA_STAGE_PARENT /usr/local/mesastage
endif
if ($#argv >= 2) then
    setenv MESA_DEMO_OVERLAY "$argv[2]"
else
    setenv MESA_DEMO_OVERLAY /tmp/_rdnteapot/overlay
endif
setenv MESA_DEMO_VARIANT RDN

if (! -d "$MESA_STAGE_PARENT/OpenStepMesa342/src") then
    echo "build-demos-rdn-pkg: no staged Mesa tree at $MESA_STAGE_PARENT"
    echo "build-demos-rdn-pkg: run openstep-mesa342/build/stage-openstep-mesa342.csh first"
    exit 2
endif
if (! -d "$MESA_DEMO_OVERLAY/Examples") then
    echo "build-demos-rdn-pkg: no overlay at $MESA_DEMO_OVERLAY"
    echo "build-demos-rdn-pkg: run pkg/build-demos-overlay.sh first"
    exit 2
endif
if (! -r "$MESA_STAGE_PARENT/OpenStepMesa342/src/packaging/openstep/OpenStepMesa342DemosRDN.info") then
    echo "build-demos-rdn-pkg: the staged Mesa tree has no DemosRDN.info -- restage it"
    exit 2
endif

csh -f "$MESA_STAGE_PARENT/OpenStepMesa342/src/packaging/openstep/build-split-packages.csh"
set rc = $status
if ($rc != 0) then
    echo "build-demos-rdn-pkg: the Mesa split builder failed ($rc)"
    exit $rc
endif
if (! -d "$MESA_STAGE_PARENT/OpenStepMesa342/dist/OpenStepMesa342DemosRDN.pkg") then
    echo "build-demos-rdn-pkg: the builder did not make OpenStepMesa342DemosRDN.pkg"
    exit 1
endif
echo "build-demos-rdn-pkg: PASS $MESA_STAGE_PARENT/OpenStepMesa342/dist"
exit 0
