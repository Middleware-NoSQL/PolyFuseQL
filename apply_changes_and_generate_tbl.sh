#!/bin/bash

# This script applies the necessary changes to the TPC-H source code
# and then generates the .tbl files.

# Set the directory where the TPC-H source code is located
TPCH_DIR="/home/andres/Downloads/GitClones/TPC-H"

# Apply the patch
echo "Applying changes to the TPC-H source code..."
patch -p1 < "$TPCH_DIR/tpch_changes.patch"

# Run the script to generate the .tbl files
echo "Generating .tbl files..."
"$TPCH_DIR/generate_tbl_files.sh"

echo "Script execution complete."
