#!/usr/bin/env python3
"""Decode RV280 register values read on the target back into meaning.

Inverse of radeon_modeset.py, for the R1 interrogation results
(docs/R1_INTERROGATION_PLAN.md section 5).  Run with no arguments for the
round-trip self-test: every mode in radeon_modeset.MODES is encoded by the
oracle and decoded here, and must come back identical; a deliberately
corrupted word must NOT come back identical.

Field layouts are taken from the encoders they invert:
  CRTC words     radeonfb.c:2528-2576 / legacy_crtc.c:928-953
  PPLL divider   radeonfb.c:1739-1779, divider table radeonfb.c:397-407
  MC location    radeonfb.c:2872-2880 (low 16 bits = start >> 16,
                 high 16 bits = end & 0xffff0000)
  PLL_DIV_SEL    radeonfbreg.h:332 (bits 8-9 of CLOCK_CNTL_INDEX)
"""

import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location('radeon_modeset', os.path.join(HERE, 'radeon_modeset.py'))
oracle = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(oracle)

CODE_TO_DIVIDER = {code: div for div, code in oracle.RFB_DIVIDERS}


def decode_crtc(h_total_disp, h_sync, v_total_disp, v_sync):
    """Return the timing the four CRTC1 words describe.

    Horizontal values come back as the multiple of 8 the register can hold;
    hsync start is exact because the encoder stores (start - 8) in full.
    """
    return dict(
        hdisp=((h_total_disp >> 16) & 0x1ff) * 8 + 8,
        htotal=((h_total_disp & 0x3ff) + 1) * 8,
        hsstart=(h_sync & 0x1fff) + 8,
        hsend=(h_sync & 0x1fff) + 8 + ((h_sync >> 16) & 0x3f) * 8,
        nhsync=(h_sync >> 23) & 1,
        vdisp=((v_total_disp >> 16) & 0xffff) + 1,
        vtotal=(v_total_disp & 0xffff) + 1,
        vsstart=(v_sync & 0xfff) + 1,
        vsend=(v_sync & 0xfff) + 1 + ((v_sync >> 16) & 0x1f),
        nvsync=(v_sync >> 23) & 1,
    )


def decode_ppll_div(word, refclk_khz, refdiv):
    """PPLL_DIV_n word -> (feedback, post divider, output kHz) or None."""
    fb = word & oracle.FB3_DIV_MASK
    code = (word & oracle.POST3_DIV_MASK) >> 16
    div = CODE_TO_DIVIDER.get(code)
    if div is None or refdiv == 0:
        return None
    return fb, div, refclk_khz * fb / refdiv / div


def decode_mc_location(value):
    """MC_FB_LOCATION / MC_AGP_LOCATION -> (start, end_inclusive)."""
    start = (value & 0xffff) << 16
    end = (value & 0xffff0000) | 0xffff
    return start, end


def decode_pll_div_sel(clock_cntl_index):
    """Which PPLL_DIV_n the CRTC is using: bits 8-9 of CLOCK_CNTL_INDEX."""
    return (clock_cntl_index >> 8) & 3


def refresh_hz(timing, clock_khz):
    return clock_khz * 1000.0 / (timing['htotal'] * timing['vtotal'])


def self_test():
    failures = 0
    keys = ('hdisp', 'htotal', 'hsstart', 'hsend', 'nhsync',
            'vdisp', 'vtotal', 'vsstart', 'vsend', 'nvsync')
    for m in oracle.MODES:
        words = oracle.rfb_crtc_words(m)
        back = decode_crtc(*words)
        want = {k: m[k] for k in keys}
        if back != want:
            print('FAIL crtc round trip', m['name'], back, want)
            failures += 1
        pbit, fb, div, _ = oracle.rfb_calc_dividers(m['clock'], **oracle.DEFAULT_CLOCKS)
        dec = decode_ppll_div(pbit | fb, oracle.DEFAULT_CLOCKS['refclk'], oracle.DEFAULT_CLOCKS['refdiv'])
        if dec is None or dec[0] != fb or dec[1] != div:
            print('FAIL ppll round trip', m['name'], dec, fb, div)
            failures += 1
    # radeonfb mcfbloc formula round trip (radeonfb.c:2876-2877)
    for base, size in ((0xe0000000, 0x08000000), (0xd8000000, 0x08000000), (0xf0000000, 0x04000000)):
        mc = (base >> 16) | ((base + size - 1) & 0xffff0000)
        if decode_mc_location(mc) != (base, base + size - 1):
            print('FAIL mc round trip', hex(base), hex(size), decode_mc_location(mc))
            failures += 1
    if decode_pll_div_sel(0x00000300) != 3 or decode_pll_div_sel(0x000000bf) != 0:
        print('FAIL div_sel')
        failures += 1
    # negative controls: a corrupted word must not round-trip
    m = oracle.MODES[2]
    w = list(oracle.rfb_crtc_words(m))
    w[1] ^= 1 << 16
    if decode_crtc(*w) == {k: m[k] for k in keys}:
        print('FAIL negative control (crtc) did not trip')
        failures += 1
    if decode_ppll_div(0x000000ad, 27000, 12)[1] == 6:
        print('FAIL negative control (post divider) did not trip')
        failures += 1
    return failures


def main():
    f = self_test()
    print('radeon_decode self-test:', 'PASS' if f == 0 else 'FAIL (%d)' % f)
    return 1 if f else 0


if __name__ == '__main__':
    sys.exit(main())
