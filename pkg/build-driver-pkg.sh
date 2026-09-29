#!/bin/sh
# Build the OPENSTEP Installer package for the display driver.
#
#   sh .../pkg/build-driver-pkg.sh [source-root] [outdir] [build-top]
#
# Runs ON the target: the package tool is OPENSTEP's.  The shape is
# openstep-matrox-remade's pkg/build-driver-pkg.sh; what differs is where the
# bundle comes from and which gates it must have passed.
#
# THE BUNDLE IS THE ONE THE INSTALLER WOULD INSTALL.  tools/r2b0/
# target-build-r2b0.sh builds it under /tmp/OSRDNDisplay-r2b0 from a tree the
# host packed and stamped, and tools/r2b0/target-install-r2b0.sh installs it
# only after (a) the build marker in the tree equals the one on NFS, (b) the
# reloc is the bytes that marker names, and (c) the host's disassembly gate
# (tools/r2b0/check_reloc_r2b0.py) wrote R2B0RELOC_PASS for those bytes.  The
# package asks the same three, and then the installer's structural checks
# (one "Server Name" per table, every member present and non-empty, nothing
# linked or writable by others), so it cannot seal a bundle the installer
# would have refused.  (docs/REL1_PACKAGING_PLAN.md 11-1, 12.)
set -e
SRC="${1:-/ndrv/openstep-radeon9250}"
OUT="${2:-/tmp/pkgout}"
TOP="${3:-/tmp/OSRDNDisplay-r2b0}"
NFSOUT="$SRC/build/r2b0"
NAME=OSRDNDisplay
PKGTOOL=/NextAdmin/Installer.app/package
BUNDLE="$TOP/$NAME/$NAME.config"
DOCDIR=OpenStep-Radeon9250

if [ ! -x "$PKGTOOL" ]; then
    echo "build-driver-pkg: $PKGTOOL not found (run on OPENSTEP)" >&2
    exit 1
fi
if [ "`/usr/bin/arch`" != i386 ]; then
    echo "build-driver-pkg: the payload is i386; build it on i386" >&2
    exit 1
fi

# 1. the build and its gates, exactly as target-install-r2b0.sh asks them
if [ ! -f "$TOP/OSRDNBUILD_PASS" ] || [ ! -f "$TOP/RUNID" ]; then
    echo "build-driver-pkg: no $TOP/OSRDNBUILD_PASS -- run target-build-r2b0.sh first (this boot)" >&2
    exit 1
fi
RUNID=`cat "$TOP/RUNID"`
# `| wc -l`, not grep -c: under set -e a count of 0 exits the script with
# nothing said (recorded trap).  wc pads, so the test is numeric.
ok=`echo "$RUNID" | grep '^[0-9][0-9]*$' | wc -l`
if [ $ok -ne 1 ]; then
    echo "build-driver-pkg: runid malformed: '$RUNID'" >&2
    exit 1
fi
if [ ! -f "$NFSOUT/$RUNID/BUILD_PASS" ]; then
    echo "build-driver-pkg: no $NFSOUT/$RUNID/BUILD_PASS" >&2
    exit 1
fi
if [ "`cat $TOP/OSRDNBUILD_PASS`" != "`cat $NFSOUT/$RUNID/BUILD_PASS`" ]; then
    echo "build-driver-pkg: OSRDNBUILD_PASS and BUILD_PASS differ" >&2
    exit 1
fi
RSUM=`awk '{ print $3, $4 }' "$NFSOUT/$RUNID/BUILD_PASS"`
if [ "`/usr/bin/sum $BUNDLE/${NAME}_reloc | awk '{print $1, $2}'`" != "$RSUM" ]; then
    echo "build-driver-pkg: the built reloc is not the bytes BUILD_PASS names" >&2
    exit 1
fi
if [ ! -f "$NFSOUT/$RUNID/R2B0RELOC_PASS" ]; then
    echo "build-driver-pkg: no R2B0RELOC_PASS -- run tools/r2b0/check_reloc_r2b0.py on the host first" >&2
    exit 1
fi
if [ "`cat $NFSOUT/$RUNID/R2B0RELOC_PASS`" != "$RSUM" ]; then
    echo "build-driver-pkg: R2B0RELOC_PASS does not name these reloc bytes ($RSUM)" >&2
    exit 1
fi
echo "build-driver-pkg: runid $RUNID reloc $RSUM"

for f in "$BUNDLE/${NAME}_reloc" "$BUNDLE/$NAME" \
         "$BUNDLE/Default.table" "$BUNDLE/Instance0.table" "$BUNDLE/Display.modes" \
         "$BUNDLE/English.lproj/Localizable.strings" \
         "$BUNDLE/English.lproj/DisplayInspector.nib/data.nib" \
         "$BUNDLE/English.lproj/DisplayInspector.nib/data.classes" \
         "$BUNDLE/English.lproj/DisplayInspector.nib/data.dependency" \
         "$SRC/pkg/$NAME.info" "$SRC/pkg/$NAME.pre_install" \
         "$SRC/pkg/$NAME.post_install" "$SRC/pkg/osrdn-identity-keys.awk" \
         "$SRC/LICENSE" "$SRC/NOTICE" "$SRC/release-packaging/INSTALL.md"; do
    if [ ! -s "$f" ]; then
        echo "build-driver-pkg: missing or empty input: $f" >&2
        exit 1
    fi
done
# NOT `if ! cmd`: this sh has no command negation.
if file "$BUNDLE/${NAME}_reloc" | grep 'Mach-O preloaded' > /dev/null; then
    :
else
    echo "build-driver-pkg: ${NAME}_reloc is not a preloaded relocatable" >&2
    exit 1
fi

# 2. the release identity: the bundle's tables ARE the release tables
#    (docs/REL1_PACKAGING_PLAN.md D7 -- the five switches stay on, which is
#    the configuration every measurement ran).  What must not ship is the
#    development title or version, or a table the build did not finish.
v=`grep '^Version ' "$SRC/pkg/$NAME.info" | sed 's/^Version //'`
for t in Default.table Instance0.table; do
    if grep 'R2b-0' "$BUNDLE/$t" > /dev/null; then
        echo "build-driver-pkg: $t still carries the development title" >&2
        exit 1
    fi
    if grep "^\"Version\" = \"$v\";" "$BUNDLE/$t" > /dev/null; then
        :
    else
        echo "build-driver-pkg: $t's Version is not $v (the package's)" >&2
        exit 1
    fi
    all=`grep '"Server Name"' "$BUNDLE/$t" | wc -l`
    ours=`grep '^"Server Name" = "OSRDNDisplay";$' "$BUNDLE/$t" | wc -l`
    if [ $all -ne 1 ] || [ $ours -ne 1 ]; then
        echo "build-driver-pkg: $t holds $all \"Server Name\" line(s), $ours naming $NAME (want 1 and 1)" >&2
        exit 1
    fi
done

# `package` builds the BOM from the stage's PARENT, so the stage needs a
# private empty parent or every file beside it lands in the BOM.
STAGEPARENT=/tmp/_rdndrvpkg
STAGE="$STAGEPARENT/p"
rm -rf "$STAGEPARENT" "$OUT/$NAME.pkg" "$OUT/$NAME.pkg.tar"
/bin/mkdirs "$STAGE/private/Drivers/i386/$NAME.config/English.lproj" \
            "$STAGE/usr/local/Documentation/$DOCDIR"

D="$STAGE/private/Drivers/i386/$NAME.config"
cp "$BUNDLE/${NAME}_reloc" "$BUNDLE/$NAME" "$BUNDLE/Default.table" \
   "$BUNDLE/Instance0.table" "$BUNDLE/Display.modes" "$D/"
cp "$BUNDLE/English.lproj/Localizable.strings" "$D/English.lproj/"
( cd "$BUNDLE/English.lproj" && tar cf - DisplayInspector.nib ) \
    | ( cd "$D/English.lproj" && tar xf - )
rm -f "$D/.lastBuildTime"
cp "$SRC/LICENSE" "$SRC/NOTICE" "$SRC/release-packaging/INSTALL.md" \
   "$STAGE/usr/local/Documentation/$DOCDIR/"

for n in data.classes data.dependency data.nib; do
    if [ ! -s "$D/English.lproj/DisplayInspector.nib/$n" ]; then
        echo "build-driver-pkg: nib file missing from stage: $n" >&2
        exit 1
    fi
done
# the installer's structural refusals, on the stage
bad=`find "$STAGE" -type l -print | wc -l`
if [ $bad != 0 ]; then echo "build-driver-pkg: a symlink in the stage" >&2; exit 1; fi
bad=`find "$STAGE" ! -type f ! -type d -print | wc -l`
if [ $bad != 0 ]; then echo "build-driver-pkg: not a regular file or directory in the stage" >&2; exit 1; fi
bad=`find "$STAGE" -type f -size 0 -print | wc -l`
if [ $bad != 0 ]; then echo "build-driver-pkg: an empty file in the stage" >&2; exit 1; fi
chmod -R go-w "$STAGE"

test -d "$OUT" || /bin/mkdirs "$OUT"
# post_install reads the identity-key transform out of the installed layout,
# so it has to be IN the payload -- copied before `package` walks the stage.
cp "$SRC/pkg/osrdn-identity-keys.awk" "$STAGE/private/Drivers/i386/osrdn-identity-keys.awk"
chmod 444 "$STAGE/private/Drivers/i386/osrdn-identity-keys.awk"

# NOTHING may reach installer_tar's 100-character limit, or `package` drops it
# in silence.  Checked against the stage, before sealing.
long=`find "$STAGE" -print | sed "s|^$STAGE|.|" | awk 'length($0) >= 100'`
if [ -n "$long" ]; then
    echo "build-driver-pkg: these paths are 100 characters or more and" >&2
    echo "build-driver-pkg: installer_tar would drop them silently:" >&2
    echo "$long" >&2
    exit 1
fi

"$PKGTOOL" "$STAGE" "$SRC/pkg/$NAME.info" -d "$OUT" < /dev/null

# BOTH hooks.
cp "$SRC/pkg/$NAME.pre_install"  "$OUT/$NAME.pkg/$NAME.pre_install"
cp "$SRC/pkg/$NAME.post_install" "$OUT/$NAME.pkg/$NAME.post_install"
chmod 555 "$OUT/$NAME.pkg/$NAME.pre_install" "$OUT/$NAME.pkg/$NAME.post_install"
echo "$RUNID $RSUM" > "$OUT/$NAME.pkg.buildid"
echo "build-driver-pkg: PASS $OUT/$NAME.pkg (runid $RUNID)"
