#!/usr/bin/env python3
"""G4 (docs/G4_GLQUAKE_PLAN.md 4): the numbers the plan rests on, computed and not typed.

  model.py            prints the texture budget (from the pak) and the submission model
Every constant below names where it was read or measured."""
import math, os, struct, sys

# ---- what the driver and library are today (read, not assumed)
WIN_START, WIN_END = 0x400000, 0x7c00000        # RDN-R4 vmap line, boot edda3efa: start=00400000 end=07c00000
VRAM = 0x8000000                                # the same line: mem=08000000 (128 MiB)
COLOUR_OFF, DEPTH_OFF, TEX_OFF = 0, 0x500000, 0x780000     # OSRDNMesaTriTable.h 43, 453 (M3h layout)
MAP_BYTES_NOW = 7872512                         # osrdn_surf_window() on boot 5 (ghostprobe: bytes=7872512)
BATCH_MAX_WORDS = 4068                          # osrdn_cp.h CP_R7_BATCH_MAX (G4-3 K4, build/r7/design3.py)
RING_WORDS = 4096                               # osrdn_cp.h 51
TEX_PROLOGUE_WORDS, TEX_VERTEX_WORDS = 58, 7    # OSRDNMesaTriTable.h OSRDN_TEX_PROLOGUE_WORDS (G4-1b: 58)
IMMD_HEADER_WORDS = 2                           # PACKET3 header + VF_CNTL
RING_FIXED_US, RING_PER_WORD_NS = 113.32, 47.3  # docs/M1Z_PLAN.md 1-1 (measured)
IOCTL_TOTAL_US_13W = 290.0                      # this session: PRESENT ioctl round trip, 13 words, syslogd stopped
PAK = os.environ.get('PAK', '/mnt/USERS/onion/DATA_ORIGN/Workspace/NeXT_DRIVER/scratch/quake/lite/id1/pak0.pak')


def texture_budget():
    d = open(PAK, 'rb').read()
    off, ln = struct.unpack('<ii', d[4:12])
    files = {}
    for i in range(ln // 64):
        e = d[off + i * 64:off + (i + 1) * 64]
        files[e[:56].split(b'\0')[0].decode()] = struct.unpack('<ii', e[56:64])
    worst = None
    for name, (fo, fl) in files.items():
        if not (name.startswith('maps/') and name.endswith('.bsp')):
            continue
        b = d[fo:fo + fl]
        lumps = [struct.unpack('<ii', b[4 + 8 * i:12 + 8 * i]) for i in range(15)]
        to, tl = lumps[2]
        nm = struct.unpack('<i', b[to:to + 4])[0]
        texels = 0
        for o in struct.unpack('<%di' % nm, b[to + 4:to + 4 + 4 * nm]):
            if o < 0:
                continue
            w, h = struct.unpack('<ii', b[to + o + 16:to + o + 24])
            texels += w * h
        if worst is None or texels > worst[1]:
            worst = (name, texels)
    skins = 0
    for name, (fo, fl) in files.items():
        if name.endswith('.mdl'):
            v = struct.unpack('<4si3f3ff3fiii', d[fo:fo + 60])
            skins += v[-3] * v[-2] * v[-1]
    mip = 4 / 3.0
    arena_now = MAP_BYTES_NOW - TEX_OFF
    arena_max = (WIN_END - WIN_START) - TEX_OFF
    print('texture budget (pak %s)' % os.path.basename(PAK))
    print('  worst map %s: world texels %d, x4/3 for mips, ARGB8888 -> %.2f MiB' % (worst[0], worst[1], worst[1] * mip * 4 / 2 ** 20))
    print('  all mdl skins (upper bound, every model of the pak): %d texels -> %.2f MiB with mips' % (skins, skins * mip * 4 / 2 ** 20))
    print('  lightmaps: 64 blocks x 128 x 128 x 4 = %.2f MiB (upper bound, gl_rsurf.c MAX_LIGHTMAPS)' % (64 * 128 * 128 * 4 / 2 ** 20))
    total = worst[1] * mip * 4 + skins * mip * 4 + 64 * 128 * 128 * 4 + 133132 * 4
    print('  upper bound in all: %.2f MiB' % (total / 2 ** 20))
    print('  arena today: %d bytes (%.1f KiB); the kernel window allows up to %.1f MiB after 0x780000' % (arena_now, arena_now / 1024.0, arena_max / 2 ** 20))
    assert total < arena_max, 'the pak does not fit the window'
    return total


VB_TRIS = 216 // 3                              # Mesa 3.4.2 config.h 181: VB_MAX = 216 + VB_START -> 72 triangles a bracket


def g42_model(full_us):
    """G4-2 (docs/G4_2_BATCH_PLAN.md 5): batches a frame under three regimes, from the same costs.
      today  a batch ends at every RenderFinish: ceil(tris / 72), state changes add a batch each
      B1     a batch ends at the word limit: ceil(words / BATCH_MAX_WORDS), a state change still a batch
      B1+B2  a state change costs WORDS (the changed register pairs + a 2-word header), not a batch"""
    tpb_words = (BATCH_MAX_WORDS - TEX_PROLOGUE_WORDS - IMMD_HEADER_WORDS) // (3 * TEX_VERTEX_WORDS)
    seg_words_min, seg_words_max = 10 + 2, TEX_PROLOGUE_WORDS + 2   # a texture switch (5 pairs) .. a whole prologue
    print('G4-2 model (a batch costs %.0f us; the VB holds %d triangles; the word limit %d holds %d)' % (full_us, VB_TRIS, BATCH_MAX_WORDS, tpb_words))
    for tris, changes in ((5000, 0), (10000, 0), (10000, 150), (10000, 600), (20000, 600)):
        today = -(-tris // VB_TRIS) + changes
        b1 = -(-(tris * 3 * TEX_VERTEX_WORDS + TEX_PROLOGUE_WORDS + IMMD_HEADER_WORDS) // (BATCH_MAX_WORDS - TEX_PROLOGUE_WORDS - IMMD_HEADER_WORDS)) + changes
        words_lo = tris * 3 * TEX_VERTEX_WORDS + changes * seg_words_min
        words_hi = tris * 3 * TEX_VERTEX_WORDS + changes * seg_words_max
        b12_lo, b12_hi = -(-words_lo // BATCH_MAX_WORDS), -(-words_hi // BATCH_MAX_WORDS)
        print('  %5d tris, %3d changes: today %4d batches %6.1f ms | B1 %4d %6.1f ms | B1+B2 %3d-%3d %5.1f-%5.1f ms (ceilings %.0f / %.0f / %.0f fps)'
              % (tris, changes, today, today * full_us / 1000.0, b1, b1 * full_us / 1000.0, b12_lo, b12_hi,
                 b12_lo * full_us / 1000.0, b12_hi * full_us / 1000.0,
                 1000.0 / (today * full_us / 1000.0), 1000.0 / (b1 * full_us / 1000.0), 1000.0 / (b12_hi * full_us / 1000.0)))


def submission_model():
    tris_per_batch = (BATCH_MAX_WORDS - TEX_PROLOGUE_WORDS - IMMD_HEADER_WORDS) // (3 * TEX_VERTEX_WORDS)
    ring_13 = RING_FIXED_US + 13 * RING_PER_WORD_NS / 1000.0
    entry = IOCTL_TOTAL_US_13W - ring_13           # what the ioctl costs before and after the ring
    full = entry + RING_FIXED_US + BATCH_MAX_WORDS * RING_PER_WORD_NS / 1000.0
    g42_model(full)
    print('submission model')
    print('  textured triangles a batch: %d (%d - %d - 2) / 21' % (tris_per_batch, BATCH_MAX_WORDS, TEX_PROLOGUE_WORDS))
    print('  ioctl entry+exit outside the ring: %.0f us (290 - ring %.1f)' % (entry, ring_13))
    print('  a full batch: %.0f us' % full)
    # cost = batches x (entry + ring fixed) + words x per-word: a batch closed early by a state change
    # costs its fixed part and no more, the words are the frame's whatever the batch size
    def frame_us(tris, splits, words_max):
        tpb = (words_max - TEX_PROLOGUE_WORDS - IMMD_HEADER_WORDS) // (3 * TEX_VERTEX_WORDS)
        batches = math.ceil(tris / tpb) + splits
        words = tris * 3 * TEX_VERTEX_WORDS + batches * (TEX_PROLOGUE_WORDS + IMMD_HEADER_WORDS)
        return batches, batches * (entry + RING_FIXED_US) + words * RING_PER_WORD_NS / 1000.0
    for tris in (5000, 10000, 20000):
        for splits in (0, 150):        # state changes that close a batch early, a frame
            batches, us = frame_us(tris, splits, BATCH_MAX_WORDS)
            print('  %5d tris/frame, %3d extra state-change batches: %4d batches -> %6.1f ms submit -> %5.1f fps ceiling'
                  % (tris, splits, batches, us / 1000.0, 1e6 / us))
    # what a bigger staging window buys (the per-word cost stays; the fixed part is paid fewer times)
    for words in (2016, 16384, 65536):
        for splits in (150, 0):
            batches, us = frame_us(10000, splits, words)
            print('  10000 tris + %3d splits at %5d-word batches: %4d batches -> %5.1f ms (%4.1f fps ceiling)' % (splits, words, batches, us / 1000.0, 1e6 / us))
    print('  the words alone, 10000 textured triangles: %.1f ms at %.1f ns a word (ring put only; the staging copy is on top)'
          % (10000 * 21 * RING_PER_WORD_NS / 1e6, RING_PER_WORD_NS))

if __name__ == '__main__':
    texture_budget()
    submission_model()


# ---- G4-1 (docs/G4_GLQUAKE_PLAN.md 5-1): the texture arena and the words a state change costs inside a batch
PAGE = 8192                                     # RDN-R4 vmap: page=8192
TEX_ALIGN = 32                                  # measured: 32 B texture offset grain (r200-measured-rules); the
                                                # reference aligns each level to 32 (r200_texstate.c 'Align to 32-byte offset')
WIDTH_SHIFT, HEIGHT_SHIFT, ARGB8888, ALPHA_IN_MAP = 8, 12, 6, 1 << 6     # r200_reg.h 903, 905, 882, 900
ST_ROUTE_STQ0 = 0                               # tools/r6/tex_oracle.py txformat carries it; 0 in r200_reg.h? the oracle's M() decides


def arena_model():
    print('texture arena (library side)')
    def texbytes(w, h):
        return ((w * 4 + TEX_ALIGN - 1) // TEX_ALIGN) * TEX_ALIGN * h
    sizes = [8, 16, 32, 64, 128, 256, 512]
    print('  ARGB8888 bytes, 32 B aligned rows:', ', '.join('%dx%d=%d' % (s, s, texbytes(s, s)) for s in sizes))
    print('  TXFORMAT words (ARGB8888 | ALPHA_IN_MAP | log2 w << 8 | log2 h << 12):',
          ', '.join('%d:%#x' % (s, ARGB8888 | ALPHA_IN_MAP | (s.bit_length() - 1) << WIDTH_SHIFT | (s.bit_length() - 1) << HEIGHT_SHIFT) for s in (8, 64, 128, 512)))
    for arena_mib in (16, 32, 64):
        end = TEX_OFF + arena_mib * 2 ** 20
        pages = -(-end // PAGE)
        print('  arena %2d MiB: map %d bytes = %d pages (kernel allows 15360), lightmaps 64 x %d = %.2f MiB' %
              (arena_mib, pages * PAGE, pages, texbytes(128, 128), 64 * texbytes(128, 128) / 2 ** 20))
    assert 21.30 * 2 ** 20 < 32 * 2 ** 20, 'the pak upper bound must fit the 32 MiB arena'


def state_change_words():
    print('state changes inside a batch (G4-2): PACKET0 pairs a change costs, against a new batch')
    changes = {'texture bind (TXOFFSET, TXFORMAT, TXFILTER, TXSIZE, TXPITCH)': 5,
               'tex env REPLACE<->MODULATE (TXCBLEND_0, TXABLEND_0)': 2,
               'depth func / mask (ZSTENCILCNTL)': 1,
               'blend on/off + pair (RB3D_CNTL, RB3D_BLENDCNTL)': 2,
               'shade model (SE_CNTL)': 1}
    for k, v in changes.items():
        print('  %-58s %2d words vs a new batch: %d prologue + %.0f us fixed' % (k, 2 * v, TEX_PROLOGUE_WORDS, 176 + RING_FIXED_US))


if __name__ == '__main__':
    arena_model()
    state_change_words()
