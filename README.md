# TopDev — AI Recruitment SaaS

> **Top Talent. Top Scores.**  
> Production-ready, scalable AI recruitment platform for the IT industry.

---

## 🚀 Quick Deploy (3 Steps)

### Step 1 — Configure Environment Variables

```bash
cp .env.example .env
```

Edit `.env` and fill in:

| Variable | Description |
|---|---|
| `SECRET_KEY` | Random secret (use `openssl rand -hex 32`) |
| `JWT_SECRET_KEY` | JWT signing secret |
| `OPENAI_API_KEY` | OpenAI API key for AI assessments |
| `STRIPE_SECRET_KEY` | Stripe secret key |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook secret |
| `SENDGRID_API_KEY` | SendGrid API key for emails |
| `AWS_ACCESS_KEY_ID` | AWS access key (S3 for file storage) |
| `AWS_SECRET_ACCESS_KEY` | AWS secret key |
| `S3_BUCKET_NAME` | S3 bucket name |

### Step 2 — Run Migrations & Seed

```bash
docker compose run --rm migrate
```

This will:
- Apply all Alembic database migrations
- Seed default settings, email templates, scoring weights, feature flags, and role templates
- Create the default admin account: `admin@topdev.ai` / `Admin@123`

### Step 3 — Deploy

```bash
docker compose up --build
```

**Services:**
- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs
- Celery Flower: http://localhost:5555 (dev profile only)

---

## 🏗️ Architecture

```
TopDev/
├── backend/                    # FastAPI Python backend
│   ├── app/
│   │   ├── api/v1/             # Route handlers
│   │   │   ├── auth.py         # JWT auth, register, login
│   │   │   ├── jobs.py         # JD upload + AI parsing
│   │   │   ├── assessments.py  # Candidate invite + test links
│   │   │   ├── candidates.py   # Test flow (start/submit/results)
│   │   │   ├── clients.py      # Client dashboard + candidate view
│   │   │   ├── admin.py        # No-code admin controls
│   │   │   ├── payments.py     # Stripe webhooks
│   │   │   └── analytics.py    # Metrics & reporting
│   │   ├── models/             # SQLAlchemy ORM models (15 tables)
│   │   ├── ai/                 # OpenAI integration layer
│   │   ├── services/           # Email, S3 storage, scoring
│   │   └── workers/            # Celery async tasks
│   ├── alembic/                # Database migrations
│   └── scripts/seed.py         # Database seed script
│
├── frontend/                   # React + Vite + TypeScript
│   └── src/
│       ├── pages/
│       │   ├── public/         # Landing page
│       │   ├── auth/           # Login / Register
│       │   ├── client/         # Dashboard, Jobs, Candidates, Analytics, Billing
│       │   ├── admin/          # No-code Admin Controls (5 panels)
│       │   └── candidate/      # Dashboard + Test-taking UI
│       ├── store/              # Zustand auth store
│       └── services/           # Axios API client
│
├── docker-compose.yml          # Full stack orchestration
└── .env.example                # All environment variables
```

---

## 🎯 Key Features

### For Clients (Hiring Companies)
- **JD Upload** — paste text or upload PDF/DOCX
- **AI Assessment Generation** — GPT-4 creates MCQ + coding + scenario questions
- **Candidate Rankings** — scored 0–100, filtered by badge (Elite/Strong/Qualified)
- **Score Breakdown** — per-question AI feedback
- **Resume Download** — signed S3 URLs
- **Analytics** — funnel metrics, conversion rates

### For Candidates
- **Secure Test Links** — token-based, 48-hour expiry
- **Full Test UI** — countdown timer, question sidebar, MCQ + coding editor
- **Auto Scoring** — AI scores answers asynchronously via Celery

### Admin No-Code Controls (No coding required!)
| Panel | What you can change |
|---|---|
| Scoring Weights | Technical / Coding / Problem Solving % |
| Platform Settings | Thresholds, counts, AI prompts, link expiry |
| Email Templates | Subject, HTML body with variable insertion |
| Feature Flags | Toggle any platform feature on/off |
| Role Templates | Create/delete reusable test structures |

---

## 💳 Subscription Plans

| Plan | Roles/month | Price |
|---|---|---|
| Starter | 5 | $49/mo |
| Growth | 20 | $149/mo |
| Enterprise | Unlimited | Custom |

Powered by Stripe. Webhooks handle plan upgrades, payment tracking.

---

## 🔐 Security

- JWT access + refresh tokens
- RBAC: `admin` / `client` / `candidate` roles
- Signed S3 URLs for file access (1hr expiry by default)
- Rate limiting (slowapi)
- CORS policy
- Stripe webhook signature verification
- Security headers (HSTS, CSP, X-Frame-Options)

---

## 🛠️ Development

```bash
# Backend only
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload

# Frontend only  
cd frontend
npm install
npm run dev

# Celery worker
cd backend
celery -A app.workers.celery_app worker --loglevel=info
```

---

## 📋 Default Admin Credentials

After running the seed script:
- **Email:** `admin@topdev.ai`
- **Password:** `Admin@123`

> ⚠️ Change the admin password immediately in production!
# TopDev
