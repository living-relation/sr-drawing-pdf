# Usage

## Before you start

1. Install the add-in as described in [Install](install.md).
2. Open the Fusion design you want to draw.

## Run

1. Click **SR Drawing PDF** on the **SR Tools** tab, or in the Design workspace Add-Ins, Make, or Insert panel.
2. In the command dialog, confirm or browse to the PDF file path. The default name is the design name plus `_drawing`.
3. Click OK. Fusion opens the **New Drawing** dialog. Click OK and accept the defaults. The add-in is listening for that drawing to open.
4. The add-in sets the sheet to A3 landscape, adds Front, Top, Right and Isometric views, tries to add overall dimensions, exports the PDF, and closes the drawing without saving it.

If no design is open, the add-in asks you to open one first. If it cannot trigger the New Drawing command, it tells you to create a drawing yourself with **File > New Drawing > From Design**; it will still finish the views and PDF when that drawing opens.

## Results

A message box reports the PDF path when the export finishes. The design document stays open. The temporary drawing is discarded.

## Limits and known issues

- The active document must be a saved design. A drawing tab, or a design that was never saved, gets a short message and nothing else happens.
- If you cancel the New Drawing dialog, the add-in stops waiting for the drawing after 5 minutes, or as soon as you run it again.

- You must click OK on the New Drawing dialog. That confirmation cannot be skipped.
- Dimensions are best-effort. If Fusion will not attach them, the PDF is still exported.
- View layout is fixed for an A3 landscape sheet. Very large or very small models may need a manual scale change; the add-in uses automatic scale for the base view.
