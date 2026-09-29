#!/usr/bin/env python3
"""Show that every R3 check in tools/r2b/gen_expect_r2b.py can fail.

  mutate_gen_r3.py

The unmutated generator must report no problem, and each mutation below must
make it report at least one problem naming what was broken -- in the same run
(docs/R3_MULTIMODE_PLAN.md 17).  Nothing is written: mutations touch a
temporary copy of the plan and the loaded modules only.
"""

import copy
import importlib.util
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
GEN = os.path.join(PROJ, 'tools', 'r2b', 'gen_expect_r2b.py')
TEMPS = []


def load():
    spec = importlib.util.spec_from_file_location('gen_for_mutation', GEN)
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    return g


def doc_edit(old, new, count=1):
    """A mutation that rewrites the plan: the first `count` occurrences."""
    def apply(g):
        text = open(g.R3, encoding='utf-8').read()
        if text.count(old) < count:
            raise AssertionError('mutation target %r not in the plan' % old)
        fd, path = tempfile.mkstemp(suffix='.md')
        os.write(fd, text.replace(old, new, count).encode('utf-8'))
        os.close(fd)
        g.R3 = path
        TEMPS.append(path)
    return apply


def text_edit(pattern, repl):
    """A mutation of the EMITTED header, before the checks that parse it."""
    def apply(g):
        build_r3, default_row_check = g.build_r3, g.default_row_check

        def edited(text):
            new = re.sub(pattern, repl, text, count=1)
            if new == text:
                raise AssertionError('mutation target %r not in the output' % pattern)
            return new

        def br3():
            text, problems = build_r3()
            text = edited(text)
            return text, problems + g.decode_check(text)
        g.build_r3 = br3
        g.default_row_check = lambda text: default_row_check(text)
    return apply


def attr(obj_name, name, value):
    def apply(g):
        target = g.rm if obj_name == 'rm' else g
        setattr(target, name, value)
    return apply


def mode_field(index, field, value):
    def apply(g):
        modes = copy.deepcopy(g.rm.MODES)
        modes[index][field] = value
        g.rm.MODES = modes
    return apply


def format_field(index, field, value):
    def apply(g):
        fmts = copy.deepcopy(g.rm.FORMATS)
        fmts[index][field] = value
        g.rm.FORMATS = fmts
    return apply


MUTATIONS = [
    # (label, mutation, a word the problem must contain)
    ('18-2 digest cell',        doc_edit('`11ccfd5cc94e82a3`', '`11ccfd5cc94e82a4`'), '18-2'),
    ('18-2 hole list',          doc_edit('| 5–182 | 8 |', '| 5–182 | 9 |'), '18-2'),
    ('18-2 refdiv 12 word',     doc_edit('| `000600ad` |', '| `000600ae` |'), '18-2'),
    ('18-2 total',              doc_edit('합계 **824** 행', '합계 **823** 행'), '18-2'),
    ('18-3 CRTC word',          doc_edit('`00910410`', '`00910411`'), '18-3'),
    ('18-3 pitch',              doc_edit('`00c800c8`', '`00c800c9`'), '18-3'),
    ('18-4 memorySize',         doc_edit('5120 / 5242880', '5120 / 5242881'), '18-4'),
    ('16-3 FIFO cell',          doc_edit('| `20002828`(', '| `20002829`('), '16-3 FIFO'),
    ('16-3 preserve mask',      doc_edit('preserve 는 모든 조합 `0f808080`', 'preserve 는 모든 조합 `0f808081`'), '16-3'),
    ('16-3 format CRTC',        doc_edit('| `RGB:555/16` | 2 | 3 |', '| `RGB:555/16` | 2 | 4 |'), '16-3 format'),
    ('16-3 format enum value',  doc_edit('`IO_OneIsWhiteColorSpace` = 1', '`IO_OneIsWhiteColorSpace` = 0'), '16-3 format'),
    ('16-3 format enum name',   doc_edit('| `IO_15BitsPerPixel` = 3', '| `IO_12BitsPerPixel` = 3'), '16-3 format'),
    ('16-3 pseudo flag',        doc_edit('`WWWWWWWW` | 아니오', '`WWWWWWWW` | 예'), '16-3 format'),
    ('oracle timing',           mode_field(0, 'hsend', 753), 'timings'),
    ('oracle polarity',         mode_field(3, 'nhsync', 1), 'timings'),
    ('NetBSD file absent',      attr('rm', 'NETBSD_VIDEOMODE', '/nonexistent/videomode.c'), 'timings'),
    ('Matrox timings absent',   attr('rm', 'check_against_matrox', lambda: (None, 0)), 'Matrox'),
    ('Matrox timings differ',   attr('rm', 'check_against_matrox', lambda: (5, 1)), 'Matrox'),
    ('Matrox formats absent',   attr('gen', 'matrox_formats', lambda: None), 'formats'),
    ('Matrox formats differ',   attr('gen', 'matrox_formats', lambda: [
        ('RGB:888/32', '4', 'IO_24BitsPerPixel', 'IO_RGBColorSpace', '--------RRRRRRRRGGGGGGGGBBBBBBBB', '0'),
        ('RGB:555/16', '2', 'IO_15BitsPerPixel', 'IO_RGBColorSpace', '-RRRRRGGGGGBBBBB', '0'),
        ('RGB:256/8', '1', 'IO_8BitsPerPixel', 'IO_RGBColorSpace', 'PPPPPPPP', '1'),
        ('BW:8', '1', 'IO_8BitsPerPixel', 'IO_OneIsBlackColorSpace', 'WWWWWWWW', '0')]), 'formats'),
    ('oracle format cspace',    format_field(3, 'io_cspace', 0), 'format'),
    ('CRTC formulas disagree',  attr('rm', 'xf86_crtc_words',
                                     lambda m: [w ^ 1 for w in __import__('builtins').list(G0.rm.xf86_crtc_words(m))]),
     'two CRTC formulas'),
    ('pitch depends on depth',  attr('rm', 'crtc_pitch',
                                     lambda m, bpp: G0.rm.crtc_pitch(m, 32) + (bpp == 16)), 'depth'),
    ('NetBSD pitch unrounded',  attr('rm', 'netbsd_pitch', lambda m, bpp: m['hdisp'] // 8), 'pitch'),
    ('decode: bad post code',   text_edit(r'\{   5, 0x0007([0-9a-f]{4})U \}', r'{   5, 0x0000\g<1>U }'),
     'decode'),
    ('decode: fb field zero',   text_edit(r'\{  12, 0x00010090U \}', '{  12, 0x00010000U }'), 'decode'),
    ('decode: stray bit',       text_edit(r'\{  12, 0x00040090U \}', '{  12, 0x80040090U }'), 'decode'),
    ('decode: refdiv order',    text_edit(r'\{   5, 0x', '{  99, 0x'), 'decode'),
    ('decode: slice overruns',  text_edit(r'1600, 1200,(.*?), 654, 170, 0UL \}', r'1600, 1200,\1, 654, 171, 0UL }'), 'decode'),
    ('default row HTOTAL_CNTL', text_edit(r'(\{ "800x600", .*?, 177, 168), 0UL \}', r'\1, 1UL }'), 'HTOTAL_CNTL'),
    ('displayDefs.h absent',    attr('gen', 'DISPLAYDEFS', '/nonexistent/displayDefs.h'), 'enums'),
    ('an enum value differs',   attr('gen', 'header_enums', lambda: dict(G0.header_enums(), IO_15BitsPerPixel=5)),
     'enums'),
    ('a pair outgrows the map', attr('gen', 'FB_MAPPED', 0x700000), 'larger than the mapping'),
    ('default row pitch',       text_edit(r'(\{ "800x600", 800, 600(?:, 0x[0-9a-f]{8}UL){4}), 0x00640064UL',
                                          r'\1, 0x00640065UL'), 'default row'),
    ('default slice row',       text_edit(r'(/\* 800x600@60.*?\n(?:.*\n){20})    \{  25, 0x([0-9a-f]{8})U \}',
                                          r'\1    {  25, 0x0003ffffU }'), 'default divider slice'),
    ('default FIFO cell',       text_edit(r'(osrdnFifoAll\[.*?\n.*\n)    \{ \{ 0x20005c5cUL',
                                          r'\1    { { 0x20005c5dUL'), 'default FIFO'),
    ('PLL count macro',         text_edit(r'OSRDN_PLL_ALL_COUNT     824', 'OSRDN_PLL_ALL_COUNT     825'), 'osrdnPllAll has'),
]

G0 = load()


def main():
    base_text, base = G0.build()
    fails = 0
    if base:
        print('  FAIL the unmutated generator reports %d problems:' % len(base))
        for p in base:
            print('       %s' % p)
        fails += 1
    else:
        print('  ok   unmutated: no problem')
    for label, mutate, word in MUTATIONS:
        g = load()
        try:
            mutate(g)
            _, problems = g.build()
        except AssertionError as e:
            print('  FAIL %-26s mutation did not apply: %s' % (label, e))
            fails += 1
            continue
        except Exception as e:                  # a crash is not a caught mutation
            print('  FAIL %-26s generator crashed: %r' % (label, e))
            fails += 1
            continue
        hit = [p for p in problems if word in p]
        if hit:
            print('  ok   %-26s caught: %s' % (label, hit[0][:90]))
        else:
            print('  FAIL %-26s NOT caught (%d other problems)' % (label, len(problems)))
            fails += 1
    for path in TEMPS:
        os.remove(path)
    print('mutate_gen_r3: %s (%d mutations)' % ('PASS' if not fails else 'FAIL', len(MUTATIONS)))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
