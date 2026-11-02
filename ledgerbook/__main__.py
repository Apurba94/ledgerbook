"""Start the app: python -m ledgerbook [data.db] [--port 8043]"""
import sys

from .fieldkit import main_cli
from .web import create_app

sys.exit(main_cli(create_app, "ledger.db", 8043, sys.argv))
