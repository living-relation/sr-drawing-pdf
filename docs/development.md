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
- `tools/check.py` — secret/path scan plus pytest. CI runs the same command.

## Coding notes

- This repository is public. Do not commit secrets, tokens, passwords, personal email addresses, machine-specific paths, or vendor CAD files.
- Keep Spark Robotic / SR- naming in user-visible text and repository docs.
- Work on a branch and open a pull request against `main`. Never commit to `main` directly.
- Run `python tools/check.py` before every push. See [AGENTS.md](../AGENTS.md).

## Tests

```
python tools/check.py
```

`dev/fusion_smoke.py` is a live test. Take the machine's Fusion lock first. It opens a new scratch design, loads the add-in module, and checks that `run`, `setup_drawing` and `add_dimensions` are present, then closes the design without saving. A full PDF export still needs the New Drawing confirmation dialog, so the smoke test does not click through that dialog. Your open documents are not touched.

`run()` also accepts an optional `pdf_path` so a test can skip the Save dialog. The normal Scripts Run still shows the Save dialog.

## Contributing

1. Create a branch from `main`.
2. Add or update documentation in `docs/` when behavior changes.
3. Run `python tools/check.py`.
4. Open a pull request against `main`. CI must stay green.
