from prompt_toolkit.completion import Completer, Completion
from console.cli import cli


class PolyFuseQLCompleter(Completer):
    def __init__(self, state):
        self.state = state
        self.meta_commands = list(cli.commands.keys())
        self.engines = ["postgres", "redis", "neo4j"]

    def get_completions(self, document, complete_event):
        text_before_cursor = document.text_before_cursor.lstrip()
        words = text_before_cursor.split()

        if not words:
            return

        # If we are typing the first word, only suggest meta-commands
        if len(words) == 1 and not text_before_cursor.endswith(" "):
            c_w = words[0]
            for command in self.meta_commands:
                if command.startswith(c_w):
                    yield Completion(command, start_position=-len(c_w))
            return

        # If the first word is 'engine', suggest engine names
        if (
            len(words) == 2
            and words[0] == "engine"
            and not text_before_cursor.endswith(" ")
        ):
            c_w = words[1]
            for engine in self.engines:
                if engine.startswith(c_w):
                    yield Completion(engine, start_position=-len(c_w))
            return
