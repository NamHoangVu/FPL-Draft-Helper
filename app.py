"""
FPL Draft Helper - website
Run: python app.py, open http://127.0.0.1:5000
"""

import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, session

from fpl_client import FPLDraftClient
from analyzer import (
    build_current_squad_picks,
    analyze_squad,
    recommend_starting_xi,
    analyze_free_agents,
    analyze_all_owned_players,
    suggest_transfers,
    build_league_squads,
    build_transactions_feed,
    build_trades_feed,
    find_trade_opportunities,
    build_waiver_timing_report,
    get_waiver_processing_info,
    build_my_fixtures,
    is_gameweek_finished,
    apply_club_change_notes,
)

load_dotenv()
app = Flask(__name__)

app.secret_key = os.environ.get("SECRET_KEY")
app.permanent_session_lifetime = timedelta(days=30)
# Vercel sets VERCEL=1 in its build/runtime environment - only require HTTPS
# cookies there, so the session cookie still works over plain http://localhost.
app.config["SESSION_COOKIE_SECURE"] = bool(os.environ.get("VERCEL"))
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

FDR_CLASS = {1: "fdr-1", 2: "fdr-2", 3: "fdr-3", 4: "fdr-4", 5: "fdr-5"}


def get_client() -> FPLDraftClient:
    cookie = os.getenv("PL_COOKIE_HEADER")
    if not cookie:
        raise RuntimeError("Missing PL_COOKIE_HEADER in .env")
    return FPLDraftClient(cookie)


def get_entry_id() -> int:
    entry_id = os.getenv("PL_ENTRY_ID")
    if not entry_id:
        raise RuntimeError("Missing PL_ENTRY_ID in .env")
    return int(entry_id)


@app.before_request
def check_auth_config():
    if not app.secret_key or not os.environ.get("APP_PASSWORD"):
        return "Server misconfigured: SECRET_KEY and APP_PASSWORD must both be set.", 500


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        expected = os.environ.get("APP_PASSWORD")
        submitted = request.form.get("password", "")
        if expected and secrets.compare_digest(submitted, expected):
            session.clear()
            session["authenticated"] = True
            session.permanent = True
            return redirect(request.args.get("next") or url_for("index"))
        error = "Wrong password."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    error = None
    context = {}

    try:
        client = get_client()
        entry_id = get_entry_id()

        bootstrap = client.get_bootstrap()
        entry_info = client.get_entry_info(entry_id)
        league_id = entry_info["entry"]["league_set"][0] if entry_info["entry"].get("league_set") else None
        team_name = entry_info["entry"].get("name", "Your team")

        current_gw = client.get_current_gameweek()
        next_gw = current_gw + 1
        current_gw_label = "Last GW" if is_gameweek_finished(bootstrap, current_gw) else "Current GW"

        # element-status shows ownership in real time, unlike get_my_picks() which
        # only has data for gameweeks that have already locked/started. Use it for
        # your team when we have a league, so transfers you just made show up correctly.
        element_status, league_details = None, None
        if league_id:
            element_status = client.get_league_element_status(league_id)
            league_details = client.get_league_details(league_id)

        if element_status:
            picks = build_current_squad_picks(element_status, entry_id)
        else:
            picks = client.get_my_picks(entry_id, current_gw)
        player_ids = [p["element"] for p in picks["picks"]]

        def fetch_history(pid):
            try:
                return pid, client.get_player_history(pid)
            except Exception:
                return pid, {}

        with ThreadPoolExecutor(max_workers=8) as executor:
            player_histories = dict(executor.map(fetch_history, player_ids))

        fixtures = client.get_fixtures_for_gameweek(next_gw)

        players = analyze_squad(picks, bootstrap, next_gw, player_histories, fixtures)
        apply_club_change_notes(players, current_gw)
        starters, bench = recommend_starting_xi(players)

        # While the current gameweek is still being played, show its remaining
        # fixtures (not next_gw's) - e.g. don't jump ahead to next week's
        # fixtures while today's matches haven't been played yet.
        if current_gw_label == "Current GW":
            fixtures_gw = current_gw
            fixtures_for_tab = client.get_fixtures_for_gameweek(current_gw)
        else:
            fixtures_gw = next_gw
            fixtures_for_tab = fixtures
        my_fixtures = build_my_fixtures(fixtures_for_tab, fixtures_gw, bootstrap, players, player_histories)

        waiver_targets = []
        transfer_suggestions = []
        league_squads = []
        transactions_feed = []
        trades_feed = []
        trade_opportunities = []
        waiver_timing = None
        waiver_processing = None
        if league_id:
            waiver_processing = get_waiver_processing_info(bootstrap, next_gw)
            free_agents = analyze_free_agents(element_status, bootstrap, next_gw, fixtures)
            apply_club_change_notes(free_agents, current_gw)
            waiver_targets = free_agents[:10]
            transfer_suggestions = suggest_transfers(players, free_agents)
            transactions = client.get_transactions(league_id)
            transactions_feed = build_transactions_feed(transactions, league_details, bootstrap)[:20]
            trades = client.get_trades(league_id)
            trades_feed = build_trades_feed(trades, league_details, bootstrap)

            owned_by_entry = analyze_all_owned_players(element_status, bootstrap, next_gw, fixtures)
            for entry_players in owned_by_entry.values():
                apply_club_change_notes(entry_players, current_gw)
            trade_opportunities = find_trade_opportunities(owned_by_entry, entry_id, league_details)
            waiver_timing = build_waiver_timing_report(league_details, owned_by_entry, free_agents, entry_id)
            league_squads = build_league_squads(league_details, owned_by_entry)

        context = {
            "team_name": team_name,
            "current_gw": current_gw,
            "current_gw_label": current_gw_label,
            "next_gw": next_gw,
            "starters": starters,
            "bench": bench,
            "my_fixtures": my_fixtures,
            "my_fixtures_gw": fixtures_gw,
            "waiver_targets": waiver_targets,
            "transfer_suggestions": transfer_suggestions,
            "league_squads": league_squads,
            "transactions_feed": transactions_feed,
            "trades_feed": trades_feed,
            "trade_opportunities": trade_opportunities,
            "waiver_timing": waiver_timing,
            "waiver_processing": waiver_processing,
        }
    except Exception as e:
        error = str(e)

    return render_template("index.html", error=error, fdr_class=FDR_CLASS, **context)


if __name__ == "__main__":
    app.run(debug=True)
