"""Sheet chrome rules this package draws.

The look follows the filed 11x17 packages: size B landscape, a full border,
an 8 by 4 zone grid, the title block, the third-angle symbol, and the
tolerance block. Size B is 431.8 by 279.4 mm. Other sizes can be registered
on a drawing; they use the same block layout until a size says otherwise.

Rev letters skip I, L, O, and Q. A clerical rev (C.01) is a drawing-only
change and is not a row in the rev table. The table shows the newest rows
when the log is long. Rev A description is Initial. DRAWN is Rev A's initials.
BY is the person who asked for the change, never an agent name.

Draft mode prints DRAFT n, NOT RELEASED and a light watermark. A draft does
not add a .01 row and does not change the rev letter.

The BOM columns are Item, Qty, Part Number, Description, and Material.
A region that fills continues into the next region, on this sheet or another.
Item balloons store the BOM row key, so a new item number shows up in the
balloon. Note flags store the note key the same way.

The tolerance block does not add an edge-break line unless the drawing
supplies that text itself.

The sheet scale comes from the title block (or the sheet's own scale). Views
at the sheet scale print no view label and no scale label. Default views
(front, top, right, left, back, isometric, trimetric, ...) print no label.
A view gets a subtitle only when its scale differs or the user asks for one.
Detail and section views keep their letter labels and add their scale only
when it differs.

Every dimension has an optional tolerance; with none, the title-block general
tolerance applies. One hole tolerance (size and position) can be set for the
whole file. It is called out in a hole note, in each hole callout, or both.
"""
