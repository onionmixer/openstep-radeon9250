#!/bin/sh
# Fetch the public reference sources this project reads.  Nothing fetched
# here is committed: ref/upstream/ is ignored, and ref/README.md says what
# each item is for.  Rerunning skips files that are already present.
#
# Every item is a third-party work under its own licence.  Reading it for
# register facts is not the same as copying it; see PLAN.md "라이선스".

set -e
failed=no
here=`dirname "$0"`
dest="$here/../ref/upstream"
mkdir -p "$dest"
cd "$dest"

get() {
    # get <local-name> <url>
    if [ -s "$1" ]; then
        echo "have  $1"
        return 0
    fi
    mkdir -p "`dirname "$1"`"
    echo "fetch $1"
    if curl -fsSL --retry 3 --max-time 600 -o "$1.part" "$2"; then
        mv "$1.part" "$1"
    else
        rm -f "$1.part"
        echo "FAILED $1" >&2
        failed=yes
    fi
}

# 2D / mode setting: the last xf86-video-ati that still carries the legacy
# (non-KMS, non-AtomBIOS) CRTC, PLL and output code RV280 uses.
get xf86-video-ati-6.14.6.tar.bz2 \
    https://xorg.freedesktop.org/releases/individual/driver/xf86-video-ati-6.14.6.tar.bz2

# 3D: classic r200 DRI driver, two generations.
get mesa-amber.tar.gz \
    https://gitlab.freedesktop.org/mesa/mesa/-/archive/amber/mesa-amber.tar.gz
get MesaLib-6.5.3.tar.gz \
    https://archive.mesa3d.org/older-versions/6.x/MesaLib-6.5.3.tar.gz

# Kernel side: the user-mode-setting Radeon DRM (CP ring, PCI GART, state
# verifier).  v3.10 still has it; later kernels removed it.
L=https://raw.githubusercontent.com/torvalds/linux/v3.10
for f in radeon_cp.c radeon_state.c radeon_drv.h radeon_irq.c radeon_mem.c \
         radeon_drv.c r300_cmdbuf.c \
         r100.c radeon_reg.h radeon_asic.c; do    # KMS: CP init/ring test for RV280 (r200_asic), R5 review
    get linux-3.10/drivers/gpu/drm/radeon/$f $L/drivers/gpu/drm/radeon/$f
done
get linux-3.10/drivers/gpu/drm/ati_pcigart.c $L/drivers/gpu/drm/ati_pcigart.c
# drm_order(): the ring size encoding in CP_RB_CNTL (R5 sequence oracle)
get linux-3.10/drivers/gpu/drm/drm_bufs.c \
    "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/plain/drivers/gpu/drm/drm_bufs.c?h=v3.10"
get linux-3.10/include/uapi/drm/radeon_drm.h $L/include/uapi/drm/radeon_drm.h
get linux-3.10/include/drm/drm_pciids.h \
    "https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/plain/include/drm/drm_pciids.h?h=v3.10"

# CP microcode.  WHENCE gives its licence (MIT for radeon/R200_cp.bin).
F=https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git/plain
get linux-firmware/radeon/R200_cp.bin $F/radeon/R200_cp.bin
get linux-firmware/WHENCE $F/WHENCE

# Framebuffer-only driver on a non-DRM kernel: closest in shape to ours.
N=https://cvsweb.netbsd.org/bsdweb.cgi/~checkout~/src/sys/dev/pci
for f in radeonfb.c radeonfbvar.h radeonfbreg.h radeonfb_bios.c; do
    get netbsd/sys/dev/pci/$f $N/$f
done
# PCI-PCI bridge window registers (R1 probe path check): 64-bit prefetch
# upper halves, header type
for f in ppbreg.h pcireg.h; do
    get netbsd/sys/dev/pci/$f $N/$f
done
# R3: the VESA DMT table NetBSD radeonfb uses (videomode_list), an upstream
# source independent of this workspace -- the oracle's mode timings are
# checked against it.  cvsweb answered 503 on 2026-09-17, so the NetBSD src
# mirror on GitHub is used for these three.
V=https://raw.githubusercontent.com/NetBSD/src/trunk/sys/dev/videomode
for f in videomode.c modelines modelines2c.awk; do
    get netbsd/sys/dev/videomode/$f $V/$f
done

# The BSD counterpart of the Linux UMS DRM above: FreeBSD's legacy
# sys/dev/drm (pre-KMS), with the R200 microcode as a header.  This is the
# primary kernel-side reference; the Linux copy is kept for cross-checking.
B="https://cgit.freebsd.org/src/plain/sys/dev/drm"
for f in radeon_cp.c radeon_microcode.h radeon_state.c radeon_drv.h \
         radeon_drv.c radeon_irq.c radeon_mem.c radeon_drm.h r300_cmdbuf.c \
         r300_reg.h ati_pcigart.c drm_pciids.h; do
    get freebsd-stable9/sys/dev/drm/$f "$B/$f?h=stable/9"
done

get xfree86-4.4-DRI.pdf https://www.xfree86.org/4.4.0/DRI.pdf

if [ $failed = yes ]; then
    echo "some items failed; rerun later" >&2
    exit 1
fi
echo done
