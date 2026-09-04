# FPL Draft Helper

![Demo](demo.gif)

A small tool for Fantasy Premier League **Draft** leagues. Pulls your team, free agents, and
league data from `draft.premierleague.com`, and gives recommendations for your starting lineup,
waiver/free agent targets, transfers, and trades.

Available as:
- **CLI** (`main.py`) – tables printed straight to the terminal
- **Website** (`app.py`) – a Flask app you open in your browser

## Setup

1. Create a virtual environment and install dependencies:

   ```bash
   python -m venv .venv
   .venv\Scripts\activate      # Windows
   pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env`:

   ```bash
   copy .env.example .env
   ```

3. Fill in the values in `.env`:

   - **`PL_COOKIE_HEADER`** – the full `Cookie` header from a logged-in request to
     `draft.premierleague.com` (also works for Google/SSO logins):
     1. Log in at [draft.premierleague.com](https://draft.premierleague.com)
     2. Open DevTools (F12) → the **Network** tab
     3. Reload the page, find a request to `api/game` or `api/element-status`
     4. Under **Request Headers**, copy the entire value of `Cookie`
   - **`PL_ENTRY_ID`** – your team ID, visible in the cookie as `activeEntry`, or in the URL on
     the "My Team" page.
   - **`APP_PASSWORD`** – the password required to log into the website (`app.py` only, not
     used by the CLI).
   - **`SECRET_KEY`** – random value used to sign the login session cookie. Generate one with:
     ```bash
     python -c "import secrets; print(secrets.token_hex(32))"
     ```
     Keep this the same across restarts/deploys, or you'll get logged out every time it changes.

## Running the app

**CLI:**

```bash
python main.py
```

**Website:**

```bash
python app.py
```

Then open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your browser.

**If Windows blocks `.venv\Scripts\python.exe` from running** (e.g. "En programkontrollpolicy
har blokkert denne filen" / a Smart App Control or corporate application-control policy), use
`run.ps1` instead – it runs your global Python interpreter with the venv's packages on
`PYTHONPATH`, avoiding the blocked copy entirely:

```powershell
.\run.ps1          # CLI (main.py)
.\run.ps1 app      # website (app.py)
```

## Deploying the website (Vercel)

The website (`app.py`) can be deployed to [Vercel](https://vercel.com) so you can check it from
your phone. A password-protected login page (see `APP_PASSWORD`/`SECRET_KEY` above) keeps it
private to you.

1. Push this repo to GitHub (already done if you're reading this from there) and import it in
   Vercel ("Add New" → "Project" → select the repo). Vercel detects `vercel.json` automatically.
2. In the Vercel project's **Settings → Environment Variables**, add `PL_COOKIE_HEADER`,
   `PL_ENTRY_ID`, `APP_PASSWORD`, and `SECRET_KEY` (same values as your local `.env`).
3. Deploy. Your team's data is only ever visible after logging in with `APP_PASSWORD`.

Two things that don't fully carry over to a serverless deployment:

- **Club-change detection** (`team_change_cache.json`) needs to persist state between runs.
  Vercel's filesystem is read-only outside of `/tmp`, and `/tmp` isn't guaranteed to survive
  between requests – so this feature quietly stops detecting changes when deployed. It still
  works normally when you run the app locally.
- **Cold starts / execution time.** The Hobby (free) plan caps function execution time, and the
  app makes several sequential requests to the FPL API. `vercel.json` requests a 60s limit and
  the player-history fetches run in parallel, but if you still hit timeouts, check the function
  logs in the Vercel dashboard.

## What the tool shows

- Recommended starting lineup and bench for the next gameweek, based on form, fixture difficulty
  (FDR), and player availability
- Free agents worth picking up
- Suggested transfers between your team and free agents
- League overview with points and squads for every manager in the league
- Waiver/transfer history and proposed trades between managers
- Trade opportunities based on what other managers own
- Waiver timing – your priority and the risk of being outbid on targets you're interested in
- A notice when a player has changed clubs since the last run (this also catches moves within
  the Premier League, which the FPL API doesn't flag directly)

## Notes

- `PL_COOKIE_HEADER` expires periodically – grab a fresh one from DevTools if you start getting
  login errors.
- `team_change_cache.json` is a local cache the tool uses to detect club changes between runs.
  It's ignored by git.
