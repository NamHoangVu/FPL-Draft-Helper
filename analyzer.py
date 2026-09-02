"""
FPL Draft Analyzer
Analyserer laget ditt og gir anbefalinger for neste gameweek.
"""

from dataclasses import dataclass, field
from typing import Optional


# Fixture Difficulty Rating: 1 = enklest, 5 = hardest
# Brukes til å score fixtures for neste gameweek
FDR_LABELS = {1: "Veldig lett ✅", 2: "Lett ✅", 3: "Middels ⚠️", 4: "Vanskelig ❌", 5: "Veldig vanskelig ❌"}


@dataclass
class PlayerAnalysis:
    id: int
    name: str
    team: str
    position: str          # GKP, DEF, MID, FWD
    is_starter: bool
    bench_position: Optional[int]  # None hvis starter

    # Form og poeng
    total_points: int
    form: float            # snitt siste 5 kamper
    points_last_gw: int
    minutes_last_gw: int

    # Neste kamp
    next_opponent: str
    next_fixture_fdr: int  # 1-5
    next_is_home: bool

    # Status
    status: str            # 'a' = available, 'd' = doubt, 'u' = unavailable
    chance_of_playing: Optional[int]  # 0-100

    # Score beregnet av analyzer
    recommendation_score: float = 0.0
    recommendation_note: str = ""

    @property
    def fixture_label(self) -> str:
        home_away = "H" if self.next_is_home else "B"
        return f"{self.next_opponent} ({home_away}) FDR:{self.next_fixture_fdr}"

    @property
    def status_emoji(self) -> str:
        if self.status == "a":
            return "✅"
        elif self.status == "d":
            pct = self.chance_of_playing or 50
            return f"⚠️ {pct}%"
        return "❌"


def build_player_lookup(bootstrap: dict) -> dict:
    """Bygger en dict med player_id -> player-data fra bootstrap."""
    return {p["id"]: p for p in bootstrap["elements"]}


def build_team_lookup(bootstrap: dict) -> dict:
    """Bygger en dict med team_id -> team-data."""
    return {t["id"]: t for t in bootstrap["teams"]}


def get_next_fixtures(fixtures: list, gameweek: int) -> dict:
    """
    Returnerer en dict: team_id -> list av (opponent_team_id, is_home, fdr)
    for den gitte gameweeken.

    fixtures: liste med fixtures (inkl. FDR) for denne gameweeken,
    fra FPLDraftClient.get_fixtures_for_gameweek().
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


def calculate_recommendation_score(player: PlayerAnalysis) -> float:
    """
    Enkel scoringsmodell:
    - Form (siste 5 GW snitt) vektes høyest
    - Fixture difficulty trekker fra
    - Minutter siste kamp indikerer om spilleren faktisk spiller
    - Status-straff for skadde/usikre spillere
    """
    score = 0.0

    # Form: 0-10 poeng → vekt 40%
    score += min(player.form, 15.0) * 2.0

    # FDR: 1=bra, 5=dårlig → inverter
    fdr_bonus = (6 - player.next_fixture_fdr) * 3.0  # 15 for FDR=1, 3 for FDR=5
    score += fdr_bonus

    # Minutter siste kamp: belønner spillere som faktisk starter
    if player.minutes_last_gw >= 60:
        score += 5.0
    elif player.minutes_last_gw >= 30:
        score += 2.0
    elif player.minutes_last_gw == 0:
        score -= 5.0

    # Poeng siste GW (momentum)
    score += min(player.points_last_gw, 20) * 0.3

    # Straff for skade/usikkerhet
    if player.status == "u":
        score -= 20.0
    elif player.status == "d":
        pct = player.chance_of_playing or 50
        score -= (100 - pct) * 0.1

    return round(score, 2)


def generate_recommendation_note(player: PlayerAnalysis) -> str:
    notes = []

    if player.status == "u":
        notes.append("❌ Ikke spilleklar")
        return " | ".join(notes)
    if player.status == "d":
        notes.append(f"⚠️ Usikker ({player.chance_of_playing}%)")

    if player.next_fixture_fdr <= 2:
        notes.append("✅ Knallbra fixture")
    elif player.next_fixture_fdr == 3:
        notes.append("⚠️ Middels fixture")
    else:
        notes.append("❌ Tøff fixture")

    if player.form >= 8:
        notes.append("🔥 I toppform")
    elif player.form >= 5:
        notes.append("📈 OK form")
    elif player.form < 3:
        notes.append("📉 Dårlig form")

    if player.minutes_last_gw == 0:
        notes.append("⚠️ Spilte ikke siste GW")

    return " | ".join(notes)


def analyze_squad(
    picks: dict,
    bootstrap: dict,
    next_gw: int,
    player_histories: dict,
    fixtures: list,
) -> list[PlayerAnalysis]:
    """
    Analyserer alle 15 spillere i laget ditt.

    picks: fra get_my_picks()
    bootstrap: fra get_bootstrap()
    next_gw: neste gameweek-nummer
    player_histories: dict med player_id -> get_player_history()
    fixtures: fra get_fixtures_for_gameweek(next_gw), inkl. FDR
    """
    player_lookup = build_player_lookup(bootstrap)
    team_lookup = build_team_lookup(bootstrap)
    next_fixtures = get_next_fixtures(fixtures, next_gw)

    # FPL posisjonskoder: 1=GKP, 2=DEF, 3=MID, 4=FWD
    pos_map = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

    results = []
    for pick in picks["picks"]:
        pid = pick["element"]
        p = player_lookup.get(pid)
        if not p:
            continue

        team_id = p["team"]
        team_name = team_lookup.get(team_id, {}).get("short_name", "?")

        # Neste fixture
        team_fixtures = next_fixtures.get(team_id, [])
        if team_fixtures:
            opp_id, is_home, fdr = team_fixtures[0]
            opp_name = team_lookup.get(opp_id, {}).get("short_name", "?")
        else:
            opp_name, is_home, fdr = "Blank", False, 3

        # Historikk: hent form og siste kamp
        history = player_histories.get(pid, {})
        past_matches = history.get("history", [])

        points_last_gw = 0
        minutes_last_gw = 0
        if past_matches:
            last = past_matches[-1]
            points_last_gw = last.get("total_points", 0)
            minutes_last_gw = last.get("minutes", 0)

        # Form: snitt siste 5 kamper (FPL gir dette direkte)
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
        )

        analysis.recommendation_score = calculate_recommendation_score(analysis)
        analysis.recommendation_note = generate_recommendation_note(analysis)
        results.append(analysis)

    return results


def recommend_starting_xi(players: list[PlayerAnalysis]) -> tuple[list, list]:
    """
    Anbefaler en startoppstilling basert på scores,
    med respekt for posisjonskrav (1 GKP, min 3 DEF, min 2 FWD, max 5 DEF/MID/FWD).

    Returnerer (startere, benk) sortert etter score.
    """
    # Skill ut skadet/utilgjengelig
    available = [p for p in players if p.status != "u"]
    unavailable = [p for p in players if p.status == "u"]

    # Sorter etter score
    by_pos: dict[str, list] = {"GKP": [], "DEF": [], "MID": [], "FWD": []}
    for p in sorted(available, key=lambda x: x.recommendation_score, reverse=True):
        by_pos[p.position].append(p)

    starters = []
    bench = []

    # 1 keeper
    if by_pos["GKP"]:
        starters.append(by_pos["GKP"][0])
        bench.extend(by_pos["GKP"][1:])

    # Minst 3 forsvarere
    starters.extend(by_pos["DEF"][:3])
    remaining_def = by_pos["DEF"][3:]

    # Minst 2 angripere
    starters.extend(by_pos["FWD"][:2])
    remaining_fwd = by_pos["FWD"][2:]

    # Fyll ut de resterende 5 feltspillerne med beste tilgjengelige
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
    Analyserer alle ledige spillere (ikke draftet av noen) i ligaen,
    sortert etter score (best først).
    """
    player_lookup = build_player_lookup(bootstrap)
    team_lookup = build_team_lookup(bootstrap)
    next_fixtures = get_next_fixtures(fixtures, next_gw)
    pos_map = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

    free_agents = []
    for status in league_element_status.get("element_status", []):
        # owner_entry = None betyr at spilleren ikke er draftet
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
    Analyserer alle draftede spillere i ligaen, gruppert på hvilken manager
    (entry_id) som eier dem. Brukes til trade-finner og waiver-timing.
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
    """Topp N ledige spillere totalt, til visning."""
    return analyze_free_agents(league_element_status, bootstrap, next_gw, fixtures)[:top_n]


def suggest_transfers(
    players: list[PlayerAnalysis],
    free_agents: list[PlayerAnalysis],
    min_score_gain: float = 3.0,
    max_suggestions: int = 5,
) -> list[dict]:
    """
    Foreslår bytter: for hver posisjon, sammenlign din svakeste spiller
    med den beste tilgjengelige ledige spilleren i samme posisjon.
    Foreslår kun bytte hvis forbedringen i score er minst min_score_gain.
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
    Bygger en oversikt over alle managere i ligaen: standings og hvilke
    spillere de eier, basert på league/details og league/element-status.
    """
    player_lookup = build_player_lookup(bootstrap)
    pos_map = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

    # standings.league_entry peker til league_entries.id, mens
    # element_status.owner peker til league_entries.entry_id. Bygg begge lookups.
    entries_by_id = {e["id"]: e for e in league_details.get("league_entries", [])}
    entry_id_to_league_entry_id = {e["entry_id"]: e["id"] for e in league_details.get("league_entries", [])}

    squads: dict = {}  # league_entry_id -> list av spillere
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


def build_transactions_feed(transactions: dict, league_details: dict, bootstrap: dict) -> list[dict]:
    """
    Bygger en lesbar liste over waiver/transfer-forespørsler fra alle
    managere i ligaen, nyest først.
    """
    player_lookup = build_player_lookup(bootstrap)
    entries_by_entry_id = {e["entry_id"]: e for e in league_details.get("league_entries", [])}

    kind_labels = {"w": "Waiver", "f": "Free agent", "t": "Trade"}
    result_labels = {"a": "Godkjent"}

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
            "result": result_labels.get(tx.get("result"), "Avvist/ikke gjennomført"),
        })

    return sorted(feed, key=lambda t: t["added"], reverse=True)


def build_trades_feed(trades: dict, league_details: dict, bootstrap: dict) -> list[dict]:
    """
    Bygger en lesbar liste over foreslåtte/pågående trades mellom managere
    (før de er godkjent/avvist), inkludert hvem som trader med hvem.

    NB: FPL Draft sitt /trades-endepunkt har uklar/udokumentert feltnavngiving
    (siden ingen trades er foreslått i ligaen ennå, kunne vi ikke verifisere
    de eksakte feltnavnene mot ekte data). Koden er skrevet defensivt med
    .get()-fallbacks, men feltnavnene kan trenge justering når en faktisk
    trade dukker opp.
    """
    player_lookup = build_player_lookup(bootstrap)
    entries_by_entry_id = {e["entry_id"]: e for e in league_details.get("league_entries", [])}

    state_labels = {
        "p": "Foreslått",
        "proposed": "Foreslått",
        "a": "Akseptert",
        "accepted": "Akseptert",
        "d": "Avvist",
        "rejected": "Avvist",
        "withdrawn": "Trukket tilbake",
        "expired": "Utløpt",
        "invalid": "Ugyldig",
        "vetoed": "Nedstemt",
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
            "state": state_labels.get(state, state or "Ukjent"),
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
    Finner gjensidig gunstige 2-for-2 trades: du gir din spareste spiller i en
    posisjon du er sterk i, pluss din svakeste spiller i en posisjon du
    trenger hjelp i. I retur får du deres svakeste spiller i posisjonen du er
    sterk i (billig for dem å gi bort), pluss deres nest beste spiller i
    posisjonen de er sterke i (overskudd for dem, de holder på sin beste).

    Dette bevarer antall spillere per posisjon på begge lag (som FPL Draft
    krever for gyldige trades), og gir netto forbedring for deg – men husk at
    den andre manageren må vurdere det som verdt det for seg også.
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
                # Jeg er sterkere i p1 (kan spare en spiller der),
                # de er sterkere i p2 (jeg trenger hjelp der).
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
    Viser waiver-prioriteten din denne runden, og flagger hvilke av de beste
    ledige spillerne som står i fare for å bli tatt av managere med bedre
    prioritet enn deg (basert på om de har en merkbart svak posisjon der).

    Vi har ikke tilgang til faktiske innsendte waiver-krav fra andre
    managere (det er ikke eksponert i API'et), så dette er en heuristikk
    basert på hvem som trenger hjelp i posisjonen, ikke en garanti.
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
