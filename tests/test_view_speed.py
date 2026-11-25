"""Large-assembly views must finish. Hidden lines are never drawn."""
from sheet2d.project import (
    VIEW_LIMIT_S,
    build_benchmark_assembly,
    part_count,
    project_view,
    time_view_set,
)


def test_benchmark_assembly_has_several_hundred_parts():
    assert part_count(build_benchmark_assembly()) >= 400


def test_hq_view_set_finishes_within_two_minutes():
    report = time_view_set(build_benchmark_assembly())
    assert report['total'] < VIEW_LIMIT_S
    assert [v['name'] for v in report['views']] == ['front', 'top', 'right', 'trimetric']
    for view in report['views']:
        assert view['seconds'] < VIEW_LIMIT_S
        assert 'hid' not in view['style_counts']
        assert all(line['style'] != 'hid' for line in view['lines'])
        assert view['lines']
    top = report['views'][1]
    assert any(line['kind'] == 'circle' for line in top['lines'])
    assert top['style_counts'].get('ctr', 0) > 0


def test_a_round_part_is_not_drawn_as_a_mesh():
    part = [('cyl', 0.0, 0.0, 0.0, 5.0, 12.0, 2)]
    top = project_view(part, 'top')
    assert any(line['kind'] == 'circle' for line in top['lines'])
    assert any(line['style'] == 'ctr' for line in top['lines'])
    assert len(top['lines']) < 8
    side = project_view(part, 'front')
    assert 'hid' not in side['style_counts']
    assert side['style_counts'].get('vis', 0) <= 4
