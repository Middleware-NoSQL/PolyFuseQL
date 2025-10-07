import pytest
from dotenv import load_dotenv
import os


@pytest.fixture(scope="session", autouse=True)
def load_env():
    """
    A session-scoped fixture to automatically load environment variables
    from a .env file at the beginning of the test session.
    """
    # Construct the path to the .env file in the project root
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dotenv_path = os.path.join(project_dir, ".env")

    # Load the .env file
    # The override=True flag ensures that any variables from the file
    # will overwrite existing system environment variables.
    if os.path.exists(dotenv_path):
        load_dotenv(dotenv_path=dotenv_path, override=True)
        print("\nLoaded environment variables from .env file.")
    else:
        print(
            "\n.env file not found, using default or system environment variables."  # noqa:E501
        )  # noqa:E501
