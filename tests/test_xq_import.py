"""vieweng.xq must import on its own, and its workers must not re-run the caller."""
import subprocess
import sys
import textwrap


def test_xq_imports_without_the_engines_package():
    code = textwrap.dedent("""
        import vieweng.xq
        from vieweng.xq import _sample_edges, _worker_ping
        assert _worker_ping(2) == 3
        print('ok')
    """)
    run = subprocess.run(
        [sys.executable, '-c', code],
        cwd='SRDrawingPDF',
        capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert 'ok' in run.stdout


def test_a_spawned_worker_imports_this_module():
    code = textwrap.dedent("""
        from vieweng.xq import _process_pool, _worker_ping
        pool = _process_pool(1)
        try:
            assert list(pool.map(_worker_ping, (1, 4))) == [2, 5]
        finally:
            pool.shutdown()
        print('ok')
    """)
    run = subprocess.run(
        [sys.executable, '-c', code],
        cwd='SRDrawingPDF',
        capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert 'ok' in run.stdout
