from pyspark.sql import SparkSession

# ==============================================================================
#  Configuration
# ==============================================================================
# --- Update these values with your Neo4j instance details ---
NEO4J_URI = "neo4j://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "password"  # Replace with your password


# ==============================================================================
#  PySpark Session Initialization
# ==============================================================================
def get_spark_session():
    """
    Initializes and returns a SparkSession configured for Neo4j.
    Note: When running with spark-submit or pyspark shell, the JAR path
    should be provided via the --jars or --packages command-line option.
    """
    app_name = "PySpark-Neo4j-Connector-Test"
    spark = SparkSession.builder.appName(app_name).getOrCreate()
    return spark


# ==============================================================================
#  Main Test Logic
# ==============================================================================
def test_neo4j_connection(spark):
    """
    Tests the connection to Neo4j by reading data using the Spark Connector.
    """
    print("Attempting to connect to Neo4j and read data...")

    try:
        # Use the Neo4j Spark Connector to read data.
        # We'll run a simple Cypher query to return a literal value.
        # This query does not depend on any existing data in your database.
        df = (
            spark.read.format("org.neo4j.spark.DataSource")
            .option("url", NEO4J_URI)
            .option("authentication.type", "basic")
            .option("authentication.basic.username", NEO4J_USER)
            .option("authentication.basic.password", NEO4J_PASSWORD)
            .option("query", "RETURN 'Connection Successful!' AS message")
            .load()
        )

        print("Successfully loaded data from Neo4j.")

        # Show the DataFrame content. If the connection works,
        # this will print a table with the message from the query.
        print("Content from Neo4j:")
        df.show()

        message = df.first()["message"]
        if message == "Connection Successful!":
            print("\nSUCCESS: The Neo4j Spark Connector is working correctly.")
        else:
            msg = "\nWARNING: Connection was made, "
            msg += "but the returned message was unexpected."
            print(msg)

    except Exception as e:
        print("\nERROR: Failed to connect to Neo4j or read data.")
        print("Please check the following:")
        print("1. Is your Neo4j database running ")
        print("and accessible at the specified URI?")
        print("2. Are the username and password correct?")
        print("3. Was the Neo4j Spark Connector JAR file ")
        print("correctly included in the Spark session?")
        print(f"Full error details: {e}")


# ==============================================================================
#  Execution
# ==============================================================================
if __name__ == "__main__":
    spark_session = get_spark_session()
    test_neo4j_connection(spark_session)
    spark_session.stop()
