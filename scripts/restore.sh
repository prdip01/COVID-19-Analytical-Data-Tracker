#!/usr/bin/env bash
#
# SQLite Database Restoration Script for COVID-19 Tracker.
# Safe restore: backs up the active database file before performing overwrite.
#

set -euo pipefail

# Configurations
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
DB_FILE="$BASE_DIR/data/covid19.db"

# Usage instructions
usage() {
    echo "Usage: $0 <path_to_backup_file.db>"
    exit 1
}

# Ensure argument is passed
if [ $# -ne 1 ]; then
    usage
fi

BACKUP_FILE="$1"

echo "=== Starting database restoration ==="
echo "Restoring from: $BACKUP_FILE"

# 1. Verify backup file exists and is not empty
if [ ! -f "$BACKUP_FILE" ] || [ ! -s "$BACKUP_FILE" ]; then
    echo "Error: Backup file does not exist or is empty: $BACKUP_FILE" >&2
    exit 1
fi

# 2. Verify that it is a valid SQLite database
if ! sqlite3 "$BACKUP_FILE" "PRAGMA integrity_check;" >/dev/null 2>&1; then
    echo "Error: Backup file is not a valid SQLite database (integrity check failed)." >&2
    exit 1
fi

# 3. Safe temporary backup of the current database (if one exists)
if [ -f "$DB_FILE" ]; then
    TEMP_BAK="$DB_FILE.pre_restore.bak"
    echo "Backing up current active database to $TEMP_BAK..."
    cp "$DB_FILE" "$TEMP_BAK"
fi

# 4. Overwrite active database with backup
echo "Restoring database..."
cp "$BACKUP_FILE" "$DB_FILE"

# 5. Quick integrity check on restored file
if sqlite3 "$DB_FILE" "PRAGMA integrity_check;" | grep -q "ok"; then
    echo "Database restored and verified successfully."
    # Clean up temp backup on success
    if [ -f "${TEMP_BAK:-}" ]; then
        rm "$TEMP_BAK"
    fi
else
    echo "Error: Restored database failed integrity check! Reverting from temporary backup..." >&2
    if [ -f "${TEMP_BAK:-}" ]; then
        mv "$TEMP_BAK" "$DB_FILE"
        echo "Reverted to pre-restoration database."
    fi
    exit 1
fi

echo "=== Restoration process completed ==="
exit 0
