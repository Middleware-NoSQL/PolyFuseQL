import logging
from pathlib import Path
from typing import Optional, List

from polyfuseql.config import settings

try:
    from pyspark.sql import SparkSession

    SPARK_AVAILABLE = True
except ImportError:
    SPARK_AVAILABLE = False

_spark_session: Optional[SparkSession] = None
_active_config: Optional[str] = None

# Maven coordinates used if local JARs are missing or Maven mode is forced.
# Adjusted to match the versions found in your local files.
PACKAGES_COORDINATES = {
    "Neo4j": "org.neo4j:neo4j-connector-apache-spark_2.13:5.3.1_for_spark_3",
    "Redis": "com.redislabs:spark-redis_2.12:3.1.0",
}


def _find_local_jars() -> List[str]:
    """
    Scans the project's 'jars' directory for known connector JARs.
    Returns a list of absolute paths.
    """
    # Adjust this path traversal based on where this file is located:
    # polyfuseql/utils/spark_manager.py -> ... -> root
    root_path = Path(__file__).parent.parent.parent.parent
    jars_dir = root_path / "jars"

    if not jars_dir.exists():
        logging.warning(f"JARs directory not found at: {jars_dir}")
        return []

    jar_paths = []
    # Scan for Neo4j and Redis jars explicitly or *.jar
    for file in jars_dir.glob("*.jar"):
        # Filter for relevant jars to avoid loading random garbage
        if "neo4j" in file.name.lower() or "redis" in file.name.lower():
            logging.info(f"Found local JAR: {file.name}")
            jar_paths.append(str(file.resolve()))

    return jar_paths


def get_spark_session(
    database_jars: str = "Neo4j", use_maven_packages: bool = False
) -> Optional[SparkSession]:
    """
    Initializes and returns a singleton SparkSession instance.

    Strategy:
    1. If `use_maven_packages` is True, configures Spark to download dependencies
       from Maven using `PACKAGES_COORDINATES`.
    2. If False (default), it looks for local JAR files.
    3. If local JAR files are NOT found, it falls back to Maven automatically.

    NOTE: In all cases, we try to load ALL known connectors (Neo4j + Redis)
    at once. This is required because Spark runs in a single JVM, and we cannot
    dynamically add JARs/Packages to the classpath after the context starts.
    """
    global _spark_session, _active_config

    if not SPARK_AVAILABLE:
        logging.warning("PySpark is not available.")
        return None

    # 1. Determine Strategy
    local_jars = _find_local_jars()

    # Priority:
    # 1. Maven Forced
    # 2. Local Files (if they exist)
    # 3. Maven Fallback (if local files missing)

    if use_maven_packages:
        config_mode = "MAVEN"
        # Join all coordinates with commas for spark.jars.packages
        config_payload = ",".join(PACKAGES_COORDINATES.values())
    elif local_jars:
        config_mode = "LOCAL_FILES"
        # Join all file paths with commas for spark.jars
        config_payload = ",".join(local_jars)
    else:
        logging.info("No local JARs found. Falling back to Maven packages.")
        config_mode = "MAVEN"
        config_payload = ",".join(PACKAGES_COORDINATES.values())

    # 2. Check active session
    # Restart if the session is stopped OR if the config mode changed
    # (e.g. Local -> Maven)
    is_active = (
        _spark_session is not None
        and not _spark_session._sc._jsc.sc().isStopped()  # noqa:E501
    )

    if is_active and _active_config != config_mode:
        msg = f"Restarting Spark Session (Config changed: {_active_config} "
        msg += f"-> {config_mode})"
        logging.info(msg)
        stop_spark_session()
        is_active = False

    if not is_active:
        logging.info("Initializing a new Spark session.")
        spark_master_url = settings.spark.master_url

        builder = SparkSession.builder.appName(settings.spark.app_name_prefix).master(
            spark_master_url
        )

        # --- Dependency Loading ---
        if config_mode == "LOCAL_FILES":
            logging.info(f"Loading {len(local_jars)} local JARs into Classpath.")
            builder = builder.config("spark.jars", config_payload)
        else:
            logging.info(f"Loading dependencies via Maven: {config_payload}")
            builder = builder.config("spark.jars.packages", config_payload)
            # Add repositories for Spark Packages and Maven Central
            builder = builder.config(
                "spark.jars.repositories",
                "https://repos.spark-packages.org/,https://repo1.maven.org/maven2/",
            )

        # --- Performance Config ---
        if "local" not in spark_master_url:
            builder = (
                builder.config("spark.cores.max", settings.spark.cores_max)
                .config("spark.driver.memory", settings.spark.driver_memory)
                .config("spark.executor.memory", settings.spark.executor_memory)
                .config(
                    "spark.sql.shuffle.partitions", settings.spark.shuffle_partitions
                )
            )
        else:
            builder = builder.config(
                "spark.driver.memory", settings.spark.driver_memory
            )

        _spark_session = builder.getOrCreate()
        _active_config = config_mode

        logging.info(
            f"Spark Session Ready. Master: {_spark_session.sparkContext.master}"
        )
        if hasattr(_spark_session.sparkContext, "uiWebUrl"):
            logging.info(f"Spark UI: {_spark_session.sparkContext.uiWebUrl}")

    return _spark_session


def stop_spark_session() -> None:
    """Stops the global Spark session."""
    global _spark_session, _active_config
    if _spark_session and not _spark_session._sc._jsc.sc().isStopped():
        logging.info("Stopping Spark session.")
        _spark_session.stop()
        _spark_session = None
        _active_config = None
