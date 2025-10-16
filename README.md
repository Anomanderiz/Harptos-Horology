# Harptos Calendar (Shiny for Python + Supabase)

A clean, interactive Harptos calendar (12 × 30 days; no intercalaries) with:

- **Beautiful year view** (3 × 4 months), responsive and glass‑UI.
- **Set current date** (month/day/year) and **auto‑advance +1** Harptos day per real day.
- **Click any day** to open a modal and **add notes/events**.
- **Supabase persistence**: events and current date/state load automatically on app start.

## Quick start

1. **Create the Supabase project** and run `schema.sql` in the SQL editor.
2. Create a `.env` with:
   ```bash
   SUPABASE_URL="https://YOUR-PROJECT.supabase.co"
   SUPABASE_ANON_KEY="YOUR-ANON-OR-SERVICE-KEY"
   ```
3. Install deps and run:
   ```bash
   pip install -r requirements.txt
   shiny run --reload app.py
   ```

> **Tip:** On Posit Cloud, set the environment variables in the project settings.  
> On Render, add them in the service’s Environment tab.

## Tables

- `state(key text primary key, value jsonb, updated_at timestamptz)` — stores `current_date` and `last_checked`.
- `events(id uuid primary key, year int, month int, day int, title text, notes text, real_world_date date, hidden boolean default false)`

## Auto‑advance logic

Every 10 minutes the app compares today’s real date with the last stored `last_checked` ISO date.  
If at least one real day has elapsed, it increments Harptos by the same number of days, persists `current_date`, then updates `last_checked`.

## Styling

All styles live in `www/styles.css`. Edit colours in the `:root` section (e.g., `--gold`, `--accent`).

## Deployment

- **Posit/RSConnect**: `rsconnect deploy shiny .` or the GUI.  
- **Render**: Use a Python web service, start command `shiny run --host 0.0.0.0 --port $PORT app.py`.

## Notes

- This build intentionally omits intercalary days (per your spec).  
- Day cells show a small dot if any event exists on that day.
- Multiple events per day are supported; you can delete existing ones from the modal.