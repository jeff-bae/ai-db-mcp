# -*- coding: utf-8 -*-
import sqlite3
import json
import os
from pathlib import Path
from datetime import datetime, timedelta
import random

import anthropic
from openai import OpenAI
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

app = FastAPI(title="AI-MCP-DB Demo")
DB_PATH = Path(__file__).parent / "demo.db"

# ── AI clients ─────────────────────────────────────────────
anthropic_client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

_deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "")
deepseek_client = OpenAI(api_key=_deepseek_key, base_url="https://api.deepseek.com") if _deepseek_key else None

SYSTEM_PROMPT = """당신은 SQLite 데이터베이스를 관리하는 AI 어시스턴트입니다.
사용자의 한국어 자연어 요청을 이해하여 적절한 SQL 쿼리를 실행합니다.

규칙:
- 항상 한국어로 간결하게 답변합니다
- 데이터 조회 결과는 핵심만 요약합니다 (전체 목록 나열 금지, 통계/요약 위주)
- 데이터 수정/삽입/삭제 전에 어떤 작업을 할지 먼저 설명합니다
- 통계 요청에는 집계 함수(COUNT, SUM, AVG, MAX, MIN 등)를 활용합니다
- SQL 실행 결과를 사람이 읽기 쉬운 문장으로 설명합니다
- 데이터베이스 스키마를 먼저 파악한 후 쿼리를 작성합니다"""

# ── Tool definitions (Anthropic format) ─────────────────────
ANTHROPIC_TOOLS = [
    {
        "name": "get_schema",
        "description": "데이터베이스의 전체 스키마(테이블 목록, 컬럼 정보, 행 수)를 조회합니다. 처음 질문을 받았을 때 먼저 호출하세요.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "query_database",
        "description": "SELECT SQL 쿼리를 실행하여 데이터를 조회합니다. 조회 전용이며 데이터를 변경하지 않습니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "실행할 SELECT SQL 쿼리. 반드시 SELECT로 시작해야 합니다."}
            },
            "required": ["sql"]
        }
    },
    {
        "name": "modify_database",
        "description": "INSERT, UPDATE, DELETE SQL을 실행하여 데이터를 변경합니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "실행할 INSERT/UPDATE/DELETE SQL"},
                "description": {"type": "string", "description": "이 변경 작업에 대한 한 줄 설명"}
            },
            "required": ["sql", "description"]
        }
    }
]

# ── Tool definitions (OpenAI/DeepSeek format) ───────────────
OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_schema",
            "description": "데이터베이스의 전체 스키마(테이블 목록, 컬럼 정보, 행 수)를 조회합니다.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_database",
            "description": "SELECT SQL 쿼리를 실행하여 데이터를 조회합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "실행할 SELECT SQL 쿼리"}
                },
                "required": ["sql"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "modify_database",
            "description": "INSERT, UPDATE, DELETE SQL을 실행하여 데이터를 변경합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "실행할 INSERT/UPDATE/DELETE SQL"},
                    "description": {"type": "string", "description": "이 변경 작업에 대한 한 줄 설명"}
                },
                "required": ["sql", "description"]
            }
        }
    }
]


# ── DB helpers ─────────────────────────────────────────────

def get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def tool_get_schema():
    conn = get_conn()
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()]
        result = {}
        for t in tables:
            cols = [
                {"name": r["name"], "type": r["type"], "pk": bool(r["pk"])}
                for r in conn.execute(f"PRAGMA table_info({t})").fetchall()
            ]
            count = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            result[t] = {"columns": cols, "row_count": count}
        return result
    finally:
        conn.close()


def tool_query(sql: str):
    if not sql.strip().upper().startswith("SELECT"):
        return {"error": "query_database는 SELECT 쿼리만 허용합니다."}
    conn = get_conn()
    try:
        cur = conn.execute(sql)
        rows = cur.fetchall()
        if not rows:
            return {"columns": [], "rows": [], "count": 0}
        cols = [d[0] for d in cur.description]
        return {
            "columns": cols,
            "rows": [dict(zip(cols, r)) for r in rows],
            "count": len(rows)
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        conn.close()


def tool_modify(sql: str):
    conn = get_conn()
    try:
        cur = conn.execute(sql)
        conn.commit()
        return {"affected_rows": cur.rowcount, "success": True}
    except Exception as e:
        conn.rollback()
        return {"error": str(e), "success": False}
    finally:
        conn.close()


def dispatch_tool(name: str, inp: dict):
    if name == "get_schema":
        return tool_get_schema()
    if name == "query_database":
        return tool_query(inp.get("sql", ""))
    if name == "modify_database":
        return tool_modify(inp.get("sql", ""))
    return {"error": f"Unknown tool: {name}"}


# ── DB initializer ─────────────────────────────────────────

def init_db():
    if DB_PATH.exists():
        return
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE customers (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            name      TEXT NOT NULL,
            email     TEXT UNIQUE NOT NULL,
            phone     TEXT,
            city      TEXT,
            grade     TEXT DEFAULT 'NORMAL',
            joined_at TEXT
        );

        CREATE TABLE products (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            name     TEXT NOT NULL,
            category TEXT,
            price    INTEGER NOT NULL,
            stock    INTEGER DEFAULT 0
        );

        CREATE TABLE orders (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER REFERENCES customers(id),
            product_id  INTEGER REFERENCES products(id),
            quantity    INTEGER DEFAULT 1,
            amount      INTEGER NOT NULL,
            status      TEXT DEFAULT 'PENDING',
            ordered_at  TEXT
        );
    """)

    customers = [
        ("김민준", "minjun@example.com",   "010-1111-2222", "서울", "VIP"),
        ("이서연", "seoyeon@example.com",  "010-2222-3333", "부산", "NORMAL"),
        ("박지호", "jiho@example.com",     "010-3333-4444", "서울", "GOLD"),
        ("최유진", "yujin@example.com",    "010-4444-5555", "인천", "NORMAL"),
        ("정하은", "haeun@example.com",    "010-5555-6666", "서울", "VIP"),
        ("강도현", "dohyun@example.com",  "010-6666-7777", "대구", "NORMAL"),
        ("윤소희", "sohee@example.com",   "010-7777-8888", "광주", "GOLD"),
        ("임태양", "taeyang@example.com", "010-8888-9999", "서울", "NORMAL"),
        ("한채원", "chaewon@example.com", "010-9999-0000", "부산", "VIP"),
        ("오스현", "seunghyun@example.com","010-0000-1111","서울", "GOLD"),
    ]
    base_date = datetime(2024, 1, 1)
    for i, (name, email, phone, city, grade) in enumerate(customers):
        joined = (base_date + timedelta(days=i * 18)).strftime("%Y-%m-%d")
        conn.execute(
            "INSERT INTO customers (name,email,phone,city,grade,joined_at) VALUES (?,?,?,?,?,?)",
            (name, email, phone, city, grade, joined)
        )

    products = [
        ("무선 이어폰",    "전자기기",  89000, 150),
        ("스마트 워치",    "전자기기", 320000,  80),
        ("노트북 파우치", "액세서리", 35000, 300),
        ("USB-C 허브",                 "전자기기",  52000, 200),
        ("기계식 키보드", "전자기기",145000, 60),
        ("마우스 패드",    "액세서리",  18000, 500),
        ("웹츐",                        "전자기기",  78000, 120),
        ("블루투스 스피커", "전자기기",115000, 90),
        ("노트북 거치대", "액세서리", 42000, 180),
        ("케이블 정리함", "액세서리", 15000, 400),
    ]
    for name, cat, price, stock in products:
        conn.execute(
            "INSERT INTO products (name,category,price,stock) VALUES (?,?,?,?)",
            (name, cat, price, stock)
        )

    statuses = ["PENDING", "CONFIRMED", "SHIPPED", "DELIVERED", "CANCELLED"]
    random.seed(42)
    order_date = datetime(2024, 3, 1)
    for i in range(40):
        cid = random.randint(1, 10)
        pid = random.randint(1, 10)
        qty = random.randint(1, 3)
        price = products[pid - 1][2]
        amount = price * qty
        status = random.choices(statuses, weights=[10, 15, 20, 45, 10])[0]
        dt = (order_date + timedelta(days=i * 2 + random.randint(0, 3))).strftime("%Y-%m-%d")
        conn.execute(
            "INSERT INTO orders (customer_id,product_id,quantity,amount,status,ordered_at) VALUES (?,?,?,?,?,?)",
            (cid, pid, qty, amount, status, dt)
        )

    conn.commit()
    conn.close()


# ── Conversation state ─────────────────────────────────────
# 현재 사용 중인 프로바이더 (세션 전체에서 유지)
active_provider: str = "anthropic"

# Anthropic 형식 히스토리 (ContentBlock 포함)
anthropic_history: list = []

# DeepSeek(OpenAI) 형식 히스토리 (plain dict)
deepseek_history: list[dict] = []


# ── Anthropic chat ─────────────────────────────────────────

def run_anthropic(user_message: str):
    anthropic_history.append({"role": "user", "content": user_message})
    tool_calls_log = []
    data_changed = False
    reply = ""

    while True:
        response = anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            tools=ANTHROPIC_TOOLS,
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
                if block.type == "tool_use":
                    result = dispatch_tool(block.name, block.input)
                    tool_calls_log.append({"tool": block.name, "input": block.input, "result": result})
                    if block.name == "modify_database" and result.get("success"):
                        data_changed = True
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    })

            anthropic_history.append({"role": "user", "content": tool_results})
        else:
            break

    return reply, tool_calls_log, data_changed


# ── DeepSeek chat ──────────────────────────────────────────

def run_deepseek(user_message: str):
    if deepseek_client is None:
        raise RuntimeError("DEEPSEEK_API_KEY가 설정되지 않았습니다.")
    # 히스토리가 비어있으면 system 메시지 먼저 추가
    if not deepseek_history:
        deepseek_history.append({"role": "system", "content": SYSTEM_PROMPT})

    deepseek_history.append({"role": "user", "content": user_message})
    tool_calls_log = []
    data_changed = False
    reply = ""

    while True:
        response = deepseek_client.chat.completions.create(
            model="deepseek-chat",
            messages=deepseek_history,
            tools=OPENAI_TOOLS,
            tool_choice="auto",
            max_tokens=2048,
        )

        choice = response.choices[0]

        if choice.finish_reason == "stop":
            reply = choice.message.content or ""
            deepseek_history.append({"role": "assistant", "content": reply})
            break

        if choice.finish_reason == "tool_calls":
            # assistant 메시지 저장 (tool_calls 포함)
            deepseek_history.append(choice.message)

            for tc in choice.message.tool_calls:
                try:
                    inp = json.loads(tc.function.arguments)
                except Exception:
                    inp = {}
                result = dispatch_tool(tc.function.name, inp)
                tool_calls_log.append({"tool": tc.function.name, "input": inp, "result": result})
                if tc.function.name == "modify_database" and result.get("success"):
                    data_changed = True

                deepseek_history.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                })
        else:
            # 예외적 finish_reason
            reply = choice.message.content or ""
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


# ── API routes ─────────────────────────────────────────────

@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    global active_provider

    reply = ""
    tool_calls_log = []
    data_changed = False

    def _run_deepseek_safe(msg):
        try:
            return run_deepseek(msg)
        except RuntimeError as e:
            # DEEPSEEK_API_KEY 미설정
            r = "DEEPSEEK_API_KEY가 설정되지 않았습니다.\n.env 파일에 키를 추가하거나 Anthropic 크레딧을 충전해 주세요."
            return r, [], False
        except Exception as e:
            err = str(e)
            if "402" in err or "Insufficient Balance" in err or "insufficient" in err.lower():
                r = "DeepSeek 크레딧이 부족합니다.\nhttps://platform.deepseek.com 에서 충전해 주세요."
            else:
                r = f"DeepSeek 오류: {err}"
            return r, [], False

    # Anthropic 먼저 시도
    if active_provider == "anthropic":
        try:
            reply, tool_calls_log, data_changed = run_anthropic(req.message)
        except anthropic.BadRequestError as e:
            if "credit balance is too low" in str(e):
                active_provider = "deepseek"
                anthropic_history.clear()
                reply, tool_calls_log, data_changed = _run_deepseek_safe(req.message)
            else:
                reply = f"API 오류: {e}"
        except anthropic.AuthenticationError:
            active_provider = "deepseek"
            anthropic_history.clear()
            reply, tool_calls_log, data_changed = _run_deepseek_safe(req.message)
        except Exception as e:
            reply = f"오류: {str(e)}"
    else:
        reply, tool_calls_log, data_changed = _run_deepseek_safe(req.message)

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
        "provider": active_provider,
        "anthropic_configured": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "deepseek_configured": deepseek_client is not None,
    }


@app.get("/api/tables")
async def list_tables():
    return tool_get_schema()


TABLE_QUERIES = {
    "orders": """
        SELECT
            o.id,
            c.name  AS 고객명,
            p.name  AS 상품명,
            o.quantity AS 수량,
            o.amount   AS 금액,
            o.status   AS 상태,
            o.ordered_at AS 주문일
        FROM orders o
        JOIN customers c ON c.id = o.customer_id
        JOIN products  p ON p.id = o.product_id
        ORDER BY o.ordered_at DESC
        LIMIT 200
    """,
}

@app.get("/api/table/{table_name}")
async def get_table(table_name: str):
    allowed = {r[0] for r in get_conn().execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()}
    if table_name not in allowed:
        raise HTTPException(status_code=404, detail="테이블 없음")
    query = TABLE_QUERIES.get(table_name, f"SELECT * FROM {table_name} LIMIT 200")
    return tool_query(query)


# ── Static files ───────────────────────────────────────────

app.mount("/pocket-kit", StaticFiles(directory=str(Path(__file__).parent / "pocket-kit")), name="pocket-kit")
app.mount("/static",     StaticFiles(directory=str(Path(__file__).parent / "static")),     name="static")


@app.get("/")
async def root():
    return FileResponse(str(Path(__file__).parent / "static" / "index.html"))


# ── Entry point ────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    init_db()
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
