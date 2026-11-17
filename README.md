# SR Drawing PDF

A Spark Robotic Fusion add-in that makes a four-view technical drawing of the active design and
exports it as a PDF.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Features

- **Toolbar button** "SR Drawing PDF" on several Design-workspace panels: **SR Tools**, Add-Ins, Make, and Insert. The panel list is configurable in `%APPDATA%/SRDrawingPDF/panels.json`.
- Fusion then opens the **New Drawing** dialog. Click OK (accept the defaults).
- The add-in adds Front, Top, Right and Isometric views on an A3 landscape sheet, adds overall dimensions when it can, exports the PDF, and closes the drawing without saving it. The design stays open.
- Dimensions are best-effort; if Fusion will not attach them, the PDF is still exported.

## Requirements

- Autodesk Fusion

## Install

1. Clone this repo and keep the folder on disk.
2. In Fusion: **Utilities > Add-ins > Scripts and Add-ins > Add-ins tab > + (green plus)**, and pick the `SRDrawingPDF` folder inside the clone. Tick **Run on Startup** and click **Run**.

   Or copy or link the `SRDrawingPDF` folder into `%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns\` and restart Fusion.
3. The button shows up on the default panels listed in [Where the buttons go](#where-the-buttons-go).

See [docs/install.md](docs/install.md) for the full steps, including uninstall.

## Where the buttons go

The **SR Drawing PDF** button can show on several Design-workspace toolbar panels at once. By default it is added to:

- **Utilities > Add-ins** (`SolidScriptsAddinsPanel`)
- **Make** (`SolidMakePanel`)
- **Insert** (`InsertPanel`)
- **SR Tools** (`SRToolsPanel`)

By default the button is pinned on SR Tools and on Add-ins. Insert and Make still get the command; Fusion keeps your own pin or unpin choice after the first run.

The list lives in `%APPDATA%\SRDrawingPDF\panels.json`. Create or edit that file, then Stop and Run the add-in (or restart Fusion) so the change takes effect. Example:

```json
{
  "panel_ids": [
    "SolidScriptsAddinsPanel",
    "SolidMakePanel",
    "InsertPanel",
    "SRToolsPanel"
  ]
}
```

Unknown panel ids are skipped. If the file is missing or `panel_ids` is empty or unusable, the defaults above are used. Stopping the add-in removes every toolbar button for this command, including leftovers from an older list.

If `SRToolsPanel` already exists (for example because another SR add-in created it on the SOLID tab), this add-in reuses it. If it does not exist, this add-in creates an **SR Tools** tab in the Design workspace and puts the panel on that tab. If the panel (and its tab) are empty after stop, they are removed too.

## Usage

Open a saved design, run **SR Drawing PDF**, pick the PDF path, then click OK on the New Drawing dialog. See [docs/usage.md](docs/usage.md).

Safety: if the active document is not a design (for example a drawing tab), or the design was never saved, the add-in shows a short message and does nothing. It waits up to 5 minutes for the new drawing and ignores every other document that becomes active, without message boxes or errors, so it cannot lock Fusion up the way the first version did.

This add-in is a stopgap. The plan is to replace it with the agent-driven drawing loop.

## Documentation

- [Overview](docs/overview.md)
- [Install](docs/install.md)
- [Usage](docs/usage.md)
- [Development](docs/development.md)
- [Documentation index](docs/README.md)

## Development

```
python tools/check.py
```

CI runs the same check. `dev/fusion_smoke.py` is a live test that runs inside Fusion. A full PDF export still needs the New Drawing confirmation click. See [docs/development.md](docs/development.md).

## Contributing

Work on a branch and open a pull request against `main`. Update `docs/` when behavior changes. See [docs/development.md](docs/development.md) and [AGENTS.md](AGENTS.md).

## License

This project is licensed under the [MIT License](LICENSE). Copyright (c) 2026 Spark Robotic.
