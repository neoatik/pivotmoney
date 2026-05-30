# PivotMoney — Financial Data Ingestion Engine

A Python/FastAPI system to parse US brokerage statement PDFs, store structured financial data in PostgreSQL, and display a premium portfolio dashboard.

## Features

- **PDF Parsing**: Multi-strategy pipeline (AI → Regex → Fallback)
- **AI-Assisted Parsing**: Google Gemini Flash extracts structured data with confidence scoring
- **Multi-Layout Support**: Works across different brokerage statement formats
- **PostgreSQL Storage**: Normalized schema supporting multiple accounts & statements
- **REST API**: Full CRUD with async FastAPI
- **Premium Dashboard**: PivotMoney-styled dark UI with charts, tables, and live updates
- **Async Processing**: Background task-based pipeline (upload returns immediately)
- **Parse Logs**: Full audit trail of extraction decisions
- **Docker**: One-command startup

---

## Quick Start (Local PostgreSQL)

### Prerequisites
- Python 3.11+
- PostgreSQL (already installed)
- A free [Gemini API key](https://aistudio.google.com/)

### 1. Create the Database

Open psql or pgAdmin and run:
```sql
CREATE DATABASE pivotmoney;
```

### 2. Configure Environment

```bash
cd backend
copy .env.example .env
```

Edit `.env`:
```env
DATABASE_URL=postgresql+asyncpg://postgres:YOUR_PASSWORD@localhost:5432/pivotmoney
GEMINI_API_KEY=your_gemini_api_key_here
```

### 3. Install Dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 4. Run Database Migrations

```bash
cd backend
alembic upgrade head
```

### 5. Start the Server

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

### 6. Open the Dashboard

Visit: **http://localhost:8000**

The dashboard is served directly from FastAPI (no separate frontend server needed).

---

## Quick Start (Docker — Full Stack)

```bash
# Set your Gemini API key
set GEMINI_API_KEY=your_key_here    # Windows
# export GEMINI_API_KEY=your_key_here  # Mac/Linux

# Start everything
docker-compose up --build
```

Visit: **http://localhost:8000**

> **Note**: Docker Compose maps Postgres to port `5433` on the host to avoid conflicts with your local PostgreSQL installation.

### Standalone Docker Image (Without Compose)

If you wish to build and run the backend image independently (using an external PostgreSQL database), you can do so from the project root:

1. **Build the Docker Image**:
   ```bash
   docker build -t pivotmoney-app .
   ```

2. **Run the Container**:
   ```bash
   docker run -p 8000:8000 \
     -e GEMINI_API_KEY="your_gemini_api_key_here" \
     -e DATABASE_URL="postgresql+asyncpg://postgres:password@host:5432/pivotmoney" \
     pivotmoney-app
   ```

The container starts the FastAPI application, running migrations and serving the frontend static files globally at `http://localhost:8000`.

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/statements/upload` | Upload a PDF statement |
| `GET` | `/api/v1/statements` | List all statements |
| `GET` | `/api/v1/statements/{id}` | Get statement details |
| `GET` | `/api/v1/statements/{id}/holdings` | Holdings for a statement |
| `GET` | `/api/v1/statements/{id}/logs` | Parse logs for a statement |
| `DELETE` | `/api/v1/statements/{id}` | Delete a statement |
| `GET` | `/api/v1/holdings` | All holdings (filterable) |
| `GET` | `/api/v1/portfolio/summary` | Aggregated portfolio summary |
| `GET` | `/api/v1/portfolio/accounts` | Per-account summaries |
| `GET` | `/api/v1/portfolio/allocation` | Asset type breakdown |
| `GET` | `/api/v1/health` | Health check |

**Interactive API Docs**: http://localhost:8000/docs (Swagger UI)

---

## PDF Parsing Pipeline

```
PDF Upload
    │
    ▼
[1] pdfplumber + PyMuPDF → raw text extraction
    │
    ▼
[2] AI Parser (Gemini Flash)
    │  confidence > 0.7?
    ├──YES──► Use AI result as primary
    └──NO───► Fall through to regex
    │
    ▼
[3] Regex Parser (pdfplumber tables + patterns)
    │
    ▼
[4] Merge & Validate
    │
    ▼
[5] Normalize → DB Write → Update Status
```

---

## Project Structure

```
pivotmoney/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI entry point
│   │   ├── config.py          # Settings
│   │   ├── database.py        # Async SQLAlchemy
│   │   ├── models/            # ORM models
│   │   ├── schemas/           # Pydantic schemas
│   │   ├── routers/           # API routes
│   │   ├── services/          # Business logic
│   │   └── tasks/             # Background workers
│   ├── alembic/               # DB migrations
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── index.html             # Dashboard
│   ├── css/style.css          # PivotMoney design system
│   └── js/app.js              # Dashboard logic
├── docker-compose.yml
├── Dockerfile                 # Root Dockerfile
├── Pivot_Money_US_Statement.pdf
└── README.md
```

---

## Database Schema

```
accounts ──────────────────────────────────────────────
  id, account_number (UNIQUE), account_name, broker_name

statements ────────────────────────────────────────────
  id, account_id (FK), statement_date, filename,
  parse_status, confidence_score, raw_text, uploaded_at

holdings ──────────────────────────────────────────────
  id, statement_id (FK), account_id (FK),
  asset_name, ticker, asset_type,
  quantity, market_value, cost_basis, currency,
  price_per_share, unrealized_gl, weight_pct

parse_logs ────────────────────────────────────────────
  id, statement_id (FK), level, message, field_name, raw_value

activities ────────────────────────────────────────────
  id, statement_id (FK), account_id (FK), trade_date,
  activity_type, description, quantity, price, amount, currency
```

---

## Bonus Features Implemented

| Bonus | Status |
|-------|--------|
| Docker containerization | ✅ |
| Async background processing | ✅ |
| AI-assisted parsing (Gemini) | ✅ |
| Multiple PDF layout support | ✅ |
| Parse audit logs | ✅ |

---

## Tech Stack

- **Python 3.11+** / **FastAPI** / **Uvicorn**
- **SQLAlchemy 2.0** (async) / **asyncpg**
- **Alembic** migrations
- **pdfplumber** + **PyMuPDF** for PDF extraction
- **Google Gemini 1.5 Flash** for AI parsing
- **PostgreSQL 16**
- **Docker** + **Docker Compose**
- Vanilla **HTML/CSS/JS** frontend
