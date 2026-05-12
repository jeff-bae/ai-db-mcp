# -*- coding: utf-8 -*-
"""
AI-MCP-DB  ·  FastAPI 메인 서버 (port 8000)
- MCP Server (mcp_server.py, port 8001) 를 subprocess로 기동
- Claude / DeepSeek AI 가 MCP 클라이언트를 통해 SQLite 도구를 호출
"""
import asyncio
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
import random

import anthropic
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from mcp import ClientSession
from mcp.client.sse import sse_client
from openai import OpenAI
from pydantic import BaseModel

load_dotenv()

# ── App & paths ────────────────────────────────────────────
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(fastapi_app):
    global mcp_process
    init_db()
    mcp_process = subprocess.Popen(
        [sys.executable, str(BASE / "mcp_server.py")],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    for _ in range(20):
        await asyncio.sleep(0.5)
        try:
            async with sse_client(MCP_URL) as (r, w):
                async with ClientSession(r, w) as s:
                    await s.initialize()
                    print(f"MCP Server ready at {MCP_URL}")
                    break
        except Exception:
            continue
    else:
        print("Warning: MCP Server did not respond in time.")
    yield
    if mcp_process:
        mcp_process.terminate()

app = FastAPI(title="AI-MCP-DB Demo", lifespan=lifespan)
BASE    = Path(__file__).parent
DB_PATH = BASE / "demo.db"
MCP_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:8001/sse")

# ── AI clients ─────────────────────────────────────────────
anthropic_client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

_deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "")
deepseek_client = (
    OpenAI(api_key=_deepseek_key, base_url="https://api.deepseek.com")
    if _deepseek_key else None
)

SYSTEM_PROMPT = """당신은 SQLite 데이터베이스를 관리하는 AI 어시스턴트입니다.
사용자의 한국어 자연어 요청을 이해하여 적절한 SQL 쿼리를 실행합니다.

규칙:
- 항상 한국어로 간결하게 답변합니다
- 데이터 조회 결과는 핵심만 요약합니다 (통계/요약 위주)
- 데이터 수정/삽입/삭제 전에 어떤 작업을 할지 먼저 설명합니다
- 통계 요청에는 집계 함수(COUNT, SUM, AVG, MAX, MIN 등)를 활용합니다
- 데이터베이스 스키마를 먼저 파악한 후 쿼리를 작성합니다"""


# ── MCP tool format converters ─────────────────────────────

def to_anthropic_tools(mcp_tools) -> list:
    return [
        {
            "name": t.name,
            "description": t.description or "",
            "input_schema": t.inputSchema,
        }
        for t in mcp_tools
    ]


def to_openai_tools(mcp_tools) -> list:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description or "",
                "parameters": t.inputSchema,
            },
        }
        for t in mcp_tools
    ]


def parse_mcp_result(mcp_result) -> dict:
    """MCP CallToolResult → dict"""
    try:
        text = mcp_result.content[0].text if mcp_result.content else "{}"
        return json.loads(text)
    except Exception:
        return {"result": str(mcp_result)}


# ── DB helpers (table view API 전용) ───────────────────────

def _db_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def db_schema():
    conn = _db_conn()
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()]
        result = {}
        for t in tables:
            cols = [{"name": r["name"], "type": r["type"], "pk": bool(r["pk"])}
                    for r in conn.execute(f"PRAGMA table_info({t})").fetchall()]
            count = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            result[t] = {"columns": cols, "row_count": count}
        return result
    finally:
        conn.close()


def db_query(sql: str):
    conn = _db_conn()
    try:
        cur = conn.execute(sql)
        rows = cur.fetchall()
        if not rows:
            return {"columns": [], "rows": [], "count": 0}
        cols = [d[0] for d in cur.description]
        return {"columns": cols,
                "rows": [dict(zip(cols, r)) for r in rows],
                "count": len(rows)}
    finally:
        conn.close()


# ── DB init (샘플 데이터) ──────────────────────────────────

def init_db():
    if DB_PATH.exists():
        return
    conn = _db_conn()
    conn.executescript("""
        CREATE TABLE customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
            phone TEXT, city TEXT, grade TEXT DEFAULT 'NORMAL', joined_at TEXT
        );
        CREATE TABLE products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, category TEXT,
            price INTEGER NOT NULL, stock INTEGER DEFAULT 0
        );
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER REFERENCES customers(id),
            product_id  INTEGER REFERENCES products(id),
            quantity INTEGER DEFAULT 1, amount INTEGER NOT NULL,
            status TEXT DEFAULT 'PENDING', ordered_at TEXT
        );
    """)
    customers = [
        ("김민준","minjun@example.com","010-1111-2222","서울","VIP"),
        ("이서연","seoyeon@example.com","010-2222-3333","부산","NORMAL"),
        ("박지호","jiho@example.com","010-3333-4444","서울","GOLD"),
        ("최유진","yujin@example.com","010-4444-5555","인천","NORMAL"),
        ("정하은","haeun@example.com","010-5555-6666","서울","VIP"),
        ("강도현","dohyun@example.com","010-6666-7777","대구","NORMAL"),
        ("윤소희","sohee@example.com","010-7777-8888","광주","GOLD"),
        ("임태양","taeyang@example.com","010-8888-9999","서울","NORMAL"),
        ("한채원","chaewon@example.com","010-9999-0000","부산","VIP"),
        ("오스현","seunghyun@example.com","010-0000-1111","서울","GOLD"),
    ]
    base = datetime(2024, 1, 1)
    for i, (name, email, phone, city, grade) in enumerate(customers):
        conn.execute(
            "INSERT INTO customers (name,email,phone,city,grade,joined_at) VALUES (?,?,?,?,?,?)",
            (name, email, phone, city, grade,
             (base + timedelta(days=i * 18)).strftime("%Y-%m-%d")))
    products = [
        ("무선 이어폰","전자기기",89000,150),
        ("스마트 워치","전자기기",320000,80),
        ("노트북 파우치","액세서리",35000,300),
        ("USB-C 허브","전자기기",52000,200),
        ("기계식 키보드","전자기기",145000,60),
        ("마우스 패드","액세서리",18000,500),
        ("웹캠","전자기기",78000,120),
        ("블루투스 스피커","전자기기",115000,90),
        ("노트북 거치대","액세서리",42000,180),
        ("케이블 정리함","액세서리",15000,400),
    ]
    for name, cat, price, stock in products:
        conn.execute("INSERT INTO products (name,category,price,stock) VALUES (?,?,?,?)",
                     (name, cat, price, stock))
    statuses = ["PENDING","CONFIRMED","SHIPPED","DELIVERED","CANCELLED"]
    random.seed(42)
    od = datetime(2024, 3, 1)
    for i in range(40):
        cid = random.randint(1, 10)
        pid = random.randint(1, 10)
        qty = random.randint(1, 3)
        amount = products[pid - 1][2] * qty
        status = random.choices(statuses, weights=[10,15,20,45,10])[0]
        dt = (od + timedelta(days=i*2 + random.randint(0,3))).strftime("%Y-%m-%d")
        conn.execute(
            "INSERT INTO orders (customer_id,product_id,quantity,amount,status,ordered_at)"
            " VALUES (?,?,?,?,?,?)", (cid, pid, qty, amount, status, dt))
    conn.commit()
    conn.close()


# ── Conversation state ─────────────────────────────────────
active_provider: str = "anthropic"
anthropic_history: list = []
deepseek_history:  list = []

mcp_process: subprocess.Popen | None = None


# ── Anthropic + MCP agentic loop ───────────────────────────

async def run_anthropic(user_message: str):
    anthropic_history.append({"role": "user", "content": user_message})
    tool_calls_log, data_changed, reply = [], False, ""

    async with sse_client(MCP_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools_resp = await session.list_tools()
            a_tools = to_anthropic_tools(tools_resp.tools)

            while True:
                response = anthropic_client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=2048,
                    system=SYSTEM_PROMPT,
                    tools=a_tools,
                    messages=anthropic_history,
                )

                if response.stop_reason == "end_turn":
                    for block in response.content:
                        if hasattr(block, "text"):
                            reply = block.text
                    anthropic_history.append({"role": "assistant", "content": response.content})
                    break

                if response.stop_reason == "tool_use":
                    anthropic_history.append({"role": "assistant", "content": response.content})
                    tool_results = []

                    for block in response.content:
                        if block.type != "tool_use":
                            continue
                        # ★ MCP 서버에 도구 실행 요청
                        mcp_result = await session.call_tool(block.name, block.input)
                        result_dict = parse_mcp_result(mcp_result)

                        tool_calls_log.append({
                            "tool":   block.name,
                            "input":  block.input,
                            "result": result_dict,
                        })
                        if block.name == "modify_database" and result_dict.get("success"):
                            data_changed = True

                        tool_results.append({
                            "type":        "tool_result",
                            "tool_use_id": block.id,
                            "content":     json.dumps(result_dict, ensure_ascii=False, default=str),
                        })

                    anthropic_history.append({"role": "user", "content": tool_results})
                else:
                    break

    return reply, tool_calls_log, data_changed


# ── DeepSeek + MCP agentic loop ────────────────────────────

async def run_deepseek(user_message: str):
    if deepseek_client is None:
        raise RuntimeError("DEEPSEEK_API_KEY가 설정되지 않았습니다.")

    if not deepseek_history:
        deepseek_history.append({"role": "system", "content": SYSTEM_PROMPT})
    deepseek_history.append({"role": "user", "content": user_message})
    tool_calls_log, data_changed, reply = [], False, ""

    async with sse_client(MCP_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools_resp = await session.list_tools()
            o_tools = to_openai_tools(tools_resp.tools)

            while True:
                response = deepseek_client.chat.completions.create(
                    model="deepseek-chat",
                    messages=deepseek_history,
                    tools=o_tools,
                    tool_choice="auto",
                    max_tokens=2048,
                )
                choice = response.choices[0]

                if choice.finish_reason == "stop":
                    reply = choice.message.content or ""
                    deepseek_history.append({"role": "assistant", "content": reply})
                    break

                if choice.finish_reason == "tool_calls":
                    deepseek_history.append(choice.message)

                    for tc in choice.message.tool_calls:
                        try:
                            inp = json.loads(tc.function.arguments)
                        except Exception:
                            inp = {}
                        # ★ MCP 서버에 도구 실행 요청
                        mcp_result = await session.call_tool(tc.function.name, inp)
                        result_dict = parse_mcp_result(mcp_result)

                        tool_calls_log.append({
                            "tool":   tc.function.name,
                            "input":  inp,
                            "result": result_dict,
                        })
                        if tc.function.name == "modify_database" and result_dict.get("success"):
                            data_changed = True

                        deepseek_history.append({
                            "role":         "tool",
                            "tool_call_id": tc.id,
                            "content":      json.dumps(result_dict, ensure_ascii=False, default=str),
                        })
                else:
                    break

    return reply, tool_calls_log, data_changed


# ── API models ─────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str

class ChatResponse(BaseModel):
    reply: str
    tool_calls: list
    data_changed: bool
    provider: str


# ── Chat endpoint ──────────────────────────────────────────

@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    global active_provider

    async def _deepseek_safe(msg):
        try:
            return await run_deepseek(msg)
        except RuntimeError as e:
            return str(e), [], False
        except Exception as e:
            err = str(e)
            if "402" in err or "Insufficient Balance" in err:
                return ("DeepSeek 크레딧이 부족합니다.\n"
                        "https://platform.deepseek.com 에서 충전해 주세요."), [], False
            return f"DeepSeek 오류: {err}", [], False

    reply, tool_calls_log, data_changed = "", [], False

    if active_provider == "anthropic":
        try:
            reply, tool_calls_log, data_changed = await run_anthropic(req.message)
        except anthropic.BadRequestError as e:
            if "credit balance is too low" in str(e):
                active_provider = "deepseek"
                anthropic_history.clear()
                reply, tool_calls_log, data_changed = await _deepseek_safe(req.message)
            else:
                reply = f"API 오류: {e}"
        except anthropic.AuthenticationError:
            active_provider = "deepseek"
            anthropic_history.clear()
            reply, tool_calls_log, data_changed = await _deepseek_safe(req.message)
        except Exception as e:
            reply = f"오류: {str(e)}"
    else:
        reply, tool_calls_log, data_changed = await _deepseek_safe(req.message)

    return ChatResponse(
        reply=reply,
        tool_calls=tool_calls_log,
        data_changed=data_changed,
        provider=active_provider,
    )


@app.post("/api/reset")
async def reset_chat():
    global active_provider
    active_provider = "anthropic"
    anthropic_history.clear()
    deepseek_history.clear()
    return {"ok": True}


@app.get("/api/status")
async def get_status():
    return {
        "provider":             active_provider,
        "anthropic_configured": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "deepseek_configured":  deepseek_client is not None,
        "mcp_server":           MCP_URL,
    }


# ── Table view endpoints ───────────────────────────────────

TABLE_QUERIES = {
    "orders": """
        SELECT o.id, c.name AS 고객명, p.name AS 상품명,
               o.quantity AS 수량, o.amount AS 금액,
               o.status AS 상태, o.ordered_at AS 주문일
        FROM orders o
        JOIN customers c ON c.id = o.customer_id
        JOIN products  p ON p.id = o.product_id
        ORDER BY o.ordered_at DESC LIMIT 200
    """,
}

@app.get("/api/tables")
async def list_tables():
    return db_schema()

@app.get("/api/table/{table_name}")
async def get_table(table_name: str):
    allowed = {r[0] for r in _db_conn().execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()}
    if table_name not in allowed:
        raise HTTPException(status_code=404, detail="테이블 없음")
    return db_query(TABLE_QUERIES.get(table_name, f"SELECT * FROM {table_name} LIMIT 200"))


# ── pocket-kit 자동 클론 ────────────────────────────────────

def ensure_pocket_kit():
    pk_dir = BASE / "pocket-kit"
    if (pk_dir / "common.css").exists():
        return
    import subprocess as sp
    print("pocket-kit not found — cloning from GitHub...")
    pk_dir.mkdir(exist_ok=True)
    result = sp.run(
        ["git", "clone", "--depth=1",
         "https://github.com/jeff-bae/pocket-kit.git", str(pk_dir)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print("git clone failed:", result.stderr)
    else:
        print("pocket-kit cloned successfully.")


ensure_pocket_kit()

# ── Static files ───────────────────────────────────────────

app.mount("/pocket-kit", StaticFiles(directory=str(BASE / "pocket-kit")), name="pocket-kit")
app.mount("/static",     StaticFiles(directory=str(BASE / "static")),     name="static")

@app.get("/")
async def root():
    return FileResponse(str(BASE / "static" / "index.html"))


# ── Entry point ────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
