# pydatashell/completer.py

from prompt_toolkit.completion import Completer, Completion
from cli import cli


class PyDataShellCompleter(Completer):
    def __init__(self, state):
        self.state = state
        # Get all command names from the click group
        self.main_commands = list(cli.commands.keys())
        # Add 'help' as it's a built-in concept in click
        self.main_commands.append("help")

    def get_completions(self, document, complete_event):
        text_before_cursor = document.text_before_cursor
        words = text_before_cursor.split()

        if not words:
            return

        # If typing the first word, suggest main commands
        if len(words) == 1 and not text_before_cursor.endswith(" "):
            c_w = words[0]
            for command in self.main_commands:

                if command.startswith(c_w):
                    yield Completion(command, start_position=-len(c_w))
            return

        # If the first word is a command that takes a table name (e.g., select)
        if (
            words in ["select"]
            and len(words) == 2
            and not text_before_cursor.endswith(" ")
        ):
            c_w = words[1]
            for t_name in self.state.database.keys():
                if t_name.startswith(c_w):
                    yield Completion(t_name, start_position=-len(c_w))
            return

        # If completing the value for the '--table' option
        if words == "insert" and "--table" in words:
            try:
                # Find the index of '--table'
                table_option_index = words.index("--table")
                flag = not text_before_cursor.endswith(" ")
                # Check if we are completing the word right after '--table'
                if len(words) == table_option_index + 2 and flag:
                    c_w = words[table_option_index + 1]
                    for t_name in self.state.database.keys():
                        if t_name.startswith(c_w):
                            yield Completion(t_name, start_position=-len(c_w))
            except (ValueError, IndexError):
                # This can happen if the input is malformed, just ignore
                pass
