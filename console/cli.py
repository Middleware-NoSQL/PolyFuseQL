# pydatashell/cli.py

import click
from rich.console import Console
from rich.table import Table
from rich import box

# Initialize Rich Console for beautiful output
console = Console()


@click.group()
@click.pass_context
def cli(ctx):
    """PyDataShell: An interactive shell for an in-memory database."""
    # This function is the entry point for the command group.
    # It ensures the context object exists and is passed to subcommands.
    pass


@cli.command()
@click.argument("name")
@click.argument("columns", nargs=-1, required=True)
@click.pass_context
def create_table(ctx, name, columns):
    """
    Creates a new table with a given name and column definitions.
    Example: create_table users id name email
    """
    state = ctx.obj
    if name in state.database:
        m = f"[bold red]Error: Table '{name}' already exists.[/bold red]"
        console.print(m)
        return

    # FIX: Added the missing empty list for the "rows" key.
    state.database[name] = {"columns": list(columns), "rows": []}
    m = f"[bold green]Success: Table '{name}'"
    m += "created with columns: {', '.join(columns)}[/bold green]"
    console.print(m)


m = "The name of the table to insert into."


@cli.command()
@click.option("--table", required=True, help=m)
@click.argument("values", nargs=-1, required=True)
@click.pass_context
def insert(ctx, table, values):
    """
    Inserts a new row of values into a table.
    Example: insert --table users 1 "John Doe" "john@example.com"
    """
    state = ctx.obj
    if table not in state.database:
        msg = f"[bold red]Error: Table '{table}' does not exist.[/bold red]"
        console.print(msg)
        return

    table_schema = state.database[table]
    if len(values) != len(table_schema["columns"]):
        msg = "[bold red]Error: Incorrect number of values."
        msg += f"Expected {len(table_schema['columns'])},"
        msg += f"got {len(values)}.[/bold red]"
        console.print(msg)
        return

    table_schema["rows"].append(list(values))
    msg = "[bold green]Success: 1 row inserted into"
    msg += f"'{table}'.[/bold green]"
    console.print(msg)


@cli.command()
@click.argument("table_name")
@click.pass_context
def select(ctx, table_name):
    """
    Selects and displays all rows from a table.
    Example: select users
    """
    state = ctx.obj
    if table_name not in state.database:
        console.print(
            f"[bold red]Error: Table '{table_name}' does not exist.[/bold red]"
        )
        return

    table_data = state.database[table_name]

    rich_table = Table(title=f"Data from '{table_name}'")
    for col in table_data["columns"]:
        rich_table.add_column(col, style="cyan", overflow="fold")

    for row in table_data["rows"]:
        rich_table.add_row(*row)

    if not table_data["rows"]:
        console.print(f"Table '{table_name}' is empty.")
    else:
        console.print(rich_table)


@cli.command()
@click.pass_context
def describe_db(ctx):
    """Shows a summary of all tables in the database."""
    state = ctx.obj
    if not state.database:
        console.print("[yellow]Database is empty.[/yellow]")
        return

    summary_table = Table(title="Database Summary", box=box.ROUNDED)
    summary_table.add_column("Table Name", style="bold magenta")
    summary_table.add_column("Columns", style="green")
    summary_table.add_column("Row Count", justify="right", style="cyan")

    for name, data in state.database.items():
        columns_str = ", ".join(data["columns"])
        row_count = str(len(data["rows"]))
        summary_table.add_row(name, columns_str, row_count)

    console.print(summary_table)


@cli.command()
@click.pass_context
def exit(ctx):
    """Exits the shell."""
    state = ctx.obj
    state.exit()
