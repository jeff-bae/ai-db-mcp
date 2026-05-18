# -*- coding: utf-8 -*-
"""
SQLite MCP Server
- FastMCP + SSE transport (port 8802)
- 3가지 도구: get_schema / query_database / modify_database
"""
import json
import sqlite3
from pathlib import Path

from mcp.server.fastmcp import FastMCP

DB_PATH = Path(__file__).parent / "demo.db"

mcp = FastMCP("SQLite MCP Server")


# ── helpers ───────────────────────────────────────────────

def _conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


# ── tools ─────────────────────────────────────────────────

@mcp.tool()
def get_schema() -> str:
    """데이터베이스의 전체 스키마(테이블 목록, 컬럼 정보, 행 수)를 조회합니다.
    처음 질문을 받았을 때 먼저 호출하세요."""
    conn = _conn()
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()]
        result = {}
        for t in tables:
            cols = [
                {"name": r["name"], "type": r["type"], "pk": bool(r["pk"])}
                for r in conn.execute(f"PRAGMA table_info({t})").fetchall()
            ]
            count = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            result[t] = {"columns": cols, "row_count": count}
        return json.dumps(result, ensure_ascii=False)
    finally:
        conn.close()


@mcp.tool()
def query_database(sql: str) -> str:
    """SELECT SQL 쿼리를 실행하여 데이터를 조회합니다. 데이터를 변경하지 않습니다."""
    if not sql.strip().upper().startswith("SELECT"):
        return json.dumps({"error": "query_database는 SELECT 쿼리만 허용합니다."})
    conn = _conn()
    try:
        cur = conn.execute(sql)
        rows = cur.fetchall()
        if not rows:
            return json.dumps({"columns": [], "rows": [], "count": 0})
        cols = [d[0] for d in cur.description]
        return json.dumps({
            "columns": cols,
            "rows": [dict(zip(cols, r)) for r in rows],
            "count": len(rows),
        }, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})
    finally:
        conn.close()


@mcp.tool()
def modify_database(sql: str, description: str) -> str:
    """INSERT, UPDATE, DELETE SQL을 실행하여 데이터를 변경합니다."""
    conn = _conn()
    try:
        cur = conn.execute(sql)
        conn.commit()
        return json.dumps({"affected_rows": cur.rowcount, "success": True,
                           "description": description})
    except Exception as e:
        conn.rollback()
        return json.dumps({"error": str(e), "success": False})
    finally:
        conn.close()


# ── entry point ───────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    # FastMCP SSE 앱을 uvicorn으로 직접 실행
    sse_app = mcp.sse_app()
    print("SQLite MCP Server running on http://0.0.0.0:8802/sse")
    uvicorn.run(sse_app, host="0.0.0.0", port=8001, log_level="warning")
