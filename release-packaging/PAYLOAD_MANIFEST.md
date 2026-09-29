# Payload manifest

Every file each package installs, where it comes from, and where it goes.
Anything not listed here is not shipped.  The shape and most of the hazards
are openstep-matrox-remade's (`release-packaging/PAYLOAD_MANIFEST.md`
there); what differs is written here.  The plan behind it is
`docs/REL1_PACKAGING_PLAN.md`.

## 1. `OSRDNDisplay.pkg` -- the driver

`DefaultLocation /`, not relocatable, `NeedsAuthorization YES`,
`DisableSparseInstall YES`.  Installs; does NOT activate.

| Destination | Source |
| --- | --- |
| `/private/Drivers/i386/OSRDNDisplay.config/OSRDNDisplay_reloc` | built on the target by `tools/r2b0/target-build-r2b0.sh`; its bytes must be the ones `BUILD_PASS` names and the host's disassembly gate passed (`R2B0RELOC_PASS`) |
| `.../OSRDNDisplay` | the Configure inspector, same build |
| `.../Default.table`, `.../Instance0.table` | `OSRDNDisplay/` -- the release tables ARE the source tables (five switches `Yes`, `Version` = the package's) |
| `.../Display.modes` | `OSRDNDisplay/Display.modes`, byte for byte, 5 x 4 |
| `.../English.lproj/Localizable.strings`, `.../English.lproj/DisplayInspector.nib/{data.classes,data.dependency,data.nib}` | same build |
| `/private/Drivers/i386/osrdn-identity-keys.awk` | `pkg/` -- post_install runs it |
| `/usr/local/Documentation/OpenStep-Radeon9250/{LICENSE,NOTICE,INSTALL.md}` | repository; `NOTICE` is required -- the CP microcode compiled into the reloc is MIT with a notice condition |

pre_install stashes the machine's instance tables beside the bundle;
post_install puts them back and rewrites only the six identity keys.

## 2. `OSRDNMesaAccel.pkg` -- the library

`DefaultLocation /LocalDeveloper`, relocatable, i386-only.

| Destination | Source |
| --- | --- |
| `Libraries/libGL_radeon.a` | `build/m1b/<runid>/libGL_radeon.a` from `tools/mesa/target-build-mesa.sh`; its bytes must be the ones `M1B_PASS` names, written by `pkg/host_release_gates.py --lib` only when `tools/mesa/judge_m1b.py` passes |
| `Headers/OSRDNMesa{Class,Depth,Hook,Present,Probe,Surface,Tex,Time,Tri,TriTable}.h` | `mesa/` -- the include closure of the two demos |
| `Documentation/OpenStep-Radeon9250-Accel/Mesa-3.4.2/{COPYRIGHT,COPYING,README.Mesa}` | the Mesa port's `upstream/Mesa-3.4.2/docs/`, byte for byte |
| `Documentation/OpenStep-Radeon9250-Accel/{PORT-NOTES.md,LICENSE,NOTICE}` | repository |
| `Tools/OSRDNAccel-Intel` | the Mesa port's `packaging/openstep/installer-architecture-marker.c` |

## 3. `OpenStepMesa342DemosRDN.pkg` -- the Mesa port's Demos, with ours

Built by the Mesa port's `build-split-packages.csh` with
`MESA_DEMO_OVERLAY` pointing at the tree `pkg/build-demos-overlay.sh` staged
and `MESA_DEMO_VARIANT=RDN`.  Version `3.4.2-openstep.1+rdn.1`.  Install
this, the Matrox variant or the plain Demos package -- one of the three.

| Destination | Source |
| --- | --- |
| `Examples/Mesa342/RDNTeapot/{osrdn-mesa-teapot.c,osrdn-mesa-nocount.c}` | `test/` |
| `Examples/Mesa342/RDNTeapot/{build-teapot.csh,README_teapot.md}` | `examples/` |
| `Examples/Mesa342/RDNTeapot/rdnteapot_sw` | built by the shipped script: stock libGL.a + the nocount stubs; no Radeon library |
| `Examples/Mesa342/RDNTeapot/rdnteapot_hybrid` | same script, `libGL_radeon.a` |
| `Examples/Mesa342/RDNSDLTeapot/{osrdn-sdl-teapot.c,build-sdl-teapot.csh,README_sdlteapot.md}` | `test/`, `examples/` -- source only; the build is checked at packaging and the binaries are not shipped |
| `.../{NOTICE,COPYRIGHT}` in both | repository `NOTICE`; Mesa's `COPYRIGHT` |

`rdnteapot_sw` is told apart from the hybrid by `OpenStepMesaAccelBuffer`,
not by OSRDN names: the nocount stubs carry those names, while the hook entry
exists only in the accelerated `osmesa.o`.  The verifier also RUNS the pair:
the hybrid with `RDNMesaAccelOff=1` must write the stock picture byte for
byte.

## Exclusions

| Not shipped | Why |
| --- | --- |
| `.lastBuildTime` | build residue |
| the development tools the driver build also makes (`rdnr2b0`, `rdnr4map`, `rdnr5cp`, `rdnr7sub`) | this project's instruments, not the product |
| `teapot-geometry.h` | cut from Mesa's `tea.c` at build time; the binaries carry the geometry under SGI's grant, the file itself stays out of the repository |
| `libGL.a`, `libGLU.a` | the Mesa port's to ship |
| `docs/review/`, `build/`, `ref/` | development material |

## How the release is built, in order

Steps on the target unless marked HOST.  Nothing here installs anything.

```sh
# 1. the driver (host packs, target builds, host judges)
python3 tools/r2b0/pack_r2b0.py ...                     # HOST: stamp and tar
sh tools/r2b0/target-build-r2b0.sh <tar> <sum> <blocks>
python3 tools/r2b0/check_reloc_r2b0.py <reloc> <sum> <blocks> --marker build/r2b0/<runid>   # HOST
python3 pkg/host_release_gates.py --driver <runid>      # HOST

# 2. the library
sh tools/mesa/target-build-mesa.sh <libid>
python3 pkg/host_release_gates.py --lib <libid>         # HOST

# 3. this project's two packages
sh pkg/build-driver-pkg.sh
sh pkg/build-accel-pkg.sh <libid>

# 4. the demos variant
sh pkg/build-demos-overlay.sh <libid>
csh -f /ndrv/openstep-mesa342/build/stage-openstep-mesa342.csh /ndrv
csh -f pkg/build-demos-rdn-pkg.csh

# 5. verify, without installing anything
sh pkg/verify-driver-pkg.sh
sh pkg/verify-accel-pkg.sh
sh pkg/verify-demos-rdn-pkg.sh
sh pkg/check-bom-overlap.sh
sh pkg/diff-against-installed.sh              # what an install would change here

# 6. collect -- BEFORE the Mesa builder runs again (it wipes dist)
sh pkg/collect-release-pkgs.sh

# 7. HOST: compress, name, checksum
bash pkg/make-release-assets.sh 1.0
```

**Editing a shipped file invalidates the built packages** -- `INSTALL.md`,
`PORT-NOTES.md`, `LICENSE`, `NOTICE`, the headers, the demo sources and
scripts are payload.  Every verifier compares what it unpacks with its
source copy, so a stale package fails instead of shipping.
