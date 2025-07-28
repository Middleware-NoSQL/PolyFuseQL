#!/bin/bash

# This script directly generates the TPC-H .tbl files.

# Set the desired data scale factor
SCALE=1

# Set the directory where the TPC-H source code is located
TPCH_DIR="/home/andres/Downloads/GitClones/TPC-H"

# Set the output directory for the generated files
OUTPUT_DIR="$TPCH_DIR/generated"

# Create the output directory if it doesn't exist
mkdir -p "$OUTPUT_DIR"

# Compile the dbgen utility
echo "Compiling TPC-H tools..."
make -C "$TPCH_DIR/00_compile_tpch/dbgen"

# Change to the dbgen directory to run the data generator
cd "$TPCH_DIR/00_compile_tpch/dbgen"

# Generate the .tbl files
echo "Generating .tbl files..."
./dbgen -s "$SCALE" -f -v

# Move the generated .tbl files to the output directory
mv *.tbl "$OUTPUT_DIR"

# Go back to the project root
cd "$TPCH_DIR"

echo "File generation complete. You can find the .tbl files in the '$OUTPUT_DIR' directory."
