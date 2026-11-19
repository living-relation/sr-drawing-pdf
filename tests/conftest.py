import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDIN = os.path.join(ROOT, 'SRDrawingPDF')
if ADDIN not in sys.path:
    sys.path.insert(0, ADDIN)
