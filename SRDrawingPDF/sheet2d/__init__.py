"""Flat sheet editor that ships inside the SR Drawing PDF add-in.

No Fusion import. The command API is sheet2d.commands.execute.
"""

__version__ = '1'


def execute(document, command, args=None):
    """Run one editor command. See sheet2d.commands.execute."""
    from .commands import execute as _execute
    return _execute(document, command, args)
