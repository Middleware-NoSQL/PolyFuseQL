import zipfile
from pathlib import Path


def extract_maven_coordinates(jar_path):
    """
    Reads the internal pom.properties file from a JAR to find its Maven coordinates.
    """
    try:
        with zipfile.ZipFile(jar_path, "r") as jar:
            # Search for pom.properties inside META-INF/maven/
            pom_files = [f for f in jar.namelist() if f.endswith("pom.properties")]

            if not pom_files:
                return None

            # If multiple pom.properties exist (shaded jars), we try to find
            # the main one.
            # We iterate through them and return the first valid one found.
            for pom_file in pom_files:
                with jar.open(pom_file) as f:
                    props = {}
                    for line in f.read().decode("utf-8", errors="ignore").splitlines():
                        if "=" in line and not line.strip().startswith("#"):
                            key, value = line.split("=", 1)
                            props[key.strip()] = value.strip()

                    if (
                        "groupId" in props
                        and "artifactId" in props
                        and "version" in props
                    ):
                        group = props["groupId"]
                        artifact = props["artifactId"]
                        version = props["version"]

                        return f"{group}:{artifact}:{version}"
            return None

    except Exception as e:
        return f"Error: {e}"


def scan_jars(directory):
    path = Path(directory)
    if not path.exists():
        print(f"❌ Directory not found: {path.absolute()}")
        msg = "Please edit the 'jars_dir' variable in this script "
        msg += "to point to your JARs folder."
        print(msg)
        return

    print(f"🔍 Scanning JARs in: {path.absolute()}\n")

    found_packages = {}

    # List all .jar files
    jar_files = list(path.glob("*.jar"))
    if not jar_files:
        print("No .jar files found in this directory.")
        return

    for file in jar_files:
        coord = extract_maven_coordinates(file)

        if coord and not coord.startswith("Error"):
            print(f"✅ {file.name}")
            print(f"   └── Maven Coordinate: {coord}")

            # Heuristic to categorize the jar
            key = file.name
            if "neo4j" in file.name.lower():
                key = "Neo4j"
            elif "redis" in file.name.lower():
                key = "Redis"
            elif "mongo" in file.name.lower():
                key = "Mongo"
            elif "postgres" in file.name.lower():
                key = "Postgres"

            found_packages[key] = coord

        elif coord and coord.startswith("Error"):
            print(f"⚠️  {file.name}: {coord}")
        else:
            print(f"⚠️  {file.name}: No Maven metadata (pom.properties) found inside.")

    print("\n" + "=" * 50)
    print("   COPY THIS INTO spark_session.py")
    print("=" * 50)
    print("PACKAGES_COORDINATES = {")
    for key, coord in found_packages.items():
        print(f'    "{key}": "{coord}",')
    print("}")
    print("=" * 50)


if __name__ == "__main__":
    # --- CONFIGURATION ---
    # Set this to the folder containing your .jar files.
    # Current guess: Looks in current dir, or 'jars' subdirectory.

    current_dir_jars = Path("jars")

    if current_dir_jars.exists():
        jars_dir = current_dir_jars
    else:
        # Fallback: Try to find it if running from root
        jars_dir = Path(".")

    scan_jars(jars_dir)
