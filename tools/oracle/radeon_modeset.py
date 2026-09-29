#!/usr/bin/env python3
"""Host oracle for the RV280 legacy CRTC/PLL register values.

Independent re-statement of two reference formulas, so the C89 driver can be
checked against something that is not itself:

  * NetBSD radeonfb (primary reference):
      radeonfb_calc_dividers  netbsd/sys/dev/pci/radeonfb.c:1739-1779
      radeonfb_setcrtc        netbsd/sys/dev/pci/radeonfb.c:2519-2577
      divider table           netbsd/sys/dev/pci/radeonfb.c:397-407
      DIVIDE()                netbsd/sys/dev/pci/radeonfbvar.h:355
  * xf86-video-ati 6.14.6 legacy (cross-check of the CRTC words):
      RADEONInitCrtcRegisters xf86-video-ati-6.14.6/src/legacy_crtc.c:878-969

Frequencies are kHz, as in radeonfb after getclocks multiplies by ten.
Run with no arguments to print the table and run the self-checks.
"""

import hashlib
import os
import re
import sys

# radeonfb.c:397-407 -- {divider, mask}, searched in this order
RFB_DIVIDERS = [(16, 5), (12, 7), (8, 3), (6, 6), (4, 2), (3, 4), (2, 1), (1, 0)]
# legacy_crtc.c post_divs -- {divider, bitvalue}
XF86_POST_DIVS = [(1, 0), (2, 1), (4, 2), (8, 3), (3, 4), (16, 5), (6, 6), (12, 7)]

H_SYNC_POL = 1 << 23          # radeonfbreg.h:483
V_SYNC_POL = 1 << 23          # radeonfbreg.h:556
FB3_DIV_MASK = 0x07ff         # radeonfbreg.h:1525
POST3_DIV_MASK = 0x00070000   # radeonfbreg.h:1526


def divide(x, y):
    """radeonfbvar.h:355  #define DIVIDE(x,y) (((x) + (y / 2)) / (y))"""
    return (x + y // 2) // y


def rfb_calc_dividers(dotclock, refclk, refdiv, minpll, maxpll, no_odd_fbdiv=False):
    """radeonfb_calc_dividers; returns (postdivbit, feedback, div, outfreq) or None.

    Note the reference skips odd DIVIDERS (not odd feedback values) when
    NO_ODD_FBDIV is set (radeonfb.c:1749); that is reproduced as written.
    """
    for div, mask in RFB_DIVIDERS:
        if no_odd_fbdiv and (div & 1):
            continue
        outfreq = div * dotclock
        if minpll <= outfreq <= maxpll:
            return (mask << 16, divide(refdiv * outfreq, refclk), div, outfreq)
    return None


def rfb_crtc_words(m):
    """radeonfb_setcrtc, CRTC1 branch (radeonfb.c:2528-2576)."""
    h_total_disp = (((m['hdisp'] // 8) - 1) << 16) | ((m['htotal'] // 8) - 1)
    h_sync = (((m['hsend'] - m['hsstart']) // 8) << 16) | (m['hsstart'] - 8)
    if m['nhsync']:
        h_sync |= H_SYNC_POL
    v_total_disp = ((m['vdisp'] - 1) << 16) | (m['vtotal'] - 1)
    v_sync = ((m['vsend'] - m['vsstart']) << 16) | (m['vsstart'] - 1)
    if m['nvsync']:
        v_sync |= V_SYNC_POL
    return h_total_disp, h_sync, v_total_disp, v_sync


def xf86_crtc_words(m):
    """RADEONInitCrtcRegisters (legacy_crtc.c:928-953), with its masks."""
    h_total_disp = ((((m['htotal'] // 8) - 1) & 0x3ff)
                    | ((((m['hdisp'] // 8) - 1) & 0x1ff) << 16))
    hsync_wid = (m['hsend'] - m['hsstart']) // 8 or 1
    hsync_start = m['hsstart'] - 8
    h_sync = ((hsync_start & 0x1fff) | ((hsync_wid & 0x3f) << 16)
              | (H_SYNC_POL if m['nhsync'] else 0))
    v_total_disp = ((m['vtotal'] - 1) & 0xffff) | ((m['vdisp'] - 1) << 16)
    vsync_wid = (m['vsend'] - m['vsstart']) or 1
    v_sync = (((m['vsstart'] - 1) & 0xfff) | ((vsync_wid & 0x1f) << 16)
              | (V_SYNC_POL if m['nvsync'] else 0))
    return h_total_disp, h_sync, v_total_disp, v_sync


# VESA DMT timings copied from openstep-matrox-remade, where all five were
# shown on a monitor: OSMGADisplay_reloc.tproj/OpenStepMGAReplacementDisplay.m
# osmgaRes[] (:1478-1486).  nhsync/nvsync are that table's hSyncNeg/vSyncNeg.
# check_against_matrox() re-reads that table so a typo here cannot survive.
MODES = [
    dict(name='640x480@60', clock=25175, hdisp=640, hsstart=656, hsend=752, htotal=800,
         vdisp=480, vsstart=490, vsend=492, vtotal=525, nhsync=1, nvsync=1),
    dict(name='800x600@60', clock=40000, hdisp=800, hsstart=840, hsend=968, htotal=1056,
         vdisp=600, vsstart=601, vsend=605, vtotal=628, nhsync=0, nvsync=0),
    dict(name='1024x768@60', clock=65000, hdisp=1024, hsstart=1048, hsend=1184, htotal=1344,
         vdisp=768, vsstart=771, vsend=777, vtotal=806, nhsync=1, nvsync=1),
    dict(name='1280x1024@60', clock=108000, hdisp=1280, hsstart=1328, hsend=1440, htotal=1688,
         vdisp=1024, vsstart=1025, vsend=1028, vtotal=1066, nhsync=0, nvsync=0),
    dict(name='1600x1200@60', clock=162000, hdisp=1600, hsstart=1664, hsend=1856, htotal=2160,
         vdisp=1200, vsstart=1201, vsend=1204, vtotal=1250, nhsync=0, nvsync=0),
]

# radeonfb.c:1671-1687 no-BIOS defaults, x10 at :1730-1734
DEFAULT_CLOCKS = dict(refclk=27000, refdiv=12, minpll=125000, maxpll=400000)


def report(clocks=DEFAULT_CLOCKS):
    rows = []
    for m in MODES:
        r = rfb_calc_dividers(m['clock'], clocks['refclk'], clocks['refdiv'],
                              clocks['minpll'], clocks['maxpll'])
        if r is None:
            rows.append((m['name'], None))
            continue
        pbit, fb, div, outfreq = r
        actual = clocks['refclk'] * fb / clocks['refdiv'] / div
        err = (actual - m['clock']) / m['clock'] * 1e6
        refresh = actual * 1000.0 / (m['htotal'] * m['vtotal'])
        rfb = rfb_crtc_words(m)
        x86 = xf86_crtc_words(m)
        # vco is the REALIZED VCO (refclk*fb/refdiv), not the requested div*dotclock:
        # for 800x600@60 they are 319500 and 320000 kHz.  A range gate must use
        # the realized one.
        rows.append((m['name'], dict(div=div, fb=fb, vco=clocks['refclk'] * fb // clocks['refdiv'],
                                     vco_requested=outfreq, div_word=pbit | fb,
                                     actual=actual, ppm=err, refresh=refresh,
                                     rfb=rfb, xf86=x86, fb_fits=fb <= FB3_DIV_MASK)))
    return rows


def check_against_matrox():
    """Re-read osmgaRes[] from the sibling Matrox tree when it is present.

    Returns (compared, differences); (None, 0) when the tree is absent, which
    is reported, not treated as a pass.  A present file that yields no rows is
    a FAILURE (the pattern no longer matches), never "absent".
    """
    import os, re
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, '..', '..', '..', 'openstep-matrox-remade', 'OSMGADisplay',
                        'OSMGADisplay_reloc.tproj', 'OpenStepMGAReplacementDisplay.m')
    if not os.path.exists(path):
        return None, 0
    rows = re.findall(r'\{\s*"(\d+x\d+)",' + r'\s*(\d+),' * 8 + r'\s*(\d+)UL,\s*(\d),\s*(\d)\s*\}',
                      open(path).read())
    diffs = 0
    for r, m in zip(rows, MODES):
        ref = tuple(int(x) for x in r[1:])
        mine = (m['hdisp'], m['vdisp'], m['hsstart'], m['hsend'], m['htotal'], m['vsstart'],
                m['vsend'], m['vtotal'], m['clock'], m['nhsync'], m['nvsync'])
        if ref != mine:
            print('DIFF', r[0], mine, ref)
            diffs += 1
    if len(rows) != len(MODES):
        print('matrox table: parsed %d rows, expected %d' % (len(rows), len(MODES)))
        diffs += 1
    return len(rows), diffs


# ---- R2b additions: the values the driver writes besides the CRTC words ----
#
# GRPH_BUFFER_CNTL bit fields, xf86 radeon_reg.h:356-365.
GRPH_START_MASK, GRPH_START_SHIFT = 0x7f, 0
GRPH_STOP_MASK, GRPH_STOP_SHIFT = 0x7f << 8, 8
GRPH_CRIT_MASK, GRPH_CRIT_SHIFT = 0x7f << 16, 16
GRPH_CRITICAL_CNTL = 1 << 28
GRPH_BUFFER_SIZE = 1 << 29
GRPH_CRITICAL_AT_SOF = 1 << 30
GRPH_STOP_CNTL = 1 << 31
RV100_MAX_STOP_REQ = 0x5c          # legacy_crtc.c: IS_RV100_VARIANT branch


def fifo(mode, pixel_bytes, max_stop_req=None, critical_point=0):
    """GRPH_BUFFER_CNTL as an integer-only read-modify-write.

    xf86's RADEONInitDispBandwidthLegacy computes the critical point in C
    `float` from the memory timing registers.  A kernel driver here has no
    floating point, so this oracle takes xf86's own DispPriority == 2
    ("HIGH") path, where the critical point is 0 and GRPH_CRITICAL_CNTL is
    cleared -- which that source says "will thus force high priority all the
    time".  Everything else in the register is the same integer arithmetic
    xf86 does.  NetBSD's radeonfb never writes this register at all.
    """
    if max_stop_req is None:          # read the module constant at CALL time:
        max_stop_req = RV100_MAX_STOP_REQ    # a default argument would freeze it
    stop_req = min(mode['hdisp'] * pixel_bytes // 16, max_stop_req)
    # THE CARD KEEPS ONLY MULTIPLES OF 4 in these two fields.  Measured
    # 2026-09-18 (boot fa2dcdbd, docs/R3_MULTIMODE_PLAN.md 24-14): at
    # 800x600 8 bpp the driver wrote 50 (0x32) into both and read back 48
    # (0x30); 92 (0x5c) was written and read back unchanged in six boots, and
    # 50 being even rules out a granularity of 2.  No reference documents it:
    # xf86 states the value as an upper bound ("GRPH_STOP_REQ <= MIN[...]",
    # legacy_crtc.c 1595) and never reads it back, NetBSD never writes the
    # register.  Rounding DOWN keeps xf86's inequality and makes what we write
    # what the card holds, which is what the entry's read-back compares.
    stop_req &= ~3
    if stop_req < 4:                  # no mode in the table comes near (the
        raise ValueError('stop_req %d: a mode this narrow has never been checked'
                         % stop_req)  # smallest is 40), and 0 is not a value
    start_req = stop_req                       # the R350-only adjustment does not apply
    set_bits = ((stop_req << GRPH_STOP_SHIFT) & GRPH_STOP_MASK |
                (start_req << GRPH_START_SHIFT) & GRPH_START_MASK |
                (critical_point << GRPH_CRIT_SHIFT) & GRPH_CRIT_MASK |
                GRPH_BUFFER_SIZE)
    clear_bits = (GRPH_STOP_MASK | GRPH_START_MASK | GRPH_CRIT_MASK |
                  GRPH_CRITICAL_CNTL | GRPH_BUFFER_SIZE | GRPH_CRITICAL_AT_SOF | GRPH_STOP_CNTL)
    return dict(stop_req=stop_req, start_req=start_req, critical_point=critical_point,
                set_bits=set_bits, clear_bits=clear_bits,
                preserve_mask=0xffffffff & ~clear_bits,
                value_from_zero=set_bits)


def crtc_pitch(mode, bpp):
    """CRTC_PITCH, both halves, in units of EIGHT PIXELS whatever the depth.

    xf86 legacy_crtc.c 955-957: (width*bpp + (bpp*8 - 1)) / (bpp*8), i.e.
    ceil(width / 8).  NetBSD radeonfb.c 2438 computes stride_bytes / bpp_bits,
    the same unit (it rounds its stride up to 64 bytes first, radeonfb.c
    918-920, so at 800 px 8 bpp it programs 104 for its own 832-byte rows).

    Until 2026-09-17 this function computed (width*bpp + 255) // 256, which
    agrees only at 32 bpp -- the R2 anchor 0x00640064 could not tell them
    apart, and a self-check here asserted the wrong dependence on bpp.  At 16
    and 8 bpp it gave a half and a quarter of the real value, and the driver's
    read-back would have agreed with it (docs/R3_MULTIMODE_PLAN.md 12-1 E1).
    """
    pitch = (mode['hdisp'] * bpp + (bpp * 8 - 1)) // (bpp * 8)
    return pitch | (pitch << 16)


def display_info(mode, pixel_bytes, clocks=DEFAULT_CLOCKS):
    """What -[OSRDNDisplay initFromDeviceDescription:] publishes."""
    r = dict(report(clocks))[mode['name']]
    return dict(width=mode['hdisp'], height=mode['vdisp'],
                rowBytes=mode['hdisp'] * pixel_bytes,
                memorySize=mode['hdisp'] * pixel_bytes * mode['vdisp'],
                dotClockRate=int(round(r['actual'] * 1000)),
                refreshRate=int(round(r['refresh'])))


def pll_rows(mode, refdivs=(6, 12), refclk=27000, minpll=200000, maxpll=400000):
    """One row per refdiv the driver may find in PPLL_REF_DIV at entry.

    The driver never writes PPLL_REF_DIV's value (it is shared by all four
    divider slots), so the feedback divider is what changes with refdiv.
    """
    rows = {}
    for refdiv in refdivs:
        got = rfb_calc_dividers(mode['clock'], refclk, refdiv, minpll, maxpll)
        if got is None:
            rows[refdiv] = None
            continue
        pbit, fb, div, requested = got
        vco = refclk * fb // refdiv                    # realized, not requested
        rows[refdiv] = dict(word=pbit | fb, fb=fb, post=div, vco=vco,
                            dot_khz=vco / float(div),
                            refresh=(vco * 1000.0 / div) / (mode['htotal'] * mode['vtotal']),
                            pll_gain=7 if vco // 10 >= 30000 else (4 if vco // 10 >= 18000 else 1),
                            fb_fits=fb <= FB3_DIV_MASK)
    return rows


# The driver accepts a boot's PPLL_REF_DIV only when the row it produces is
# within this much of the mode's requested dot clock.  0.5% is VESA's limit
# for a generic timing, and it is what separates refdiv 5 (0.44%) from
# refdiv 4 (0.86%).
PLL_TABLE_TOL = 0.005


def pll_table(mode, refclk=27000, minpll=200000, maxpll=400000, tol=None):
    """Every PPLL_REF_DIV the driver may accept, with its PPLL_DIV_3 word.

    The driver never writes PPLL_REF_DIV -- it is shared by all four divider
    slots -- so the boot's value decides the feedback divider, and the driver
    needs a row for whatever it finds.  A refdiv is accepted when

      * rfb_calc_dividers finds a post divider keeping the VCO in range,
      * the feedback divider fits its field, and
      * the realized dot clock is within `tol` of the requested one.

    Below refdiv 5 the rounding of the feedback divider is coarser than the
    tolerance; above 172 the feedback divider overflows its field.
    """
    if tol is None:
        tol = PLL_TABLE_TOL
    rows = pll_rows(mode, refdivs=tuple(range(1, 1 << 10)), refclk=refclk,
                    minpll=minpll, maxpll=maxpll)
    out = {}
    for rd in sorted(rows):
        r = rows[rd]
        if r is None or not r['fb_fits']:
            continue
        if abs(r['dot_khz'] - mode['clock']) > tol * mode['clock']:
            continue
        out[rd] = r
    return out


def pll_table_digest(table):
    """A fingerprint of the whole table, so a plan can approve 168 rows with
    one literal.  Any changed row changes this."""
    text = '\n'.join('%d %08x' % (rd, table[rd]['word']) for rd in sorted(table))
    return hashlib.sha256(text.encode()).hexdigest()[:16]


# NetBSD's VESA DMT table (sys/dev/videomode/videomode.c), fetched into the
# reference mirror by tools/fetch-ref.sh.  Unlike osmgaRes, from which MODES
# was copied, this is an upstream source nobody in this workspace wrote, so
# comparing against it checks the timings themselves and not just the copying
# (docs/R3_MULTIMODE_PLAN.md 16-1 A1).
NETBSD_VIDEOMODE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                                'ref', 'upstream', 'netbsd', 'sys', 'dev', 'videomode',
                                'videomode.c')


def netbsd_modes(path=None):
    """{name 'WxHxR': timing dict} from videomode.c, first non-doublescan entry
    of each name.  None when the file is absent."""
    path = path or NETBSD_VIDEOMODE
    if not os.path.exists(path):
        return None
    text = open(path, errors='replace').read()
    rows = {}
    for m in re.finditer(r'M\("(\d+x\d+x\d+)",(\d+),(\d+),(\d+),(\d+),(\d+),(\d+),'
                         r'(\d+),(\d+),(\d+),([A-Z|]+)\)', text):
        name, flags = m.group(1), m.group(11)
        if 'DS' in flags or name in rows:
            continue
        v = [int(x) for x in m.groups()[1:10]]
        rows[name] = dict(hdisp=v[0], vdisp=v[1], clock=v[2], hsstart=v[3], hsend=v[4],
                          htotal=v[5], vsstart=v[6], vsend=v[7], vtotal=v[8],
                          nhsync=int('HN' in flags), nvsync=int('VN' in flags))
    return rows


def check_against_netbsd(modes=None, table=None, path=None):
    """Problems, one string each; an absent file IS a problem."""
    table = netbsd_modes(path) if table is None else table
    if table is None:
        return ['NetBSD videomode.c is not in the mirror (run tools/fetch-ref.sh)']
    out = []
    for m in (MODES if modes is None else modes):
        n = table.get(m['name'].replace('@', 'x'))
        if n is None:
            out.append('%s is not in NetBSD videomode.c' % m['name'])
            continue
        for k in sorted(n):
            if n[k] != m[k]:
                out.append('%s %s: ours %r, NetBSD %r' % (m['name'], k, m[k], n[k]))
    return out


# The four pixel formats (docs/R3_MULTIMODE_PLAN.md 16-3).  io_bpp and
# io_cspace are the numeric values of IOBitsPerPixel / IOColorSpace in
# driverkit/displayDefs.h 18-35; crtc_format is CRTC_GEN_CNTL bits 8-11 as
# xf86 legacy_crtc.c 890-894 assigns them.
FORMATS = [
    dict(token='RGB:888/32', bytes=4, bpp=32, crtc_format=6, io_bpp=4, io_cspace=2,
         encoding='--------RRRRRRRRGGGGGGGGBBBBBBBB', pseudo=0),
    dict(token='RGB:555/16', bytes=2, bpp=16, crtc_format=3, io_bpp=3, io_cspace=2,
         encoding='-RRRRRGGGGGBBBBB', pseudo=0),
    dict(token='RGB:256/8', bytes=1, bpp=8, crtc_format=2, io_bpp=1, io_cspace=2,
         encoding='PPPPPPPP', pseudo=1),
    dict(token='BW:8', bytes=1, bpp=8, crtc_format=2, io_bpp=1, io_cspace=1,
         encoding='WWWWWWWW', pseudo=0),
]


def netbsd_pitch(mode, bpp):
    """NetBSD radeonfb.c 918-920 and 2438: stride rounded up to 64 bytes,
    divided by the bit depth."""
    stride = mode['hdisp'] * bpp // 8
    stride = (stride + 63) // 64 * 64
    return stride // bpp


def mode_by_name(name):
    for m in MODES:
        if m['name'] == name:
            return m
    raise KeyError(name)


def self_check():
    failures = 0
    # 1. xf86 hard-codes ppll_div_3 = 0x000600ad for iBook panels
    #    (legacy_crtc.c:1264).  An independent formula giving the same
    #    word for 65 MHz at the default clocks is a check on this oracle.
    pbit, fb, div, _ = rfb_calc_dividers(65000, **DEFAULT_CLOCKS)
    if (pbit | fb) != 0x000600ad:
        print('FAIL ibook anchor: got %08x' % (pbit | fb)); failures += 1
    # 2. the two post-divider tables must agree on every divider->code pair
    if dict(RFB_DIVIDERS) != dict(XF86_POST_DIVS):
        print('FAIL divider tables differ'); failures += 1
    # 3. the two CRTC formulas must agree for every mode in the table
    for m in MODES:
        if rfb_crtc_words(m) != xf86_crtc_words(m):
            print('FAIL crtc words differ for', m['name']); failures += 1
    # 4. negative control: a deliberately wrong divider table must fail #1
    saved = list(RFB_DIVIDERS)
    RFB_DIVIDERS[3] = (6, 5)
    pbit2, fb2, _, _ = rfb_calc_dividers(65000, **DEFAULT_CLOCKS)
    RFB_DIVIDERS[:] = saved
    if (pbit2 | fb2) == 0x000600ad:
        print('FAIL negative control did not trip'); failures += 1

    # ---- R2b: every value the driver will write, against a measurement or a
    # value a person wrote in a document (never against this oracle's own output)
    mode = mode_by_name('800x600@60')
    rows = pll_rows(mode)
    # 5. refdiv 6 must reproduce the PPLL_DIV_3 word measured on the R2a boot's
    #    console: docs/R2A_RESULT.md "PPLL_DIV_3 | 00030047 | fb 71, post 3 (/8)"
    if rows[6]['word'] != 0x00030047:
        print('FAIL R2a console anchor: got %08x' % rows[6]['word']); failures += 1
    # 6. both refdiv rows must land on the same realized VCO and dot clock --
    #    that is what makes dotClockRate independent of the boot state
    if rows[6]['vco'] != rows[12]['vco'] or rows[6]['dot_khz'] != rows[12]['dot_khz']:
        print('FAIL refdiv rows disagree on the clock'); failures += 1
    if rows[12]['word'] != 0x0003008e:
        print('FAIL refdiv 12 row: got %08x' % rows[12]['word']); failures += 1
    # 7. the values docs/R2_FIRST_LIGHT_PLAN.md and docs/R2B_IMPL_PLAN.md state
    if crtc_pitch(mode, 32) != 0x00640064:
        print('FAIL CRTC_PITCH: got %08x' % crtc_pitch(mode, 32)); failures += 1
    di = display_info(mode, 4)
    if (di['rowBytes'], di['memorySize'], di['dotClockRate']) != (3200, 1920000, 39937500):
        print('FAIL displayInfo: %r' % di); failures += 1
    f = fifo(mode, 4)
    # stop_req = 800*4/16 = 200, clamped to the RV100-variant maximum
    if (f['stop_req'], f['start_req'], f['critical_point']) != (0x5c, 0x5c, 0):
        print('FAIL fifo fields: %r' % f); failures += 1
    if f['set_bits'] != 0x20005c5c or f['preserve_mask'] != 0x0f808080:
        print('FAIL fifo word: set %08x preserve %08x' % (f['set_bits'], f['preserve_mask'])); failures += 1
    # 8. negative control for the clamp: a 320-pixel mode must not clamp
    if fifo(dict(hdisp=320), 4)['stop_req'] != 80:
        print('FAIL fifo clamp control'); failures += 1
    # 9. negative controls: each R2b anchor must FAIL when its input is wrong,
    #    proved in this same run (a check that cannot fail proves nothing)
    if fifo(mode, 4, max_stop_req=0x7c)['set_bits'] == 0x20005c5c:
        print('FAIL fifo anchor does not depend on the RV100 maximum'); failures += 1
    # the pitch is in units of 8 pixels at EVERY depth (xf86 legacy_crtc.c
    # 955-957): the same value at 32, 16 and 8 bpp for a given width ...
    if not (crtc_pitch(mode, 32) == crtc_pitch(mode, 16) == crtc_pitch(mode, 8) == 0x00640064):
        print('FAIL pitch is not width/8 at every depth: %08x %08x %08x'
              % (crtc_pitch(mode, 32), crtc_pitch(mode, 16), crtc_pitch(mode, 8))); failures += 1
    # ... it does depend on the width ...
    if crtc_pitch(dict(mode, hdisp=1024), 16) != 0x00800080:
        print('FAIL pitch does not follow the width'); failures += 1
    # ... and the formula this file used before 2026-09-17 is caught: it
    # agrees at 32 bpp and gives half the pitch at 16
    old_pitch = lambda w, b: (w * b + 255) // 256
    if old_pitch(800, 32) != 100 or old_pitch(800, 16) == (crtc_pitch(mode, 16) & 0xffff):
        print('FAIL the old pitch formula is not told apart'); failures += 1
    # every published width is a whole number of 8-pixel units
    for m in MODES:
        if m['hdisp'] % 8:
            print('FAIL %s width is not a multiple of 8' % m['name']); failures += 1
    # 11. the timings against an upstream table nobody here wrote (R3 16-1 A1)
    for problem in check_against_netbsd():
        print('FAIL netbsd: %s' % problem); failures += 1
    # negative controls: a changed porch and a missing file are both caught
    bent = [dict(m) for m in MODES]
    bent[2]['hsend'] += 1
    if not check_against_netbsd(bent):
        print('FAIL a changed porch is not caught against NetBSD'); failures += 1
    if netbsd_modes('/nonexistent') is not None or not check_against_netbsd(path='/nonexistent'):
        print('FAIL an absent videomode.c is not reported'); failures += 1
    # 12. pitch: xf86 and NetBSD agree everywhere except 800 px at 8 bpp, where
    #     NetBSD's 64-byte stride rounding gives 104 for its own 832-byte rows
    for m in MODES:
        for f in FORMATS:
            x = crtc_pitch(m, f['bpp']) & 0xffff
            n = netbsd_pitch(m, f['bpp'])
            expected_diff = (m['hdisp'] == 800 and f['bpp'] == 8)
            if (x != n) != expected_diff:
                print('FAIL pitch %s %s: xf86 %d NetBSD %d' % (m['name'], f['token'], x, n)); failures += 1
    # 13. formats: bytes and depth agree, and the CRTC format codes are xf86's
    xf86_format = {8: 2, 15: 3, 16: 4, 24: 5, 32: 6}      # legacy_crtc.c 890-894
    for f in FORMATS:
        if f['bytes'] * 8 != f['bpp']:
            print('FAIL format %s: %d bytes vs %d bpp' % (f['token'], f['bytes'], f['bpp'])); failures += 1
        # 16 bpp here is 555, which xf86 calls depth 15 (code 3)
        depth = 15 if f['token'] == 'RGB:555/16' else f['bpp']
        if xf86_format[depth] != f['crtc_format']:
            print('FAIL format %s: CRTC code %d, xf86 %d' % (f['token'], f['crtc_format'], xf86_format[depth])); failures += 1
        if len(f['encoding']) != f['bpp']:
            print('FAIL format %s: encoding has %d characters' % (f['token'], len(f['encoding']))); failures += 1
    wrong = dict(mode, clock=65000)
    if pll_rows(wrong)[6]['word'] == 0x00030047:
        print('FAIL R2a anchor does not depend on the mode clock'); failures += 1
    if display_info(dict(mode, hdisp=1024), 4)['rowBytes'] == 3200:
        print('FAIL displayInfo anchor does not depend on the width'); failures += 1
    # 10. the divider table the driver carries (R2b revision 3)
    tab = pll_table(mode)
    keys = sorted(tab)
    if keys != list(range(5, 173)):
        print('FAIL pll_table is not refdiv 5..172: %d rows %r..%r'
              % (len(keys), keys[:3], keys[-3:])); failures += 1
    if pll_table_digest(tab) != '0bbf9ca83b478bc7':
        print('FAIL pll_table digest %s' % pll_table_digest(tab)); failures += 1
    for rd, want in ((6, 0x00030047), (12, 0x0003008e)):
        if tab[rd]['word'] != want:
            print('FAIL pll_table refdiv %d is %08x, the machine measured %08x'
                  % (rd, tab[rd]['word'], want)); failures += 1
    for rd, r in tab.items():
        if not (200000 <= r['vco'] <= 400000):
            print('FAIL pll_table refdiv %d realizes VCO %d kHz' % (rd, r['vco'])); failures += 1
            break
        if abs(r['dot_khz'] - mode['clock']) > PLL_TABLE_TOL * mode['clock']:
            print('FAIL pll_table refdiv %d realizes %s kHz' % (rd, r['dot_khz'])); failures += 1
            break
    # negative controls: the two refdivs just outside must stay out, and a
    # looser tolerance must let refdiv 4 in (so the gate is the tolerance)
    if 4 in tab or 173 in tab:
        print('FAIL pll_table accepts a refdiv outside 5..172'); failures += 1
    if 4 not in pll_table(mode, tol=0.01):
        print('FAIL pll_table refdiv 4 is not excluded by the tolerance'); failures += 1
    if 173 in pll_table(mode, tol=0.5):
        print('FAIL pll_table refdiv 173 is not excluded by the field width'); failures += 1
    return failures


def main():
    for name, r in report():
        if r is None:
            print('%-14s no divider in PLL range' % name)
            continue
        print('%-14s div=%2d fb=%3d vco=%6d kHz word=%08x actual=%9.3f kHz '
              '(%+.0f ppm) refresh=%.3f Hz fb_fits=%s' %
              (name, r['div'], r['fb'], r['vco'], r['div_word'], r['actual'],
               r['ppm'], r['refresh'], r['fb_fits']))
        print('%14s H_TOTAL_DISP=%08x H_SYNC=%08x V_TOTAL_DISP=%08x V_SYNC=%08x'
              % ('', *r['rfb']))
    f = self_check()
    n, d = check_against_matrox()
    if n is None:
        print('matrox table: not present, timings NOT cross-checked')
    else:
        print('matrox table: %d rows compared, %d differences' % (n, d))
        f += d
    print('self-check:', 'PASS' if f == 0 else 'FAIL (%d)' % f)
    return 1 if f else 0


if __name__ == '__main__':
    sys.exit(main())
