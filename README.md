# AI-MCP-DB

자연어로 SQLite 데이터베이스를 조회·수정·통계 분석하는 AI 데모 앱입니다.

Claude(Anthropic) 또는 DeepSeek AI가 사용자의 한국어 요청을 이해하여 SQL을 직접 생성·실행합니다.
UI는 [pocket-kit](https://github.com/jeff-bae/pocket-kit) 디자인 시스템을 사용합니다.

---

## 주요 기능

| 기능 | 설명 |
|---|---|
| **자연어 → SQL** | "서울 VIP 고객 몇 명이야?" → AI가 SQL 생성 후 실행 |
| **SQL 쿼리 로그** | 채팅창에 실행된 SQL 쿼리를 실시간으로 표시 |
| **데이터 수정** | INSERT / UPDATE / DELETE를 자연어로 요청 |
| **통계 분석** | COUNT / SUM / AVG / GROUP BY 등 집계 쿼리 자동 생성 |
| **자동 Fallback** | Anthropic 크레딧 부족 시 DeepSeek으로 자동 전환 |
| **테이블 뷰** | 상단 탭으로 테이블 전환, 데이터 실시간 반영 |

---

## 기술 스택

```
Backend   FastAPI + Python 3.13
Database  SQLite3
AI        Claude Sonnet (Anthropic) → DeepSeek Chat (fallback)
Frontend  Vanilla JS + pocket-kit (PocketBase 디자인 시스템)
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
DEEPSEEK_API_KEY=sk-...        # Anthropic 크레딧 부족 시 자동으로 사용
```

### 3. 서버 시작

```bash
python app.py
# 또는 Windows: start.bat 더블클릭
```

### 4. 브라우저 접속

```
http://localhost:8000
```

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

## 프로젝트 구조

```
ai-mcp-db/
├── app.py              # FastAPI 서버 + Claude/DeepSeek Tool Use
├── static/
│   └── index.html      # 프론트엔드 (채팅 UI + 데이터 뷰)
├── pocket-kit/         # UI 디자인 시스템 (jeff-bae/pocket-kit)
├── demo.db             # SQLite DB (최초 실행 시 자동 생성)
├── .env                # API 키 설정
├── requirements.txt
└── start.bat           # Windows 실행 스크립트
```

---

## AI 동작 방식 (MCP 개념)

```
사용자 자연어
     ↓
  AI (Claude / DeepSeek)
     ↓  Tool Use
  ┌──────────────────┐
  │  get_schema      │  → DB 테이블/컬럼 구조 파악
  │  query_database  │  → SELECT 실행 (조회)
  │  modify_database │  → INSERT/UPDATE/DELETE 실행
  └──────────────────┘
     ↓
  결과 요약 + SQL 로그 표시
```

AI는 먼저 DB 스키마를 파악한 뒤, 사용자 의도에 맞는 SQL을 생성하여 직접 실행합니다.
실행된 모든 SQL은 채팅창에 실시간으로 표시됩니다.

---

## API 엔드포인트

| Method | Path | 설명 |
|---|---|---|
| `POST` | `/api/chat` | AI 채팅 (자연어 → SQL 실행) |
| `POST` | `/api/reset` | 대화 기록 초기화 |
| `GET` | `/api/status` | 현재 사용 중인 AI 프로바이더 확인 |
| `GET` | `/api/tables` | 전체 테이블 스키마 조회 |
| `GET` | `/api/table/{name}` | 특정 테이블 데이터 조회 |
