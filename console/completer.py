from prompt_toolkit.completion import Completer, Completion
from console.cli import cli


class PolyFuseQLCompleter(Completer):
    """
    Provides autocompletion for the PolyFuseQL shell, suggesting both
    meta-commands and SQL keywords.
    """

    def __init__(self, state):
        self.state = state
        self.meta_commands = list(cli.commands.keys())
        self.engines = ["postgres", "redis", "neo4j"]
        self.sql_keywords = [
            "SELECT",
            "FROM",
            "WHERE",
            "INSERT INTO",
            "VALUES",
            "UPDATE",
            "SET",
            "DELETE FROM",
            "JOIN",
            "ON",
            "GROUP BY",
            "COUNT",
            "AS",
            "INNER",
            "LEFT",
            "RIGHT",
            "FULL",
        ]

    def get_completions(self, document, complete_event):
        text_before_cursor = document.text_before_cursor.lstrip()
        words = text_before_cursor.split()

        if not words:
            return

        # Check if we are currently typing a word
        # or if there's a space at the end
        on_new_word = text_before_cursor.endswith(" ")

        # --- Case 1: Typing the very first word ---
        if len(words) == 1 and not on_new_word:
            current_word = words[0]
            # Suggest both meta-commands and SQL keywords
            all_suggestions = sorted(self.meta_commands + self.sql_keywords)
            for suggestion in all_suggestions:
                if suggestion.lower().startswith(current_word.lower()):
                    yield Completion(
                        suggestion, start_position=-len(current_word)
                    )  # noqa: F501
            return

        first_word = words[0].lower()

        # --- Case 2: It's a known meta-command with specific arguments ---
        if first_word == "engine":
            if len(words) == 1 and on_new_word:
                for engine in self.engines:
                    yield Completion(engine, start_position=0)
            elif len(words) == 2 and not on_new_word:
                current_word = words[1]
                for engine in self.engines:
                    if engine.startswith(current_word):
                        yield Completion(
                            engine, start_position=-len(current_word)
                        )  # noqa: F501
            return

        # --- Case 3: It's an SQL query (not a meta-command) ---
        if first_word not in self.meta_commands:
            current_word = ""
            if not on_new_word:
                current_word = words[-1]

            for keyword in self.sql_keywords:
                if keyword.lower().startswith(current_word.lower()):
                    yield Completion(
                        keyword, start_position=-len(current_word)
                    )  # noqa: F501
