import shlex
import click
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from rich.console import Console
from rich.panel import Panel

from console.state import PolyFuseQLState
from console.cli import cli, print_results
from console.completer import PolyFuseQLCompleter


class PolyFuseQLShell:
    def __init__(self):
        self.state = PolyFuseQLState()
        self.console = Console()

    def get_prompt_text(self) -> str:
        """Constructs the prompt string based on the current state."""
        engine = self.state.current_engine
        if engine == "redis":
            redis_type = self.state.client.rd.get_data_type()
            return f"poly-sql ({engine}:{redis_type})> "
        return f"poly-sql ({engine})> "

    async def run(self):
        """The main async run loop of the shell."""
        session = PromptSession(history=FileHistory(self.state.history_file))
        completer = PolyFuseQLCompleter(self.state)

        self.console.print(
            Panel(
                "[bold cyan]Welcome to PolyFuseQL![/bold cyan]\n"
                "Type SQL queries directly, or 'help' for shell commands.",
                title="Polyglot Database Shell",
                border_style="green",
            )
        )

        async with self.state.client:
            while self.state.is_running:
                try:
                    prompt_text = self.get_prompt_text()
                    text = await session.prompt_async(
                        prompt_text, completer=completer, refresh_interval=0.5
                    )

                    if not text.strip():
                        continue

                    # NEW LOGIC: Distinguish between meta-commands and SQL
                    first_word = text.strip().split()[0].lower()

                    if first_word in cli.commands:
                        # It's a meta-command, process with click
                        args = shlex.split(text)
                        cli(args, obj=self.state, standalone_mode=False)
                    else:
                        # It's not a meta-command, so treat it as SQL
                        full_sql = text
                        target_engine = self.state.current_engine
                        msg = (
                            f"Executing on [bold magenta]"
                            f"{target_engine}[/bold magenta]..."
                        )
                        self.console.print(msg)
                        results = await self.state.client.execute(
                            full_sql, engine=target_engine
                        )
                        print_results(results)

                except click.exceptions.UsageError as e:
                    self.console.print(
                        f"[yellow]Usage Error: {e.format_message()}[/yellow]"
                    )
                except click.exceptions.Abort:
                    self.state.exit()
                except (KeyboardInterrupt, EOFError):
                    self.state.exit()
                except Exception as e:
                    msg = f"[bold red]An error occurred: {e}[/bold red]"
                    self.console.print(msg)

        self.console.print("\nGoodbye!")
