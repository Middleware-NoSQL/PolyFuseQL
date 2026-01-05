#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# collect_evolution.sh
#
# Generates a linear dataset of the repository history.
# AUTOMATICALLY ROTATES output files when they exceed a size limit.
#
# Usage:
#     ./collect_evolution.sh [output_prefix]
#
# Example:
#     ./collect_evolution.sh my_dataset
#     -> Generates: my_dataset_part001.txt, my_dataset_part002.txt...
# -----------------------------------------------------------------------------
set -u
set -o pipefail

# --- Configuration ---
# Default prefix if none provided
OUTPUT_PREFIX="${1:-evolution_dataset}"
# Max size in Bytes (80MB = 80 * 1024 * 1024 = 83886080)
MAX_BYTES=83886080

# Known binary extensions to skip immediately (performance optimization)
BINARY_EXT_BLACKLIST="png|jpg|jpeg|gif|ico|pdf|zip|tar|gz|7z|jar|war|class|pyc|so|dll|exe|bin|iso|mp4|mov"

# --- Setup ---
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "❌ Error: Not inside a Git repository."
    exit 1
fi

# Get all commits (Reverse Chronological: Oldest -> Newest)
echo "📊 Analyzing repository history..."
mapfile -t COMMITS < <(git rev-list --reverse HEAD)
TOTAL_COMMITS=${#COMMITS[@]}
echo "📌 Found $TOTAL_COMMITS commits to process."

# --- Helper Functions ---

# Portable file size checker (works on Mac/BSD and Linux)
get_file_size() {
    local f="$1"
    if [ ! -f "$f" ]; then echo 0; return; fi
    # 'wc -c' counts bytes
    wc -c < "$f" | tr -d ' '
}

# Check if stream is binary using Perl
is_binary_content() {
    perl -e '
        binmode(STDIN);
        read(STDIN, $buf, 1024);
        if (index($buf, "\0") != -1) { exit 0; } # Null byte found
        if (-B $buf) { exit 0; } # Perl heuristic
        exit 1; # Is text
    '
}

# --- Initialization ---
PART_NUM=1
# Pad with zeros (e.g., 001) for correct sorting later
CURRENT_OUTPUT="${OUTPUT_PREFIX}_part$(printf "%03d" $PART_NUM).txt"
: > "$CURRENT_OUTPUT" # Create empty file

echo "📝 Starting Output: $CURRENT_OUTPUT"

# --- Main Loop ---
START_TIME=$(date +%s)
COUNTER=0

for COMMIT_HASH in "${COMMITS[@]}"; do
    ((COUNTER++))

    # 1. CHECK SIZE & ROTATE IF NEEDED
    # We check before processing the commit to ensure commits remain atomic
    CURRENT_SIZE=$(get_file_size "$CURRENT_OUTPUT")

    if [ "$CURRENT_SIZE" -ge "$MAX_BYTES" ]; then
        echo -e "\n💾 Limit reached ($((CURRENT_SIZE / 1024 / 1024)) MB). Rotating file..."
        ((PART_NUM++))
        CURRENT_OUTPUT="${OUTPUT_PREFIX}_part$(printf "%03d" $PART_NUM).txt"
        : > "$CURRENT_OUTPUT"
        echo "📝 New Output: $CURRENT_OUTPUT"
    fi

    # 2. Progress Indicator
    # Calculate percentage
    PCT=$(( COUNTER * 100 / TOTAL_COMMITS ))
    # Print progress bar on one line
    printf "\r[ %d%% ] Commit %d/%d (%s) -> %s" "$PCT" "$COUNTER" "$TOTAL_COMMITS" "${COMMIT_HASH:0:7}" "$CURRENT_OUTPUT"

    # 3. Get Metadata
    COMMIT_DATE=$(git show -s --format='%ci' "$COMMIT_HASH")

    # 4. Write Header
    echo "====== COMMIT $COMMIT_HASH $COMMIT_DATE ======" >> "$CURRENT_OUTPUT"

    # 5. Process Files
    # git ls-tree: -r (recursive), -z (null-terminated), --name-only
    git ls-tree -r -z --name-only "$COMMIT_HASH" | while IFS= read -r -d '' FILE_PATH; do

        # A. Extension Filter (Fast)
        EXTENSION="${FILE_PATH##*.}"
        if [[ "$EXTENSION" =~ ^($BINARY_EXT_BLACKLIST)$ ]]; then
            continue
        fi

        # B. Content Inspection (Robust)
        # We pipe git-show output directly to checker without writing to disk
        if ! git show "$COMMIT_HASH:$FILE_PATH" | is_binary_content; then
            # It IS text.
            echo "--- BEGIN FILE $FILE_PATH ---" >> "$CURRENT_OUTPUT"
            git show "$COMMIT_HASH:$FILE_PATH" >> "$CURRENT_OUTPUT"
            echo -e "\n" >> "$CURRENT_OUTPUT"
        fi
    done

done

END_TIME=$(date +%s)
DURATION=$(( END_TIME - START_TIME ))

echo -e "\n\n✅ Done!"
echo "-----------------------------------"
echo "Total Parts:   $PART_NUM"
echo "Total Commits: $COUNTER"
echo "Time Taken:    ${DURATION}s"