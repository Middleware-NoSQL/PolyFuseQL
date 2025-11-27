import pytest
from unittest.mock import MagicMock, patch
from polyfuseql.utils.spark_manager import get_spark_session, stop_spark_session
import polyfuseql.utils.spark_manager as spark_manager_module


@pytest.fixture(autouse=True)
def reset_spark_global():
    """Resets the global _spark_session before and after each test."""
    spark_manager_module._spark_session = None
    yield
    spark_manager_module._spark_session = None


def test_spark_not_available(caplog):
    """
    Test that get_spark_session returns None and logs a warning
    when SPARK_AVAILABLE is False (simulating missing pyspark).
    """
    with patch("polyfuseql.utils.spark_manager.SPARK_AVAILABLE", False):
        session = get_spark_session()
        assert session is None
        assert "PySpark is not available" in caplog.text


@patch("polyfuseql.utils.spark_manager.SparkSession")
def test_get_existing_active_session(MockSparkSession):
    """
    Test that if a session exists and is active, it is returned directly.
    """
    mock_session = MagicMock()
    # Set sc.jsc.sc().isStopped() to False to simulate active session
    mock_session._sc._jsc.sc.return_value.isStopped.return_value = False

    # Inject the mock into the global variable
    spark_manager_module._spark_session = mock_session

    session = get_spark_session()
    assert session is mock_session

    # FIX: Instead of hasattr (which MagicMock passes by default),
    # check that the builder was NOT called.
    assert not MockSparkSession.builder.called


def test_create_session_jar_not_found():
    """
    Test that FileNotFoundError is raised if the Neo4j JAR does not exist.
    """
    with patch("polyfuseql.utils.spark_manager.settings") as mock_settings, patch(
        "pathlib.Path.exists", return_value=False
    ):

        mock_settings.spark.neo4j_spark_jar_path = "/fake/path/neo4j.jar"

        with pytest.raises(
            FileNotFoundError, match="Neo4j Spark connector JAR not found"
        ):
            get_spark_session()


@patch("polyfuseql.utils.spark_manager.SparkSession")
@patch("pathlib.Path.exists", return_value=True)
def test_create_new_session_local(mock_exists, MockSparkSession):
    """
    Test creating a new session with 'local' master URL.
    """
    # FIX: Ensure the fluent interface returns the same mock at every step
    mock_builder = MockSparkSession.builder
    mock_builder.appName.return_value = mock_builder
    mock_builder.master.return_value = mock_builder
    # Even if config is called, return the same builder
    mock_builder.config.return_value = mock_builder
    mock_builder.getOrCreate.return_value = MagicMock()

    with patch("polyfuseql.utils.spark_manager.settings") as mock_settings:
        mock_settings.spark.master_url = "local[*]"
        mock_settings.spark.neo4j_spark_jar_path = "/valid/path.jar"

        session = get_spark_session()

        assert session is not None
        # Check that getOrCreate was called on our builder
        assert mock_builder.getOrCreate.called


@patch("polyfuseql.utils.spark_manager.SparkSession")
@patch("pathlib.Path.exists", return_value=True)
def test_create_new_session_remote(mock_exists, MockSparkSession):
    """
    Test creating a new session with a remote master URL.
    """
    # FIX: Setup the chain so 'builder' in the code always refers to 'mock_builder'
    mock_builder = MockSparkSession.builder
    mock_builder.appName.return_value = mock_builder
    mock_builder.master.return_value = mock_builder
    mock_builder.config.return_value = mock_builder  # Critical for chaining
    mock_builder.getOrCreate.return_value = MagicMock()

    with patch("polyfuseql.utils.spark_manager.settings") as mock_settings:
        # Use a remote URL to trigger the else block
        mock_settings.spark.master_url = "spark://remote:7077"

        get_spark_session()

        # Inspect all calls to .config() on our single mock_builder object
        config_calls = [str(call) for call in mock_builder.config.call_args_list]

        # Debug print if needed
        # print(config_calls)

        # Assert that the specific config for remote execution was set
        has_shuffle = any("spark.sql.shuffle.partitions" in c for c in config_calls)
        assert has_shuffle, "Remote configuration block was not executed"


def test_stop_session():
    """
    Test stopping an active session.
    """
    mock_session = MagicMock()
    mock_session._sc._jsc.sc.return_value.isStopped.return_value = False

    spark_manager_module._spark_session = mock_session

    stop_spark_session()

    assert mock_session.stop.called
    assert spark_manager_module._spark_session is None


def test_stop_session_already_stopped():
    """
    Test stopping a session that is already None or stopped.
    """
    # Case 1: None
    spark_manager_module._spark_session = None
    stop_spark_session()

    # Case 2: Exists but stopped
    mock_session = MagicMock()
    mock_session._sc._jsc.sc.return_value.isStopped.return_value = True
    spark_manager_module._spark_session = mock_session

    stop_spark_session()
    assert not mock_session.stop.called
