import asyncio
from console.shell import PolyFuseQLShell


def start_shell():
    """Entry point function for the console script."""
    shell = PolyFuseQLShell()
    try:
        asyncio.run(shell.run())
    except KeyboardInterrupt:
        print("\nExiting.")


if __name__ == "__main__":
    start_shell()
