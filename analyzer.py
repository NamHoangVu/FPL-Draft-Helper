"""
FPL Draft Analyzer
Analyzes your squad and gives recommendations for the next gameweek.
"""

import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

NORWAY_TZ = ZoneInfo("Europe/Oslo")

# Catches FPL's news text for players who have left the club,
# e.g. "Has joined Al Hilal permanently" or "Has joined Como on loan..."
NEW_CLUB_PATTERN = re.compile(r"[Jj]oined\s+(.+?)(?:\s+on loan|\s+permanently|\s*$)")


def extract_new_club(news: str) -> Optional[str]:
    """Finds the new club name from FPL's news text, if the player has left the club."""
    if not news:
        return None
    match = NEW_CLUB_PATTERN.search(news)
    return match.group(1) if match else None


# Fixture Difficulty Rating: 1 = easiest, 5 = hardest
# Used to score fixtures for the next gameweek
FDR_LABELS = {1: "Very easy ✅", 2: "Easy ✅", 3: "Medium ⚠️", 4: "Hard ❌", 5: "Very hard ❌"}


@dataclass
class PlayerAnalysis:
    id: int
    name: str
    team: str
    position: str          # GKP, DEF, MID, FWD
    is_starter: bool
    bench_position: Optional[int]  # None if starter

    # Form and points
    total_points: int
    form: float            # average over the last 5 matches
    points_last_gw: int
    minutes_last_gw: int

    # Next match
    next_opponent: str
    next_fixture_fdr: int  # 1-5
    next_is_home: bool

    # Status
    status: str            # 'a' = available, 'd' = doubt, 'u' = unavailable
    chance_of_playing: Optional[int]  # 0-100
    news: str = ""         # FPL's news text, e.g. injury or club transfer

    # Score calculated by the analyzer
    recommendation_score: float = 0.0
    recommendation_note: str = ""

    @property
    def fixture_label(self) -> str:
        home_away = "H" if self.next_is_home else "A"
        return f"{self.next_opponent} ({home_away}) FDR:{self.next_fixture_fdr}"

    @property
    def status_emoji(self) -> str:
        if self.status == "a":
            return "✅"
        elif self.status == "d":
            pct = self.chance_of_playing or 50
            return f"⚠️ {pct}%"
        return "❌"


def build_current_squad_picks(league_element_status: dict, entry_id: int) -> dict:
    """
    Builds a picks object (same shape as get_my_picks()) from league/element-status.

    get_my_picks() fetches a gameweek's *locked* lineup, which doesn't exist until that
    gameweek has started – element-status instead shows ownership in real time, so this
    picks up transfers/waivers you've made since the last locked gameweek.
    """
    picks = [
        {"element": status["element"], "position": i}
        for i, status in enumerate(
            (s for s in league_element_status.get("element_status", []) if s.get("owner") == entry_id),
            start=1,
        )
    ]
    return {"picks": picks}


def build_player_lookup(bootstrap: dict) -> dict:
    """Builds a dict of player_id -> player data from bootstrap."""
    return {p["id"]: p for p in bootstrap["elements"]}


def build_team_lookup(bootstrap: dict) -> dict:
    """Builds a dict of team_id -> team data."""
    return {t["id"]: t for t in bootstrap["teams"]}


def get_waiver_processing_info(bootstrap: dict, gameweek: int) -> Optional[dict]:
    """
    Returns when waivers for the given gameweek get processed by FPL, based on
    bootstrap's events data (event.waivers_time). Returns None if the gameweek
    or its waivers_time isn't found (e.g. league doesn't use waivers).
    """
    events = bootstrap.get("events", {}).get("data", [])
    event = next((e for e in events if e.get("id") == gameweek), None)
    if not event or not event.get("waivers_time"):
        return None

    waivers_time_utc = datetime.fromisoformat(event["waivers_time"].replace("Z", "+00:00"))
    local_time = waivers_time_utc.astimezone()
    now = datetime.now(local_time.tzinfo)
    return {
        "gameweek": gameweek,
        "label": local_time.strftime("%a %d %b, %H:%M"),
        "has_passed": local_time < now,
    }


def is_gameweek_finished(bootstrap: dict, gameweek: int) -> bool:
    """
    Whether the given gameweek's matches have all finished, per bootstrap's events data.

    get_current_gameweek() returns the gameweek as soon as its deadline passes and
    squads lock - not once it's actually been played - so this is needed to tell
    a genuinely finished gameweek apart from one that's still live or upcoming.
    """
    events = bootstrap.get("events", {}).get("data", [])
    event = next((e for e in events if e.get("id") == gameweek), None)
    return bool(event and event.get("finished"))


def get_next_fixtures(fixtures: list, gameweek: int) -> dict:
    """
    Returns a dict: team_id -> list of (opponent_team_id, is_home, fdr)
    for the given gameweek.

    fixtures: list of fixtures (incl. FDR) for this gameweek,
    from FPLDraftClient.get_fixtures_for_gameweek().
    """
    fixtures_by_team: dict = {}
    for fixture in fixtures:
        if fixture["event"] != gameweek:
            continue
        h = fixture["team_h"]
        a = fixture["team_a"]
        h_fdr = fixture["team_h_difficulty"]
        a_fdr = fixture["team_a_difficulty"]

        fixtures_by_team.setdefault(h, []).append((a, True, h_fdr))
        fixtures_by_team.setdefault(a, []).append((h, False, a_fdr))

    return fixtures_by_team


def build_my_fixtures(
    fixtures: list,
    gameweek: int,
    bootstrap: dict,
    players: list["PlayerAnalysis"],
    player_histories: Optional[dict] = None,
    bench_ids: Optional[set] = None,
) -> list[dict]:
    """
    Returns the gameweek's fixtures that involve at least one team you have a
    player in, with kickoff time converted to Norwegian time, sorted chronologically.

    Once a fixture has been played, it's flagged as finished and each of your
    players' points in that match are looked up from player_histories (dict of
    player_id -> get_player_history()). bench_ids flags players who were on
    your FPL Draft bench (not the real-life match squad) for this gameweek.
    """
    team_lookup = build_team_lookup(bootstrap)
    my_teams = {p.team for p in players}
    player_histories = player_histories or {}
    bench_ids = bench_ids or set()

    entries = []
    for fixture in fixtures:
        if fixture["event"] != gameweek:
            continue
        home = team_lookup.get(fixture["team_h"], {}).get("short_name", "?")
        away = team_lookup.get(fixture["team_a"], {}).get("short_name", "?")
        if home not in my_teams and away not in my_teams:
            continue

        kickoff = fixture.get("kickoff_time")
        local_dt = (
            datetime.fromisoformat(kickoff.replace("Z", "+00:00")).astimezone(NORWAY_TZ)
            if kickoff else None
        )
        # finished_provisional flips true right after full-time - finished only
        # once bonus points are confirmed, which can lag by up to an hour.
        played = bool(fixture.get("finished_provisional"))

        my_players = []
        for p in players:
            if p.team not in (home, away):
                continue
            details = []
            if played:
                history = player_histories.get(p.id, {}).get("history", [])
                match = next((h for h in history if h.get("event") == gameweek), None)
                pts = match.get("total_points", 0) if match else 0
                details.append(f"{pts} pts")
            if p.id in bench_ids:
                details.append("🪑")
            label = f"{p.name} ({', '.join(details)})" if details else p.name
            my_players.append(label)
        my_players.sort()

        entries.append((
            local_dt or datetime.max.replace(tzinfo=NORWAY_TZ),
            {
                "home": home,
                "away": away,
                "kickoff_label": local_dt.strftime("%a %d %b, %H:%M") if local_dt else "TBC",
                "played": played,
                "my_players": my_players,
            },
        ))

    entries.sort(key=lambda e: e[0])
    return [entry for _, entry in entries]


def calculate_recommendation_score(player: PlayerAnalysis) -> float:
    """
    Simple scoring model:
    - Form (average of the last 5 GWs) is weighted highest
    - Fixture difficulty is subtracted
    - Minutes in the last match indicate whether the player actually plays
    - Status penalty for injured/doubtful players
    """
    score = 0.0

    # Form: 0-10 points -> weight 40%
    score += min(player.form, 15.0) * 2.0

    # FDR: 1=good, 5=bad -> invert
    fdr_bonus = (6 - player.next_fixture_fdr) * 3.0  # 15 for FDR=1, 3 for FDR=5
    score += fdr_bonus

    # Minutes in the last match: rewards players who actually start
    if player.minutes_last_gw >= 60:
        score += 5.0
    elif player.minutes_last_gw >= 30:
        score += 2.0
    elif player.minutes_last_gw == 0:
        score -= 5.0

    # Points in the last GW (momentum)
    score += min(player.points_last_gw, 20) * 0.3

    # Penalty for injury/doubt
    if player.status == "u":
        score -= 20.0
    elif player.status == "d":
        pct = player.chance_of_playing or 50
        score -= (100 - pct) * 0.1

    return round(score, 2)


def generate_recommendation_note(player: PlayerAnalysis) -> str:
    notes = []

    if player.status == "u":
        new_club = extract_new_club(player.news)
        if new_club:
            notes.append(f"❌ No longer in the Premier League (moved to {new_club})")
        else:
            notes.append("❌ Not available")
        return " | ".join(notes)
    if player.status == "d":
        notes.append(f"⚠️ Doubtful ({player.chance_of_playing}%)")

    if player.next_fixture_fdr <= 2:
        notes.append("✅ Great fixture")
    elif player.next_fixture_fdr == 3:
        notes.append("⚠️ Medium fixture")
    else:
        notes.append("❌ Tough fixture")

    if player.form >= 8:
        notes.append("🔥 In top form")
    elif player.form >= 5:
        notes.append("📈 OK form")
    elif player.form < 3:
        notes.append("📉 Poor form")

    if player.minutes_last_gw == 0:
        notes.append("⚠️ Didn't play last GW")

    return " | ".join(notes)


def analyze_squad(
    picks: dict,
    bootstrap: dict,
    next_gw: int,
    player_histories: dict,
    fixtures: list,
) -> list[PlayerAnalysis]:
    """
    Analyzes all 15 players in your squad.

    picks: from get_my_picks()
    bootstrap: from get_bootstrap()
    next_gw: next gameweek number
    player_histories: dict of player_id -> get_player_history()
    fixtures: from get_fixtures_for_gameweek(next_gw), incl. FDR
    """
    player_lookup = build_player_lookup(bootstrap)
    team_lookup = build_team_lookup(bootstrap)
    next_fixtures = get_next_fixtures(fixtures, next_gw)

    # FPL position codes: 1=GKP, 2=DEF, 3=MID, 4=FWD
    pos_map = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

    # While a gameweek is still in progress, FPL already adds a placeholder
    # history entry for it (0 minutes) for any player whose match hasn't
    # kicked off yet. Use the last *completed* gameweek instead, so those
    # players don't wrongly show as "didn't play last GW".
    current_gw = next_gw - 1
    last_completed_gw = current_gw if is_gameweek_finished(bootstrap, current_gw) else current_gw - 1

    results = []
    for pick in picks["picks"]:
        pid = pick["element"]
        p = player_lookup.get(pid)
        if not p:
            continue

        team_id = p["team"]
        team_name = team_lookup.get(team_id, {}).get("short_name", "?")

        # Next fixture
        team_fixtures = next_fixtures.get(team_id, [])
        if team_fixtures:
            opp_id, is_home, fdr = team_fixtures[0]
            opp_name = team_lookup.get(opp_id, {}).get("short_name", "?")
        else:
            opp_name, is_home, fdr = "Blank", False, 3

        # History: get form and the last completed match
        history = player_histories.get(pid, {})
        past_matches = history.get("history", [])

        points_last_gw = 0
        minutes_last_gw = 0
        last = next((m for m in reversed(past_matches) if m.get("event", 0) <= last_completed_gw), None)
        if last:
            points_last_gw = last.get("total_points", 0)
            minutes_last_gw = last.get("minutes", 0)

        # Form: average of the last 5 matches (FPL provides this directly)
        try:
            form = float(p.get("form", 0))
        except (ValueError, TypeError):
            form = 0.0

        analysis = PlayerAnalysis(
            id=pid,
            name=f"{p['first_name']} {p['second_name']}",
            team=team_name,
            position=pos_map.get(p["element_type"], "?"),
            is_starter=pick["position"] <= 11,
            bench_position=pick["position"] - 11 if pick["position"] > 11 else None,
            total_points=p.get("total_points", 0),
            form=form,
            points_last_gw=points_last_gw,
            minutes_last_gw=minutes_last_gw,
            next_opponent=opp_name,
            next_fixture_fdr=fdr,
            next_is_home=is_home,
            status=p.get("status", "a"),
            chance_of_playing=p.get("chance_of_playing_this_round"),
            news=p.get("news", ""),
        )

        analysis.recommendation_score = calculate_recommendation_score(analysis)
        analysis.recommendation_note = generate_recommendation_note(analysis)
        results.append(analysis)

    return results


def recommend_starting_xi(players: list[PlayerAnalysis]) -> tuple[list, list]:
    """
    Recommends a starting lineup based on scores,
    respecting position requirements (1 GKP, min 3 DEF, min 2 FWD, max 5 DEF/MID/FWD).

    Returns (starters, bench) sorted by score.
    """
    # Separate out injured/unavailable
    available = [p for p in players if p.status != "u"]
    unavailable = [p for p in players if p.status == "u"]

    # Sort by score
    by_pos: dict[str, list] = {"GKP": [], "DEF": [], "MID": [], "FWD": []}
    for p in sorted(available, key=lambda x: x.recommendation_score, reverse=True):
        by_pos[p.position].append(p)

    starters = []
    bench = []

    # 1 keeper
    if by_pos["GKP"]:
        starters.append(by_pos["GKP"][0])
        bench.extend(by_pos["GKP"][1:])

    # At least 3 defenders
    starters.extend(by_pos["DEF"][:3])
    remaining_def = by_pos["DEF"][3:]

    # At least 2 forwards
    starters.extend(by_pos["FWD"][:2])
    remaining_fwd = by_pos["FWD"][2:]

    # Fill the remaining 5 outfield slots with the best available
    remaining_slots = 11 - len(starters)
    extras = sorted(
        remaining_def + by_pos["MID"] + remaining_fwd,
        key=lambda x: x.recommendation_score,
        reverse=True,
    )
    starters.extend(extras[:remaining_slots])
    bench.extend(extras[remaining_slots:])
    bench.extend(unavailable)

    return starters, bench


def analyze_free_agents(
    league_element_status: dict,
    bootstrap: dict,
    next_gw: int,
    fixtures: list,
) -> list[PlayerAnalysis]:
    """
    Analyzes all free agents (not drafted by anyone) in the league,
    sorted by score (best first).
    """
    player_lookup = build_player_lookup(bootstrap)
    team_lookup = build_team_lookup(bootstrap)
    next_fixtures = get_next_fixtures(fixtures, next_gw)
    pos_map = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

    free_agents = []
    for status in league_element_status.get("element_status", []):
        # owner_entry = None means the player hasn't been drafted
        if status.get("owner") is not None:
            continue

        pid = status["element"]
        p = player_lookup.get(pid)
        if not p or p.get("status") == "u":
            continue

        team_id = p["team"]
        team_name = team_lookup.get(team_id, {}).get("short_name", "?")
        team_fixtures = next_fixtures.get(team_id, [])

        if team_fixtures:
            opp_id, is_home, fdr = team_fixtures[0]
            opp_name = team_lookup.get(opp_id, {}).get("short_name", "?")
        else:
            opp_name, is_home, fdr = "Blank", False, 3

        try:
            form = float(p.get("form", 0))
        except (ValueError, TypeError):
            form = 0.0

        analysis = PlayerAnalysis(
            id=pid,
            name=f"{p['first_name']} {p['second_name']}",
            team=team_name,
            position=pos_map.get(p["element_type"], "?"),
            is_starter=False,
            bench_position=None,
            total_points=p.get("total_points", 0),
            form=form,
            points_last_gw=0,
            minutes_last_gw=90,
            next_opponent=opp_name,
            next_fixture_fdr=fdr,
            next_is_home=is_home,
            status=p.get("status", "a"),
            chance_of_playing=p.get("chance_of_playing_this_round"),
            news=p.get("news", ""),
        )
        analysis.recommendation_score = calculate_recommendation_score(analysis)
        analysis.recommendation_note = generate_recommendation_note(analysis)
        free_agents.append(analysis)

    return sorted(free_agents, key=lambda x: x.recommendation_score, reverse=True)


def analyze_all_owned_players(
    league_element_status: dict,
    bootstrap: dict,
    next_gw: int,
    fixtures: list,
) -> dict:
    """
    Analyzes all drafted players in the league, grouped by which manager
    (entry_id) owns them. Used for the trade finder and waiver timing.
    """
    player_lookup = build_player_lookup(bootstrap)
    team_lookup = build_team_lookup(bootstrap)
    next_fixtures = get_next_fixtures(fixtures, next_gw)
    pos_map = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

    owned_by_entry: dict = {}
    for status in league_element_status.get("element_status", []):
        owner_entry_id = status.get("owner")
        if owner_entry_id is None:
            continue

        pid = status["element"]
        p = player_lookup.get(pid)
        if not p:
            continue

        team_id = p["team"]
        team_name = team_lookup.get(team_id, {}).get("short_name", "?")
        team_fixtures = next_fixtures.get(team_id, [])

        if team_fixtures:
            opp_id, is_home, fdr = team_fixtures[0]
            opp_name = team_lookup.get(opp_id, {}).get("short_name", "?")
        else:
            opp_name, is_home, fdr = "Blank", False, 3

        try:
            form = float(p.get("form", 0))
        except (ValueError, TypeError):
            form = 0.0

        analysis = PlayerAnalysis(
            id=pid,
            name=f"{p['first_name']} {p['second_name']}",
            team=team_name,
            position=pos_map.get(p["element_type"], "?"),
            is_starter=False,
            bench_position=None,
            total_points=p.get("total_points", 0),
            form=form,
            points_last_gw=0,
            minutes_last_gw=90,
            next_opponent=opp_name,
            next_fixture_fdr=fdr,
            next_is_home=is_home,
            status=p.get("status", "a"),
            chance_of_playing=p.get("chance_of_playing_this_round"),
            news=p.get("news", ""),
        )
        analysis.recommendation_score = calculate_recommendation_score(analysis)
        analysis.recommendation_note = generate_recommendation_note(analysis)
        owned_by_entry.setdefault(owner_entry_id, []).append(analysis)

    return owned_by_entry


def find_waiver_targets(
    league_element_status: dict,
    bootstrap: dict,
    next_gw: int,
    fixtures: list,
    top_n: int = 10,
) -> list[PlayerAnalysis]:
    """Top N free agents overall, for display."""
    return analyze_free_agents(league_element_status, bootstrap, next_gw, fixtures)[:top_n]


def suggest_transfers(
    players: list[PlayerAnalysis],
    free_agents: list[PlayerAnalysis],
    min_score_gain: float = 3.0,
    max_suggestions: int = 5,
) -> list[dict]:
    """
    Suggests transfers: for each position, compares your weakest player
    with the best available free agent in the same position.
    Only suggests a transfer if the score improvement is at least min_score_gain.
    """
    own_by_position: dict = {}
    for p in players:
        own_by_position.setdefault(p.position, []).append(p)

    free_agents_by_position: dict = {}
    for fa in free_agents:
        free_agents_by_position.setdefault(fa.position, []).append(fa)

    suggestions = []
    for position, own_players in own_by_position.items():
        if not own_players:
            continue
        weakest = min(own_players, key=lambda p: p.recommendation_score)

        candidates = free_agents_by_position.get(position, [])
        if not candidates:
            continue
        best_candidate = candidates[0]

        score_gain = best_candidate.recommendation_score - weakest.recommendation_score
        if score_gain >= min_score_gain:
            suggestions.append({
                "drop": weakest,
                "add": best_candidate,
                "position": position,
                "score_gain": round(score_gain, 2),
            })

    return sorted(suggestions, key=lambda s: s["score_gain"], reverse=True)[:max_suggestions]


def build_league_overview(league_details: dict, league_element_status: dict, bootstrap: dict) -> list[dict]:
    """
    Builds an overview of all managers in the league: standings and which
    players they own, based on league/details and league/element-status.
    """
    player_lookup = build_player_lookup(bootstrap)
    pos_map = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

    # standings.league_entry points to league_entries.id, while
    # element_status.owner points to league_entries.entry_id. Build both lookups.
    entries_by_id = {e["id"]: e for e in league_details.get("league_entries", [])}
    entry_id_to_league_entry_id = {e["entry_id"]: e["id"] for e in league_details.get("league_entries", [])}

    squads: dict = {}  # league_entry_id -> list of players
    for status in league_element_status.get("element_status", []):
        owner_entry_id = status.get("owner")
        if owner_entry_id is None:
            continue
        league_entry_id = entry_id_to_league_entry_id.get(owner_entry_id)
        if league_entry_id is None:
            continue
        pid = status["element"]
        p = player_lookup.get(pid)
        if not p:
            continue
        squads.setdefault(league_entry_id, []).append({
            "name": f"{p['first_name']} {p['second_name']}",
            "position": pos_map.get(p["element_type"], "?"),
        })

    overview = []
    for standing in sorted(league_details.get("standings", []), key=lambda s: s["rank"]):
        entry = entries_by_id.get(standing["league_entry"], {})
        overview.append({
            "rank": standing["rank"],
            "team_name": entry.get("entry_name", "?"),
            "manager": f"{entry.get('player_first_name', '')} {entry.get('player_last_name', '')}".strip(),
            "total_points": standing["total"],
            "event_points": standing["event_total"],
            "squad": squads.get(standing["league_entry"], []),
        })

    return overview


def build_league_squads(league_details: dict, owned_by_entry: dict, picks_by_entry: dict) -> list[dict]:
    """
    Like build_league_overview, but returns each manager's actual starting lineup
    for the (locked) gameweek picks_by_entry was fetched for - not our own
    recommendation - so their team can be shown as a real formation.

    picks_by_entry: dict of entry_id -> get_my_picks() result for that gameweek.
    """
    entries_by_id = {e["id"]: e for e in league_details.get("league_entries", [])}

    overview = []
    for standing in sorted(league_details.get("standings", []), key=lambda s: s["rank"]):
        entry = entries_by_id.get(standing["league_entry"], {})
        entry_id = entry.get("entry_id")
        players_by_id = {p.id: p for p in owned_by_entry.get(entry_id, [])}
        picks = picks_by_entry.get(entry_id, {}).get("picks", [])
        starters = [
            players_by_id[pick["element"]]
            for pick in picks
            if pick["position"] <= 11 and pick["element"] in players_by_id
        ]
        overview.append({
            "rank": standing["rank"],
            "team_name": entry.get("entry_name", "?"),
            "manager": f"{entry.get('player_first_name', '')} {entry.get('player_last_name', '')}".strip(),
            "total_points": standing["total"],
            "event_points": standing["event_total"],
            "starters": starters,
        })

    return overview


def build_transactions_feed(transactions: dict, league_details: dict, bootstrap: dict) -> list[dict]:
    """
    Builds a readable list of waiver/transfer requests from all
    managers in the league, newest first.
    """
    player_lookup = build_player_lookup(bootstrap)
    entries_by_entry_id = {e["entry_id"]: e for e in league_details.get("league_entries", [])}

    kind_labels = {"w": "Waiver", "f": "Free agent", "t": "Trade"}
    result_labels = {"a": "Approved"}

    def player_name(pid):
        p = player_lookup.get(pid)
        return f"{p['first_name']} {p['second_name']}" if p else "?"

    feed = []
    for tx in transactions.get("transactions", []):
        entry = entries_by_entry_id.get(tx.get("entry"), {})
        feed.append({
            "added": tx.get("added", ""),
            "event": tx.get("event"),
            "team_name": entry.get("entry_name", "?"),
            "manager": f"{entry.get('player_first_name', '')} {entry.get('player_last_name', '')}".strip(),
            "kind": kind_labels.get(tx.get("kind"), tx.get("kind")),
            "player_in": player_name(tx.get("element_in")),
            "player_out": player_name(tx.get("element_out")),
            "result": result_labels.get(tx.get("result"), "Rejected/not completed"),
        })

    return sorted(feed, key=lambda t: t["added"], reverse=True)


def build_trades_feed(trades: dict, league_details: dict, bootstrap: dict) -> list[dict]:
    """
    Builds a readable list of proposed/pending trades between managers
    (before they're accepted/rejected), including who's trading with whom.

    NOTE: FPL Draft's /trades endpoint has unclear/undocumented field naming
    (since no trades had been proposed in the league yet, we couldn't verify
    the exact field names against real data). The code is written defensively
    with .get() fallbacks, but the field names may need adjusting once an
    actual trade shows up.
    """
    player_lookup = build_player_lookup(bootstrap)
    entries_by_entry_id = {e["entry_id"]: e for e in league_details.get("league_entries", [])}

    state_labels = {
        "p": "Proposed",
        "proposed": "Proposed",
        "a": "Accepted",
        "accepted": "Accepted",
        "d": "Rejected",
        "rejected": "Rejected",
        "withdrawn": "Withdrawn",
        "expired": "Expired",
        "invalid": "Invalid",
        "vetoed": "Vetoed",
    }

    def entry_label(entry_id):
        e = entries_by_entry_id.get(entry_id, {})
        team = e.get("entry_name", "?")
        manager = f"{e.get('player_first_name', '')} {e.get('player_last_name', '')}".strip()
        return f"{team} ({manager})" if manager else team

    def player_names(pids):
        names = []
        for pid in pids or []:
            p = player_lookup.get(pid)
            names.append(f"{p['first_name']} {p['second_name']}" if p else "?")
        return names

    feed = []
    for trade in trades.get("trades", []):
        proposer_id = trade.get("entry") or trade.get("proposing_entry")
        counterpart_id = trade.get("other_entry") or trade.get("recipient_entry") or trade.get("accepting_entry")
        offer_out = trade.get("offer") or trade.get("elements_out") or []
        offer_in = trade.get("reply") or trade.get("elements_in") or []
        state = trade.get("state") or trade.get("status")

        feed.append({
            "added": trade.get("added") or trade.get("index") or "",
            "proposer": entry_label(proposer_id),
            "counterpart": entry_label(counterpart_id),
            "gives": ", ".join(player_names(offer_out)) or "?",
            "receives": ", ".join(player_names(offer_in)) or "?",
            "state": state_labels.get(state, state or "Unknown"),
        })

    return feed


def _group_by_position(players: list[PlayerAnalysis]) -> dict:
    grouped: dict = {}
    for p in players:
        grouped.setdefault(p.position, []).append(p)
    for pos in grouped:
        grouped[pos].sort(key=lambda p: p.recommendation_score, reverse=True)
    return grouped


def _avg_score(players: list[PlayerAnalysis]) -> float:
    return sum(p.recommendation_score for p in players) / len(players) if players else 0.0


def find_trade_opportunities(
    owned_by_entry: dict,
    my_entry_id: int,
    league_details: dict,
    min_gain: float = 5.0,
    max_suggestions: int = 5,
) -> list[dict]:
    """
    Finds mutually beneficial 2-for-2 trades: you give your most spare player in a
    position you're strong in, plus your weakest player in a position you need
    help in. In return you get their weakest player in the position you're
    strong in (cheap for them to give up), plus their second-best player in
    the position they're strong in (a surplus for them, since they keep their best).

    This preserves the number of players per position on both teams (as FPL Draft
    requires for valid trades), and gives a net improvement for you – but remember
    the other manager also has to consider it worth it for them.
    """
    entries_by_entry_id = {e["entry_id"]: e for e in league_details.get("league_entries", [])}
    positions = ["GKP", "DEF", "MID", "FWD"]

    def entry_label(entry_id):
        e = entries_by_entry_id.get(entry_id, {})
        team = e.get("entry_name", "?")
        manager = f"{e.get('player_first_name', '')} {e.get('player_last_name', '')}".strip()
        return f"{team} ({manager})" if manager else team

    my_players = owned_by_entry.get(my_entry_id, [])
    my_by_pos = _group_by_position(my_players)
    my_avg = {pos: _avg_score(my_by_pos.get(pos, [])) for pos in positions}

    suggestions = []
    for other_entry_id, other_players in owned_by_entry.items():
        if other_entry_id == my_entry_id:
            continue
        other_by_pos = _group_by_position(other_players)
        other_avg = {pos: _avg_score(other_by_pos.get(pos, [])) for pos in positions}

        best_for_this_manager = None
        for p1 in positions:
            for p2 in positions:
                if p1 == p2:
                    continue
                # I'm stronger in p1 (can spare a player there),
                # they're stronger in p2 (I need help there).
                my_edge_p1 = my_avg[p1] - other_avg[p1]
                their_edge_p2 = other_avg[p2] - my_avg[p2]
                if my_edge_p1 < min_gain / 2 or their_edge_p2 < min_gain / 2:
                    continue

                if not my_by_pos.get(p1) or not my_by_pos.get(p2):
                    continue
                if not other_by_pos.get(p1) or len(other_by_pos.get(p2, [])) < 2:
                    continue

                give_p1 = my_by_pos[p1][-1]
                give_p2 = my_by_pos[p2][-1]
                get_p1 = other_by_pos[p1][-1]
                get_p2 = other_by_pos[p2][1]

                my_gain = (get_p1.recommendation_score - give_p1.recommendation_score) + \
                          (get_p2.recommendation_score - give_p2.recommendation_score)

                if my_gain < min_gain:
                    continue

                candidate = {
                    "other_manager": entry_label(other_entry_id),
                    "give": [give_p1, give_p2],
                    "receive": [get_p1, get_p2],
                    "my_gain": round(my_gain, 2),
                }
                if best_for_this_manager is None or candidate["my_gain"] > best_for_this_manager["my_gain"]:
                    best_for_this_manager = candidate

        if best_for_this_manager:
            suggestions.append(best_for_this_manager)

    return sorted(suggestions, key=lambda s: s["my_gain"], reverse=True)[:max_suggestions]


def build_waiver_timing_report(
    league_details: dict,
    owned_by_entry: dict,
    free_agents: list[PlayerAnalysis],
    my_entry_id: int,
    top_n: int = 8,
) -> dict:
    """
    Shows your waiver priority this round, and flags which of the best free
    agents are at risk of being taken by managers with better priority than
    you (based on whether they have a noticeably weak spot in that position).

    We don't have access to actual submitted waiver claims from other
    managers (it's not exposed in the API), so this is a heuristic based on
    who needs help at that position, not a guarantee.
    """
    positions = ["GKP", "DEF", "MID", "FWD"]
    entries = league_details.get("league_entries", [])

    league_avg_by_pos = {pos: [] for pos in positions}
    for players in owned_by_entry.values():
        grouped = _group_by_position(players)
        for pos in positions:
            if grouped.get(pos):
                league_avg_by_pos[pos].append(_avg_score(grouped[pos]))
    league_avg_by_pos = {
        pos: (sum(vals) / len(vals) if vals else 0.0) for pos, vals in league_avg_by_pos.items()
    }

    my_entry = next((e for e in entries if e["entry_id"] == my_entry_id), {})
    my_pick = my_entry.get("waiver_pick")

    ahead_of_me = [
        e for e in entries
        if e.get("waiver_pick") is not None and my_pick is not None and e["waiver_pick"] < my_pick
    ]

    targets = []
    for fa in free_agents[:top_n]:
        threats = []
        for entry in ahead_of_me:
            other_players = owned_by_entry.get(entry["entry_id"], [])
            grouped = _group_by_position(other_players)
            their_avg = _avg_score(grouped.get(fa.position, []))
            if their_avg < league_avg_by_pos.get(fa.position, 0.0) - 3.0:
                manager = f"{entry.get('player_first_name', '')} {entry.get('player_last_name', '')}".strip()
                threats.append(f"{entry.get('entry_name', '?')} ({manager})")
        targets.append({"player": fa, "threatened_by": threats})

    return {
        "my_waiver_pick": my_pick,
        "total_entries": len(entries),
        "targets": targets,
    }


# On Vercel the deployed code lives on a read-only filesystem - only /tmp is
# writable, and even that isn't guaranteed to persist between invocations.
CLUB_CHANGE_CACHE_FILE = (
    os.path.join(tempfile.gettempdir(), "fpl_team_change_cache.json")
    if os.environ.get("VERCEL")
    else os.path.join(os.path.dirname(__file__), "team_change_cache.json")
)


def apply_club_change_notes(
    players: list[PlayerAnalysis],
    current_gw: int,
    cache_path: str = CLUB_CHANGE_CACHE_FILE,
) -> None:
    """
    FPL's API only shows the current club, not history. This function stores
    which club each player had the last time the tool ran, and flags a change
    if the club is different now – even transfers *within* the Premier League
    (which aren't caught by the status/news field).

    The flag stays on the note for the entire gameweek the change was detected
    in (no matter how many times you run the tool), and disappears automatically
    once the next gameweek starts (current_gw increases).

    Updates player.recommendation_note directly (in memory), and writes the
    updated cache to disk afterwards.
    """
    try:
        with open(cache_path) as f:
            cache: dict = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        cache = {}

    for player in players:
        key = str(player.id)
        entry = cache.get(key, {"team": None, "prev_team": None, "flag_gw": None})
        if isinstance(entry, str):  # migration from an older cache format
            entry = {"team": entry, "prev_team": None, "flag_gw": None}

        old_team = entry.get("team")
        if old_team and old_team != player.team:
            # New change detected now – start the flag for this gameweek
            entry["prev_team"] = old_team
            entry["flag_gw"] = current_gw
        elif entry.get("flag_gw") is not None and entry.get("flag_gw") != current_gw:
            # The next gameweek has started – clear the flag
            entry["flag_gw"] = None
            entry["prev_team"] = None

        entry["team"] = player.team

        if entry.get("flag_gw") == current_gw and entry.get("prev_team"):
            player.recommendation_note = (
                f"🔁 Changed club (from {entry['prev_team']} to {player.team}) | {player.recommendation_note}"
            )

        cache[key] = entry

    try:
        with open(cache_path, "w") as f:
            json.dump(cache, f, indent=2)
    except OSError:
        pass  # read-only filesystem - club-change detection just won't persist between runs
