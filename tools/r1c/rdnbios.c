/*
 * rdnbios.c - R1c: copy the video BIOS shadow at physical 0xC0000 to a file.
 *
 * Plan: docs/R1C_R2A_IMPL_PLAN.md section 1-2.  Built and run on the target
 * by tools/r1c/target-r1c.sh; checked on the host by tools/r1c/hostcheck.sh.
 *
 *   rdnbios <runid> <length>
 *
 * What it does, and all it does:
 *   - length must be a multiple of 512 from 512 to 65536, runid a decimal
 *     from 1 to 999999999; otherwise it exits 2 without opening anything
 *   - creates /tmp/rdn-bios-<runid>-<length>.bin with O_EXCL (the name is
 *     built here, never taken from the command line)
 *   - opens the memory device read-only, seeks to the one compiled-in
 *     physical address, reads exactly <length> bytes, closes it
 *   - writes the bytes to the file in one write, fsyncs, closes
 *   - prints one line and exits with a code naming the step that failed
 *
 * The kernel's /dev/mem read maps the physical page at the file offset and
 * copies it out; lseek sets that offset
 * for a character device.  Nothing here writes the device, maps it, or
 * issues an ioctl.  No retries: a short read is a failure.
 *
 * Exit codes: 0 done, 2 arguments or output file, 3 device open or seek,
 * 4 short read, 5 device close, 6 output write, fsync or close.
 *
 * C89 for cc 2.7.2.1: declarations first, no // comments, no long long,
 * no identifier named id, in or out.
 */

#import <libc.h>
#import <sys/fcntl.h>

#ifndef RDN_MEM_PATH
#define RDN_MEM_PATH        "/dev/mem"
#endif

#define BIOS_PHYS           0xC0000
#define CHUNK               512
#define MAX_LENGTH          65536
#define MAX_RUNID           999999999L

static char image[MAX_LENGTH];

/* A decimal number with nothing else around it, within [lo, hi]. */
static int
decimal(const char *s, long lo, long hi, long *value)
{
    long v;
    int digits;

    v = 0;
    digits = 0;
    while (*s >= '0' && *s <= '9') {
        if (digits >= 10)
            return 0;
        v = v * 10 + (*s - '0');
        s++;
        digits++;
    }
    if (digits == 0 || *s != '\0' || v < lo || v > hi)
        return 0;
    *value = v;
    return 1;
}

static void
finish(long runid, long length, int got, int code)
{
    printf("RDNBIOS runid=%u offset=%08x length=%u got=%u first=%02x%02x exit=%d\n",
           (unsigned int)runid, (unsigned int)BIOS_PHYS, (unsigned int)length,
           (unsigned int)got,
           (unsigned int)(got > 0 ? (unsigned char)image[0] : 0),
           (unsigned int)(got > 1 ? (unsigned char)image[1] : 0), code);
    fflush(stdout);
    exit(code);
}

int
main(int argc, char **argv)
{
    long runid;
    long length;
    char path[64];
    int ofd;
    int dfd;
    int got;
    int n;
    off_t where;

    runid = 0;
    length = 0;
    if (argc != 3 || !decimal(argv[1], 1L, MAX_RUNID, &runid) ||
        !decimal(argv[2], (long)CHUNK, (long)MAX_LENGTH, &length) ||
        length % CHUNK != 0) {
        printf("usage: rdnbios <runid 1..999999999> <length: 512..65536, a multiple of 512>\n");
        finish(runid, length, 0, 2);
    }

    sprintf(path, "/tmp/rdn-bios-%u-%u.bin", (unsigned int)runid, (unsigned int)length);
    ofd = open(path, O_WRONLY | O_CREAT | O_EXCL, 0644);
    if (ofd < 0)
        finish(runid, length, 0, 2);

    dfd = open(RDN_MEM_PATH, O_RDONLY);
    if (dfd < 0)
        finish(runid, length, 0, 3);
    where = lseek(dfd, (off_t)BIOS_PHYS, SEEK_SET);
    if (where != (off_t)BIOS_PHYS) {
        close(dfd);
        finish(runid, length, 0, 3);
    }

    got = 0;
    while (got < (int)length) {
        n = read(dfd, image + got, (int)length - got);
        if (n <= 0)
            break;
        got += n;
    }
    if (close(dfd) != 0)
        finish(runid, length, got, 5);
    if (got != (int)length)
        finish(runid, length, got, 4);

    if (write(ofd, image, (int)length) != (int)length)
        finish(runid, length, got, 6);
    if (fsync(ofd) != 0)
        finish(runid, length, got, 6);
    if (close(ofd) != 0)
        finish(runid, length, got, 6);
    finish(runid, length, got, 0);
    return 0;
}
