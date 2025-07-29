# scripts/load_tpch_data.py (New File)
import asyncio
import logging
from pathlib import Path
from rich.console import Console
from rich.progress import Progress
from polyfuseql.client import PolyClient

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

console = Console()

# Path to the generated .tbl files from the dbgen container
# This path assumes you run this script from the project root.
DATA_DIR = Path("./docker/tpch-data")


async def main():
    """
    Master script to load all TPC-H data into the configured backends.
    """
    console.print("[bold green]Starting TPC-H Data Loading Process...[/bold green]")

    # Ensure data directory exists
    if not DATA_DIR.is_dir():
        console.print(
            f"[bold red]Error: Data directory not found at {DATA_DIR}[/bold red]"
        )
        console.print(
            "Please run 'docker-compose up dbgen' first to generate the data."
        )
        return

    # The tables are ordered to respect foreign key constraints for relational dbs
    tables_to_load = [
        "region",
        "nation",
        "part",
        "supplier",
        "partsupp",
        "customer",
        "orders",
        "lineitem",
    ]

    async with PolyClient() as client:
        with Progress(console=console, transient=True) as progress:
            main_task = progress.add_task(
                "[cyan]Total Progress...", total=len(tables_to_load)
            )

            for table_name in tables_to_load:
                file_path = DATA_DIR / f"{table_name}.tbl"
                if not file_path.exists():
                    console.print(
                        f"[yellow]Warning: Data file not found for table '{table_name}'. Skipping.[/yellow]"
                    )
                    progress.update(main_task, advance=1)
                    continue

                backends = ["postgres", "redis", "neo4j"]

                table_task = progress.add_task(
                    f"Loading [bold]{table_name}[/bold]...", total=len(backends)
                )
                for backend in backends:
                    progress.update(
                        table_task,
                        advance=0,
                        description=f"Loading [bold]{table_name}[/bold] to [magenta]{backend}[/magenta]...",
                    )
                    try:
                        inserted_count = await client.bulk_load_table(
                            table_name, str(file_path), backend
                        )
                        progress.console.print(
                            f"  [green]✓[/green] Loaded {inserted_count} records into [magenta]{backend}[/magenta] for table [bold]{table_name}[/bold]."
                        )
                    except Exception as e:
                        progress.console.print(
                            f"  [red]✗[/red] Failed to load table [bold]{table_name}[/bold] into [magenta]{backend}[/magenta]: {e}"
                        )
                    progress.update(table_task, advance=1)

                progress.update(main_task, advance=1)

    console.print("[bold green]TPC-H Data Loading Process Completed.[/bold green]")


if __name__ == "__main__":
    asyncio.run(main())
