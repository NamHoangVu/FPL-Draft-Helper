# FPL Draft Helper

![Demo](demo.gif)

A small tool for Fantasy Premier League **Draft** leagues. Pulls your team, free agents, and
league data from `draft.premierleague.com`, and gives recommendations for your starting lineup,
waiver/free agent targets, transfers, and trades.

**Live:** [fpl-draft-helper.vercel.app](https://fpl-draft-helper.vercel.app) (password-protected —
only accessible to me)

## What the tool shows

- Recommended starting lineup and bench for the next gameweek, based on form, fixture difficulty
  (FDR), and player availability
- The current/next gameweek's fixtures involving your players, with kickoff times
- Free agents worth picking up, and suggested transfers between your team and free agents
- League overview with points and squads (shown as a formation) for every manager in the league
- Waiver/transfer history and proposed trades between managers
- Trade opportunities based on what other managers own
- Waiver timing – your priority and the risk of being outbid on targets you're interested in
- A notice when a player has changed clubs since the last run (this also catches moves within
  the Premier League, which the FPL API doesn't flag directly)

Available as a **CLI** (`main.py`, tables printed to the terminal) or a **website** (`app.py`,
what's deployed above).

## Local development

1. Create a virtual environment and install dependencies:

   ```bash
   python -m venv .venv
   .venv\Scripts\activate      # Windows
   pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and fill in the values:

   - **`PL_COOKIE_HEADER`** – the full `Cookie` header from a logged-in request to
     `draft.premierleague.com` (also works for Google/SSO logins). Log in at
     [draft.premierleague.com](https://draft.premierleague.com), open DevTools (F12) → **Network**,
     reload, find a request to `api/game` or `api/element-status`, and copy the entire
     `Cookie` request header.
   - **`PL_ENTRY_ID`** – your team ID, visible in the cookie as `activeEntry`, or in the URL on
     the "My Team" page.
   - **`APP_PASSWORD`** – login password for the website (`app.py` only, not used by the CLI).
   - **`SECRET_KEY`** – random value signing the login session cookie, e.g. from
     `python -c "import secrets; print(secrets.token_hex(32))"`. Keep it stable, or you'll get
     logged out whenever it changes.

3. Run it:

   ```bash
   python main.py      # CLI
   python app.py        # website → http://127.0.0.1:5000
   ```

   **Windows app-control policies** (e.g. Smart App Control) sometimes block the python.exe that
   `venv` copies into `.venv\Scripts`. If you hit that, use `.\run.ps1` / `.\run.ps1 app` instead –
   it runs your global Python with the venv's packages on `PYTHONPATH`.

## Deploying (Vercel)

The website deploys to [Vercel](https://vercel.com) using `vercel.json` (Flask via
`@vercel/python`). Import the repo in Vercel, add the same four env vars from `.env` under
**Settings → Environment Variables**, and deploy.

Two things don't fully carry over to a serverless deployment: **club-change detection**
(`team_change_cache.json`) needs state to persist between runs, which Vercel's filesystem doesn't
guarantee outside a request — it just quietly stops detecting changes. And the **Hobby plan's
function timeout** can be tight since the app makes several sequential FPL API requests (player
history fetches run in parallel to help).

## Notes

- `PL_COOKIE_HEADER` expires periodically – grab a fresh one from DevTools if you start getting
  login errors.
- `team_change_cache.json` is a local cache the tool uses to detect club changes between runs.
  It's ignored by git.
