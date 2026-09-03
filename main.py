"""
FPL Draft Helper – hovedprogram
Kjør: python main.py
"""

import os
import sys
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich import box
from rich.panel import Panel
from rich.text import Text

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
console = Console()


def get_cookie_header() -> str:
    cookie = os.getenv("PL_COOKIE_HEADER")
    if not cookie:
        console.print(
            Panel(
                "[bold red]Mangler PL_COOKIE_HEADER![/]\n\n"
                "Slik henter du den (fungerer også for Google-innlogging):\n"
                "1. Logg inn på [link=https://draft.premierleague.com]draft.premierleague.com[/link]\n"
                "2. Åpne DevTools (F12) → fanen Network\n"
                "3. Last siden på nytt, finn en forespørsel til [bold]api/game[/bold] eller [bold]api/element-status[/bold]\n"
                "4. Under Request Headers, kopier hele verdien av [bold]Cookie[/bold]\n"
                "5. Lim inn i [bold].env[/bold]-filen:\n\n"
                "   [green]PL_COOKIE_HEADER=din_verdi_her[/]",
                title="Oppsett kreves",
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
                "[bold red]Mangler PL_ENTRY_ID![/]\n\n"
                "Dette er lag-ID-en din, synlig i cookien som [bold]activeEntry[/bold], "
                "eller i URL-en når du er på 'My Team'-siden.\n\n"
                "Legg til i [bold].env[/bold]-filen:\n\n"
                "   [green]PL_ENTRY_ID=123456[/]",
                title="Oppsett kreves",
                border_style="red",
            )
        )
        sys.exit(1)
    return int(entry_id)


def print_squad_table(starters, bench):
    table = Table(
        title="📋 Anbefalt startlag",
        box=box.ROUNDED,
        show_lines=True,
        header_style="bold cyan",
    )
    table.add_column("Pos", style="dim", width=5)
    table.add_column("Spiller", min_width=22)
    table.add_column("Lag", width=6)
    table.add_column("Form", justify="right", width=6)
    table.add_column("Siste GW", justify="right", width=9)
    table.add_column("Neste kamp", min_width=18)
    table.add_column("Score", justify="right", width=7)
    table.add_column("Notat", min_width=28)

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

    # Benk
    bench_table = Table(title="🪑 Benk", box=box.SIMPLE, header_style="bold dim")
    bench_table.add_column("Pos", width=5)
    bench_table.add_column("Spiller", min_width=22)
    bench_table.add_column("Lag", width=6)
    bench_table.add_column("Neste kamp", min_width=18)
    bench_table.add_column("Notat", min_width=28)

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


def print_waiver_table(targets):
    if not targets:
        console.print("[dim]Ingen ledige spillere funnet.[/]")
        return

    table = Table(
        title="🔄 Waiver/Free Agent anbefalinger",
        box=box.ROUNDED,
        header_style="bold magenta",
    )
    table.add_column("#", width=3)
    table.add_column("Pos", width=5)
    table.add_column("Spiller", min_width=22)
    table.add_column("Lag", width=6)
    table.add_column("Form", justify="right", width=6)
    table.add_column("Total pts", justify="right", width=9)
    table.add_column("Neste kamp", min_width=18)
    table.add_column("Score", justify="right", width=7)
    table.add_column("Notat", min_width=25)

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
        console.print("[dim]Ingen bytter anbefales – laget ditt ser bra ut i alle posisjoner.[/]")
        return

    table = Table(
        title="🔁 Anbefalte bytter",
        box=box.ROUNDED,
        header_style="bold green",
    )
    table.add_column("Pos", width=5)
    table.add_column("Bytt ut", min_width=22)
    table.add_column("Hent inn", min_width=22)
    table.add_column("Gevinst", justify="right", width=8)

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
        title="🏆 Ligaoversikt",
        box=box.ROUNDED,
        header_style="bold blue",
    )
    table.add_column("#", width=3)
    table.add_column("Lag", min_width=18)
    table.add_column("Manager", min_width=16)
    table.add_column("Poeng", justify="right", width=7)
    table.add_column("Siste GW", justify="right", width=9)

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
        console.print("[dim]Ingen transaksjoner funnet i ligaen.[/]")
        return

    table = Table(
        title="📜 Waiver/transfer-historikk i ligaen",
        box=box.ROUNDED,
        header_style="bold yellow",
    )
    table.add_column("Dato", width=12)
    table.add_column("Lag", min_width=16)
    table.add_column("Type", width=11)
    table.add_column("Inn", min_width=20)
    table.add_column("Ut", min_width=20)
    table.add_column("Resultat", width=22)

    for tx in feed[:limit]:
        result_color = "green" if tx["result"] == "Godkjent" else "red"
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
        console.print("[dim]Ingen foreslåtte trades mellom managere akkurat nå.[/]")
        return

    table = Table(
        title="🤝 Foreslåtte trades mellom managere",
        box=box.ROUNDED,
        header_style="bold cyan",
    )
    table.add_column("Fra", min_width=18)
    table.add_column("Til", min_width=18)
    table.add_column("Gir", min_width=20)
    table.add_column("Får", min_width=20)
    table.add_column("Status", width=16)

    for t in feed:
        table.add_row(t["proposer"], t["counterpart"], t["gives"], t["receives"], t["state"])
    console.print(table)


def print_trade_opportunities(opportunities):
    if not opportunities:
        console.print("[dim]Fant ingen gode trade-muligheter akkurat nå.[/]")
        return

    table = Table(
        title="🔄 Trade-muligheter",
        box=box.ROUNDED,
        header_style="bold magenta",
    )
    table.add_column("Manager", min_width=18)
    table.add_column("Du gir", min_width=24)
    table.add_column("Du får", min_width=24)
    table.add_column("Gevinst", justify="right", width=8)

    for o in opportunities:
        give = ", ".join(f"{p.position} {p.name}" for p in o["give"])
        receive = ", ".join(f"{p.position} {p.name}" for p in o["receive"])
        table.add_row(o["other_manager"], give, receive, f"+{o['my_gain']}")
    console.print(table)
    console.print("[dim]NB: forslag til deg – den andre manageren må også vurdere det verdt det.[/]")


def print_waiver_timing(report):
    pick, total = report["my_waiver_pick"], report["total_entries"]
    if pick is None:
        console.print("[dim]Fant ikke waiver-prioritet.[/]")
        return

    console.print(f"[bold]Din waiver-prioritet denne runden:[/] #{pick} av {total} "
                  f"({'du velger tidlig' if pick <= total / 2 else 'du velger sent'})\n")

    table = Table(
        title="⏱️  Waiver-mål og risiko for å bli tatt før din tur",
        box=box.ROUNDED,
        header_style="bold red",
    )
    table.add_column("Spiller", min_width=22)
    table.add_column("Pos", width=5)
    table.add_column("Score", justify="right", width=7)
    table.add_column("Risiko", min_width=30)

    for t in report["targets"]:
        p = t["player"]
        risk = ", ".join(t["threatened_by"]) if t["threatened_by"] else "[dim]Lav risiko[/]"
        table.add_row(p.name, p.position, str(p.recommendation_score), risk)
    console.print(table)


def main():
    console.print(Panel("[bold green]FPL Draft Helper 🏆[/]", subtitle="Henter data...", expand=False))

    cookie_header = get_cookie_header()
    entry_id = get_entry_id()
    client = FPLDraftClient(cookie_header)

    # ── Hent grunndata ────────────────────────────────────────────────────────
    with console.status("Henter bootstrap-data..."):
        bootstrap = client.get_bootstrap()

    with console.status("Henter brukerinfo..."):
        entry_info = client.get_entry_info(entry_id)

    league_id = entry_info["entry"]["league_set"][0] if entry_info["entry"].get("league_set") else None
    team_name = entry_info["entry"].get("name", "Laget ditt")

    with console.status("Henter gameweek-info..."):
        current_gw = client.get_current_gameweek()
        next_gw = current_gw + 1

    console.print(f"\n[bold]Lag:[/] {team_name}  |  [bold]Siste GW:[/] {current_gw}  |  [bold]Neste GW:[/] {next_gw}\n")

    # ── Hent ligadata og picks ────────────────────────────────────────────────
    # element-status viser eierskap i realtid, i motsetning til get_my_picks() som
    # bare har data for gameweeks som allerede er låst/startet. Bruk den til laget
    # ditt når vi har en liga, så transfers du nettopp har gjort vises riktig.
    element_status, league_details = None, None
    if league_id:
        with console.status("Henter ligainfo..."):
            try:
                element_status = client.get_league_element_status(league_id)
                league_details = client.get_league_details(league_id)
            except Exception as e:
                console.print(f"[yellow]Kunne ikke hente ligadata: {e}[/]")

    with console.status(f"Henter laget for GW{next_gw}..."):
        if element_status:
            picks = build_current_squad_picks(element_status, entry_id)
        else:
            picks = client.get_my_picks(entry_id, current_gw)

    # ── Hent spillerhistorikk ────────────────────────────────────────────────
    player_ids = [p["element"] for p in picks["picks"]]
    player_histories = {}
    with console.status("Henter spillerhistorikk..."):
        for pid in player_ids:
            try:
                player_histories[pid] = client.get_player_history(pid)
            except Exception:
                player_histories[pid] = {}

    # ── Hent fixtures for neste GW (med FDR) ─────────────────────────────────
    with console.status("Henter fixtures..."):
        fixtures = client.get_fixtures_for_gameweek(next_gw)

    # ── Analyser laget ────────────────────────────────────────────────────────
    with console.status("Analyserer laget..."):
        players = analyze_squad(picks, bootstrap, next_gw, player_histories, fixtures)
        apply_club_change_notes(players, current_gw)
        starters, bench = recommend_starting_xi(players)

    # ── Vis resultater ────────────────────────────────────────────────────────
    console.rule(f"[bold cyan]GW{next_gw} – Anbefalt oppstilling[/]")
    print_squad_table(starters, bench)

    # ── Waiver-anbefalinger og ligaoversikt ──────────────────────────────────
    if league_id:
        free_agents = []
        if element_status:
            console.rule("[bold magenta]Ledige spillere du kan hente[/]")
            try:
                free_agents = analyze_free_agents(element_status, bootstrap, next_gw, fixtures)
                apply_club_change_notes(free_agents, current_gw)
                print_waiver_table(free_agents[:10])
            except Exception as e:
                console.print(f"[yellow]Kunne ikke regne ut waiver-anbefalinger: {e}[/]")

        if free_agents:
            console.rule("[bold green]Anbefalte bytter[/]")
            try:
                suggestions = suggest_transfers(players, free_agents)
                print_transfer_suggestions(suggestions)
            except Exception as e:
                console.print(f"[yellow]Kunne ikke regne ut byttanbefalinger: {e}[/]")

        if element_status and league_details:
            console.rule("[bold blue]Ligaoversikt[/]")
            try:
                overview = build_league_overview(league_details, element_status, bootstrap)
                print_league_overview(overview)
            except Exception as e:
                console.print(f"[yellow]Kunne ikke bygge ligaoversikt: {e}[/]")

        owned_by_entry = {}
        if element_status and league_details:
            console.rule("[bold magenta]Trade-muligheter[/]")
            try:
                owned_by_entry = analyze_all_owned_players(element_status, bootstrap, next_gw, fixtures)
                for entry_players in owned_by_entry.values():
                    apply_club_change_notes(entry_players, current_gw)
                opportunities = find_trade_opportunities(owned_by_entry, entry_id, league_details)
                print_trade_opportunities(opportunities)
            except Exception as e:
                console.print(f"[yellow]Kunne ikke regne ut trade-muligheter: {e}[/]")

        if free_agents and league_details:
            console.rule("[bold red]Waiver-timing[/]")
            try:
                report = build_waiver_timing_report(league_details, owned_by_entry, free_agents, entry_id)
                print_waiver_timing(report)
            except Exception as e:
                console.print(f"[yellow]Kunne ikke bygge waiver-timing-rapport: {e}[/]")

        if league_details:
            console.rule("[bold yellow]Waiver/transfer-historikk[/]")
            try:
                transactions = client.get_transactions(league_id)
                feed = build_transactions_feed(transactions, league_details, bootstrap)
                print_transactions_feed(feed)
            except Exception as e:
                console.print(f"[yellow]Kunne ikke hente transaksjonshistorikk: {e}[/]")

        if league_details:
            console.rule("[bold cyan]Foreslåtte trades[/]")
            try:
                trades = client.get_trades(league_id)
                trades_feed = build_trades_feed(trades, league_details, bootstrap)
                print_trades_feed(trades_feed)
            except Exception as e:
                console.print(f"[yellow]Kunne ikke hente trades: {e}[/]")
    else:
        console.print("[dim]Ingen liga funnet – hopper over waiver- og ligadata.[/]")

    console.print("\n[dim]Tips: Sjekk alltid lagoppsett og skader på fantasyfootballscout.co.uk før deadline![/]\n")


if __name__ == "__main__":
    main()
