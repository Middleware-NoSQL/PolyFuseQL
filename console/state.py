from polyfuseql.client import PolyClient
from pathlib import Path
import os


class PolyFuseQLState:
    """Encapsulates all application and session state for the console."""

    def __init__(self):
        self.client = PolyClient.PolyClient()
        self.is_running = True

        # New: Track the current default engine, defaulting to postgres
        self.current_engine = "postgres"

        self.history_file = Path(os.path.expanduser("~/.polyfuseql_history"))
        self.history_file.touch(exist_ok=True)

    def exit(self):
        """Signals the application to exit."""
        self.is_running = False
