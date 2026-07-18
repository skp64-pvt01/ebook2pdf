"""Allow running as python3 -m ebook2pdf."""
from .cli import run_cli
import sys

sys.exit(run_cli())
