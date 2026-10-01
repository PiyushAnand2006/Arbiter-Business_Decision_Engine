"""SQLite store. One connection per Store guarded by a re-entrant lock.

Every SQL statement in the app lives here, so the engine and agents stay pure.
A Store can point at the demo database or at a throwaway file (evaluation).
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS crm_deals(
    deal_id TEXT PRIMARY KEY, company TEXT, stage TEXT, value TEXT, owner TEXT,
    last_contacted TEXT, close_date TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS finance_records(
    deal_id TEXT PRIMARY KEY, company TEXT, stage TEXT, value TEXT,
    invoice_status TEXT, close_date TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS pipeline_records(
    deal_id TEXT PRIMARY KEY, company TEXT, stage TEXT, value TEXT,
    forecast_category TEXT, close_date TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS audit_log(
    id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, deal_id TEXT, field TEXT,
    old_value TEXT, new_value TEXT, changed_at TEXT, changed_by TEXT, reason TEXT);
CREATE INDEX IF NOT EXISTS ix_audit_deal ON audit_log(deal_id);
CREATE TABLE IF NOT EXISTS conflicts(
    id INTEGER PRIMARY KEY AUTOINCREMENT, deal_id TEXT, field TEXT, reason TEXT,
    conflict_hash TEXT, sources_json TEXT, detected_at TEXT, status TEXT,
    decision_id INTEGER);
CREATE INDEX IF NOT EXISTS ix_conflicts_hash ON conflicts(conflict_hash);
CREATE TABLE IF NOT EXISTS decisions(
    id INTEGER PRIMARY KEY AUTOINCREMENT, deal_id TEXT, signature TEXT, card_json TEXT,
    status TEXT, path TEXT, created_at TEXT, updated_at TEXT);
CREATE INDEX IF NOT EXISTS ix_decisions_sig ON decisions(signature);
CREATE TABLE IF NOT EXISTS debates(
    id INTEGER PRIMARY KEY AUTOINCREMENT, conflict_hash TEXT UNIQUE, deal_id TEXT,
    field TEXT, transcript_json TEXT, verdict_json TEXT, llm_calls INTEGER,
    provider TEXT, model TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS approvals(
    id INTEGER PRIMARY KEY AUTOINCREMENT, decision_id INTEGER REFERENCES decisions(id),
    action TEXT, actor TEXT, note TEXT, effect TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS events(
    id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, kind TEXT, title TEXT, detail TEXT,
    deal_id TEXT, decision_id INTEGER, severity TEXT);
"""

SOURCE_TABLES = {
    "crm": "crm_deals",
    "finance": "finance_records",
    "pipeline": "pipeline_records",
}
SOURCE_FIELDS = {
    "crm": ["company", "stage", "value", "owner", "last_contacted", "close_date"],
    "finance": ["company", "stage", "value", "invoice_status", "close_date"],
    "pipeline": ["company", "stage", "value", "forecast_category", "close_date"],
}
RESET_TABLES = ["crm_deals", "finance_records", "pipeline_records", "audit_log",
                "conflicts", "decisions", "approvals", "events"]


def audit_evidence_id(audit_id: int) -> str:
    return f"A{audit_id:04d}"


class Store:
    def __init__(self, path: Path | str):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        if self.path != ":memory:":
            self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)

    # ------------------------------------------------------------------ core
    @contextmanager
    def tx(self):
        with self.lock:
            self.conn.execute("BEGIN")
            try:
                yield self.conn
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, tuple(params)).fetchall()]

    def query_one(self, sql: str, params: Iterable[Any] = ()) -> Optional[dict]:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def close(self):
        with self.lock:
            self.conn.close()

    # ------------------------------------------------------------------ seed
    def reset(self, clear_debate_cache: bool = False):
        with self.tx() as c:
            for t in RESET_TABLES:
                c.execute(f"DELETE FROM {t}")
            c.execute("DELETE FROM sqlite_sequence WHERE name IN ('audit_log','conflicts','decisions','approvals','events')")
            if clear_debate_cache:
                c.execute("DELETE FROM debates")
            c.execute("DELETE FROM meta")

    def load_dataset(self, dataset: dict):
        """dataset = {crm: [...], finance: [...], pipeline: [...], audit: [...]}"""
        with self.tx() as c:
            for source, table in SOURCE_TABLES.items():
                cols = ["deal_id", *SOURCE_FIELDS[source], "updated_at"]
                sql = f"INSERT INTO {table}({','.join(cols)}) VALUES({','.join('?' * len(cols))})"
                c.executemany(sql, [[row.get(k) for k in cols] for row in dataset[source]])
            c.executemany(
                "INSERT INTO audit_log(source,deal_id,field,old_value,new_value,changed_at,changed_by,reason)"
                " VALUES(?,?,?,?,?,?,?,?)",
                [[a["source"], a["deal_id"], a["field"], a["old_value"], a["new_value"],
                  a["changed_at"], a["changed_by"], a["reason"]] for a in sorted(dataset["audit"], key=lambda x: x["changed_at"])],
            )

    # --------------------------------------------------------------- sources
    def source_rows(self, source: str) -> list[dict]:
        return self.query(f"SELECT * FROM {SOURCE_TABLES[source]} ORDER BY deal_id")

    def source_row(self, source: str, deal_id: str) -> Optional[dict]:
        return self.query_one(f"SELECT * FROM {SOURCE_TABLES[source]} WHERE deal_id=?", [deal_id])

    def all_records(self) -> dict[str, dict[str, dict]]:
        """{source: {deal_id: row}}"""
        return {s: {r["deal_id"]: r for r in self.source_rows(s)} for s in SOURCE_TABLES}

    def deal_ids(self) -> list[str]:
        ids: set[str] = set()
        for s in SOURCE_TABLES:
            ids.update(r["deal_id"] for r in self.query(f"SELECT deal_id FROM {SOURCE_TABLES[s]}"))
        return sorted(ids)

    def update_source_field(self, source: str, deal_id: str, field: str, new_value: str,
                            at: str, changed_by: str, reason: str) -> Optional[int]:
        if field not in SOURCE_FIELDS[source]:
            raise ValueError(f"{source} has no field {field!r}")
        table = SOURCE_TABLES[source]
        with self.tx() as c:
            row = c.execute(f"SELECT {field} FROM {table} WHERE deal_id=?", [deal_id]).fetchone()
            if row is None:
                raise KeyError(f"{source} has no deal {deal_id}")
            old = row[0]
            c.execute(f"UPDATE {table} SET {field}=?, updated_at=? WHERE deal_id=?", [new_value, at, deal_id])
            cur = c.execute(
                "INSERT INTO audit_log(source,deal_id,field,old_value,new_value,changed_at,changed_by,reason)"
                " VALUES(?,?,?,?,?,?,?,?)", [source, deal_id, field, old, new_value, at, changed_by, reason])
            return cur.lastrowid

    def touch_source(self, source: str, deal_id: str, at: str):
        with self.tx() as c:
            c.execute(f"UPDATE {SOURCE_TABLES[source]} SET updated_at=? WHERE deal_id=?", [at, deal_id])

    # ----------------------------------------------------------------- audit
    def audit_for_deal(self, deal_id: str) -> list[dict]:
        return self.query("SELECT * FROM audit_log WHERE deal_id=? ORDER BY changed_at, id", [deal_id])

    def audit_since(self, since_iso: str) -> list[dict]:
        return self.query("SELECT source, field, reason FROM audit_log WHERE changed_at>=?", [since_iso])

    # ------------------------------------------------------------- conflicts
    def upsert_conflict(self, deal_id: str, field: str, reason: str, conflict_hash: str,
                        sources: list[dict], at: str) -> bool:
        """Returns True if the conflict is new (not seen with this hash before)."""
        with self.tx() as c:
            row = c.execute("SELECT id FROM conflicts WHERE conflict_hash=? AND status='open'", [conflict_hash]).fetchone()
            if row:
                return False
            c.execute("UPDATE conflicts SET status='replaced' WHERE deal_id=? AND field=? AND status='open'",
                      [deal_id, field])
            c.execute(
                "INSERT INTO conflicts(deal_id,field,reason,conflict_hash,sources_json,detected_at,status)"
                " VALUES(?,?,?,?,?,?, 'open')",
                [deal_id, field, reason, conflict_hash, json.dumps(sources), at])
            return True

    def close_conflicts_not_in(self, open_hashes: set[str]):
        with self.tx() as c:
            rows = c.execute("SELECT id, conflict_hash FROM conflicts WHERE status='open'").fetchall()
            for r in rows:
                if r["conflict_hash"] not in open_hashes:
                    c.execute("UPDATE conflicts SET status='cleared' WHERE id=?", [r["id"]])

    def link_conflicts(self, hashes: list[str], decision_id: int):
        with self.tx() as c:
            for h in hashes:
                c.execute("UPDATE conflicts SET decision_id=? WHERE conflict_hash=? AND status='open'", [decision_id, h])

    def open_conflicts(self) -> list[dict]:
        return self.query("SELECT * FROM conflicts WHERE status='open' ORDER BY detected_at DESC")

    # ------------------------------------------------------------- decisions
    def insert_decision(self, deal_id: str, signature: str, card: dict, at: str) -> int:
        with self.tx() as c:
            cur = c.execute(
                "INSERT INTO decisions(deal_id,signature,card_json,status,path,created_at,updated_at)"
                " VALUES(?,?,?,?,?,?,?)",
                [deal_id, signature, "{}", card["status"], card["path"], at, at])
            did = cur.lastrowid
            card["id"] = did
            c.execute("UPDATE decisions SET card_json=? WHERE id=?", [json.dumps(card), did])
            return did

    def save_decision(self, card: dict, at: str):
        with self.tx() as c:
            c.execute("UPDATE decisions SET card_json=?, status=?, path=?, updated_at=? WHERE id=?",
                      [json.dumps(card), card["status"], card["path"], at, card["id"]])

    def get_decision(self, decision_id: int) -> Optional[dict]:
        row = self.query_one("SELECT card_json FROM decisions WHERE id=?", [decision_id])
        return json.loads(row["card_json"]) if row else None

    def find_decision_by_signature(self, signature: str) -> Optional[dict]:
        row = self.query_one("SELECT card_json FROM decisions WHERE signature=? ORDER BY id DESC LIMIT 1", [signature])
        return json.loads(row["card_json"]) if row else None

    def list_decisions(self, status: Optional[str] = None, path: Optional[str] = None,
                       deal_id: Optional[str] = None, limit: int = 200) -> list[dict]:
        sql, params = "SELECT card_json FROM decisions WHERE 1=1", []
        if status:
            sql += " AND status=?"
            params.append(status)
        if path:
            sql += " AND path=?"
            params.append(path)
        if deal_id:
            sql += " AND deal_id=?"
            params.append(deal_id)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        return [json.loads(r["card_json"]) for r in self.query(sql, params)]

    # --------------------------------------------------------------- debates
    def cached_debate(self, conflict_hash: str) -> Optional[dict]:
        row = self.query_one("SELECT transcript_json FROM debates WHERE conflict_hash=?", [conflict_hash])
        return json.loads(row["transcript_json"]) if row else None

    def cache_debate(self, conflict_hash: str, deal_id: str, field: str, record: dict,
                     llm_calls: int, provider: str, model: str, at: str):
        with self.tx() as c:
            c.execute(
                "INSERT OR REPLACE INTO debates(conflict_hash,deal_id,field,transcript_json,verdict_json,"
                "llm_calls,provider,model,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                [conflict_hash, deal_id, field, json.dumps(record), json.dumps(record["verdict"]),
                 llm_calls, provider, model, at])

    def debate_cache_size(self) -> int:
        return self.query_one("SELECT COUNT(*) AS n FROM debates")["n"]

    # ------------------------------------------------------------- approvals
    def insert_approval(self, decision_id: int, action: str, actor: str, note: str, effect: str, at: str) -> dict:
        with self.tx() as c:
            cur = c.execute("INSERT INTO approvals(decision_id,action,actor,note,effect,at) VALUES(?,?,?,?,?,?)",
                            [decision_id, action, actor, note, effect, at])
            return {"id": cur.lastrowid, "decision_id": decision_id, "action": action,
                    "actor": actor, "note": note, "effect": effect, "at": at}

    def approvals_for(self, decision_id: int) -> list[dict]:
        return self.query("SELECT * FROM approvals WHERE decision_id=? ORDER BY id", [decision_id])

    # ---------------------------------------------------------------- events
    def log_event(self, at: str, kind: str, title: str, detail: str = "", deal_id: Optional[str] = None,
                  decision_id: Optional[int] = None, severity: Optional[str] = None):
        with self.tx() as c:
            c.execute("INSERT INTO events(at,kind,title,detail,deal_id,decision_id,severity) VALUES(?,?,?,?,?,?,?)",
                      [at, kind, title, detail, deal_id, decision_id, severity])

    def events(self, limit: int = 50) -> list[dict]:
        return self.query("SELECT * FROM events ORDER BY id DESC LIMIT ?", [limit])

    def corrections_by_source(self, since_iso: str) -> dict[str, int]:
        rows = self.query("SELECT source, COUNT(*) AS n FROM audit_log WHERE changed_at>=? AND reason IN "
                          "('correction','arbiter_sync') GROUP BY source", [since_iso])
        return {r["source"]: r["n"] for r in rows}

    # ------------------------------------------------------------------ meta
    def get_meta(self, key: str, default: Any = None) -> Any:
        row = self.query_one("SELECT value FROM meta WHERE key=?", [key])
        return json.loads(row["value"]) if row else default

    def set_meta(self, key: str, value: Any):
        with self.tx() as c:
            c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", [key, json.dumps(value)])

    def incr_meta(self, key: str, by: int = 1) -> int:
        with self.lock:
            val = int(self.get_meta(key, 0)) + by
            self.set_meta(key, val)
            return val
