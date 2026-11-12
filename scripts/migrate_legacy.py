#!/usr/bin/env python3
"""
Safe legacy → new BizSuite data migration.

Rules enforced:
- NEVER modifies LEGACY_DATABASE_URL (source is read-only)
- Writes only to DATABASE_URL (target)
- Preserves IDs where possible
- Skips duplicates
- Logs every success / skip / failure
- Generates JSON migration report
- Does not invent fake business records
- Password hashes: copied only if column mapping is verified; otherwise preserved for review

Usage:
  export LEGACY_DATABASE_URL=postgresql://...
  export DATABASE_URL=postgresql://...   # separate empty or new DB recommended
  python scripts/migrate_legacy.py
"""
import os
import sys
import json
from datetime import datetime
from collections import defaultdict

try:
    from sqlalchemy import create_engine, text, inspect
except ImportError:
    print("Install sqlalchemy and psycopg2-binary.")
    sys.exit(1)


def normalize_url(url: str) -> str:
    if url and url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


def table_exists(insp, schema, table):
    return table in insp.get_table_names(schema=schema)


def get_columns(insp, schema, table):
    return {c["name"] for c in insp.get_columns(table, schema=schema)}


def main():
    legacy_url = normalize_url(os.environ.get("LEGACY_DATABASE_URL"))
    target_url = normalize_url(os.environ.get("DATABASE_URL"))

    if not legacy_url:
        print("ERROR: LEGACY_DATABASE_URL is required.")
        sys.exit(1)
    if not target_url:
        print("ERROR: DATABASE_URL (target) is required.")
        sys.exit(1)
    if legacy_url == target_url:
        print("ERROR: LEGACY and TARGET must be different databases.")
        sys.exit(1)

    legacy = create_engine(legacy_url, pool_pre_ping=True)
    target = create_engine(target_url, pool_pre_ping=True)
    leg_insp = inspect(legacy)
    tgt_insp = inspect(target)

    report = {
        "started_at": datetime.utcnow().isoformat() + "Z",
        "source": "LEGACY_DATABASE_URL",
        "target": "DATABASE_URL",
        "imported": defaultdict(int),
        "skipped": defaultdict(list),
        "failed": defaultdict(list),
        "notes": [],
        "password_hash_handling": "unknown",
    }

    # --- Users ---
    # Map public.users if present. Prefer password_hash, fall back to pw_hash with warning.
    if table_exists(leg_insp, "public", "users") and table_exists(tgt_insp, "public", "users"):
        leg_cols = get_columns(leg_insp, "public", "users")
        hash_col = None
        if "password_hash" in leg_cols:
            hash_col = "password_hash"
            report["password_hash_handling"] = "copied from password_hash (verify algorithm compatibility)"
        elif "pw_hash" in leg_cols:
            hash_col = "pw_hash"
            report["password_hash_handling"] = (
                "copied from pw_hash — VERIFY Argon2/bcrypt compatibility. "
                "If incompatible, force password reset for affected users."
            )
            report["notes"].append("Legacy pw_hash mapped to password_hash. Review hashes before production login.")
        else:
            report["notes"].append("No password hash column found on legacy users. Users will need password reset.")
            report["password_hash_handling"] = "missing — users need reset"

        with legacy.connect() as lconn, target.begin() as tconn:
            rows = lconn.execute(text("SELECT * FROM public.users")).mappings().all()
            for row in rows:
                try:
                    email = (row.get("email") or "").lower().strip()
                    if not email:
                        report["skipped"]["users"].append({"id": row.get("id"), "reason": "no email"})
                        continue
                    exists = tconn.execute(
                        text("SELECT id FROM public.users WHERE email = :e OR id = :i"),
                        {"e": email, "i": row.get("id")},
                    ).first()
                    if exists:
                        report["skipped"]["users"].append({"id": row.get("id"), "email": email, "reason": "duplicate"})
                        continue

                    pw = row.get(hash_col) if hash_col else None
                    if not pw:
                        # Placeholder — user must reset; do not invent a real password
                        from passlib.context import CryptContext
                        pw = CryptContext(schemes=["argon2"]).hash("MUST_RESET_" + secrets_token())

                    role = (row.get("role") or "employee").lower()
                    if role not in ("admin", "manager", "employee"):
                        role = "employee"

                    tconn.execute(
                        text("""
                            INSERT INTO public.users
                            (id, email, name, password_hash, role, is_active, phone, department, created_at, updated_at)
                            VALUES
                            (:id, :email, :name, :password_hash, :role, :is_active, :phone, :department, :created_at, :updated_at)
                            ON CONFLICT DO NOTHING
                        """),
                        {
                            "id": row.get("id"),
                            "email": email,
                            "name": row.get("name") or row.get("full_name") or email.split("@")[0],
                            "password_hash": pw,
                            "role": role,
                            "is_active": bool(row.get("is_active", True)),
                            "phone": row.get("phone"),
                            "department": row.get("department"),
                            "created_at": row.get("created_at") or datetime.utcnow(),
                            "updated_at": row.get("updated_at") or datetime.utcnow(),
                        },
                    )
                    report["imported"]["users"] += 1
                except Exception as e:
                    report["failed"]["users"].append({"id": row.get("id"), "error": str(e)})
    else:
        report["notes"].append("public.users missing on legacy or target — skipped user migration.")

    # Warn about auth.users (Supabase)
    if table_exists(leg_insp, "auth", "users"):
        report["notes"].append(
            "auth.users present (Supabase). NOT imported. Never mix auth.users.encrypted_password "
            "into BizSuite public.users without explicit verification."
        )

    # --- Generic helper for simple tables ---
    def migrate_simple(table, column_map, order_by="id"):
        if not table_exists(leg_insp, "public", table) or not table_exists(tgt_insp, "public", table):
            report["notes"].append(f"Table {table} missing on legacy or target — skipped.")
            return
        with legacy.connect() as lconn, target.begin() as tconn:
            rows = lconn.execute(text(f'SELECT * FROM public."{table}" ORDER BY {order_by}')).mappings().all()
            for row in rows:
                try:
                    params = {}
                    for tgt_col, src_col in column_map.items():
                        params[tgt_col] = row.get(src_col) if isinstance(src_col, str) else src_col(row)
                    # Skip if ID already exists
                    if "id" in params and params["id"] is not None:
                        exists = tconn.execute(
                            text(f'SELECT id FROM public."{table}" WHERE id = :id'),
                            {"id": params["id"]},
                        ).first()
                        if exists:
                            report["skipped"][table].append({"id": params["id"], "reason": "duplicate"})
                            continue
                    cols = ", ".join(params.keys())
                    binds = ", ".join(f":{k}" for k in params.keys())
                    tconn.execute(text(f'INSERT INTO public."{table}" ({cols}) VALUES ({binds}) ON CONFLICT DO NOTHING'), params)
                    report["imported"][table] += 1
                except Exception as e:
                    report["failed"][table].append({"id": row.get("id"), "error": str(e)})

    # Projects
    migrate_simple(
        "projects",
        {
            "id": "id",
            "name": "name",
            "description": "description",
            "status": lambda r: (r.get("status") or "planning").lower().replace(" ", "_"),
            "start_date": "start_date",
            "end_date": "end_date",
            "manager_id": "manager_id",
            "created_at": "created_at",
            "updated_at": "updated_at",
        },
    )

    # Tasks
    migrate_simple(
        "tasks",
        {
            "id": "id",
            "title": "title",
            "description": "description",
            "status": lambda r: (r.get("status") or "todo").lower().replace(" ", "_"),
            "priority": lambda r: (r.get("priority") or "normal").lower(),
            "start_date": "start_date",
            "due_date": "due_date",
            "feedback": "feedback",
            "created_by_id": "created_by_id",
            "assignee_id": "assignee_id",
            "project_id": "project_id",
            "created_at": "created_at",
            "updated_at": "updated_at",
        },
    )

    # Announcements
    migrate_simple(
        "announcements",
        {
            "id": "id",
            "title": "title",
            "body": "body",
            "target_audience": lambda r: r.get("target_audience") or "all",
            "created_by_id": "created_by_id",
            "is_active": lambda r: bool(r.get("is_active", True)),
            "created_at": "created_at",
            "updated_at": "updated_at",
        },
    )

    # File metadata only (bytes recovered separately from storage)
    migrate_simple(
        "stored_files",
        {
            "id": "id",
            "original_filename": "original_filename",
            "stored_filename": "stored_filename",
            "content_type": "content_type",
            "size_bytes": "size_bytes",
            "uploader_id": "uploader_id",
            "task_id": "task_id",
            "project_id": "project_id",
            "created_at": "created_at",
        },
    )
    report["notes"].append(
        "File metadata migrated if present. Actual file bytes must be recovered from original "
        "storage (Render disk / S3 / etc.) separately."
    )

    report["finished_at"] = datetime.utcnow().isoformat() + "Z"
    report["imported"] = dict(report["imported"])
    report["skipped"] = {k: v for k, v in report["skipped"].items()}
    report["failed"] = {k: v for k, v in report["failed"].items()}

    out = f"migration_report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    print(json.dumps(report, indent=2, default=str))
    print(f"\nReport: {out}")
    print("Source database was NOT modified.")


def secrets_token():
    import secrets
    return secrets.token_urlsafe(8)


if __name__ == "__main__":
    main()