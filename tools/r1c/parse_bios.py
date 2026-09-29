#!/usr/bin/env python3
"""Judge the R1c video BIOS shadow captures (docs/R1C_R2A_IMPL_PLAN.md section 1-5).

  parse_bios.py first <cap512> <r1log> <r1runid>
        the first capture: exactly 512 bytes, 55 AA, size byte >= 2; prints the
        length of the second read (512 x size byte, at most 65536)
  parse_bios.py full <cap512> <capN> <r1log> <r1runid> [<r2afacts>] [--out DIR]
        hard gates 1-7 of docs/R2_FIRST_LIGHT_PLAN.md section 3 (R1c), the
        recorded facts, and a facts file bios-facts-<sha256 of capN, 16 hex>.txt
  parse_bios.py --self-test
        synthetic images: one good image, two healthy variants, and one broken
        variant per gate; every broken one must fail and every healthy one pass

Where the numbers come from, and why from two places:

  The parser reads the BIOS with offsets extracted by regular expression from
  NetBSD radeonfb.c (the ROM header pointer, the PLL block pointer, the four
  PLL fields and their widths, the ATOM test) and NetBSD pcireg.h (the PCI ROM
  structures).  The synthetic image generator used by the self-test places
  the same fields with offsets extracted from xf86-video-ati radeon_bios.c.
  If both used one table, an extraction mistake would be shared and the
  self-test would only prove that the parser agrees with itself.  The overlap
  of the two extractions is compared, field by field, before anything else.

  The PLL fields are in units of 10 kHz.  The conversion to the kHz the divider
  oracle takes (tools/oracle/radeon_modeset.py) happens in exactly one place,
  and the self-test checks it against NetBSD's own defaults and multiplier
  (radeonfb.c) versus the oracle's DEFAULT_CLOCKS: two files by different
  authors.

  mclk (+0x08), sclk (+0x0a) and, for rev > 9, +0x36/+0x3a are read only by
  xf86; the parser writes those four offsets by hand and the self-test places
  them with the xf86 extraction, so a disagreement still shows.

  The ROM size byte at offset 2 is the PC option ROM convention; no reference
  in the tree reads it.  A wrong size byte can only shorten or lengthen the
  second read (bounded at 64 KiB), and a too-short image then fails the bounds
  gates.

What this cannot show: that the capture really came from physical 0xC0000.
The real-capture checks that are independent of this file's offsets are the
PCIR vendor against R1's configuration-space read, refclk landing exactly on
2700 or 1432, and (recorded) the BIOS refdiv against R2a's measured
PPLL_REF_DIV.
"""

import hashlib
import importlib.util
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
UP = os.path.join(PROJ, 'ref', 'upstream')
NETBSD_RADEONFB = os.path.join(UP, 'netbsd/sys/dev/pci/radeonfb.c')
NETBSD_PCIREG = os.path.join(UP, 'netbsd/sys/dev/pci/pcireg.h')
XF86_BIOS = os.path.join(UP, 'unpacked/xf86-video-ati-6.14.6/src/radeon_bios.c')


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


pr1 = _load('parse_r1', os.path.join(PROJ, 'tools', 'r1', 'parse_r1.py'))
ms = _load('radeon_modeset', os.path.join(PROJ, 'tools', 'oracle', 'radeon_modeset.py'))

ATI_VENDOR = 0x1002
REFCLK_ALLOWED = (2700, 1432)          # 10 kHz; xf86 also accepts 2950 -- excluded on purpose
REFDIV_MASK = 0x3ff                    # radeonfbreg.h RADEON_PPLL_REF_DIV_MASK
FB_DIV_MASK = 0x07ff                   # radeon_modeset.FB3_DIV_MASK
MAX_IMAGE = 65536
MODE_CLOCK_KHZ = 65000                 # 1024x768@60, docs/R2_FIRST_LIGHT_PLAN.md section 2


class ExtractError(Exception):
    pass


def _one(pattern, text, what):
    found = re.findall(pattern, text)
    if len(found) != 1:
        raise ExtractError('%s: expected one match of %r, found %d' % (what, pattern, len(found)))
    return found[0]


def _num(s):
    return int(s, 0)


# ---- offsets from NetBSD (the parser's) -----------------------------------

def extract_netbsd():
    src = open(NETBSD_RADEONFB, errors='replace').read()
    start = src.find('/* Legacy BIOS */')
    stop = src.find('dontprobe:', start)
    if start < 0 or stop < 0:
        raise ExtractError('radeonfb.c: legacy BIOS block not found')
    legacy = src[start:stop]
    o = {}
    o['rom_header_ptr'] = _num(_one(r'ptr = GETBIOS16\(sc, (0x[0-9a-fA-F]+)\);', legacy, 'header ptr'))
    o['pll_block_ptr'] = _num(_one(r'ptr = GETBIOS16\(sc, ptr \+ (0x[0-9a-fA-F]+)\);', legacy, 'pll ptr'))
    for name, field in (('refclk', 'refclk'), ('refdiv', 'refdiv'), ('minpll', 'minpll'), ('maxpll', 'maxpll')):
        width, off = _one(r'%s = %s \? %s : GETBIOS(16|32)\(sc, ptr \+ (0x[0-9a-fA-F]+)\);' % (field, field, field),
                          legacy, name)
        o[name] = (_num(off), int(width))
    # the ATOM test (radeonfb.c, BIOS type probe): GETBIOS32(ptr + 4) against two constants
    atom = re.findall(r'GETBIOS32\(sc, ptr \+ (\d+)\) == (0x[0-9a-fA-F]+) /\* "(\w{4})" \*/', src)
    if len(atom) != 2 or atom[0][0] != atom[1][0]:
        raise ExtractError('radeonfb.c: ATOM test not found as expected: %r' % (atom,))
    o['atom_off'] = int(atom[0][0])
    o['atom_words'] = sorted(_num(w) for _, w, _ in atom)
    # units: getclocks multiplies the BIOS values by ten
    mult = set(re.findall(r'sc->sc_(?:refclk|minpll|maxpll) = (?:refclk|minpll|maxpll) \* (\d+);', src))
    if len(mult) != 1:
        raise ExtractError('radeonfb.c: kHz multiplier not unique: %r' % (mult,))
    o['khz_multiplier'] = int(mult.pop())
    # no-BIOS defaults (not IGP): refclk, refdiv, minpll, maxpll
    nobios = src[src.find('/* no BIOS */'):src.find('} else if (IS_ATOM(sc))')]
    o['default_refclk'] = int(_one(r'else\s+refclk = refclk \? refclk : (\d+);', nobios, 'default refclk'))
    o['default_refdiv'] = int(_one(r'refdiv = refdiv \? refdiv : (\d+);', nobios, 'default refdiv'))
    o['default_minpll'] = int(_one(r'minpll = minpll \? minpll : (\d+);', nobios, 'default minpll'))
    o['default_maxpll'] = int(_one(r'maxpll = maxpll \? maxpll : (\d+)/\*', nobios, 'default maxpll'))
    return o


def extract_pcireg():
    """Offsets inside the packed PCI ROM structures, from the field types."""
    src = open(NETBSD_PCIREG, errors='replace').read()
    sizes = {'uint8_t': 1, 'uint16_t': 2, 'uint32_t': 4}
    typedefs = dict((name, sizes[base]) for base, name in re.findall(r'typedef (uint\d+_t) (pci_\w+_t);', src))

    def layout(struct_name):
        body = _one(r'(?s)struct %s \{(.*?)\} __packed;' % struct_name, src.replace('\r', ''), struct_name)
        off = 0
        out = {}
        for typ, name, count in re.findall(r'^\s*(\w+)\s+(\w+)(?:\[(\d+)\])?;', body, flags=re.M):
            size = sizes.get(typ, typedefs.get(typ))
            if size is None:
                raise ExtractError('pcireg.h: unknown type %s in %s' % (typ, struct_name))
            out[name] = off
            off += size * (int(count) if count else 1)
        return out

    h = layout('pci_rom_header')
    r = layout('pci_rom')
    sig = _num(_one(r'#define\s+PCI_ROM_SIGNATURE\s+(0x[0-9a-fA-F]+)', src, 'PCI_ROM_SIGNATURE'))
    x86 = _num(_one(r'#define\s+PCI_ROM_CODE_TYPE_X86\s+(\d+)', src, 'PCI_ROM_CODE_TYPE_X86'))
    return {'pcir_ptr': h['romh_data_ptr'], 'sig': r['rom_signature'], 'vendor': r['rom_vendor'],
            'device': r['rom_product'], 'rom_len': r['rom_len'], 'code_type': r['rom_code_type'],
            'sig_value': sig, 'x86': x86}


# ---- offsets from xf86 (the generator's) ----------------------------------

def extract_xf86():
    src = open(XF86_BIOS, errors='replace').read()
    o = {}
    o['pcir_ptr'] = _num(_one(r'dptr = RADEON_BIOS16\((0x[0-9a-fA-F]+)\);', src, 'dptr'))
    chars = _one(r"RADEON_BIOS32\(dptr\) != \(\('(.)' << 24\) \| \('(.)' << 16\) \| \('(.)' << 8\) \| '(.)'\)", src, 'sig')
    o['sig_value'] = (ord(chars[0]) << 24) | (ord(chars[1]) << 16) | (ord(chars[2]) << 8) | ord(chars[3])
    o['code_type'] = _num(_one(r'info->VBIOS\[dptr \+ (0x[0-9a-fA-F]+)\] != 0x0', src, 'code type'))
    o['rom_header_ptr'] = _num(_one(r'info->ROMHeaderStart = RADEON_BIOS16\((0x[0-9a-fA-F]+)\);', src, 'header'))
    o['atom_off'] = int(_one(r'tmp = info->ROMHeaderStart \+ (\d+);', src, 'atom off'))
    o['pll_block_ptr'] = _num(_one(r'pll_info_block = RADEON_BIOS16 \(info->ROMHeaderStart \+ (0x[0-9a-fA-F]+)\);',
                                   src, 'pll block'))
    for name, field in (('refclk', 'reference_freq'), ('refdiv', 'reference_div'),
                        ('minpll', 'pll_out_min'), ('maxpll', 'pll_out_max')):
        width, off = _one(r'pll->%s = RADEON_BIOS(16|32) \(pll_info_block \+ (0x[0-9a-fA-F]+)\);' % field, src, name)
        o[name] = (_num(off), int(width))
    _one(r'rev = RADEON_BIOS8\(pll_info_block\);', src, 'rev')      # the revision is the block's first byte
    o['rev'] = 0
    clock = src[src.find('Bool RADEONGetClockInfoFromBIOS'):src.find('Bool RADEONGetDAC2InfoFromBIOS')]
    o['rev_threshold'] = int(_one(r'if \(rev > (\d+)\) \{', clock, 'rev threshold'))
    for name, field in (('pll_in_min', 'pll_in_min'), ('pll_in_max', 'pll_in_max')):
        off = _one(r'pll->%s = RADEON_BIOS32\(pll_info_block \+ (0x[0-9a-fA-F]+)\);' % field, src, name)
        o[name] = (_num(off), 32)
    o['sclk'] = (_num(_one(r'info->sclk = RADEON_BIOS16\(pll_info_block \+ (\d+)\) / 100\.0;', src, 'sclk')), 16)
    o['mclk'] = (_num(_one(r'info->mclk = RADEON_BIOS16\(pll_info_block \+ (\d+)\) / 100\.0;', src, 'mclk')), 16)
    return o


def overlap_check(nb, pcireg, xf):
    """The two extractions must agree where they overlap."""
    bad = []
    for k in ('rom_header_ptr', 'pll_block_ptr', 'refclk', 'refdiv', 'minpll', 'maxpll', 'atom_off'):
        if nb[k] != xf[k]:
            bad.append('%s: NetBSD %r, xf86 %r' % (k, nb[k], xf[k]))
    if pcireg['pcir_ptr'] != xf['pcir_ptr']:
        bad.append('PCIR pointer: pcireg.h %#x, xf86 %#x' % (pcireg['pcir_ptr'], xf['pcir_ptr']))
    if pcireg['sig_value'] != xf['sig_value']:
        bad.append('PCIR signature: pcireg.h %#x, xf86 %#x' % (pcireg['sig_value'], xf['sig_value']))
    if pcireg['code_type'] != xf['code_type']:
        bad.append('PCIR code type offset: pcireg.h %#x, xf86 %#x' % (pcireg['code_type'], xf['code_type']))
    # NetBSD compares a little-endian 32-bit word; xf86 compares bytes in order.
    xf_strings = {b'ATOM', b'MOTA'}
    nb_strings = set(struct.pack('<I', w) for w in nb['atom_words'])
    if nb_strings != xf_strings:
        bad.append('ATOM strings: NetBSD %r, xf86 %r' % (sorted(nb_strings), sorted(xf_strings)))
    return bad


def to_khz(value_10khz, nb):
    """The one place a BIOS PLL value becomes kHz (radeonfb.c getclocks)."""
    return value_10khz * nb['khz_multiplier']


# ---- reading --------------------------------------------------------------

def u8(b, off):
    return b[off]


def u16(b, off):
    return struct.unpack_from('<H', b, off)[0]


def u32(b, off):
    return struct.unpack_from('<I', b, off)[0]


def field(b, off, width):
    return u16(b, off) if width == 16 else u32(b, off)


def r1_card(r1log_text, r1runid):
    """The single RV280 function R1 read from configuration space."""
    facts, _, _, _ = pr1.parse(r1log_text, r1runid)
    cards = [p for p in facts['pci'] if int(p['vid'], 16) == ATI_VENDOR and int(p['did'], 16) in pr1.RV280_IDS]
    if len(cards) != 1:
        return None
    return int(cards[0]['vid'], 16), int(cards[0]['did'], 16)


def judge_first(cap512):
    fail = []
    out = []
    if len(cap512) != 512:
        fail.append('gate 1: first capture is %d bytes, not 512' % len(cap512))
        return out, fail, None
    if cap512[0] != 0x55 or cap512[1] != 0xaa:
        fail.append('gate 1: signature %02x %02x, not 55 AA' % (cap512[0], cap512[1]))
        return out, fail, None
    size = cap512[2]
    out.append('size byte %d -> image %d bytes' % (size, size * 512))
    if size < 2:
        fail.append('gate 1: size byte %d < 2' % size)
        return out, fail, None
    length = size * 512
    if length > MAX_IMAGE:
        fail.append('gate 1: image %d bytes > %d' % (length, MAX_IMAGE))
        return out, fail, None
    return out, fail, length


def judge_full(cap512, capN, card, r2a_refdiv=None, nb=None, pcireg=None):
    """Return (report, failures, facts).  Never raises on capture content."""
    try:
        return _judge_full(cap512, capN, card, r2a_refdiv, nb or extract_netbsd(), pcireg or extract_pcireg())
    except Exception as e:
        return [], ['parser raised %s: %s' % (type(e).__name__, e)], {}


def _judge_full(cap512, capN, card, r2a_refdiv, nb, pcireg):
    out, fail, length = judge_first(cap512)
    facts = {}
    if fail:
        return out, fail, facts
    # gate 1 (full): the second capture is the declared image, no more, no less
    if len(capN) != length:
        fail.append('gate 1: second capture %d bytes, size byte says %d' % (len(capN), length))
        return out, fail, facts
    # gate 2: the shadow did not change between the reads
    if capN[:512] != cap512:
        fail.append('gate 2: first 512 bytes of the second capture differ from the first capture')
        return out, fail, facts
    bound = len(capN)
    facts['image_bytes'] = bound
    facts['sha256'] = hashlib.sha256(capN).hexdigest()
    facts['sha256_first512'] = hashlib.sha256(cap512).hexdigest()
    facts['checksum8'] = sum(capN) & 0xff          # recorded only

    # gate 3: PCI data structure
    dptr = u16(capN, pcireg['pcir_ptr'])
    end = dptr + max(pcireg['code_type'] + 1, pcireg['rom_len'] + 2)
    facts['pcir_ptr'] = dptr
    if dptr == 0 or end > bound:
        fail.append('gate 3: PCIR pointer %#x (structure end %#x) outside the %d-byte image' % (dptr, end, bound))
        return out, fail, facts
    if u32(capN, dptr + pcireg['sig']) != pcireg['sig_value']:
        fail.append('gate 3: PCIR signature %#010x' % u32(capN, dptr + pcireg['sig']))
        return out, fail, facts
    vendor = u16(capN, dptr + pcireg['vendor'])
    device = u16(capN, dptr + pcireg['device'])
    rom_len = u16(capN, dptr + pcireg['rom_len'])
    code = u8(capN, dptr + pcireg['code_type'])
    facts.update(pcir_vendor='%04x' % vendor, pcir_device='%04x' % device, pcir_rom_len=rom_len,
                 pcir_code_type=code)
    if card is None:
        fail.append('gate 3: the R1 log does not name exactly one RV280 card')
        return out, fail, facts
    if vendor != ATI_VENDOR or vendor != card[0]:
        fail.append('gate 3: PCIR vendor %04x, R1 card vendor %04x' % (vendor, card[0]))
    if code != pcireg['x86']:
        fail.append('gate 3: PCIR code type %d, not x86' % code)
    size_byte = cap512[2]
    if size_byte > rom_len:
        fail.append('gate 3: size byte %d > PCIR image length %d' % (size_byte, rom_len))
    facts['pcir_device_matches_r1'] = int(device == card[1])
    facts['pcir_device_in_rv280_list'] = int(device in pr1.RV280_IDS)
    out.append('PCIR vendor %04x device %04x (R1 card %04x:%04x) image length %d x 512, code type %d'
               % (vendor, device, card[0], card[1], rom_len, code))
    if fail:
        return out, fail, facts

    # gate 4: legacy (not ATOM) ROM header
    hdr = u16(capN, nb['rom_header_ptr'])
    facts['rom_header'] = hdr
    if hdr == 0:
        fail.append('gate 4: ROM header pointer at %#x is 0' % nb['rom_header_ptr'])
        return out, fail, facts
    if hdr + max(nb['atom_off'] + 4, nb['pll_block_ptr'] + 2) > bound:
        fail.append('gate 4: ROM header %#x outside the image' % hdr)
        return out, fail, facts
    if u32(capN, hdr + nb['atom_off']) in nb['atom_words']:
        fail.append('gate 4: ATOM BIOS (not a legacy BIOS)')
        return out, fail, facts

    # gate 5: PLL block within bounds
    pll = u16(capN, hdr + nb['pll_block_ptr'])
    facts['pll_block'] = pll
    need = max(off + width // 8 for off, width in (nb['refclk'], nb['refdiv'], nb['minpll'], nb['maxpll']))
    need = max(need, 0x0a + 2)                       # mclk +0x08, sclk +0x0a (xf86, recorded fields)
    if pll == 0 or pll + need > bound:
        fail.append('gate 5: PLL block %#x (+%#x bytes) outside the image' % (pll, need))
        return out, fail, facts

    # gate 6: fields
    rev = u8(capN, pll)
    refclk = field(capN, pll + nb['refclk'][0], nb['refclk'][1])
    refdiv = field(capN, pll + nb['refdiv'][0], nb['refdiv'][1])
    minpll = field(capN, pll + nb['minpll'][0], nb['minpll'][1])
    maxpll = field(capN, pll + nb['maxpll'][0], nb['maxpll'][1])
    mclk = u16(capN, pll + 0x08)
    sclk = u16(capN, pll + 0x0a)
    facts.update(pll_rev=rev, refclk_10khz=refclk, refdiv=refdiv, minpll_10khz=minpll,
                 maxpll_10khz=maxpll, mclk_10khz=mclk, sclk_10khz=sclk)
    if rev > 9:
        if pll + 0x3a + 4 <= bound:
            facts['pll_in_min'] = u32(capN, pll + 0x36)
            facts['pll_in_max'] = u32(capN, pll + 0x3a)
        else:
            facts['pll_in_minmax'] = 'out-of-bounds'
    out.append('PLL block %#x rev %d: refclk %d refdiv %d min %d max %d mclk %d sclk %d (10 kHz)'
               % (pll, rev, refclk, refdiv, minpll, maxpll, mclk, sclk))

    # gate 7: plausibility
    if refclk not in REFCLK_ALLOWED:
        fail.append('gate 7: refclk %d not one of %r' % (refclk, REFCLK_ALLOWED))
    if not 2 <= refdiv <= REFDIV_MASK:
        fail.append('gate 7: refdiv %d outside 2..%d' % (refdiv, REFDIV_MASK))
    if not 0 < minpll < maxpll:
        fail.append('gate 7: min %d / max %d not 0 < min < max' % (minpll, maxpll))
    if mclk == 0 or sclk == 0:
        fail.append('gate 7: mclk %d sclk %d (zero)' % (mclk, sclk))
    if not fail:
        sel = ms.rfb_calc_dividers(MODE_CLOCK_KHZ, to_khz(refclk, nb), refdiv, to_khz(minpll, nb), to_khz(maxpll, nb))
        if sel is None:
            fail.append('gate 7: no post divider puts %d kHz inside %d..%d kHz'
                        % (MODE_CLOCK_KHZ, to_khz(minpll, nb), to_khz(maxpll, nb)))
        else:
            postbit, fb, div, outfreq = sel
            # target PLL output (post divider x mode clock) and the one the integer feedback gives
            vco_num = to_khz(refclk, nb) * fb
            facts.update(sel_post_div=div, sel_feedback=fb, sel_target_khz=outfreq, sel_postbit='%08x' % postbit,
                         sel_vco_actual_khz='%d/%d' % (vco_num, refdiv))
            out.append('1024x768 divider: post %d feedback %d, target %d kHz, actual VCO %.3f kHz'
                       % (div, fb, outfreq, vco_num / refdiv))
            if not 0 < fb <= FB_DIV_MASK:
                fail.append('gate 7: feedback divider %d outside 1..%#x' % (fb, FB_DIV_MASK))

    # recorded: BIOS refdiv against R2a's measured register (the independent check of the offsets)
    if r2a_refdiv is not None:
        match = int((r2a_refdiv & REFDIV_MASK) == refdiv)
        facts['refdiv_matches_r2a'] = match
        out.append('WARNING-REFDIV bios %d register %d %s' % (refdiv, r2a_refdiv & REFDIV_MASK,
                                                          'match' if match else 'MISMATCH'))
    return out, fail, facts


# ---- synthetic images (self-test), placed with xf86 offsets --------------

def synth(xf, pcireg_vendor_off, pcireg_device_off, pcireg_romlen_off, size=0x30, rom_len=None,
          vendor=ATI_VENDOR, device=0x5960, code=0, sig=None, header=0x0200, pcir=0x0100,
          atom=None, pll=0x0400, rev=9, refclk=2700, refdiv=12, minpll=12500, maxpll=40000,
          mclk=16600, sclk=20000):
    img = bytearray(size * 512)
    img[0] = 0x55
    img[1] = 0xaa
    img[2] = size & 0xff
    struct.pack_into('<H', img, xf['pcir_ptr'], pcir)
    if pcir + 0x18 <= len(img):
        struct.pack_into('<I', img, pcir, xf['sig_value'] if sig is None else sig)
        struct.pack_into('<H', img, pcir + pcireg_vendor_off, vendor)
        struct.pack_into('<H', img, pcir + pcireg_device_off, device)
        struct.pack_into('<H', img, pcir + pcireg_romlen_off, size if rom_len is None else rom_len)
        img[pcir + xf['code_type']] = code
    struct.pack_into('<H', img, xf['rom_header_ptr'], header)
    if header and header + 0x40 <= len(img):
        img[header + xf['atom_off']:header + xf['atom_off'] + 4] = atom if atom else b'ATI '
        struct.pack_into('<H', img, header + xf['pll_block_ptr'], pll)
    if pll and pll + 0x40 <= len(img):
        img[pll] = rev
        for name, value in (('refclk', refclk), ('refdiv', refdiv), ('minpll', minpll), ('maxpll', maxpll),
                            ('sclk', sclk), ('mclk', mclk)):
            off, width = xf[name]
            struct.pack_into('<H' if width == 16 else '<I', img, pll + off, value)
    return bytes(img)


def self_test():
    failures = 0

    def check(label, ok):
        nonlocal failures
        print('  %s %s' % ('ok  ' if ok else 'FAIL', label))
        if not ok:
            failures += 1

    nb = extract_netbsd()
    pcireg = extract_pcireg()
    xf = extract_xf86()
    bad = overlap_check(nb, pcireg, xf)
    check('NetBSD/pcireg.h and xf86 extractions agree (%s)' % ('; '.join(bad) or 'all overlapping fields'), not bad)
    check('PCIR offsets from pcireg.h: ptr %#x vendor +%#x device +%#x len +%#x code +%#x'
          % (pcireg['pcir_ptr'], pcireg['vendor'], pcireg['device'], pcireg['rom_len'], pcireg['code_type']),
          (pcireg['pcir_ptr'], pcireg['vendor'], pcireg['device'], pcireg['rom_len'], pcireg['code_type'])
          == (0x18, 4, 6, 0x10, 0x14))
    # units: NetBSD defaults x NetBSD multiplier == the oracle's DEFAULT_CLOCKS
    d = ms.DEFAULT_CLOCKS
    check('units: NetBSD defaults %d/%d/%d x%d == oracle %d/%d/%d kHz'
          % (nb['default_refclk'], nb['default_minpll'], nb['default_maxpll'], nb['khz_multiplier'],
             d['refclk'], d['minpll'], d['maxpll']),
          (to_khz(nb['default_refclk'], nb), to_khz(nb['default_minpll'], nb), to_khz(nb['default_maxpll'], nb),
           nb['default_refdiv']) == (d['refclk'], d['minpll'], d['maxpll'], d['refdiv']))
    check('extraction refuses a mangled source', _extraction_can_fail())

    card = (ATI_VENDOR, 0x5960)
    S = lambda **kw: synth(xf, pcireg['vendor'], pcireg['device'], pcireg['rom_len'], **kw)

    def run(image, label, expect_pass, first=None, cardv=card, r2a=None, want=None):
        cap512 = image[:512] if first is None else first
        out, fail, facts = judge_full(cap512, image, cardv, r2a, nb, pcireg)
        ok = (not fail) if expect_pass else bool(fail)
        if ok and want and not expect_pass:
            ok = any(want in f for f in fail)
        check('%s -> %s%s' % (label, 'PASS' if not fail else 'FAIL', '' if not fail else ' (%s)' % fail[0]), ok)
        return facts

    good = S()
    f = run(good, 'good image', True, r2a=0x0000000c)
    check('good image facts: 27000 kHz/12, post 6, feedback 173, refdiv matches',
          (f.get('sel_post_div'), f.get('sel_feedback'), f.get('refdiv_matches_r2a')) == (6, 173, 1))
    run(S(rom_len=0x40), 'healthy: size byte < PCIR image length', True)
    f = run(S(maxpll=35000), 'healthy: max 350 MHz picks post 4', True)
    check('max 350 MHz facts: post 4, feedback 116', (f.get('sel_post_div'), f.get('sel_feedback')) == (4, 116))
    f = run(S(device=0x5964), 'healthy: PCIR device 5964 (recorded only)', True)
    check('device mismatch recorded, in RV280 list', (f.get('pcir_device_matches_r1'),
                                                     f.get('pcir_device_in_rv280_list')) == (0, 1))
    f = run(good, 'refdiv against R2a mismatch is not a gate', True, r2a=0x7)
    check('refdiv mismatch recorded', f.get('refdiv_matches_r2a') == 0)
    run(S(rev=10), 'healthy: rev 10 records pll_in_min/max', True)

    bad_sig = bytearray(good)
    bad_sig[1] = 0xab
    run(bytes(bad_sig), 'broken: signature', False, want='gate 1')
    run(S(size=1), 'broken: size byte 1', False, want='gate 1')
    run(good[:-512], 'broken: second capture shorter than size byte', False, want='gate 1')
    changed = bytearray(good[:512])
    changed[0x40] ^= 1
    run(good, 'broken: first captures differ', False, first=bytes(changed), want='gate 2')
    run(good, 'broken: first capture 511 bytes', False, first=good[:511], want='gate 1')
    run(S(pcir=0x5ff0), 'broken: PCIR structure past the image end', False, want='gate 3')
    run(S(sig=0x52494351), 'broken: PCIR signature', False, want='gate 3')
    run(S(vendor=0x10de), 'broken: PCIR vendor', False, want='gate 3')
    run(S(code=1), 'broken: PCIR code type (Open Firmware)', False, want='gate 3')
    run(S(rom_len=0x20), 'broken: size byte > PCIR image length', False, want='gate 3')
    run(good, 'broken: R1 log names no card', False, cardv=None, want='gate 3')
    run(S(header=0), 'broken: ROM header pointer 0', False, want='gate 4')
    run(S(atom=b'ATOM'), 'broken: ATOM BIOS', False, want='gate 4')
    run(S(atom=b'MOTA'), 'broken: ATOM BIOS (MOTA)', False, want='gate 4')
    run(S(pll=0x5ff0), 'broken: PLL block outside the image', False, want='gate 5')
    run(S(refclk=2950), 'broken: refclk 2950 (xf86 accepts, gate narrows)', False, want='gate 7')
    run(S(refclk=0), 'broken: refclk 0', False, want='gate 7')
    run(S(refdiv=1), 'broken: refdiv 1', False, want='gate 7')
    run(S(minpll=40000, maxpll=12500), 'broken: min >= max', False, want='gate 7')
    run(S(mclk=0), 'broken: mclk 0', False, want='gate 7')
    run(S(minpll=13200, maxpll=19000), 'broken: no post divider fits (132-190 MHz)', False, want='gate 7')

    # first mode
    out, fail, length = judge_first(good[:512])
    check('first: good image -> second length %s' % length, not fail and length == len(good))
    out, fail, length = judge_first(good[:500])
    check('first: 500 bytes refused', bool(fail))
    out, fail, length = judge_first(bytes([0x55, 0xaa, 0xff]) + bytes(509))
    check('first: size byte 255 (> 64 KiB) refused', bool(fail))

    # a hostile capture must fail, never raise
    out, fail, facts = judge_full(b'\x55\xaa\x02' + bytes(509), b'\x55\xaa\x02' + bytes(509) + b'\xff' * 512,
                                  card, None, nb, pcireg)
    check('garbage image fails without raising (%s)' % (fail[0] if fail else ''), bool(fail))

    print('parse_bios self-test: %s' % ('PASS' if failures == 0 else 'FAIL (%d)' % failures))
    return failures == 0


def _extraction_can_fail():
    global NETBSD_RADEONFB
    import tempfile
    saved = NETBSD_RADEONFB
    text = open(saved, errors='replace').read().replace('GETBIOS16(sc, ptr + 0x0E)', 'GETBIOS16(sc, ptr + 0x0F)', 1)
    with tempfile.NamedTemporaryFile('w', suffix='.c', delete=False) as t:
        t.write(text)
    try:
        NETBSD_RADEONFB = t.name
        nb = extract_netbsd()
        return bool(overlap_check(nb, extract_pcireg(), extract_xf86()))
    except ExtractError:
        return True
    finally:
        NETBSD_RADEONFB = saved
        os.unlink(t.name)


def read_r2a_refdiv(path):
    for line in open(path):
        m = re.match(r'ppll_ref_div=([0-9a-f]{8})\s*$', line.strip())
        if m:
            return int(m.group(1), 16)
    raise SystemExit('%s: no ppll_ref_div=<hex8> line' % path)


def main(argv):
    if argv[1:] == ['--self-test']:
        return 0 if self_test() else 1
    if len(argv) == 5 and argv[1] == 'first':
        cap512 = open(argv[2], 'rb').read()
        card = r1_card(open(argv[3], errors='replace').read(), argv[4])
        out, fail, length = judge_first(cap512)
        for line in out:
            print(line)
        if card is None:
            fail.append('the R1 log does not name exactly one RV280 card')
        for f in fail:
            print('FAIL ' + f)
        if fail:
            print('R1C FIRST: FAIL')
            return 1
        print('second read length %d' % length)
        print('R1C FIRST: PASS')
        return 0
    if argv[1:2] == ['full'] and len(argv) >= 6:
        args = argv[2:]
        outdir = None
        if '--out' in args:
            i = args.index('--out')
            outdir = args[i + 1]
            args = args[:i] + args[i + 2:]
        cap512 = open(args[0], 'rb').read()
        capN = open(args[1], 'rb').read()
        card = r1_card(open(args[2], errors='replace').read(), args[3])
        r2a = read_r2a_refdiv(args[4]) if len(args) > 4 else None
        out, fail, facts = judge_full(cap512, capN, card, r2a)
        for line in out:
            print(line)
        for f in fail:
            print('FAIL ' + f)
        verdict = 'FAIL' if fail else 'PASS'
        if outdir and facts.get('sha256'):
            path = os.path.join(outdir, 'bios-facts-%s.txt' % facts['sha256'][:16])
            with open(path, 'w') as fh:
                fh.write('verdict=%s\n' % verdict)
                for k in sorted(facts):
                    fh.write('%s=%s\n' % (k, facts[k]))
            print('facts: %s' % path)
        print('R1C FULL: %s' % verdict)
        return 1 if fail else 0
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
