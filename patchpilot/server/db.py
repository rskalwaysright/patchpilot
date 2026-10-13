import sqlite3
import json
import os
from typing import Any, Dict, List, Optional


DB_PATH = os.path.join(os.path.dirname(__file__), "patchpilot.db")


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS traces (
            id TEXT PRIMARY KEY,
            repo_path TEXT,
            bug_description TEXT,
            strategy TEXT,
            tokens INTEGER,
            cost_usd REAL,
            latency_sec REAL,
            inconclusive INTEGER,
            validation_status TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            data_json TEXT
        )
    """)
    conn.commit()
    conn.close()


def save_trace(trace_dict: Dict[str, Any]):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    diag = trace_dict.get("diagnosis") or {}
    acc = trace_dict.get("accounting") or {}
    
    cursor.execute("""
        INSERT OR REPLACE INTO traces (
            id, repo_path, bug_description, strategy, tokens, cost_usd, latency_sec, inconclusive, validation_status, data_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        trace_dict.get("task_id", ""),
        trace_dict.get("repo_path", ""),
        trace_dict.get("bug_description", ""),
        trace_dict.get("strategy_used", ""),
        acc.get("total_tokens", 0),
        acc.get("estimated_cost_usd", 0.0),
        trace_dict.get("latency_seconds", 0.0),
        1 if diag.get("is_inconclusive") else 0,
        diag.get("validation_status", "UNKNOWN"),
        json.dumps(trace_dict),
    ))
    conn.commit()
    conn.close()


def list_traces(limit: int = 20) -> List[Dict[str, Any]]:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT data_json FROM traces ORDER BY created_at DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [json.loads(r[0]) for r in rows]
