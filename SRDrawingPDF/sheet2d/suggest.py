"""Drawing suggestions for the engineer. Nothing here changes a sheet.

The engine (or an AI pass) can flag places that may want a detail view:

- a section feature such as an o-ring groove, seal gland, undercut or thread
  relief, best shown as a detail of a section view;
- a cluster of small features whose dimensions and callouts would be too
  crowded to read at the view's scale.

Open suggestions show as a yellow exclamation-mark indicator in the app's
status bar (status_bar command). The engineer accepts one, which adds the
detail view with the suggested circle and scale, or dismisses it. A
suggestion never prints on the PDF.
"""
import math

SECTION_KINDS = frozenset(('o_ring_groove', 'groove', 'seal_gland', 'undercut', 'thread_relief', 'snap_ring_groove'))
STANDARD_SCALES = (1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 8.0, 10.0)
SMALL_MM = 2.5      # a feature smaller than this on the sheet is hard to dimension
CLUSTER_MM = 15.0   # small features this close together on the sheet form a cluster
MIN_CLUSTER = 3
READABLE_MM = 5.0   # a suggested scale makes the smallest feature at least this big


def _suggested_scale(view_scale, smallest_model_mm):
    need = READABLE_MM / max(smallest_model_mm, 1e-6)
    for s in STANDARD_SCALES:
        if s * 1.0 >= need and s > view_scale:
            return s
    return max(STANDARD_SCALES[-1], view_scale * 2)


def find_candidates(features, view_scales, small_mm=SMALL_MM, cluster_mm=CLUSTER_MM, min_cluster=MIN_CLUSTER):
    """features: [{'id', 'view', 'x', 'y' (sheet mm), 'size' (model mm), 'kind'}].
    view_scales: {view id: scale number}. Returns suggestion dicts (no ids)."""
    out = []
    by_view = {}
    for f in features:
        by_view.setdefault(f.get('view'), []).append(f)
    for view, feats in by_view.items():
        s = view_scales.get(view) or 1.0
        for f in feats:
            if str(f.get('kind') or '').lower() in SECTION_KINDS:
                out.append({
                    'kind': 'detail_view', 'reason': 'section_feature', 'view': view,
                    'features': [f.get('id')], 'cx': float(f['x']), 'cy': float(f['y']),
                    'r': max(6.0, float(f.get('size') or 1) * s * 1.5),
                    'scale': _scale_text(_suggested_scale(s, float(f.get('size') or 1))),
                    'text': '%s %s may need a detail of a section view' % (
                        str(f.get('kind')).replace('_', ' '), f.get('id')),
                })
        small = [f for f in feats if float(f.get('size') or 0) * s < small_mm
                 and str(f.get('kind') or '').lower() not in SECTION_KINDS]
        used = set()
        for f in small:
            if f.get('id') in used:
                continue
            group = [g for g in small if g.get('id') not in used
                     and math.hypot(float(g['x']) - float(f['x']), float(g['y']) - float(f['y'])) <= cluster_mm]
            if len(group) < min_cluster:
                continue
            used.update(g.get('id') for g in group)
            cx = sum(float(g['x']) for g in group) / len(group)
            cy = sum(float(g['y']) for g in group) / len(group)
            r = max(math.hypot(float(g['x']) - cx, float(g['y']) - cy) for g in group) + 3.0
            smallest = min(float(g.get('size') or 1) for g in group)
            out.append({
                'kind': 'detail_view', 'reason': 'crowded_small_features', 'view': view,
                'features': [g.get('id') for g in group], 'cx': round(cx, 3), 'cy': round(cy, 3),
                'r': round(r, 3), 'scale': _scale_text(_suggested_scale(s, smallest)),
                'text': '%d small features near each other are too crowded to dimension at this scale' % len(group),
            })
    return out


def _scale_text(v):
    from fractions import Fraction
    f = Fraction(v).limit_denominator(100)
    return '%d:%d' % (f.numerator, f.denominator)


def status_bar(suggestions):
    """What the app's status bar shows: a yellow '!' while any suggestion is open."""
    open_items = [s for s in suggestions if s.get('status', 'open') == 'open']
    return {
        'indicator': {'symbol': '!', 'color': 'yellow'} if open_items else None,
        'open': len(open_items),
        'items': [{'id': s.get('id'), 'kind': s.get('kind'), 'text': s.get('text'), 'view': s.get('view')}
                  for s in open_items],
    }
