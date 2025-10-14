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


def get_spark_session() -> Optional[SparkSession]:
    """
    Initializes and returns a singleton SparkSession instance.
    If a session exists but is stopped, it creates a new one.
    """
    global _spark_session
    if not SPARK_AVAILABLE:
        logging.warning(
            "PySpark is not available. Cannot create Spark session."
        )  # noqa:F501
        return None

    if _spark_session is None or _spark_session._sc._jsc.sc().isStopped():
        logging.info("No active Spark session found. Initializing a new one.")
        spark_master_url = settings.spark_master_url

        jar_path_str = settings.neo4j_spark_jar_path or str(
            Path(__file__).parent.parent.parent
            / "jars"
            / "neo4j-spark-connector-5.3.1-s_2.13.jar"
        )
        jar_path = Path(jar_path_str)
        if not jar_path.exists():
            raise FileNotFoundError(
                f"Neo4j Spark connector JAR not found at: {jar_path}"
            )

        builder = (
            SparkSession.builder.appName(settings.spark_app_name_prefix)
            .master(spark_master_url)
            .config("spark.jars", str(jar_path))
        )

        if "local" not in spark_master_url:
            builder = (
                builder.config("spark.cores.max", settings.spark_cores_max)
                .config("spark.driver.memory", settings.spark_driver_memory)
                .config(
                    "spark.executor.memory", settings.spark_executor_memory
                )  # noqa:F501
                .config(
                    "spark.sql.shuffle.partitions",
                    settings.spark_shuffle_partitions,
                )
                .config(
                    "spark.network.timeout", settings.spark_network_timeout
                )  # noqa:F501
                .config(
                    "spark.executor.heartbeatInterval",
                    settings.spark_executor_heartbeat_interval,
                )
            )
        else:
            builder = builder.config(
                "spark.driver.memory", settings.spark_driver_memory
            )

        _spark_session = builder.getOrCreate()
        logging.info(
            "Spark session initialized. Master: "
            f"{_spark_session.sparkContext.master}"
        )
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
