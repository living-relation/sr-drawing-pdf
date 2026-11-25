"""Time the fast views of an assembly and write a PNG.

From the repo folder, the built-in benchmark assembly (no CAD file needed):

  python dev/time_views.py views.png

A real assembly exported from Fusion as STEP (needs OCP: pip install cadquery-ocp):

  python dev/time_views.py views.png --step assembly.step

Keep STEP files outside this public repo.
"""
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, 'SRDrawingPDF'))
sys.path.insert(0, os.path.join(_ROOT, 'dev'))

from sheet2d.project import VIEW_LIMIT_S, build_benchmark_assembly, part_count, render_views_png  # noqa: E402


def main(argv):
    args = argv[1:]
    step = None
    if '--step' in args:
        i = args.index('--step')
        if i + 1 >= len(args):
            print('usage: python dev/time_views.py views.png [--step assembly.step]')
            return 2
        step = args[i + 1]
        del args[i:i + 2]
    if len(args) != 1:
        print('usage: python dev/time_views.py views.png [--step assembly.step]')
        return 2
    mesh_s = 0.0
    if step:
        from step_mesh import load_step
        parts, info = load_step(step)
        mesh_s = info['mesh_s']
        print('STEP read %.3f s (not counted: Fusion would hand the bodies over directly)' % info['read_s'])
        print('mesh %.3f s  solids %d  triangles %d  deflection %.3f' % (
            mesh_s, info['solids'], info['triangles'], info['deflection']))
    else:
        t0 = time.perf_counter()
        parts = build_benchmark_assembly()
        mesh_s = time.perf_counter() - t0
    views = render_views_png(parts, args[0])
    total = mesh_s + sum(v['seconds'] for v in views)
    print('parts %d' % part_count(parts))
    for view in views:
        print('%s %.3f s  lines %d' % (view['name'], view['seconds'], len(view['lines'])))
    print('total %.3f s (mesh + views)  limit %.0f s  %s' % (total, VIEW_LIMIT_S, 'PASS' if total < VIEW_LIMIT_S else 'FAIL'))
    print(args[0])
    return 0 if total < VIEW_LIMIT_S else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
