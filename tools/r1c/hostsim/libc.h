/* hostsim/libc.h -- Linux stand-in for NeXT's <libc.h>, used only by
 * tools/r1c/sim_r1c.py to build tools/r1c/rdnbios.c unchanged on the host.
 * The target build uses the real header (hostcheck.sh checks it with the
 * mirror); this file only supplies the same functions from glibc. */
#include <fcntl.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
