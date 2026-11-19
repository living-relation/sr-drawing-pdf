"""Write the sample two-sheet PDF. Runs outside Fusion.

Usage:
  python dev/render_sample.py out.pdf

Inside Fusion, do not use this script. Call editor_api() on the loaded add-in.
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ADDIN = os.path.join(_ROOT, 'SRDrawingPDF')
if _ADDIN not in sys.path:
    sys.path.insert(0, _ADDIN)

from sheet2d.commands import execute  # noqa: E402
from sheet2d.sample import build_sample  # noqa: E402


def main(argv):
    if len(argv) != 2:
        print('usage: python dev/render_sample.py out.pdf')
        return 2
    doc = build_sample()
    out = execute(doc, 'export_pdf', {'path': argv[1]})
    print(out['result']['path'])
    print('pages %s' % out['result']['pages'])
    for warning in out['result']['warnings']:
        print('warning: %s' % warning)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
