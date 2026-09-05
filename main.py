"""
FPL Draft Helper - main program
Run: python main.py
"""

import os
import sys
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich import box
from rich.panel import Panel
from rich.text import Text

from fpl_client import FPLDraftClient
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
    get_waiver_processing_info,
    is_gameweek_finished,
    build_my_fixtures,
    apply_club_change_notes,
)

load_dotenv()
console = Console()


def get_cookie_header() -> str:
    cookie = os.getenv("PL_COOKIE_HEADER")
    if not cookie:
        console.print(
            Panel(
                "[bold red]Missing PL_COOKIE_HEADER![/]\n\n"
                "How to get it (also works for Google login):\n"
                "1. Log in at [link=https://draft.premierleague.com]draft.premierleague.com[/link]\n"
                "2. Open DevTools (F12) → the Network tab\n"
                "3. Reload the page, find a request to [bold]api/game[/bold] or [bold]api/element-status[/bold]\n"
                "4. Under Request Headers, copy the entire value of [bold]Cookie[/bold]\n"
                "5. Paste it into the [bold].env[/bold] file:\n\n"
                "   [green]PL_COOKIE_HEADER=your_value_here[/]",
                title="Setup required",
                border_style="red",
            )
        )
        sys.exit(1)
    return cookie


def get_entry_id() -> int:
    entry_id = os.getenv("PL_ENTRY_ID")
    if not entry_id:
        console.print(
            Panel(
                "[bold red]Missing PL_ENTRY_ID![/]\n\n"
                "This is your team ID, visible in the cookie as [bold]activeEntry[/bold], "
                "or in the URL when you're on the 'My Team' page.\n\n"
                "Add it to the [bold].env[/bold] file:\n\n"
                "   [green]PL_ENTRY_ID=123456[/]",
                title="Setup required",
                border_style="red",
            )
        )
        sys.exit(1)
    return int(entry_id)


def print_squad_table(starters, bench):
    table = Table(
        title="📋 Recommended starting lineup",
        box=box.ROUNDED,
        show_lines=True,
        header_style="bold cyan",
    )
    table.add_column("Pos", style="dim", width=5)
    table.add_column("Player", min_width=22)
    table.add_column("Team", width=6)
    table.add_column("Form", justify="right", width=6)
    table.add_column("Last GW", justify="right", width=9)
    table.add_column("Next match", min_width=18)
    table.add_column("Score", justify="right", width=7)
    table.add_column("Note", min_width=28)

    for p in starters:
        name = p.name
        fdr_color = ["", "green", "green", "yellow", "red", "red"][p.next_fixture_fdr]
        fixture = f"[{fdr_color}]{p.fixture_label}[/]"
        score_color = "green" if p.recommendation_score >= 20 else ("yellow" if p.recommendation_score >= 12 else "red")
        table.add_row(
            p.position,
            name,
            p.team,
            str(p.form),
            str(p.points_last_gw),
            fixture,
            f"[{score_color}]{p.recommendation_score}[/]",
            p.recommendation_note,
        )

    console.print(table)

    # Bench
    bench_table = Table(title="🪑 Bench", box=box.SIMPLE, header_style="bold dim")
    bench_table.add_column("Pos", width=5)
    bench_table.add_column("Player", min_width=22)
    bench_table.add_column("Team", width=6)
    bench_table.add_column("Next match", min_width=18)
    bench_table.add_column("Note", min_width=28)

    for p in bench:
        fdr_color = ["", "green", "green", "yellow", "red", "red"][p.next_fixture_fdr]
        bench_table.add_row(
            p.position,
            p.name,
            p.team,
            f"[{fdr_color}]{p.fixture_label}[/]",
            p.recommendation_note,
        )
    console.print(bench_table)


def print_fixtures_table(my_fixtures):
    if not my_fixtures:
        console.print("[dim]No fixtures found involving your players.[/]")
        return

    table = Table(
        title="📅 Fixtures involving your players (Norwegian time)",
        box=box.ROUNDED,
        header_style="bold blue",
    )
    table.add_column("Kickoff", min_width=18)
    table.add_column("Match", min_width=10)
    table.add_column("Your players", min_width=30)

    for f in my_fixtures:
        kickoff = f"✅ {f['kickoff_label']}" if f["played"] else f["kickoff_label"]
        table.add_row(kickoff, f"{f['home']} v {f['away']}", ", ".join(f["my_players"]))
    console.print(table)


def print_waiver_table(targets):
    if not targets:
        console.print("[dim]No free agents found.[/]")
        return

    table = Table(
        title="🔄 Waiver/Free Agent recommendations",
        box=box.ROUNDED,
        header_style="bold magenta",
    )
    table.add_column("#", width=3)
    table.add_column("Pos", width=5)
    table.add_column("Player", min_width=22)
    table.add_column("Team", width=6)
    table.add_column("Form", justify="right", width=6)
    table.add_column("Total pts", justify="right", width=9)
    table.add_column("Next match", min_width=18)
    table.add_column("Score", justify="right", width=7)
    table.add_column("Note", min_width=25)

    for i, p in enumerate(targets, 1):
        fdr_color = ["", "green", "green", "yellow", "red", "red"][p.next_fixture_fdr]
        score_color = "green" if p.recommendation_score >= 20 else ("yellow" if p.recommendation_score >= 12 else "red")
        table.add_row(
            str(i),
            p.position,
            p.name,
            p.team,
            str(p.form),
            str(p.total_points),
            f"[{fdr_color}]{p.fixture_label}[/]",
            f"[{score_color}]{p.recommendation_score}[/]",
            p.recommendation_note,
        )
    console.print(table)


def print_transfer_suggestions(suggestions):
    if not suggestions:
        console.print("[dim]No transfers recommended – your squad looks good in every position.[/]")
        return

    table = Table(
        title="🔁 Recommended transfers",
        box=box.ROUNDED,
        header_style="bold green",
    )
    table.add_column("Pos", width=5)
    table.add_column("Drop", min_width=22)
    table.add_column("Add", min_width=22)
    table.add_column("Gain", justify="right", width=8)

    for s in suggestions:
        table.add_row(
            s["position"],
            f"{s['drop'].name} ({s['drop'].team}) – score {s['drop'].recommendation_score}",
            f"{s['add'].name} ({s['add'].team}) – score {s['add'].recommendation_score}",
            f"+{s['score_gain']}",
        )
    console.print(table)


def print_league_overview(overview):
    table = Table(
        title="🏆 League overview",
        box=box.ROUNDED,
        header_style="bold blue",
    )
    table.add_column("#", width=3)
    table.add_column("Team", min_width=18)
    table.add_column("Manager", min_width=16)
    table.add_column("Points", justify="right", width=7)
    table.add_column("Last GW", justify="right", width=9)

    for entry in overview:
        team_label = entry["team_name"]
        table.add_row(
            str(entry["rank"]),
            team_label,
            entry["manager"],
            str(entry["total_points"]),
            str(entry["event_points"]),
        )
    console.print(table)

    console.print()
    for entry in overview:
        squad_line = ", ".join(f"{p['position']} {p['name']}" for p in entry["squad"])
        console.print(f"[bold]{entry['team_name']}[/] ({entry['manager']}): {squad_line}\n")


def print_transactions_feed(feed, limit=15):
    if not feed:
        console.print("[dim]No transactions found in the league.[/]")
        return

    table = Table(
        title="📜 Waiver/transfer history in the league",
        box=box.ROUNDED,
        header_style="bold yellow",
    )
    table.add_column("Date", width=12)
    table.add_column("Team", min_width=16)
    table.add_column("Type", width=11)
    table.add_column("In", min_width=20)
    table.add_column("Out", min_width=20)
    table.add_column("Result", width=22)

    for tx in feed[:limit]:
        result_color = "green" if tx["result"] == "Approved" else "red"
        table.add_row(
            tx["added"][:10],
            tx["team_name"],
            tx["kind"],
            tx["player_in"],
            tx["player_out"],
            f"[{result_color}]{tx['result']}[/]",
        )
    console.print(table)


def print_trades_feed(feed):
    if not feed:
        console.print("[dim]No trades proposed between managers right now.[/]")
        return

    table = Table(
        title="🤝 Proposed trades between managers",
        box=box.ROUNDED,
        header_style="bold cyan",
    )
    table.add_column("From", min_width=18)
    table.add_column("To", min_width=18)
    table.add_column("Gives", min_width=20)
    table.add_column("Receives", min_width=20)
    table.add_column("Status", width=16)

    for t in feed:
        table.add_row(t["proposer"], t["counterpart"], t["gives"], t["receives"], t["state"])
    console.print(table)


def print_trade_opportunities(opportunities):
    if not opportunities:
        console.print("[dim]No good trade opportunities found right now.[/]")
        return

    table = Table(
        title="🔄 Trade opportunities",
        box=box.ROUNDED,
        header_style="bold magenta",
    )
    table.add_column("Manager", min_width=18)
    table.add_column("You give", min_width=24)
    table.add_column("You get", min_width=24)
    table.add_column("Gain", justify="right", width=8)

    for o in opportunities:
        give = ", ".join(f"{p.position} {p.name}" for p in o["give"])
        receive = ", ".join(f"{p.position} {p.name}" for p in o["receive"])
        table.add_row(o["other_manager"], give, receive, f"+{o['my_gain']}")
    console.print(table)
    console.print("[dim]NB: a suggestion for you – the other manager also has to consider it worth it.[/]")


def print_waiver_timing(report):
    pick, total = report["my_waiver_pick"], report["total_entries"]
    if pick is None:
        console.print("[dim]Couldn't find waiver priority.[/]")
        return

    console.print(f"[bold]Your waiver priority this round:[/] #{pick} of {total} "
                  f"({'you pick early' if pick <= total / 2 else 'you pick late'})\n")

    table = Table(
        title="⏱️  Waiver targets and risk of being taken before your turn",
        box=box.ROUNDED,
        header_style="bold red",
    )
    table.add_column("Player", min_width=22)
    table.add_column("Pos", width=5)
    table.add_column("Score", justify="right", width=7)
    table.add_column("Risk", min_width=30)

    for t in report["targets"]:
        p = t["player"]
        risk = ", ".join(t["threatened_by"]) if t["threatened_by"] else "[dim]Low risk[/]"
        table.add_row(p.name, p.position, str(p.recommendation_score), risk)
    console.print(table)


def main():
    console.print(Panel("[bold green]FPL Draft Helper 🏆[/]", subtitle="Fetching data...", expand=False))

    cookie_header = get_cookie_header()
    entry_id = get_entry_id()
    client = FPLDraftClient(cookie_header)

    # ── Fetch base data ──────────────────────────────────────────────────────
    with console.status("Fetching bootstrap data..."):
        bootstrap = client.get_bootstrap()

    with console.status("Fetching user info..."):
        entry_info = client.get_entry_info(entry_id)

    league_id = entry_info["entry"]["league_set"][0] if entry_info["entry"].get("league_set") else None
    team_name = entry_info["entry"].get("name", "Your team")

    with console.status("Fetching gameweek info..."):
        current_gw = client.get_current_gameweek()
        next_gw = current_gw + 1
        current_gw_label = "Last GW" if is_gameweek_finished(bootstrap, current_gw) else "Current GW"

    console.print(f"\n[bold]Team:[/] {team_name}  |  [bold]{current_gw_label}:[/] {current_gw}  |  [bold]Next GW:[/] {next_gw}\n")

    # ── Fetch league data and picks ──────────────────────────────────────────
    # element-status shows ownership in real time, unlike get_my_picks() which
    # only has data for gameweeks that have already locked/started. Use it for
    # your team when we have a league, so transfers you just made show up correctly.
    element_status, league_details = None, None
    if league_id:
        with console.status("Fetching league info..."):
            try:
                element_status = client.get_league_element_status(league_id)
                league_details = client.get_league_details(league_id)
            except Exception as e:
                console.print(f"[yellow]Could not fetch league data: {e}[/]")

    with console.status(f"Fetching your team for GW{next_gw}..."):
        if element_status:
            picks = build_current_squad_picks(element_status, entry_id)
        else:
            picks = client.get_my_picks(entry_id, current_gw)

    # ── Fetch player history ─────────────────────────────────────────────────
    player_ids = [p["element"] for p in picks["picks"]]
    player_histories = {}
    with console.status("Fetching player history..."):
        for pid in player_ids:
            try:
                player_histories[pid] = client.get_player_history(pid)
            except Exception:
                player_histories[pid] = {}

    # ── Fetch fixtures for the next GW (with FDR) ────────────────────────────
    with console.status("Fetching fixtures..."):
        fixtures = client.get_fixtures_for_gameweek(next_gw)

    # ── Analyze the squad ────────────────────────────────────────────────────
    with console.status("Analyzing your squad..."):
        players = analyze_squad(picks, bootstrap, next_gw, player_histories, fixtures)
        apply_club_change_notes(players, current_gw)
        starters, bench = recommend_starting_xi(players)

        # While the current gameweek is still being played, show its remaining
        # fixtures (not next_gw's) - e.g. don't jump ahead to next week's
        # fixtures while today's matches haven't been played yet.
        if current_gw_label == "Current GW":
            fixtures_gw = current_gw
            fixtures_for_tab = client.get_fixtures_for_gameweek(current_gw)
            # current_gw is already locked, so get_my_picks has the bench
            # arrangement you actually set for it - not just our recommendation.
            locked_picks = client.get_my_picks(entry_id, current_gw)
            bench_ids = {p["element"] for p in locked_picks["picks"] if p["position"] > 11}
        else:
            fixtures_gw = next_gw
            fixtures_for_tab = fixtures
            bench_ids = {p.id for p in bench}
        my_fixtures = build_my_fixtures(fixtures_for_tab, fixtures_gw, bootstrap, players, player_histories, bench_ids)

    # ── Show results ─────────────────────────────────────────────────────────
    console.rule(f"[bold cyan]GW{next_gw} – Recommended lineup[/]")
    print_squad_table(starters, bench)

    console.rule(f"[bold blue]GW{fixtures_gw} – Fixtures[/]")
    print_fixtures_table(my_fixtures)

    # ── Waiver recommendations and league overview ───────────────────────────
    if league_id:
        free_agents = []
        if element_status:
            console.rule("[bold magenta]Free agents you can pick up[/]")
            waiver_processing = get_waiver_processing_info(bootstrap, next_gw)
            if waiver_processing:
                status = "were processed" if waiver_processing["has_passed"] else "will be processed"
                console.print(f"[dim]⏰ Waivers for GW{waiver_processing['gameweek']} {status}: "
                               f"{waiver_processing['label']}[/]\n")
            try:
                free_agents = analyze_free_agents(element_status, bootstrap, next_gw, fixtures)
                apply_club_change_notes(free_agents, current_gw)
                print_waiver_table(free_agents[:10])
            except Exception as e:
                console.print(f"[yellow]Could not calculate waiver recommendations: {e}[/]")

        if free_agents:
            console.rule("[bold green]Recommended transfers[/]")
            try:
                suggestions = suggest_transfers(players, free_agents)
                print_transfer_suggestions(suggestions)
            except Exception as e:
                console.print(f"[yellow]Could not calculate transfer recommendations: {e}[/]")

        if element_status and league_details:
            console.rule("[bold blue]League overview[/]")
            try:
                overview = build_league_overview(league_details, element_status, bootstrap)
                print_league_overview(overview)
            except Exception as e:
                console.print(f"[yellow]Could not build league overview: {e}[/]")

        owned_by_entry = {}
        if element_status and league_details:
            console.rule("[bold magenta]Trade opportunities[/]")
            try:
                owned_by_entry = analyze_all_owned_players(element_status, bootstrap, next_gw, fixtures)
                for entry_players in owned_by_entry.values():
                    apply_club_change_notes(entry_players, current_gw)
                opportunities = find_trade_opportunities(owned_by_entry, entry_id, league_details)
                print_trade_opportunities(opportunities)
            except Exception as e:
                console.print(f"[yellow]Could not calculate trade opportunities: {e}[/]")

        if free_agents and league_details:
            console.rule("[bold red]Waiver timing[/]")
            try:
                report = build_waiver_timing_report(league_details, owned_by_entry, free_agents, entry_id)
                print_waiver_timing(report)
            except Exception as e:
                console.print(f"[yellow]Could not build waiver timing report: {e}[/]")

        if league_details:
            console.rule("[bold yellow]Waiver/transfer history[/]")
            try:
                transactions = client.get_transactions(league_id)
                feed = build_transactions_feed(transactions, league_details, bootstrap)
                print_transactions_feed(feed)
            except Exception as e:
                console.print(f"[yellow]Could not fetch transaction history: {e}[/]")

        if league_details:
            console.rule("[bold cyan]Proposed trades[/]")
            try:
                trades = client.get_trades(league_id)
                trades_feed = build_trades_feed(trades, league_details, bootstrap)
                print_trades_feed(trades_feed)
            except Exception as e:
                console.print(f"[yellow]Could not fetch trades: {e}[/]")
    else:
        console.print("[dim]No league found – skipping waiver and league data.[/]")

    console.print("\n[dim]Tip: Always check team news and injuries on fantasyfootballscout.co.uk before the deadline![/]\n")


if __name__ == "__main__":
    main()
