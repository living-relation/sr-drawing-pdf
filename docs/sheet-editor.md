# Sheet editor

The add-in folder contains a sheet editor, `sheet2d`. It draws size B sheets (11 by 17 inches, 431.8 by 279.4 mm) and writes a PDF. It does not use Fusion's drawing sheets. The toolbar button is unchanged and does not open this editor yet.

The same commands serve a future Fusion panel and an agent. A command takes the drawing as a dict and returns a new dict. Nothing here imports Fusion.

## Drawing dict

`execute(None, ...)` starts a new drawing. After that, keep the `document` from each result and pass it back.

The dict holds:

- `properties` — project, title, part number (`pn`), rev, material, scale, units, date, drawn, source, and an optional `tol` string
- `draft` — a draft number, or null
- `revlog` — release rows (rev, description, by, date)
- `bom` — rows with a stable `key` and a display `item` number
- `notes` — notes with a stable `key`
- `sheets` — ordered sheets, each with elements (view frame, BOM region, notes block, balloon, note flag)
- `sizes` — extra sheet sizes. Size B is always available.

`save` writes that dict as JSON. `load` reads it back. That file is the drawing.

Title fields are linked. `set_title` changes the document, and every sheet shows the new value on the next export. `SHEET` is `n OF m` from the sheet order. A sheet can set its own scale (sheet 2 of the sample uses `AS SHOWN`).

## Commands

Call `execute(document, name, args)`. `args` is a dict. The result is always:

```python
{'document': {...}, 'result': {...}}
```

The dict you passed is not changed.

Pass an `id` or `key` when you create something. Sending the same command again updates that item instead of adding a second one. Removing a missing id does nothing.

| Command | What it does |
| --- | --- |
| `list_commands` | The command names |
| `add_sheet` | Add a sheet. `size` defaults to `B`. Optional `scale` |
| `remove_sheet` | Remove a sheet and the items placed on it |
| `reorder_sheets` | `order` lists every sheet id once |
| `add_sheet_size` | Register another size on this drawing (`name`, `width`, `height`, `label`) |
| `set_title` | Set one linked field (`field`, `value`) |
| `title_block` | The values one sheet will draw, including `n OF m` |
| `add_revision` | Add or update a rev-log row. Needs `rev`, `desc`, `by`, `date` |
| `revision_table` | The rows sheet 1 will draw |
| `load_revlog` / `save_revlog` | Read or write `REVLOG.md` |
| `set_draft` | `n` is the draft number, or null to clear it |
| `add_bom_row` / `edit_bom_row` / `remove_bom_row` | BOM rows |
| `renumber_bom` | New item numbers in list order. Balloons follow the row key |
| `load_bom_csv` | CSV text or a file. Headers: item, qty, part number, description, material, shown |
| `load_bom_components` | A list of records with `part_number`, `description`, `material`, `qty` |
| `place_bom` / `move_bom` / `remove_bom` | A BOM region: `sheet`, `x1`, `ytop`, `max_height` (mm) |
| `layout_bom` | Which rows fit in each region |
| `place_balloon` / `move_balloon` / `delete_balloon` | An item balloon. Stores `bom_key`, not a frozen number |
| `add_note` / `edit_note` / `delete_note` | Numbered notes |
| `place_notes` / `move_notes` / `delete_notes` | Where the notes block sits |
| `place_note_flag` / `move_note_flag` / `delete_note_flag` | A flag balloon. Stores `note_key` |
| `place_view` / `move_view` / `delete_view` | An empty view frame |
| `sheet_marks` | Balloons and note flags on one sheet, with the numbers they show now |
| `check` | Warnings. Export still runs |
| `export_pdf` | Write the PDF (`path`) |
| `save` / `load` | The drawing JSON |

Named functions do the same thing: `api.set_title(document, field='title', value='BRACKET')`.

Rev letters skip I, L, O, and Q. `add_revision` refuses a clerical rev such as `C.01` (use `set_title` for that; it does not add a log row). Rev A is always "Initial", and that row sets DRAWN. The sheet shows the newest rows when the log is long. Dates in the log are dd/mm/yy.

`set_draft` prints `DRAFT n, NOT RELEASED` and a light watermark. It does not change the rev letter and it does not add a `.01` row.

A BOM region that fills continues into the next region, on the same sheet or another. The continuation is labeled `BILL OF MATERIALS (CONT.)`. Rows that still do not fit are listed in `overflow` and are not drawn.

`load_bom_components` takes plain records. It does not read Fusion. A later stage can fill those records from SR BOM properties on the components.

`check` warns if the title rev letter does not match the newest log row, if initials look wrong, if two BOM rows share an item number, if a BOM region has no height, overlaps the title block or the rev table, or runs off the sheet, if BOM rows do not fit, or if a balloon points at a missing row. The PDF is still written, so a drawing can be saved in the middle of an edit. `place_bom` rejects a `max_height` of 0 or less.

The PDF embeds DejaVu Sans (the same family as the filed drawings), subset to the glyphs that PDF uses, with a ToUnicode map so the text stays searchable. Diameter (⌀), ≤, and ≥ draw as themselves. A character the font does not have is named in the export warnings. BOM text uses the handbuilt parts-list size: 2.0 mm, drawn at 7.874 pt.

The tolerance block does not add an edge-break line. Put that text in the `tol` field only when you want it on that drawing.

Sheet rules that this package draws are in `SRDrawingPDF/sheet2d/SHEET-RULES.md`.

## Preview outside Fusion

```text
python dev/render_sample.py sample-sheet.pdf
```

That writes a two-sheet sample through the same commands. The view frames are empty. The parts are stand-ins, not a filed package.

## Driving from an agent

The owner's Fusion MCP (https://github.com/living-relation/autodesk-fusion-mcp) is a separate add-in. This repo does not include it. That add-in has an `execute_python` tool that runs code on Fusion's main thread. A call should finish well under its 120 second limit. These commands are local drawing math and a PDF write.

Do not call the add-in's `run()` or `stop()` from `execute_python`. `stop()` froze Fusion's main thread in testing. Use `editor_api()` and the commands below. Nothing else.

Fusion keeps simple variables between calls, not imported modules. Keep the drawing dict in `drawing_doc`. On a PC where the add-in folder is junctioned into Fusion's AddIns folder, Fusion can load two copies of this file (the junction path and the real folder). They are the same add-in. Ask every loaded copy for the API; `editor_api()` follows the link and returns the one command module.

```python
import sys
copies = [m for m in sys.modules.values() if getattr(m, 'CMD_ID', None) == 'srDrawingPdfCmd']
if not copies:
    raise RuntimeError('SR Drawing PDF is not loaded. Start the add-in. Do not call run() or stop().')
api = None
err = None
for addin in copies:
    try:
        api = addin.editor_api()
        break
    except RuntimeError as exc:
        err = exc
if api is None:
    raise err
drawing_doc = globals().get('drawing_doc')
```

Set a title:

```python
step = api.execute(drawing_doc, 'add_sheet', {'id': 's1', 'name': 'Sheet 1'})
drawing_doc = step['document']
step = api.execute(drawing_doc, 'set_title', {'field': 'title', 'value': 'SAMPLE BRACKET ASSEMBLY'})
drawing_doc = step['document']
step = api.execute(drawing_doc, 'set_title', {'field': 'pn', 'value': 'SR-SAMPLE-100'})
drawing_doc = step['document']
_mcp_result = step['result']
```

Use the same id on a retry. `add_sheet` with `id` `s1` again does not add a second sheet.

Export:

```python
pdf_path = globals().get('pdf_path')  # a path you chose
step = api.execute(drawing_doc, 'export_pdf', {'path': pdf_path})
drawing_doc = step['document']
_mcp_result = {'pages': step['result']['pages'], 'warnings': step['result']['warnings']}
```

`by` on `add_revision` is the initials of the person who asked for the change (2 to 4 letters). Do not send an agent or tool name.
