#!/usr/bin/env bash
set -euo pipefail
# Import hilbert database from a compressed SQL dump
# Usage: ./scripts/import_db.sh [dump_path]

INPUT="${1:-hilbert_dump.sql.gz}"

if [ ! -f "$INPUT" ]; then
    echo "File not found: $INPUT"
    echo "Usage: $0 [path/to/hilbert_dump.sql.gz]"
    exit 1
fi

echo "Creating database hilbert..."
createdb -U postgres hilbert 2>/dev/null || echo "  (database may already exist)"

echo "Importing $INPUT ..."
gunzip -c "$INPUT" | PGPASSWORD="${PGPASSWORD:-123456}" psql -U postgres -d hilbert

echo "Done. Verify:"
echo "  psql -U postgres -d hilbert -c 'SELECT count(*) FROM vacancies;'"
