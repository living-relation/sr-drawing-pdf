"""Time the fast views of the benchmark assembly and write a PNG.

From the repo folder:

  python dev/time_views.py views.png
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, 'SRDrawingPDF'))

from sheet2d.project import VIEW_LIMIT_S, build_benchmark_assembly, part_count, render_views_png  # noqa: E402


def main(argv):
    if len(argv) != 2:
        print('usage: python dev/time_views.py views.png')
        return 2
    parts = build_benchmark_assembly()
    views = render_views_png(parts, argv[1])
    total = sum(v['seconds'] for v in views)
    print('parts %d' % part_count(parts))
    for view in views:
        print('%s %.3f s  lines %d' % (view['name'], view['seconds'], len(view['lines'])))
    print('total %.3f s  limit %.0f s  %s' % (total, VIEW_LIMIT_S, 'PASS' if total < VIEW_LIMIT_S else 'FAIL'))
    print(argv[1])
    return 0 if total < VIEW_LIMIT_S else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
