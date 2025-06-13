# pydatashell/main.py

import shlex
import click
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from rich.console import Console
from rich.panel import Panel

from state import PyDataShellState
from cli import cli
from completer import PyDataShellCompleter


class PyDataShell:
    def __init__(self):
        self.state = PyDataShellState()
        self.console = Console()

    def run(self):
        """The main run loop of the shell, using prompt_toolkit."""

        session = PromptSession(history=FileHistory(self.state.history_file))
        completer = PyDataShellCompleter(self.state)
        msg = (
            "[bold cyan]Welcome to PyDataShell![/bold cyan] "
            "Type 'help' for commands, 'exit' to quit."
        )
        self.console.print(msg)

        while self.state.is_running:
            try:
                text = session.prompt(
                    "pds> ",
                    completer=completer,
                    auto_suggest=AutoSuggestFromHistory(),  # noqa: F501
                )

                if not text.strip():
                    continue

                args = shlex.split(text)

                # Programmatically invoke the click CLI
                cli(args, obj=self.state, standalone_mode=False)

            except click.exceptions.UsageError as e:
                self.console.print(
                    Panel(
                        f"[yellow]{e.format_message()}[/yellow]",
                        title="Usage Error",
                        border_style="yellow",
                    )
                )
            except click.exceptions.ClickException as e:
                self.console.print(
                    Panel(
                        f"[red]{e.format_message()}[/red]",
                        title="Error",
                        border_style="red",
                    )
                )
            except click.exceptions.Abort:
                # This is raised by click on exit, so we can ignore it
                pass
            except KeyboardInterrupt:
                # Pressing Ctrl-C will cancel the current line
                continue
            except EOFError:
                # Pressing Ctrl-D will exit
                self.state.exit()

        self.console.print("Goodbye!")


def start_shell():
    """Entry point function for the console script."""
    shell = PyDataShell()
    shell.run()


if __name__ == "__main__":
    start_shell()
