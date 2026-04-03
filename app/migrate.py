"""
migrate.py — run once to sync hrms.db with models.py
Adds missing columns to tickets and leave_requests tables.

Usage:
    python migrate.py
"""

from sqlalchemy import create_engine, text

DB_PATH = r"C:\HRMS\hrms.db"
engine  = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})

# Columns to add: {table: [(column, definition), ...]}
MIGRATIONS = {
    "tickets": [
        ("notes",       "TEXT"),
        ("assigned_to", "VARCHAR"),
        ("resolved_at", "DATETIME"),
        ("closed_at",   "DATETIME"),
    ],
    "leave_requests": [
        ("notes",        "TEXT"),
        ("approved_by",  "VARCHAR"),
        ("approved_at",  "DATETIME"),
        ("rejected_at",  "DATETIME"),
    ],
}

def existing_columns(conn, table: str) -> set[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {r[1] for r in rows}

def run():
    with engine.begin() as conn:
        for table, columns in MIGRATIONS.items():
            current = existing_columns(conn, table)
            for col_name, col_type in columns:
                if col_name not in current:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}"))
                    print(f"  ✅ Added {table}.{col_name} ({col_type})")
                else:
                    print(f"  ⏭️  {table}.{col_name} already exists — skipped")

    print("\n✅ Migration complete. hrms.db is now in sync with models.py")

if __name__ == "__main__":
    run()
