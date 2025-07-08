import click
from rich.console import Console
from rich.table import Table
from rich import box

console = Console()


def print_results(results: list | dict | None):
    """Renders query results in a rich table."""
    if not results:
        console.print("[yellow]Query returned no results.[/yellow]")
        return
    if not isinstance(results, list):
        results = [results]
    if not results:
        console.print("[yellow]Query returned no results.[/yellow]")
        return

    headers = results[0].keys()
    table = Table(box=box.ROUNDED, show_lines=True, expand=True)

    for header in headers:
        table.add_column(header, style="cyan", overflow="fold")

    for row in results:
        table.add_row(*(str(row.get(h, "")) for h in headers))

    console.print(table)


@click.group()
def cli():
    """PolyFuseQL: The Polyglot Database Query Shell."""
    pass


@cli.command()
@click.argument("name", type=click.Choice(["postgres", "redis", "neo4j"]))
@click.pass_context
def engine(ctx, name):
    """
    Sets the default database engine for the current session.

    Example: engine neo4j
    """
    state = ctx.obj
    state.current_engine = name
    msg = f"Default engine set to [bold magenta]{name}[/bold magenta]."
    console.print(msg)


@cli.command()
@click.pass_context
async def ping(ctx):
    """
    Pings all configured databases to check their connection status.
    """
    state = ctx.obj
    statuses = {}
    try:
        statuses["PostgreSQL"] = await state.client.pg.ping()
    except Exception:
        statuses["PostgreSQL"] = False
    try:
        statuses["Redis"] = await state.client.rd.ping()
    except Exception:
        statuses["Redis"] = False
    try:
        statuses["Neo4j"] = await state.client.nj.ping()
    except Exception:
        statuses["Neo4j"] = False

    table = Table(title="Database Connection Status")
    table.add_column("Database", style="magenta")
    table.add_column("Status", style="cyan")
    for db, status in statuses.items():
        status_text = (
            "[bold green]Online[/bold green]"
            if status
            else "[bold red]Offline[/bold red]"
        )
        table.add_row(db, status_text)
    console.print(table)


@cli.command(name="help")
@click.pass_context
def show_help(ctx):
    """Displays the help message."""
    console.print(ctx.parent.get_help())


@cli.command()
@click.pass_context
def exit(ctx):
    """Exits the shell."""
    ctx.obj.exit()
