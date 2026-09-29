#!/usr/bin/env python3
"""The user tool's accepted geometries equal the generated header's resolutions.

  check_tool_mode.py [--self-test]

tools/r2b0/rdnr2b0.m refuses to act unless IOGetDisplayInfo reports one of the
resolutions the driver can publish (R3b-2: which one is chosen at boot from
"Display Mode").  The tool is compiled on the target without
osrdn_mode_expect.h on its include path, so it carries the table as literals --
and a table that drifts from the header turns the tool's own gate into a lie.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
TOOL = os.path.join(PROJ, 'tools', 'r2b0', 'rdnr2b0.m')
HDR = os.path.join(PROJ, 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj', 'osrdn_mode_expect.h')


def tool_table(text):
    """[(w, h)] from the tool's wantGeometry, None if absent or miscounted."""
    m = re.search(r'#define\s+WANT_GEOMETRIES\s+(\d+)', text)
    t = re.search(r'wantGeometry\[WANT_GEOMETRIES\]\[2\]\s*=\s*\{(.*?)\};', text, re.S)
    if not m or not t:
        return None
    rows = [(int(a), int(b)) for a, b in re.findall(r'\{\s*(\d+)\s*,\s*(\d+)\s*\}', t.group(1))]
    return rows if len(rows) == int(m.group(1)) else None


def header_table(text):
    """[(w, h)] from the generated header's osrdnResAll rows."""
    return [(int(a), int(b)) for a, b in re.findall(r'\{ "\d+x\d+", (\d+), (\d+),', text)]


def check(tool_text, hdr_text):
    t, h = tool_table(tool_text), header_table(hdr_text)
    if t is None:
        return ['the tool has no well-formed wantGeometry table']
    if not h:
        return ['the header has no resolution rows']
    if t != h:
        return ['the tool accepts %s, the header publishes %s' % (t, h)]
    if 'knownGeometry(info[0], info[1])' not in tool_text:
        return ['the tool does not check the display info against its table']
    return []


def self_test():
    hdr = '{ "640x480", 640, 480, 0x1UL },\n{ "800x600", 800, 600, 0x1UL },\n'
    good = ('#define WANT_GEOMETRIES 2\nstatic const unsigned wantGeometry[WANT_GEOMETRIES][2] = {\n'
            '    {  640,  480 },\n    {  800,  600 }\n};\n  !knownGeometry(info[0], info[1])')
    cases = [(good, 0), (good.replace('600 }', '601 }'), 1), (good.replace('GEOMETRIES 2', 'GEOMETRIES 3'), 1),
             (good.replace('knownGeometry(info[0], info[1])', 'info[0] != 800U'), 1), ('', 1)]
    ok = all(len(check(t, hdr)) == n for t, n in cases)
    print('  %s tool-mode self-test' % ('ok  ' if ok else 'FAIL'))
    return 0 if ok else 1


def main():
    if '--self-test' in sys.argv:
        return self_test()
    bad = self_test()
    problems = check(open(TOOL).read(), open(HDR).read())
    for p in problems:
        print('  FAIL %s' % p)
    if not problems:
        print('  ok   the tool accepts exactly the generated header\'s resolutions')
    return 1 if (problems or bad) else 0


if __name__ == '__main__':
    sys.exit(main())
