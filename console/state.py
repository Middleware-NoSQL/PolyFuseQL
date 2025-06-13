# pydatashell/state.py

import os
from pathlib import Path


class PyDataShellState:
    """Encapsulates all application and session state."""

    def __init__(self):
        # Application State: The core data store.
        # A dictionary where keys are table names and values are table data.
        # Each table is a dict with 'columns' (a list) and 'rows'
        # (a list of lists).
        self.database = {}

        # UI State: Path for command history
        self.history_file = Path(os.path.expanduser("~/.pydatashell_history"))
        self.history_file.touch(exist_ok=True)

        # Session State: Flag to control the main loop
        self.is_running = True

    def exit(self):
        """Signals the application to exit."""
        self.is_running = False
