#!/usr/bin/env bash
#
# SQLite Database Backup Script for COVID-19 Tracker.
# Performs a transaction-safe hot copy of the database and prunes old files.
#

# exit on error, unset variable, or pipeline failure
set -euo pipefail

# Configurations
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
DB_FILE="$BASE_DIR/data/covid19.db"
BACKUP_DIR="$BASE_DIR/data/backups"
TIMESTAMP="$(date +"%Y%m%d_%H%M%S")"
BACKUP_FILE="$BACKUP_DIR/backup_$TIMESTAMP.db"

echo "=== Starting database backup ==="
echo "Time: $(date)"

# Ensure backup folder exists
mkdir -p "$BACKUP_DIR"

# Verify database file exists before backing up
if [ ! -f "$DB_FILE" ]; then
    echo "Error: Database file not found at $DB_FILE. Run ETL pipeline first." >&2
    exit 1
fi

# SQLite online backup command (safe to execute while database is under read/write)
echo "Backing up $DB_FILE to $BACKUP_FILE..."
sqlite3 "$DB_FILE" ".backup '$BACKUP_FILE'"

# Verify backup was created successfully and is not empty
if [ -f "$BACKUP_FILE" ] && [ -s "$BACKUP_FILE" ]; then
    echo "Backup completed successfully: $(basename "$BACKUP_FILE")"
else
    echo "Error: Backup file is empty or was not created." >&2
    exit 1
fi

# Delete backups older than 30 days to save space
echo "Pruning backups older than 30 days..."
find "$BACKUP_DIR" -name "backup_*.db" -type f -mtime +30 -delete

echo "=== Backup process completed ==="
exit 0
