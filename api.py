"""
FPL Draft API Client
Henter data fra draft.premierleague.com
"""

import requests
import json
from typing import Optional

BASE_URL = "https://draft.premierleague.com/api"
CLASSIC_BASE_URL = "https://fantasy.premierleague.com/api"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Referer": "https://draft.premierleague.com/",
}


class FPLDraftClient:
    def __init__(self, raw_cookie_header: str):
        """
        raw_cookie_header: hele Cookie-header-verdien fra en innlogget forespørsel
        mot draft.premierleague.com/api/me, kopiert fra DevTools → Network.
        Nødvendig for kontoer som logger inn via Google/SSO, der det ikke finnes
        et fast cookie-navn (som pl_profile) man kan stole på.
        """
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.session.headers["Cookie"] = raw_cookie_header
        self._bootstrap = None

    # ── Bootstrap (all player/team/fixture data) ──────────────────────────────

    def get_bootstrap(self) -> dict:
        """Henter all grunndata: spillere, lag, fixtures, gameweeks."""
        if self._bootstrap is None:
            r = self.session.get(f"{BASE_URL}/bootstrap-static")
            r.raise_for_status()
            self._bootstrap = r.json()
        return self._bootstrap

    def get_current_gameweek(self) -> int:
        """Returnerer nåværende gameweek-nummer."""
        r = self.session.get(f"{BASE_URL}/game")
        r.raise_for_status()
        data = r.json()
        return data["current_event"]

    def get_next_gameweek(self) -> int:
        return self.get_current_gameweek() + 1

    def get_fixtures_for_gameweek(self, gameweek: int) -> list:
        """
        Draft-API'et har ikke fixture difficulty rating (FDR), så vi henter
        fixtures med FDR fra den offentlige classic-FPL-API'et i stedet.
        Lag-ID-ene er de samme i begge API-ene.
        """
        r = requests.get(f"{CLASSIC_BASE_URL}/fixtures/", params={"event": gameweek})
        r.raise_for_status()
        return r.json()

    # ── Bruker og lag ─────────────────────────────────────────────────────────

    def get_my_picks(self, entry_id: int, gameweek: int) -> dict:
        """Henter laget ditt (startere + benk) for en gitt gameweek."""
        r = self.session.get(f"{BASE_URL}/entry/{entry_id}/event/{gameweek}")
        r.raise_for_status()
        return r.json()

    def get_entry_info(self, entry_id: int) -> dict:
        r = self.session.get(f"{BASE_URL}/entry/{entry_id}/public")
        r.raise_for_status()
        return r.json()

    # ── Spillerdetaljer ───────────────────────────────────────────────────────

    def get_player_history(self, player_id: int) -> dict:
        """Henter historikk og siste kamper for en spiller."""
        r = self.session.get(f"{BASE_URL}/element-summary/{player_id}")
        r.raise_for_status()
        return r.json()

    # ── League / waiver ───────────────────────────────────────────────────────

    def get_league_element_status(self, league_id: int) -> dict:
        """Viser hvilke spillere som er ledige (waiver/free agent) i ligaen, og hvem som eier resten."""
        r = self.session.get(f"{BASE_URL}/league/{league_id}/element-status")
        r.raise_for_status()
        return r.json()

    def get_league_details(self, league_id: int) -> dict:
        """Henter managere, standings og liga-info."""
        r = self.session.get(f"{BASE_URL}/league/{league_id}/details")
        r.raise_for_status()
        return r.json()

    def get_transactions(self, league_id: int) -> dict:
        """Historikk over gjennomførte waivers/free agent-hentinger/trades."""
        r = self.session.get(f"{BASE_URL}/draft/league/{league_id}/transactions")
        r.raise_for_status()
        return r.json()

    def get_trades(self, league_id: int) -> dict:
        """Pågående/foreslåtte trades mellom managere (før de er godkjent/avvist)."""
        r = self.session.get(f"{BASE_URL}/draft/league/{league_id}/trades")
        r.raise_for_status()
        return r.json()
