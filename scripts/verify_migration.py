#!/usr/bin/env python3
"""
Verify migration: compare row counts and basic FK integrity between legacy and target.
Does not modify either database.
"""
import os
import sys
import json
from datetime import datetime

try:
    from sqlalchemy import create_engine, text, inspect
except ImportError:
    print("Install sqlalchemy and psycopg2-binary.")
    sys.exit(1)


def normalize(url):
    if url and url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


TABLES = ["users", "projects", "tasks", "announcements", "stored_files", "project_members", "messages"]


def count(engine, table):
    try:
        with engine.connect() as c:
            return c.execute(text(f'SELECT COUNT(*) FROM public."{table}"')).scalar()
    except Exception as e:
        return f"error: {e}"


def main():
    legacy_url = normalize(os.environ.get("LEGACY_DATABASE_URL"))
    target_url = normalize(os.environ.get("DATABASE_URL"))
    if not legacy_url or not target_url:
        print("Set LEGACY_DATABASE_URL and DATABASE_URL")
        sys.exit(1)

    legacy = create_engine(legacy_url, pool_pre_ping=True)
    target = create_engine(target_url, pool_pre_ping=True)

    result = {
        "verified_at": datetime.utcnow().isoformat() + "Z",
        "tables": {},
        "fk_checks": [],
        "ok": True,
    }

    for t in TABLES:
        lc = count(legacy, t)
        tc = count(target, t)
        result["tables"][t] = {"legacy": lc, "target": tc, "match": lc == tc if isinstance(lc, int) else False}
        if isinstance(lc, int) and isinstance(tc, int) and tc < lc:
            result["ok"] = False

    # Sample FK: tasks.assignee_id must exist in users
    try:
        with target.connect() as c:
            orphans = c.execute(text("""
                SELECT COUNT(*) FROM public.tasks t
                LEFT JOIN public.users u ON t.assignee_id = u.id
                WHERE t.assignee_id IS NOT NULL AND u.id IS NULL
            """)).scalar()
            result["fk_checks"].append({"check": "tasks.assignee_id → users", "orphan_count": orphans})
            if orphans:
                result["ok"] = False
    except Exception as e:
        result["fk_checks"].append({"check": "tasks.assignee_id", "error": str(e)})

    out = f"verify_report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    with open(out, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(json.dumps(result, indent=2, default=str))
    print(f"Wrote {out}")
    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()