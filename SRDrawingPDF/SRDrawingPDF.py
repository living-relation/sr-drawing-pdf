"""SR Drawing PDF: a toolbar button that builds a 4-view drawing and exports a PDF.

How it works:
  1. Click SR Drawing PDF. A command dialog asks where to save the PDF.
  2. Click OK. Fusion opens the New Drawing dialog. Click OK (accept the defaults).
  3. The add-in adds Front, Top, Right and Isometric views, adds overall dimensions
     when it can, exports the PDF, and closes the drawing without saving it.
"""
# Compatible with Fusion 360 v2703+
import os
import sys
import time
import traceback

import adsk.core
import adsk.fusion
import adsk.drawing

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from sr_fusion_common import settings, panels  # noqa: E402

CMD_ID = 'srDrawingPdfCmd'
SETTINGS = 'drawing'
_handlers = []  # keep references alive so Python does not garbage-collect them

# Globals to pass state into the drawing-activated handler
_app = None
_ui = None
_design_doc = None
_design = None
_pdf_path = None


def _app_ui():
    return adsk.core.Application.get().userInterface


class _Created(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            app = adsk.core.Application.get()
            design = adsk.fusion.Design.cast(app.activeProduct)
            cmd = args.command
            cmd.setDialogInitialSize(440, 180)
            inputs = cmd.commandInputs
            s = settings.load(SETTINGS, {'pdf_path': ''})
            default_name = 'drawing.pdf'
            if app.activeDocument:
                default_name = app.activeDocument.name + '_drawing.pdf'
            path = s.get('pdf_path') or os.path.join(os.path.expanduser('~'), default_name)
            if not path.lower().endswith('.pdf'):
                path += '.pdf'
            inputs.addStringValueInput('pdf_path', 'PDF file', path)
            inputs.addBoolValueInput('browse', 'Choose file...', False, '', False)
            inputs.addTextBoxCommandInput(
                'note', '',
                'After OK, Fusion opens the New Drawing dialog. Click OK there to accept the defaults.',
                2, True)
            for h, ev in ((_Changed(), cmd.inputChanged), (_Execute(), cmd.execute)):
                ev.add(h)
                _handlers.append(h)
            if design is None:
                inputs.itemById('note').formattedText = ('The active document is not a design. Switch to a design '
                                                         'tab first; OK does nothing here.')
        except Exception:
            _app_ui().messageBox('SR Drawing PDF failed to open:\n' + traceback.format_exc())


class _Changed(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        try:
            if args.input.id != 'browse':
                return
            inputs = args.inputs
            dlg = _app_ui().createFileDialog()
            dlg.title = 'SR Drawing PDF'
            dlg.filter = 'PDF files (*.pdf)'
            dlg.filterIndex = 0
            cur = inputs.itemById('pdf_path').value
            if cur:
                dlg.initialFilename = os.path.basename(cur)
                folder = os.path.dirname(cur)
                if folder and os.path.isdir(folder):
                    dlg.initialDirectory = folder
            dlg.isMultiSelectEnabled = False
            if dlg.showSave() == adsk.core.DialogResults.DialogOK:
                path = dlg.filename
                if not path.lower().endswith('.pdf'):
                    path += '.pdf'
                inputs.itemById('pdf_path').value = path
            args.input.value = False
        except Exception:
            _app_ui().messageBox(traceback.format_exc())


class _Execute(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            inputs = args.command.commandInputs
            path = (inputs.itemById('pdf_path').value or '').strip()
            if not path:
                _app_ui().messageBox('Pick a PDF file path first.')
                return
            if not path.lower().endswith('.pdf'):
                path += '.pdf'
            settings.save(SETTINGS, {'pdf_path': path})
            if adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct) is None:
                _app_ui().messageBox('The active document is not a design. Switch to a design tab first.',
                                     'SR Drawing PDF')
                return
            start_export(path)
        except Exception:
            _app_ui().messageBox('SR Drawing PDF failed:\n' + traceback.format_exc())


def run(context, pdf_path=None):
    """Register the toolbar button. If pdf_path is passed (smoke tests), export directly."""
    if pdf_path:
        start_export(pdf_path)
        return
    try:
        ui = _app_ui()
        _remove_ui(ui)
        cd = ui.commandDefinitions.addButtonDefinition(
            CMD_ID, 'SR Drawing PDF',
            'Create a four-view drawing of the active design and export a PDF',
            os.path.join(_HERE, 'resources', 'icon'))
        h = _Created()
        cd.commandCreated.add(h)
        _handlers.append(h)
        panels.add_command(ui, cd, CMD_ID)
    except Exception:
        _app_ui().messageBox('SR Drawing PDF run failed:\n' + traceback.format_exc())


def _remove_ui(ui):
    panels.remove_command(ui, CMD_ID)
    cd = ui.commandDefinitions.itemById(CMD_ID)
    if cd:
        cd.deleteMe()


def stop(context):
    try:
        _stop_listening()
        _remove_ui(_app_ui())
        _handlers.clear()
    except Exception:
        pass


def product_of(doc, product_type):
    """The document's product of this type, or None. Never raises: Fusion's itemByProductType throws
    'RuntimeError: 3 : failed to find product' when a document has no such product (for example asking a
    design for its drawing), and that error inside an event handler is what Daniel hit."""
    try:
        prods = doc.products
        for i in range(prods.count):
            p = prods.item(i)
            if p.productType == product_type:
                return p
    except Exception:
        pass
    return None


def editor_api():
    """The sheet-editor commands, the copy already loaded in this process.

    Agents call this on the add-in module Fusion loaded. It looks in
    sys.modules first and does not put this folder on sys.path again when
    the folder is already there.
    """
    import importlib
    import sys
    here = os.path.dirname(os.path.abspath(__file__))

    def _real(path):
        # realpath follows the junction Fusion uses for AddIns, and a symlink.
        return os.path.normcase(os.path.realpath(path))

    package_root = _real(os.path.join(here, 'sheet2d')) + os.sep

    def _from_here(mod):
        path = getattr(mod, '__file__', None) or ''
        if not path:
            return False
        return _real(path).startswith(package_root)

    named = sys.modules.get('sheet2d.commands')
    if named is not None and getattr(named, 'API_ID', None) == 'srDrawingPdfSheetApi':
        if _from_here(named):
            return named
        raise RuntimeError(
            'sheet2d.commands is already loaded from a different folder. '
            'Restart Fusion so only this add-in is loaded.')
    for mod in list(sys.modules.values()):
        if getattr(mod, 'API_ID', None) == 'srDrawingPdfSheetApi' and _from_here(mod):
            return mod
    target = _real(here)
    already = False
    for entry in sys.path:
        if not entry:
            continue
        try:
            if _real(entry) == target:
                already = True
                break
        except OSError:
            continue
    if not already:
        sys.path.insert(0, here)
    return importlib.import_module('sheet2d.commands')


LISTEN_SECONDS = 300  # stop waiting for the new drawing after this long (cancelled New Drawing dialog)
SETUP_EVENT = 'srDrawingPdfSetup'
_listener = None
_setup_event = None
_listen_started = 0.0
_pending = {}


def _stop_listening():
    """Remove the documentActivated listener and the custom event. Safe to call twice."""
    global _listener, _setup_event
    app = adsk.core.Application.get()
    if _listener is not None:
        try:
            app.documentActivated.remove(_listener)
        except Exception:
            pass
        if _listener in _handlers:
            _handlers.remove(_listener)
        _listener = None
    if _setup_event is not None:
        try:
            app.unregisterCustomEvent(SETUP_EVENT)
        except Exception:
            pass
        _setup_event = None


def start_export(pdf_path=None):
    """Check the active document is a design, then open Fusion's New Drawing dialog and wait for the drawing.

    Fail-safe rules (the old version locked Fusion up):
    - never call itemByProductType (it raises); use product_of()
    - a document that is not a design gets a clear message and nothing else happens
    - the documentActivated handler never shows a message box, never sleeps and never raises; it only
      hands the drawing to a custom event, so the drawing work runs after Fusion finishes opening it
    - only one listener at a time, and it gives up after LISTEN_SECONDS
    """
    global _app, _ui, _design_doc, _design, _pdf_path, _listener, _setup_event, _listen_started

    _app = adsk.core.Application.get()
    _ui = _app.userInterface
    try:
        _stop_listening()
        _design_doc = _app.activeDocument
        if _design_doc is None:
            _ui.messageBox('Open a design first.', 'SR Drawing PDF')
            return False
        _design = adsk.fusion.Design.cast(product_of(_design_doc, 'DesignProductType'))
        if not _design:
            kind = 'a drawing' if product_of(_design_doc, 'DrawingProductType') else 'not a design'
            _ui.messageBox('The active document (%s) is %s.\n\nSwitch to the design tab you want a drawing of, '
                           'then run SR Drawing PDF again.' % (_design_doc.name, kind), 'SR Drawing PDF')
            return False
        if not _design_doc.isSaved:
            _ui.messageBox('Save the design once before making a drawing of it (Fusion makes drawings only from '
                           'saved designs).', 'SR Drawing PDF')
            return False

        if pdf_path:
            _pdf_path = pdf_path
        else:
            dlg = _ui.createFileDialog()
            dlg.title = 'SR Drawing PDF'
            dlg.filter = 'PDF files (*.pdf)'
            dlg.initialFilename = _design_doc.name + '_drawing'
            dlg.isMultiSelectEnabled = False
            if dlg.showSave() != adsk.core.DialogResults.DialogOK:
                return False
            _pdf_path = dlg.filename
        if not _pdf_path.lower().endswith('.pdf'):
            _pdf_path += '.pdf'

        cmd_def = None
        for cmd_id in ('FusionDrawingCreateFromComponentsCommand', 'NewDrawingMenuCommand',
                       'NewFusionDrawingDocumentCommand'):
            cmd_def = _ui.commandDefinitions.itemById(cmd_id)
            if cmd_def:
                break
        if cmd_def is None:
            _ui.messageBox('This Fusion version has no New Drawing command the add-in can open.\n'
                           'Make the drawing with File > New Drawing > From Design instead.', 'SR Drawing PDF')
            return False

        _setup_event = _app.registerCustomEvent(SETUP_EVENT)
        sh = _SetupHandler()
        _setup_event.add(sh)
        _handlers.append(sh)
        _listener = DrawingActivatedHandler()
        _handlers.append(_listener)
        _app.documentActivated.add(_listener)
        _listen_started = time.time()
        cmd_def.execute()
        return True
    except Exception:
        _stop_listening()
        _ui.messageBox('SR Drawing PDF could not start:\n' + traceback.format_exc(), 'SR Drawing PDF')
        return False


class DrawingActivatedHandler(adsk.core.DocumentEventHandler):
    """Fires whenever any document becomes active. Ignores everything that is not a drawing. Never shows UI,
    never sleeps and never raises (a modal box or an exception while Fusion opens a document can hang it)."""

    def notify(self, args):
        try:
            if time.time() - _listen_started > LISTEN_SECONDS:
                _stop_listening()
                return
            doc = args.document
            if product_of(doc, 'DrawingProductType') is None:
                return  # the design (or another document) became active: keep waiting
            _pending['doc'] = doc
            try:
                adsk.core.Application.get().documentActivated.remove(self)
            except Exception:
                pass
            # run the drawing work later, after Fusion has finished activating the drawing
            adsk.core.Application.get().fireCustomEvent(SETUP_EVENT, '')
        except Exception:
            _stop_listening()


class _SetupHandler(adsk.core.CustomEventHandler):
    def notify(self, args):
        doc = _pending.pop('doc', None)
        _stop_listening()
        if doc is None:
            return
        drawing = adsk.drawing.Drawing.cast(product_of(doc, 'DrawingProductType'))
        if not drawing:
            _app_ui().messageBox('SR Drawing PDF: the new document is not a drawing; nothing was done.',
                                 'SR Drawing PDF')
            return
        setup_drawing(drawing, doc)


def setup_drawing(drawing, draw_doc):
    """Add views, dimensions, and export PDF."""
    try:
        sheet = drawing.sheets.item(0)

        # A3 landscape
        fmt = sheet.sheetFormat
        fmt.sheetSize   = adsk.drawing.DrawingSheetSizes.A3SheetSize
        fmt.isLandscape = True
        sheet.sheetFormat = fmt
        adsk.doEvents()

        # ── Base view: Front (lower-left) ────────────────────────────────────
        bi = sheet.drawingViews.createBaseViewInput()
        bi.referencedDocument = _design_doc
        bi.position      = adsk.core.Point3D.create(10.5, 7.4, 0)   # cm
        bi.scale         = 0                                           # auto
        bi.viewOrientation = adsk.drawing.DrawingViewOrientations.FrontDrawingViewOrientation
        bi.viewStyle     = adsk.drawing.DrawingViewStyles.VisibleAndHiddenEdgesDrawingViewStyle
        front = sheet.drawingViews.addBaseView(bi)
        adsk.doEvents()

        # ── Projected views ───────────────────────────────────────────────────
        def proj(parent, x, y):
            pi = sheet.drawingViews.createProjectedViewInput(parent)
            pi.position = adsk.core.Point3D.create(x, y, 0)
            v = sheet.drawingViews.addProjectedView(pi)
            adsk.doEvents()
            return v

        # Layout:  Top (above Front) | Iso (top-right)
        #          Front (lower-left)| Right (lower-right)
        top   = proj(front, 10.5, 19.0)
        right = proj(front, 24.0,  7.4)
        iso   = proj(front, 31.5, 19.0)

        try:
            iso.orientation = adsk.drawing.DrawingViewOrientations.HomeDrawingViewOrientation
        except Exception:
            pass

        adsk.doEvents()

        # ── Overall bounding dimensions ───────────────────────────────────────
        try:
            add_dimensions(sheet, front, top, _design)
        except Exception:
            pass   # dimensions are best-effort

        # ── Export PDF ────────────────────────────────────────────────────────
        exp  = drawing.exportManager
        opts = exp.createPDFExportOptions()
        opts.filename          = _pdf_path
        opts.isOpenAfterExport = True
        exp.execute(opts)
        adsk.doEvents()

        _ui.messageBox(f'SR Drawing PDF saved to:\n{_pdf_path}')

        draw_doc.close(False)   # close drawing, keep design open

    except Exception:
        _ui.messageBox(f'Error (setup_drawing):\n{traceback.format_exc()}')


def add_dimensions(sheet, front_view, top_view, design):
    """Add width, height, and depth overall dimensions."""
    bb = design.rootComponent.boundingBox
    if not bb:
        return

    # Fusion units are cm
    w = bb.maxPoint.x - bb.minPoint.x   # width
    h = bb.maxPoint.z - bb.minPoint.z   # height
    d = bb.maxPoint.y - bb.minPoint.y   # depth

    dims = sheet.drawingDimensions

    def pt(x, y):
        return adsk.core.Point3D.create(x, y, 0)

    def linear(view, p1, p2, text_pt):
        try:
            di = dims.createLinearDimensionInput(
                adsk.drawing.DimensionReferenceGeometryTypes.PointDimensionReferenceGeometryType,
                adsk.drawing.DimensionReferenceGeometryTypes.PointDimensionReferenceGeometryType,
            )
            di.setByPoints(view, p1, view, p2, text_pt)
            dims.addLinearDimension(di)
        except Exception:
            pass

    # Front: width across the bottom, height up the right side
    fp = front_view.position
    linear(front_view,
           pt(fp.x - w/2, fp.y - h/2), pt(fp.x + w/2, fp.y - h/2),
           pt(fp.x,        fp.y - h/2 - 1.5))
    linear(front_view,
           pt(fp.x + w/2, fp.y - h/2), pt(fp.x + w/2, fp.y + h/2),
           pt(fp.x + w/2 + 1.5, fp.y))

    # Top: depth up the right side
    tp = top_view.position
    linear(top_view,
           pt(tp.x + w/2, tp.y - d/2), pt(tp.x + w/2, tp.y + d/2),
           pt(tp.x + w/2 + 1.5, tp.y))
