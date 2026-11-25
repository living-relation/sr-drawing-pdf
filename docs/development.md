# Development

**SR Drawing PDF** is a Fusion add-in written in Python (not an add-in).

## Clone

```
git clone https://github.com/living-relation/sr-drawing-pdf.git
```

Load the `SRDrawingPDF` folder into Fusion as described in [Install](install.md).

## Layout

- `SRDrawingPDF/` — the Fusion add-in (junction this folder into Scripts). Entry point: `SRDrawingPDF.py` and `SRDrawingPDF.manifest`.
- `SRDrawingPDF/sheet2d/` — the size B sheet editor. Pure Python, no Fusion import. The command API is `sheet2d.commands.execute`. See [Sheet editor](sheet-editor.md).
- `tests/` — checks that do not need Fusion (manifest, the sheet model, rev letters, BOM split, balloons).
- `dev/fusion_smoke.py` — live test that runs inside Fusion.
- `dev/render_sample.py` — writes a sample two-sheet PDF with the command API. It does not need Fusion.
- `dev/sheet_demo.py` — a local page for the sample sheet. It does not need Fusion.
- `dev/time_views.py` — times front, top, right and trimetric views of a several-hundred-part assembly and writes a PNG. It does not need Fusion. The full set must finish in 120 seconds. Add `--step assembly.step` to time a real assembly exported from Fusion; that needs OCP (`pip install cadquery-ocp`) and reads it through `dev/step_mesh.py`. Keep STEP files outside this repo.
- `SRDrawingPDF/fusion_read.py` — reads the open Fusion design in short steps (visible bodies, placements, meshes) into a folder. See [Sheet editor](sheet-editor.md#real-views-from-the-open-fusion-design).
- `dev/fusion_sheet.py` — four real views on a size B sheet at one standard scale, to PDF, from a Fusion dump or a STEP file. Prints the times.
- `tools/check.py` — secret/path scan plus pytest. CI runs the same command.

## Coding notes

- This repository is public. Do not commit secrets, tokens, passwords, personal email addresses, machine-specific paths, or vendor CAD files.
- Keep Spark Robotic / SR- naming in user-visible text and repository docs.
- Work on a branch and open a pull request against `main`. Never commit to `main` directly.
- Run `python tools/check.py` before every push. See [AGENTS.md](../AGENTS.md).

## Sheet editor demo

From the repo folder, in a terminal:

```
python dev/sheet_demo.py
```

Open http://127.0.0.1:8765/ . The page draws the sample sheet. To show real views instead, add `--fusion DUMP_FOLDER` (written by `fusion_read.py`) or `--step assembly.step` (needs OCP). Reset goes back to those views. Click a BOM row to highlight that part and show its thumbnail. Drag the top band of a BOM piece to move it. Split above or below the selected row. The yellow ! in the status bar is an open detail-view suggestion; Accept adds the view.

## Tests

```
python tools/check.py
```

`dev/fusion_smoke.py` is a live test. It opens a new scratch design, loads the add-in module, and checks that `run`, `setup_drawing` and `add_dimensions` are present, then closes the design without saving. A full PDF export still needs the New Drawing confirmation dialog, so the smoke test does not click through that dialog. Your open documents are not touched.

`run()` also accepts an optional `pdf_path` so a test can skip the Save dialog. The normal Scripts Run still shows the Save dialog.

## Contributing

1. Create a branch from `main`.
2. Add or update documentation in `docs/` when behavior changes.
3. Run `python tools/check.py`.
4. Open a pull request against `main`. CI must stay green.
