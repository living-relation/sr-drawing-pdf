"""Pluggable view engines.

The sheet asks an engine for one view's lines. Every engine returns the same
line dicts (visible edges only). Hidden lines are dropped here, so an engine
cannot put dashed back edges on the sheet.

Presets are what the editor offers. The bake-off picked XQ for both:
Draft is Quick Look, HQ is Exact Lines.
"""
def _xq():
    from vieweng.xq import XqEngine
    return XqEngine()


def _fusion():
    from vieweng.fusion import FusionEngine
    return FusionEngine()

# Provisional until the bake-off. Both presets are XQ: Draft is Quick Look,
# HQ is Exact Lines (ADR-052). The old mesh line engine is not a choice.
PRESETS = {
    'draft': ('xq', 'quick'),
    'hq': ('xq', 'exact'),
}

# Built on first use. Building it at import time loads vieweng.xq while that
# module is still importing this package, which crashes a worker process.
_ENGINES = None


def _registry():
    global _ENGINES
    if _ENGINES is None:
        _ENGINES = {'xq': _xq(), 'fusion': _fusion()}
    return _ENGINES


def engine_names():
    return tuple(_registry())


def get_engine(name):
    engines = _registry()
    key = (name or '').strip().lower()
    if key not in engines:
        raise ValueError('view engine must be one of %s' % ', '.join(engines))
    return engines[key]


def engine_for_preset(preset):
    """(engine, mode, note). note is set when that engine cannot run.

    There is no mesh fallback. Lines come from exact edges, or from Fusion.
    """
    key = (preset or 'draft').strip().lower()
    if key not in PRESETS:
        raise ValueError('view preset must be one of %s' % ', '.join(PRESETS))
    name, mode = PRESETS[key]
    chosen = get_engine(name)
    _ok, why = chosen.available()
    return chosen, mode, why


def normalize_lines(lines):
    """Visible edges only. A dashed or hidden style never reaches the sheet."""
    out = []
    for line in lines or []:
        style = line.get('style') or 'vis'
        if style in ('hid', 'hidden', 'dash'):
            continue
        item = dict(line)
        item['style'] = 'thin' if style in ('tan', 'thin') else 'vis' if style != 'ctr' else 'ctr'
        out.append(item)
    return out


def project_view(engine, name, parts=None, step=None, **opts):
    """One view from the named engine, with hidden lines removed."""
    eng = engine if hasattr(engine, 'project_view') else get_engine(engine)
    ok, why = eng.available()
    if not ok:
        raise RuntimeError(why)
    view = eng.project_view(name, parts=parts, step=step, **opts)
    view = dict(view)
    view['lines'] = normalize_lines(view.get('lines'))
    view['engine'] = eng.name
    counts = {}
    for line in view['lines']:
        counts[line['style']] = counts.get(line['style'], 0) + 1
    view['style_counts'] = counts
    return view
