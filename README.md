# AI-MCP-DB

자연어로 SQLite 데이터베이스를 조회·수정·통계 분석하는 AI 데모 앱입니다.

Claude(Anthropic) 또는 DeepSeek AI가 사용자의 한국어 요청을 이해하고,  
**MCP(Model Context Protocol)** 를 통해 SQLite 도구를 실행합니다.  
UI는 [pocket-kit](https://github.com/jeff-bae/pocket-kit) 디자인 시스템을 사용합니다.

---

## 아키텍처

```
사용자 (브라우저)
      │
      ▼
┌─────────────────────────────┐
│  FastAPI  (port 8000)       │  ← 웹 서버 + AI 채팅 API
│  app.py                     │
│                             │
│  MCP Client (SSE 연결)      │──────────────────────────┐
│  session.list_tools()       │                          │
│  session.call_tool(...)     │                          ▼
│                             │       ┌──────────────────────────────┐
│  Claude / DeepSeek API      │       │  MCP Server  (port 8001)     │
└─────────────────────────────┘       │  mcp_server.py               │
                                      │                              │
                                      │  @mcp.tool() get_schema      │
                                      │  @mcp.tool() query_database  │
                                      │  @mcp.tool() modify_database │
                                      └──────────────┬───────────────┘
                                                     │
                                                     ▼
                                               SQLite (demo.db)
```

> `python app.py` 실행 시 MCP 서버(port 8001)가 자동으로 함께 기동됩니다.

---

## MCP란?

**Model Context Protocol** — Anthropic이 만든 AI-도구 연결 표준 프로토콜입니다.

| | 기존 방식 (Tool Use) | MCP |
|---|---|---|
| 도구 정의 위치 | AI 앱 코드 내부 | 독립 MCP 서버 |
| 재사용성 | 앱마다 다시 구현 | 어떤 클라이언트든 연결 가능 |
| 클라이언트 | 특정 앱만 | Claude Desktop, Cursor, Zed 등 |
| 통신 방식 | 함수 직접 호출 | SSE / stdio 표준 프로토콜 |

이 프로젝트의 MCP 서버(`mcp_server.py`)는 Claude Desktop에서도 그대로 연결할 수 있습니다.

---

## 주요 기능

| 기능 | 설명 |
|---|---|
| **자연어 → SQL** | "서울 VIP 고객 몇 명이야?" → AI가 SQL 생성 후 MCP로 실행 |
| **SQL 쿼리 로그** | 채팅창에 실행된 SQL 쿼리를 실시간으로 표시 |
| **데이터 수정** | INSERT / UPDATE / DELETE를 자연어로 요청 |
| **통계 분석** | COUNT / SUM / AVG / GROUP BY 등 집계 쿼리 자동 생성 |
| **자동 Fallback** | Anthropic 크레딧 부족 시 DeepSeek으로 자동 전환 |
| **테이블 뷰** | 상단 탭으로 테이블 전환, 데이터 실시간 반영 |

---

## 기술 스택

```
MCP Server   mcp (FastMCP + SSE transport)  ← port 8001
Web Server   FastAPI + uvicorn              ← port 8000
Database     SQLite3
AI           Claude Sonnet (Anthropic) → DeepSeek Chat (fallback)
Frontend     Vanilla JS + pocket-kit (PocketBase 디자인 시스템)
```

---

## 설치 및 실행

### 1. 의존성 설치

```bash
cd ai-mcp-db
pip install -r requirements.txt
```

### 2. API 키 설정

`.env` 파일에 키를 입력합니다.

```env
ANTHROPIC_API_KEY=sk-ant-...
DEEPSEEK_API_KEY=sk-...        # 선택사항 — Anthropic 크레딧 부족 시 자동 사용
```

### 3. 서버 시작

```bash
python app.py
```

`app.py` 하나만 실행하면 MCP 서버(8001)가 자동으로 함께 기동됩니다.

```
SQLite MCP Server running on http://0.0.0.0:8001/sse
MCP Server ready at http://localhost:8001/sse
INFO: Uvicorn running on http://0.0.0.0:8000
```

### 4. 브라우저 접속

```
http://localhost:8000
```

---

## 파일 구조

```
ai-mcp-db/
├── mcp_server.py       # MCP 서버 (SQLite 도구 3개 정의)
├── app.py              # FastAPI 서버 + MCP 클라이언트 + AI 채팅
├── static/
│   └── index.html      # 프론트엔드 (채팅 UI + 데이터 뷰)
├── pocket-kit/         # UI 디자인 시스템 (최초 실행 시 자동 클론)
├── demo.db             # SQLite DB (최초 실행 시 자동 생성)
├── .env                # API 키 설정
├── requirements.txt
└── start.bat           # Windows 실행 스크립트
```

---

## MCP 도구 목록

`mcp_server.py`에 정의된 3가지 도구입니다.

| 도구 | 설명 | AI 사용 시점 |
|---|---|---|
| `get_schema` | 테이블 목록·컬럼 구조·행 수 조회 | 질문을 처음 받았을 때 |
| `query_database` | SELECT SQL 실행 (조회 전용) | 데이터 조회·통계 요청 시 |
| `modify_database` | INSERT / UPDATE / DELETE 실행 | 데이터 추가·수정·삭제 요청 시 |

---

## 샘플 데이터

서버 최초 실행 시 `demo.db`가 자동으로 생성됩니다.

| 테이블 | 행 수 | 주요 컬럼 |
|---|---|---|
| `customers` | 10 | name, email, city, grade(VIP/GOLD/NORMAL), joined_at |
| `products` | 10 | name, category, price, stock |
| `orders` | 40 | 고객명, 상품명, quantity, amount, status, ordered_at |

> `orders` 테이블은 자동으로 고객·상품 JOIN되어 이름으로 표시됩니다.

---

## 시연 예시

```
"전체 테이블 구조 알려줘"
"서울에 사는 고객 몇 명이야?"
"고객 등급별 인원수와 평균 주문금액 알려줘"
"카테고리별 상품 매출 합계 분석해줘"
"재고 100개 이하인 상품 목록 보여줘"
"배송완료된 주문 총 금액 얼마야?"
"VIP 등급인 고객 이름이랑 도시 알려줘"
"스마트 워치 재고를 50개 추가해줘"
"주문 상태가 PENDING인 것들 CONFIRMED로 바꿔줘"
"신규 고객 추가해줘 - 이름: 홍길동, 이메일: hong@test.com, 도시: 서울"
```

---

## API 엔드포인트

| Method | Path | 설명 |
|---|---|---|
| `POST` | `/api/chat` | AI 채팅 (자연어 → MCP → SQL 실행) |
| `POST` | `/api/reset` | 대화 기록 초기화 |
| `GET` | `/api/status` | 현재 AI 프로바이더 및 MCP 서버 정보 |
| `GET` | `/api/tables` | 전체 테이블 스키마 조회 |
| `GET` | `/api/table/{name}` | 특정 테이블 데이터 조회 |

---

## Claude Desktop에서 MCP 서버 연결하기

`mcp_server.py`는 독립적인 MCP 서버이므로 Claude Desktop에서도 연결할 수 있습니다.

`claude_desktop_config.json`에 아래를 추가하세요.

```json
{
  "mcpServers": {
    "sqlite-db": {
      "command": "python",
      "args": ["/path/to/ai-mcp-db/mcp_server.py"],
      "env": {}
    }
  }
}
```
