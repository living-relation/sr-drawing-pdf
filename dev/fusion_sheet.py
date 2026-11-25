"""Real views on a size B sheet, from a Fusion read or a STEP file. Writes a PDF.

From the repo folder, after fusion_read.py wrote a folder (see docs/fusion-read.md):

  python dev/fusion_sheet.py out.pdf --fusion DUMP_FOLDER [--title "..."]
  python dev/fusion_sheet.py out.pdf --step assembly.step [--title "..."]

Prints the time for each step. Keep model files and dumps outside this repo.
"""
import datetime
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, 'SRDrawingPDF'))
sys.path.insert(0, os.path.join(_ROOT, 'dev'))

from sheet2d.project import VIEW_LIMIT_S  # noqa: E402
from sheet2d.render import export_pdf  # noqa: E402
from sheet2d.viewsheet import build_view_sheet  # noqa: E402


def _arg(args, flag):
    if flag in args:
        i = args.index(flag)
        if i + 1 < len(args):
            value = args[i + 1]
            del args[i:i + 2]
            return value
    return None


def load_parts(fusion=None, step=None):
    """(parts, title, source, seconds)."""
    t0 = time.perf_counter()
    if fusion:
        from sheet2d.meshparts import load_fusion_dump
        parts, info = load_fusion_dump(fusion)
        title = info['document']
        source = '%s (Fusion)' % info['document']
    else:
        from step_mesh import load_step
        parts, info = load_step(step)
        title = os.path.splitext(os.path.basename(step))[0]
        source = os.path.basename(step)
    return parts, title, source, time.perf_counter() - t0


def main(argv):
    args = list(argv[1:])
    fusion = _arg(args, '--fusion')
    step = _arg(args, '--step')
    title = _arg(args, '--title')
    if len(args) != 1 or not (fusion or step):
        print(__doc__)
        return 2
    parts, name, source, load_s = load_parts(fusion, step)
    print('load %.2f s  parts %d' % (load_s, len(parts)))
    doc, report = build_view_sheet(parts, (title or name).upper(), source=source,
                                   date=datetime.date.today().isoformat())
    for v in report['views']:
        print('%-9s %6.2f s  scale %-6s buffer %dx%d  lines %d' % (
            v['name'], v['seconds'], v['scale'], v['buffer'][0], v['buffer'][1], v['lines']))
    t0 = time.perf_counter()
    from sheet2d.model import DrawingDocument
    export_pdf(DrawingDocument.from_dict(doc), args[0])
    pdf_s = time.perf_counter() - t0
    views_s = sum(v['seconds'] for v in report['views'])
    total = load_s + report['seconds'] + pdf_s
    print('sheet scale %s  views %.2f s  sheet build %.2f s  pdf %.2f s' % (report['scale'], views_s, report['seconds'], pdf_s))
    print('total %.2f s  limit %.0f s  %s' % (total, VIEW_LIMIT_S, 'PASS' if total < VIEW_LIMIT_S else 'FAIL'))
    print(args[0])
    return 0 if total < VIEW_LIMIT_S else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
