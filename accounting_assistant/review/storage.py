"""Append-only document, review and calculation history in SQLite."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4


@contextmanager
def connect(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path, timeout=30) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        yield connection


def initialize(path: Path) -> None:
    with connect(path) as db:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS documents (
                sha256 TEXT PRIMARY KEY, filename TEXT NOT NULL, content BLOB NOT NULL,
                created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS transactions (
                id TEXT PRIMARY KEY, document_sha256 TEXT NOT NULL REFERENCES documents(sha256),
                payload TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS review_decisions (
                id INTEGER PRIMARY KEY, transaction_id TEXT NOT NULL REFERENCES transactions(id),
                reviewer TEXT NOT NULL, created_at TEXT NOT NULL,
                before_json TEXT NOT NULL, after_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS calculations (
                id TEXT PRIMARY KEY, reviewer TEXT NOT NULL, created_at TEXT NOT NULL,
                profile_json TEXT NOT NULL, rows_json TEXT NOT NULL, rule_json TEXT,
                rule_id TEXT, rule_version INTEGER, result_json TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS review_transaction_idx ON review_decisions(transaction_id, id);
        ''')
        for table in ("documents", "transactions", "review_decisions", "calculations"):
            for action in ("UPDATE", "DELETE"):
                db.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'append-only history'); END")


def import_document(path: Path, filename: str, content: bytes, rows) -> None:
    digest = sha256(content).hexdigest()
    now = datetime.now(timezone.utc).isoformat()
    with connect(path) as db:
        db.execute("INSERT OR IGNORE INTO documents VALUES (?, ?, ?, ?)", (digest, filename, content, now))
        for row in rows:
            if row.document_sha256 != digest:
                raise ValueError("Document hash does not match transaction evidence")
            db.execute("INSERT OR IGNORE INTO transactions VALUES (?, ?, ?, ?)", (row.transaction_id, digest, row.model_dump_json(), now))


def latest_rows(path: Path, rows):
    from accounting_assistant.tax_engine.period_balance import EvidenceRow
    with connect(path) as db:
        result = []
        for row in rows:
            found = db.execute("SELECT after_json FROM review_decisions WHERE transaction_id = ? ORDER BY id DESC LIMIT 1", (row.transaction_id,)).fetchone()
            result.append(EvidenceRow.model_validate_json(found[0]) if found else row)
        return result


def save_calculation(path: Path, reviewer: str, before, after, profile, rule, result) -> str:
    if not reviewer.strip():
        raise ValueError("Reviewer is required")
    if len(before) != len(after):
        raise ValueError("Review row count changed")
    identifier = uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    with connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        for old, new in zip(before, after):
            if old.transaction_id != new.transaction_id:
                raise ValueError("Transaction identity changed")
            current = db.execute("SELECT after_json FROM review_decisions WHERE transaction_id = ? ORDER BY id DESC LIMIT 1", (old.transaction_id,)).fetchone()
            if current and json.loads(current[0]) != old.model_dump(mode="json"):
                raise ValueError("Операция уже изменена другим проверяющим. Перезагрузите документ.")
            if any(getattr(old, key) != getattr(new, key) for key in ("document_sha256", "page", "passage")):
                raise ValueError("Original evidence cannot be edited")
            db.execute("INSERT INTO review_decisions (transaction_id, reviewer, created_at, before_json, after_json) VALUES (?, ?, ?, ?, ?)", (old.transaction_id, reviewer, now, old.model_dump_json(), new.model_dump_json()))
        db.execute("INSERT INTO calculations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (identifier, reviewer, now, profile.model_dump_json(), json.dumps([row.model_dump(mode="json") for row in after]), rule.model_dump_json() if rule else None, rule.rule_id if rule else None, rule.version if rule else None, result.model_dump_json()))
    return identifier


def save_profile(path: Path, taxpayer_key: str, profile) -> None:
    with connect(path) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS taxpayer_profiles (
            taxpayer_key TEXT PRIMARY KEY, profile_json TEXT NOT NULL, updated_at TEXT NOT NULL)''')
        db.execute('''CREATE TRIGGER IF NOT EXISTS taxpayer_profiles_no_delete
            BEFORE DELETE ON taxpayer_profiles BEGIN SELECT RAISE(ABORT, 'append-only history'); END''')
        db.execute('''CREATE TRIGGER IF NOT EXISTS taxpayer_profiles_no_update
            BEFORE UPDATE ON taxpayer_profiles BEGIN SELECT RAISE(ABORT, 'append-only history'); END''')
        db.execute('''INSERT INTO taxpayer_profiles VALUES (?, ?, ?)
            ON CONFLICT(taxpayer_key) DO NOTHING''', (taxpayer_key, profile.model_dump_json(), datetime.now(timezone.utc).isoformat()))


def load_profile(path: Path, taxpayer_key: str):
    from accounting_assistant.tax_engine.period_balance import PeriodProfile
    with connect(path) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS taxpayer_profiles (
            taxpayer_key TEXT PRIMARY KEY, profile_json TEXT NOT NULL, updated_at TEXT NOT NULL)''')
        row = db.execute('SELECT profile_json FROM taxpayer_profiles WHERE taxpayer_key = ?', (taxpayer_key,)).fetchone()
    return PeriodProfile.model_validate_json(row[0]) if row else None
