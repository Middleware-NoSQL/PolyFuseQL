import logging
from pathlib import Path
from typing import Optional

from polyfuseql.config import settings

try:
    from pyspark.sql import SparkSession

    SPARK_AVAILABLE = True
except ImportError:
    SPARK_AVAILABLE = False

_spark_session: Optional[SparkSession] = None

jars_filenames = {
    "Neo4j": "neo4j-spark-connector-5.3.1-s_2.13.jar",
    "Redis": "spark-redis-2.3.0.jar",
}


def get_spark_session(database_jars: str = "Neo4j") -> Optional[SparkSession]:
    """
    Initializes and returns a singleton SparkSession instance.
    If a session exists but is stopped, it creates a new one.

    This is now configured to load BOTH the local Neo4j JAR
    and the remote spark-redis package.
    """
    global _spark_session
    if not SPARK_AVAILABLE:
        logging.warning(
            "PySpark is not available. Cannot create Spark session."
        )  # noqa:F501
        return None

    if _spark_session is None or _spark_session._sc._jsc.sc().isStopped():
        logging.info("No active Spark session found. Initializing a new one.")
        spark_master_url = settings.spark.master_url

        # --- Neo4j JAR Configuration ---

        neo4j_jar_path_str = settings.spark.neo4j_spark_jar_path or str(
            Path(__file__).parent.parent.parent.parent
            / "jars"
            / jars_filenames.get(database_jars, "Neo4j")
        )
        neo4j_jar_path = Path(neo4j_jar_path_str)
        if not neo4j_jar_path.exists():
            raise FileNotFoundError(
                f"Neo4j Spark connector JAR not found at: {neo4j_jar_path}"
            )

        builder = (
            SparkSession.builder.appName(
                settings.spark.app_name_prefix
            ).master(  # noqa:E501
                spark_master_url
            )
            # 1. Load the local Neo4j JAR file
            .config("spark.jars", str(neo4j_jar_path))
            # 2. Load the remote spark-redis package from Maven
            # .config("spark.jars", str(redis_jar_path))
        )

        if "local" not in spark_master_url:
            builder = (
                builder.config("spark.cores.max", settings.spark.cores_max)
                .config("spark.driver.memory", settings.spark.driver_memory)
                .config(
                    "spark.executor.memory", settings.spark.executor_memory
                )  # noqa:F501
                .config(
                    "spark.sql.shuffle.partitions",
                    settings.spark.shuffle_partitions,
                )
                .config(
                    "spark.network.timeout", settings.spark.network_timeout
                )  # noqa:F501
                .config(
                    "spark.executor.heartbeatInterval",
                    settings.spark.executor_heartbeat_interval,
                )
            )
        else:
            builder = builder.config(
                "spark.driver.memory", settings.spark.driver_memory
            )

        _spark_session = builder.getOrCreate()
        msg = "Spark session initialized with "
        msg += "Neo4j and Redis connectors. Master: "
        msg += f"{_spark_session.sparkContext.master}"
        logging.info()
        logging.info(
            "Spark UI available at: " f"{_spark_session.sparkContext.uiWebUrl}"
        )

    return _spark_session


def stop_spark_session() -> None:
    """Stops the global Spark session if it exists and is active."""
    global _spark_session
    if _spark_session and not _spark_session._sc._jsc.sc().isStopped():
        logging.info("Stopping the global Spark session.")
        _spark_session.stop()
        _spark_session = None
