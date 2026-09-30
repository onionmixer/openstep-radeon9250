#!/usr/bin/env python3
"""build-inspector-nib.py - build OSRDNDisplay's DisplayInspector.nib.

docs/R3_MULTIMODE_PLAN.md 25-4 and 26.  The base is Configure.app's own
DisplayInspector.nib, taken byte for byte, with only the File's Owner class
renamed to OSRDNDisplayInspector.  Onto that we graft one radio matrix for
"Gray Levels" and two labels.  This is the Matrox replacement driver's
script (openstep-matrox-remade/OSMGADisplay/nib-src/build-inspector-nib.py)
cut down to one control; every step it keeps is one that script needs too.

    python3 tools/r3/build-inspector-nib.py <nibmaker-dir> <stock-nib-dir> \\
            <switch-template.xml> <radio-template.xml> <out-dir>

    switch-template.xml = openstep-spacesaver2ps2/ref/nibtemplates/
                          PS2MouseInspector.xml   (its label 23 is used)
    radio-template.xml  = openstep-spacesaver2ps2/ref/nibtemplates/
                          radio-template-BusLogicIntrInspector.xml  (Matrix 12)
    stock nib           = /NextAdmin/Configure.app/English.lproj/
                          DisplayInspector.nib, fetched once (build/stocknib;
                          docs/R3_MULTIMODE_PLAN.md 25-11 has its sha256)

The stock inspection view (NeXT coordinates, y up):

    65 WindowTemplate
      49 View  [1,1,399,93]                 content of the inspection window
        48 Box [9,14,382,66]                outlet displayMode
          52 View [0,0,382,66]
            54 CustomView [10,9,362,19]     outlet displayAccessoryHolder
            55 Box [8,9,364,53]             modeText + "Select..."

Everything goes inside box 48: IODisplayInspector installs that box into the
base inspector's accessory area and drops the rest of this nib's content
view (measured on the Matrox driver, same machine, same stock nib).  Box 48,
its view 52, the content view and the window grow by GROW, and 54/55 move up
by GROW so the new rows sit underneath them.

Layout, y counting up inside view 52 (python, docs/R3_MULTIMODE_PLAN.md 25-4;
REL3 row added by docs/REL3_DISPLAY_FIX_PLAN.md 3-4):
    caption  y=6,  h=14  -> top 20
    row      y=28, h=15  -> top 43   ("Gray levels:" label + 4-cell radio)
    row      y=50, h=16  -> top 66   ("H position:" label + slider + its value)
The stock children were at y=9, so the gap above our top row is
(9 + GROW) - 66; the Matrox rule keeps it at the 23 the panel already has,
so GROW = 23 + 66 - 9 = 80 (57 with the gray row alone, 1.0 and 1.1).  The
same rule gives Matrox's 174.  The built
nib is measured against all of this by tools/r3/check_nib_r3d.py (H5).
"""
import os
import subprocess
import sys

NIBMAKER, STOCK, SWITCH_TEMPLATE, RADIO_TEMPLATE, OUT = sys.argv[1:6]
sys.path.insert(0, os.path.join(NIBMAKER, 'tools'))
from nibgraft import Nib  # noqa: E402

OWNER_CLASS = 'OSRDNDisplayInspector'
OWNER = '1'          # File's Owner
WINDOW = '65'        # WindowTemplate of the inspection view
CONTENT = '49'       # its content view
MODE_BOX = '48'      # outlet displayMode -- the only part Configure shows
MODE_VIEW = '52'     # box 48's content view; the new rows go here
MODE_INNER = ('54', '55')   # its existing children, moved up to make room
EXPECT_CLASS = {WINDOW: 'WindowTemplate', CONTENT: 'View', MODE_BOX: 'Box',
                MODE_VIEW: 'View', '54': 'CustomView', '55': 'Box'}

TEMPLATE_FONT = '10'     # Helvetica 12 in both templates
LABEL_SRC = '23'         # a plain borderless TextField label in the switch template
LABEL_SUPERVIEW = '2'    # its superview there

STOCK_CHILD_Y = 9        # where 54 and 55 sit in the stock nib
GAP_ABOVE = 23           # the stock panel's own gap, kept
Y_CAPTION, H_CAPTION = 6, 14
Y_GRAY, H_GRAY = 28, 15
Y_HSYNC, H_HSYNC = 50, 16                 # the template slider's own height
TOP = max(Y_CAPTION + H_CAPTION, Y_GRAY + H_GRAY, Y_HSYNC + H_HSYNC)
GROW = GAP_ABOVE + TOP - STOCK_CHILD_Y
assert GROW == 80, GROW

CAPTION_X, CAPTION_W = 14, 340
GRAY_LABEL_X, GRAY_LABEL_W = 12, 96
GRAY_MATRIX_X = 112
GRAY_CELL_W, GRAY_CELL_H, GRAY_GAP = 54, 15, 4
GRAY_TITLES = ('256', '16', '4', '2')     # tag = index = osrdn_graypanel.h's table
CAPTION = 'Gray levels: BW:8 only. Both take effect after the next reboot.'
# REL3: "RDN HSync Adjust", -16..48 pixels (osrdn_hsyncpanel.h); the slider is
# PS2MouseInspector.xml's (oid 21, SliderCell 22), proven in a shipped panel
SLIDER_SRC = '21'
HSYNC_LABEL_X, HSYNC_LABEL_W = GRAY_LABEL_X, GRAY_LABEL_W
HSYNC_SLIDER_X, HSYNC_SLIDER_W = GRAY_MATRIX_X, 151
HSYNC_VALUE_X, HSYNC_VALUE_W = HSYNC_SLIDER_X + HSYNC_SLIDER_W + 6, 40
HSYNC_MIN, HSYNC_MAX, HSYNC_DEFAULT = -16, 48, 7


# ---------------------------------------------------------------- base
stock_xml = os.path.join(OUT, 'stock.xml')
with open(stock_xml, 'w') as fh:
    subprocess.check_call([os.path.join(NIBMAKER, 'nib2xml'),
                           os.path.join(STOCK, 'data.nib')], stdout=fh)
n = Nib(stock_xml)

# the object numbers are the stock nib's; check them by class, not by trust
for oid, cls in EXPECT_CLASS.items():
    got = n.obj(oid).get('cls')
    assert got == cls, 'stock object %s is %s, expected %s' % (oid, got, cls)

owners = [o for o in n.find_by_class('CustomObject')
          if n.cstring(o, '*@').get('v') == 'IODisplayInspector']
assert len(owners) == 1, 'expected exactly one IODisplayInspector owner'
assert owners[0].get('oid') == OWNER, 'the owner is not object %s' % OWNER
sh = n.cstring(owners[0], '*@')
sh.set('v', OWNER_CLASS)
sh.set('wrap', '1')


def cell_of(control):
    """The cell object defined inside a Control's 'i@s' group."""
    return [c for c in n.group(control, 'i@s')][1]


def set_ints(group, values):
    """Integers in place, with the wide flag a value over 127 needs."""
    ints = [i for i in group if i.tag == 'i']
    assert len(ints) >= len(values), 'group holds fewer integers than given'
    for i, v in zip(ints, values):
        i.set('v', str(v))
        i.set('w', '1' if abs(int(v)) > 127 else '0')


# ------------------------------------------------------------ make room
# The WindowTemplate has ONE 'ffff' group, so set_frame (which also writes a
# second, the bounds) cannot be used on it; 93 + 57 = 150 needs the wide flag.
win = n.obj(WINDOW)
wx, wy, ww, wh = n.frame(win)
set_ints(n.group(win, 'ffff', 0), (wx, wy, ww, wh + GROW))

for oid in (CONTENT, MODE_BOX, MODE_VIEW):
    x, y, w, h = n.frame(n.obj(oid))
    n.set_frame(n.obj(oid), x, y, w, h + GROW)

for oid in MODE_INNER:
    x, y, w, h = n.frame(n.obj(oid))
    n.set_frame(n.obj(oid), x, y + GROW, w, h)

# ------------------------------------------------------------ the rows
tmpl = Nib(SWITCH_TEMPLATE)
# Two Helvetica 12 fonts exist in the stock nib; the first in document order
# is the one the Matrox panel uses.
OURS_HELVETICA_12 = next(oid for oid, o in n.objs.items()
                         if o.get('cls') == 'Font'
                         and [c.get('v') for c in n.group(o, '%fss')][:2]
                             == ['Helvetica', '12'])
LABEL_MAP = {LABEL_SUPERVIEW: MODE_VIEW, TEMPLATE_FONT: OURS_HELVETICA_12}


def add_slider(x, y, w, h, lo, hi, value, outlet, action):
    """The template slider, its cell's range and value set: the SliderCell's
    'dddf@d@' group holds max, min, value first (the template's 400, 50, 350
    is the only order in which the value lies inside the range)."""
    sl = n.graft_from(tmpl, SLIDER_SRC, obj_map=dict(LABEL_MAP))
    n.reindex()
    n.add_subview(MODE_VIEW, sl, x, y, w, h)
    n.reindex()
    cell = cell_of(sl)
    assert cell.get('cls') == 'SliderCell', cell.get('cls')
    set_ints(n.group(cell, 'dddf@d@'), (hi, lo, value))
    n.add_connector('IBOutletConnector', OWNER, sl.get('oid'), outlet)
    n.add_connector('IBControlConnector', sl.get('oid'), OWNER, action)
    n.reindex()
    return sl


def add_label(text, x, y, w):
    # graft -> attach -> reindex, never two grafts before attaching:
    # reindex counts attached objects only, so a detached graft's numbers
    # would be handed out again
    lb = n.graft_from(tmpl, LABEL_SRC, obj_map=dict(LABEL_MAP))
    n.reindex()
    n.set_cstring(cell_of(lb), text)
    n.add_subview(MODE_VIEW, lb, x, y, w, H_CAPTION)
    n.reindex()
    return lb


def add_matrix(titles, x, y, cell_w, cell_h, gap, outlet, action):
    """The template matrix is 2 rows x 1 column of two cells; clone the
    second until there are len(titles), then re-lay it as one row."""
    radio = Nib(RADIO_TEMPLATE)
    rmatrix = [o for o in radio.objs.values() if o.get('cls') == 'Matrix'][0]
    rsuper = [c for c in radio.groups(rmatrix)[0]][0].get('oid')
    mat = n.graft_from(radio, rmatrix.get('oid'),
                       obj_map={TEMPLATE_FONT: OURS_HELVETICA_12, rsuper: MODE_VIEW})
    n.reindex()
    n.add_subview(MODE_VIEW, mat, x, y,
                  len(titles) * cell_w + (len(titles) - 1) * gap, cell_h)
    n.reindex()

    cells_group = n.group(mat, '@:@iiii')
    cells_list = [c for c in cells_group][0]
    assert cells_list.get('cls') == 'List', 'matrix cell list not where expected'
    first_cells = list(n.list_items(cells_list))
    assert len(first_cells) == 2, 'the template matrix should have two cells'
    cells = first_cells[:]
    for _ in range(len(titles) - len(first_cells)):
        c = n.clone(first_cells[1].get('oid'))
        n.list_append(cells_list, c)
        n.reindex()
        cells.append(c)
    for tag, (c, title) in enumerate(zip(cells, titles)):
        n.set_cstring(c, title)
        set_ints(n.group(c, 'i:'), (tag,))

    # selected cell -> the first (tag 0, "256"), and one row of len(titles)
    sel = [c for c in cells_group][2]
    sel.set('oid', cells[0].get('oid'))
    sel.set('ref', '0')
    set_ints(cells_group, (0, 0, 1, len(titles)))
    set_ints(n.group(mat, 'ff', 0), (cell_w, cell_h))
    set_ints(n.group(mat, 'ff', 1), (gap, 0))
    n.add_connector('IBOutletConnector', OWNER, mat.get('oid'), outlet)
    n.add_connector('IBControlConnector', mat.get('oid'), OWNER, action)
    n.reindex()
    return mat


add_label('Gray levels:', GRAY_LABEL_X, Y_GRAY, GRAY_LABEL_W)
add_matrix(GRAY_TITLES, GRAY_MATRIX_X, Y_GRAY, GRAY_CELL_W, GRAY_CELL_H, GRAY_GAP,
           'grayMatrix', 'grayChanged:')
# the driver reads the key once, at initialisation; a control that looks
# live but is not would be the worst of the options
add_label(CAPTION, CAPTION_X, Y_CAPTION, CAPTION_W)
add_label('H position:', HSYNC_LABEL_X, Y_HSYNC + 1, HSYNC_LABEL_W)
add_slider(HSYNC_SLIDER_X, Y_HSYNC, HSYNC_SLIDER_W, H_HSYNC, HSYNC_MIN, HSYNC_MAX, HSYNC_DEFAULT,
           'hsyncSlider', 'hsyncChanged:')
value = add_label(str(HSYNC_DEFAULT), HSYNC_VALUE_X, Y_HSYNC + 1, HSYNC_VALUE_W)
n.add_connector('IBOutletConnector', OWNER, value.get('oid'), 'hsyncValue')
n.reindex()

# ------------------------------------------------------- write & verify
# Nib.write() runs fix_object_order/fix_class_order itself; never write the
# tree any other way.
xml_out = os.path.join(OUT, 'DisplayInspector.built.xml')
n.write(xml_out)
nib_out = os.path.join(OUT, 'data.nib')
subprocess.check_call([os.path.join(NIBMAKER, 'xml2nib'), '-r', '-o', nib_out, xml_out])
subprocess.check_call([os.path.join(NIBMAKER, 'nibroundtrip'), nib_out])
subprocess.check_call(['python3', 'tools/validate-xml.py', os.path.abspath(xml_out)], cwd=NIBMAKER)
print('built', nib_out)
