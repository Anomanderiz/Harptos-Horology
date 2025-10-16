
# Mithril Glass — Shiny (Python) + Supabase starter

Private, aesthetically modern Shiny app with a glass UI and animated backdrop. Designed for Posit Cloud deployment, using Supabase (Postgres) as a simple back end.

## What you get
- **Shiny for Python** app with a perpetual, subtle animated gradient backdrop and glass components.
- Minimal CRUD example for a single `items` table on Supabase (create/list).
- No public auth by default — intended for **private Posit Cloud** usage. Keep your keys private via environment variables.
- Accessibility-friendly defaults: honours `prefers-reduced-motion`; high-contrast palette.

## Quick start (local)
1. **Create/activate** a Python 3.11+ venv.
2. `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and fill in:
   - `SUPABASE_URL` = your project URL
   - `SUPABASE_SERVICE_KEY` = your service role key (private)
4. Create the table on Supabase (SQL editor): open `schema.sql`, run the `CREATE TABLE` statement.
5. Run: `shiny run --reload app.py`

## Deploy on Posit Cloud (private)
1. Create a new **Posit Cloud** project, upload this repo (or connect via Git).
2. In **Environment Variables**, add:
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_KEY`
3. Install deps: `pip install -r requirements.txt`
4. Click **Run App** → point to `app.py`.
5. Share the project privately by inviting collaborators.

## Security & policies
- This starter assumes **Row Level Security (RLS) OFF** for quick private use. For broader sharing, **enable RLS** and swap the service role key for a per-user flow (or keep server-only operations).
- Never expose the service role key in client code or front-end assets.

## Table schema
See `schema.sql`. Minimal columns:
- `id` UUID primary key
- `title` text (not null)
- `body` text
- `tags` text[] (optional)
- `created_at`/`updated_at` timestamps (default now())

## Theming & motion
- Animated gradient backdrop (60 s cycle), reduced for users who prefer reduced motion.
- Glass cards with translucent surfaces, golden hairlines, and soft elevation.
- Palette chosen for readability on dark backdrops.

## Troubleshooting
- If the Items pane shows an error, confirm env vars are set and the `items` table exists.
- Posit Cloud sessions sleep when idle — that’s fine for private use.

---

© Yours to adapt. No code licensing constraints beyond the package licences.
