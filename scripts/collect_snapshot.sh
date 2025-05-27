#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# collect_snapshot.sh   –   Concatenate all *readable text* files of the repo
#                          into a single snapshot file.
#
# Usage:
#     ./scripts/collect_snapshot.sh [output_file]
#
# If no output file is given, it creates one named
#     snapshot_YYYYMMDD_HHMMSS.txt  in the current directory.
# -----------------------------------------------------------------------------
set -euo pipefail

# ----------- choose output file ------------------
out=${1:-snapshot_$(date +%Y%m%d_%H%M%S).txt}
>"$out"   # truncate or create

echo "📄  Writing snapshot to $out"

# ----------- function to decide if file is text ---
is_text() {
    file --mime "$1" 2>/dev/null | grep -q "text/"
}

# ----------- iterate over tracked files -----------
for f in $(git ls-files); do
    # skip if file unreadable or symlink etc.
    [ -f "$f" ] || continue
    [ -r "$f" ] || continue
    if is_text "$f"; then
        echo "===== BEGIN $f =====" >>"$out"
        cat "$f" >>"$out"
        echo -e "\n===== END $f =====\n" >>"$out"
    fi
done

echo "✅  Snapshot complete: $(wc -l < "$out") lines"