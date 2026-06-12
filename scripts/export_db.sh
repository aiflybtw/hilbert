#!/usr/bin/env bash
set -euo pipefail
# Export hilbert database to a compressed SQL dump (for handover)
# Usage: ./scripts/export_db.sh [output_path]

OUTPUT="${1:-hilbert_dump.sql.gz}"

# Find correct pg_dump version
PG_DUMP=$(which pg_dump)
if [ -f /Library/PostgreSQL/18/bin/pg_dump ]; then
    PG_DUMP=/Library/PostgreSQL/18/bin/pg_dump
fi

echo "Exporting hilbert DB to $OUTPUT ..."
PGPASSWORD="${PGPASSWORD:-123456}" "$PG_DUMP" \
    -U postgres -d hilbert \
    --no-owner --no-acl | gzip > "$OUTPUT"

echo "Done: $(ls -lh "$OUTPUT" | awk '{print $5}')"
