# GP Triage Assistant — AI Powered

NHS-branded RAG proof-of-concept for GP triage, built with Streamlit, LangChain, ChromaDB, and PostgreSQL (Supabase).

> **Not for clinical production use.** This is a showcase/validation prototype.

---

## Deploying to Streamlit Community Cloud

### 1. Fork / push the repository

Push the `showcase-v2` branch to a public (or connected private) GitHub repository.

### 2. Create a Supabase project

1. Go to [supabase.com](https://supabase.com) and create a free project.
2. Once created, click **Connect** in the top toolbar.
3. Under **Connection pooling > Session mode**, copy the connection string.
   It will look like:
   ```
   postgresql://postgres.[project-ref]:[password]@aws-0-[region].pooler.supabase.com:5432/postgres
   ```
   > **Use the pooler URL, not the direct `db.*` URL.**
   > The direct `db.*` URL is IPv6-only and unreachable from many networks and from Streamlit Cloud.

### 3. Create the app on Streamlit Community Cloud

1. Go to [share.streamlit.io](https://share.streamlit.io) and click **New app**.
2. Connect your GitHub repo, set branch to `showcase-v2`, main file to `app.py`.
3. Click **Advanced settings > Secrets** and paste:

```toml
[database]
url = "postgresql://postgres.YOUR_PROJECT_REF:YOUR_PASSWORD@aws-0-YOUR_REGION.pooler.supabase.com:5432/postgres"

[openai]
api_key = "sk-..."

[smtp]
email = "your-email@gmail.com"
password = "your-gmail-app-password"
```

4. Click **Deploy**.

### 4. Initialise the database tables

Tables are created automatically on first load via `init_db()` — no manual SQL required.

### 5. Seed demo data (optional)

Run locally after setting `DATABASE_URL` in your `.env`:

```bash
python scripts/seed_demo_data.py
```

This seeds 5 complete patient journeys with ward data, observations, medications, safeguarding flags, and discharge checklists.

---

## Local Development

```bash
# Clone and set up
git clone <repo-url>
cd gp-triage-poc
python -m venv venv
venv\Scripts\activate          # Windows
source venv/bin/activate        # Mac/Linux

pip install -r requirements.txt

# Configure environment
copy .env.example .env
# Edit .env — add OPENAI_API_KEY at minimum.
# Add DATABASE_URL (Supabase pooler) for PostgreSQL; omit to fall back to local SQLite.

# Build the vector store (first run, ~5-10 min)
python scripts/setup_vectorstore.py

# (Optional) Seed demo patients
python scripts/seed_demo_data.py

# Run the app
streamlit run app.py
# Opens at http://localhost:8501
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | Yes | GPT-4o API key |
| `DATABASE_URL` | No | PostgreSQL pooler URL (Supabase). Omit to use local SQLite. |
| `SMTP_EMAIL` | No | Gmail address for letter emailing |
| `SMTP_PASSWORD` | No | Gmail App Password |

Set in `.env` (local), `.streamlit/secrets.toml` (local Streamlit — never commit), or Streamlit Cloud Secrets dashboard (production).

---

## Database

- **Production**: PostgreSQL via Supabase (12 tables, connection-pooled via Supavisor/PgBouncer)
- **Local fallback**: SQLite (`gp_triage.db`) — used automatically when `DATABASE_URL` is not set
- Tables are created idempotently on startup — no migration scripts needed

### Getting the correct Supabase DATABASE_URL

| URL type | Hostname | Port | When to use |
|---|---|---|---|
| Direct | `db.{ref}.supabase.co` | 5432 | IPv6 networks only |
| **Pooler (Session)** | `aws-0-{region}.pooler.supabase.com` | **5432** | **Recommended** — IPv4, standard connections |
| Pooler (Transaction) | `aws-0-{region}.pooler.supabase.com` | 6543 | Serverless / ephemeral connections |

Copy the pooler URL from: **Supabase Dashboard > Connect > Connection pooling > Session mode**

---

## Running Tests

```bash
pytest -v
# 46 unit tests — no OpenAI calls, no database required
```

---

## Architecture

See [CLAUDE.md](CLAUDE.md) for full module architecture, data flow, and database schema documentation.
