#!/usr/bin/env python3
"""
Inspect a legacy BizSuite / related PostgreSQL database.
READ-ONLY. Never modifies the source database.

Usage:
  export LEGACY_DATABASE_URL=postgresql://user:pass@host:5432/dbname
  python scripts/inspect_legacy_db.py
"""
import os
import sys
import json
from datetime import datetime

try:
    from sqlalchemy import create_engine, text, inspect
except ImportError:
    print("Install sqlalchemy and psycopg2-binary first.")
    sys.exit(1)


def main():
    url = os.environ.get("LEGACY_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: Set LEGACY_DATABASE_URL (or DATABASE_URL) environment variable.")
        sys.exit(1)
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)

    engine = create_engine(url, pool_pre_ping=True)
    insp = inspect(engine)

    report = {
        "inspected_at": datetime.utcnow().isoformat() + "Z",
        "schemas": {},
        "notes": [],
    }

    with engine.connect() as conn:
        # List all non-system tables
        rows = conn.execute(text("""
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
            ORDER BY table_schema, table_name
        """)).fetchall()

        for schema, table in rows:
            report["schemas"].setdefault(schema, {})
            cols = conn.execute(text("""
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = :s AND table_name = :t
                ORDER BY ordinal_position
            """), {"s": schema, "t": table}).fetchall()

            count = None
            try:
                count = conn.execute(text(f'SELECT COUNT(*) FROM "{schema}"."{table}"')).scalar()
            except Exception as e:
                count = f"error: {e}"

            report["schemas"][schema][table] = {
                "row_count": count,
                "columns": [
                    {
                        "name": c[0],
                        "type": c[1],
                        "nullable": c[2],
                        "default": str(c[3]) if c[3] is not None else None,
                    }
                    for c in cols
                ],
            }

    # Highlight common patterns
    public = report["schemas"].get("public", {})
    auth = report["schemas"].get("auth", {})
    if "users" in public:
        cols = [c["name"] for c in public["users"]["columns"]]
        if "pw_hash" in cols:
            report["notes"].append("public.users has pw_hash (legacy). Map carefully to password_hash.")
        if "password_hash" in cols:
            report["notes"].append("public.users already has password_hash.")
        if "encrypted_password" in cols:
            report["notes"].append("public.users has encrypted_password — verify hash algorithm before mapping.")
    if "users" in auth:
        report["notes"].append(
            "auth.users detected (likely Supabase). Do NOT copy auth.users.encrypted_password "
            "into BizSuite without verifying compatibility. Keep BizSuite public.users separate."
        )

    out_path = f"migration_inspect_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    print(json.dumps(report, indent=2, default=str))
    print(f"\nReport written to {out_path}")
    print("REMINDER: This script is read-only. Source database was not modified.")


if __name__ == "__main__":
    main()