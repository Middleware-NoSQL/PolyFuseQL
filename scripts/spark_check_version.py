import sys

try:
    import pyspark
    from pyspark.sql import SparkSession
except ImportError:
    print("Error: PySpark is not installed in this environment.")
    sys.exit(1)


def check_versions():
    print(f"PySpark Library Version: {pyspark.__version__}")

    try:
        # Initialize a minimal SparkSession without loading extra packages
        # to avoid the crashes you are seeing with the connector JARs
        spark = (
            SparkSession.builder.appName("VersionCheck").master("local").getOrCreate()
        )

        spark_version = spark.version
        # Access the Scala version via the JVM bridge
        scala_version = spark.sparkContext._jvm.scala.util.Properties.versionString()
        java_version = spark.sparkContext._jvm.java.lang.System.getProperty(
            "java.version"
        )

        print("-" * 30)
        print(f"Spark Runtime Version: {spark_version}")
        print(f"Scala Version:         {scala_version}")
        print(f"Java Version:          {java_version}")
        print("-" * 30)

        spark.stop()

    except Exception as e:
        print(f"\nFailed to initialize Spark Session: {e}")
        print("This suggests an issue with the underlying Java/Spark installation.")


if __name__ == "__main__":
    check_versions()
