# Agent rules for sr-drawing-pdf

- **Archived.** Work in living-relation/sr-drawing-pack instead (its ADR-065). Do not open new PRs here.

- This repo is **public**. Never commit secrets, tokens, personal or machine paths, or vendor CAD
  files (STEP, f3d, SLDPRT, and the like). `tools/check.py` scans for these.
- Work on a branch and open a PR. Never commit to `main`. Delete the branch once it is merged.
- Run `python tools/check.py` before every push. CI runs the same check.
- This is the SR Drawing PDF Fusion add-in (not an add-in). Keep the add-in folder
  (`SRDrawingPDF/`) self-contained so a junction into Fusion's Scripts folder works.
- Do not write assembly instructions such as tightening torque or threadlocker notes.
- Live Fusion tests: never touch other people's open documents.
  The smoke test closes its own design without saving.
- This is the only agent rules file in the repo. Do not add a CLAUDE.md or any other agent file; put rules here.
- Drawing items: when you add one, offer the options the SOLIDWORKS drawing editor offers for it
  (PropertyManager or table menu) and cite the SOLIDWORKS help page. Never add a detail view
  automatically; only suggest one.
