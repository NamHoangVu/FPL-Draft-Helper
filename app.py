"""
FPL Draft Helper – nettside
Kjør: python app.py, åpne http://127.0.0.1:5000
"""

import os
from dotenv import load_dotenv
from flask import Flask, render_template

from api import FPLDraftClient
from analyzer import (
    build_current_squad_picks,
    analyze_squad,
    recommend_starting_xi,
    analyze_free_agents,
    analyze_all_owned_players,
    suggest_transfers,
    build_league_overview,
    build_transactions_feed,
    build_trades_feed,
    find_trade_opportunities,
    build_waiver_timing_report,
    apply_club_change_notes,
)

load_dotenv()
app = Flask(__name__)

FDR_CLASS = {1: "fdr-1", 2: "fdr-2", 3: "fdr-3", 4: "fdr-4", 5: "fdr-5"}


def get_client() -> FPLDraftClient:
    cookie = os.getenv("PL_COOKIE_HEADER")
    if not cookie:
        raise RuntimeError("Mangler PL_COOKIE_HEADER i .env")
    return FPLDraftClient(cookie)


def get_entry_id() -> int:
    entry_id = os.getenv("PL_ENTRY_ID")
    if not entry_id:
        raise RuntimeError("Mangler PL_ENTRY_ID i .env")
    return int(entry_id)


@app.route("/")
def index():
    error = None
    context = {}

    try:
        client = get_client()
        entry_id = get_entry_id()

        bootstrap = client.get_bootstrap()
        entry_info = client.get_entry_info(entry_id)
        league_id = entry_info["entry"]["league_set"][0] if entry_info["entry"].get("league_set") else None
        team_name = entry_info["entry"].get("name", "Laget ditt")

        current_gw = client.get_current_gameweek()
        next_gw = current_gw + 1

        # element-status viser eierskap i realtid, i motsetning til get_my_picks() som
        # bare har data for gameweeks som allerede er låst/startet. Bruk den til laget
        # ditt når vi har en liga, så transfers du nettopp har gjort vises riktig.
        element_status, league_details = None, None
        if league_id:
            element_status = client.get_league_element_status(league_id)
            league_details = client.get_league_details(league_id)

        if element_status:
            picks = build_current_squad_picks(element_status, entry_id)
        else:
            picks = client.get_my_picks(entry_id, current_gw)
        player_ids = [p["element"] for p in picks["picks"]]
        player_histories = {}
        for pid in player_ids:
            try:
                player_histories[pid] = client.get_player_history(pid)
            except Exception:
                player_histories[pid] = {}

        fixtures = client.get_fixtures_for_gameweek(next_gw)

        players = analyze_squad(picks, bootstrap, next_gw, player_histories, fixtures)
        apply_club_change_notes(players, current_gw)
        starters, bench = recommend_starting_xi(players)

        waiver_targets = []
        transfer_suggestions = []
        league_overview = []
        transactions_feed = []
        trades_feed = []
        trade_opportunities = []
        waiver_timing = None
        if league_id:
            free_agents = analyze_free_agents(element_status, bootstrap, next_gw, fixtures)
            apply_club_change_notes(free_agents, current_gw)
            waiver_targets = free_agents[:10]
            transfer_suggestions = suggest_transfers(players, free_agents)
            league_overview = build_league_overview(league_details, element_status, bootstrap)
            transactions = client.get_transactions(league_id)
            transactions_feed = build_transactions_feed(transactions, league_details, bootstrap)[:20]
            trades = client.get_trades(league_id)
            trades_feed = build_trades_feed(trades, league_details, bootstrap)

            owned_by_entry = analyze_all_owned_players(element_status, bootstrap, next_gw, fixtures)
            for entry_players in owned_by_entry.values():
                apply_club_change_notes(entry_players, current_gw)
            trade_opportunities = find_trade_opportunities(owned_by_entry, entry_id, league_details)
            waiver_timing = build_waiver_timing_report(league_details, owned_by_entry, free_agents, entry_id)

        context = {
            "team_name": team_name,
            "current_gw": current_gw,
            "next_gw": next_gw,
            "starters": starters,
            "bench": bench,
            "waiver_targets": waiver_targets,
            "transfer_suggestions": transfer_suggestions,
            "league_overview": league_overview,
            "transactions_feed": transactions_feed,
            "trades_feed": trades_feed,
            "trade_opportunities": trade_opportunities,
            "waiver_timing": waiver_timing,
        }
    except Exception as e:
        error = str(e)

    return render_template("index.html", error=error, fdr_class=FDR_CLASS, **context)


if __name__ == "__main__":
    app.run(debug=True)
