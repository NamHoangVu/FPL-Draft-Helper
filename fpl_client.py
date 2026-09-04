"""
FPL Draft API Client
Fetches data from draft.premierleague.com
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
        raw_cookie_header: the entire Cookie header value from a logged-in request
        to draft.premierleague.com/api/me, copied from DevTools → Network.
        Needed for accounts that log in via Google/SSO, where there's no fixed
        cookie name (like pl_profile) you can rely on.
        """
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        # .strip() guards against a stray trailing newline from copy-pasting the
        # cookie value (e.g. into an env var field) - HTTP headers can't contain one.
        self.session.headers["Cookie"] = raw_cookie_header.strip()
        self._bootstrap = None

    # ── Bootstrap (all player/team/fixture data) ──────────────────────────────

    def get_bootstrap(self) -> dict:
        """Fetches all base data: players, teams, fixtures, gameweeks."""
        if self._bootstrap is None:
            r = self.session.get(f"{BASE_URL}/bootstrap-static")
            r.raise_for_status()
            self._bootstrap = r.json()
        return self._bootstrap

    def get_current_gameweek(self) -> int:
        """Returns the current gameweek number."""
        r = self.session.get(f"{BASE_URL}/game")
        r.raise_for_status()
        data = r.json()
        return data["current_event"]

    def get_next_gameweek(self) -> int:
        return self.get_current_gameweek() + 1

    def get_fixtures_for_gameweek(self, gameweek: int) -> list:
        """
        The Draft API doesn't have a fixture difficulty rating (FDR), so we fetch
        fixtures with FDR from the public classic FPL API instead.
        The team IDs are the same in both APIs.
        """
        r = requests.get(f"{CLASSIC_BASE_URL}/fixtures/", params={"event": gameweek})
        r.raise_for_status()
        return r.json()

    # ── User and team ────────────────────────────────────────────────────────

    def get_my_picks(self, entry_id: int, gameweek: int) -> dict:
        """Fetches your team (starters + bench) for a given gameweek."""
        r = self.session.get(f"{BASE_URL}/entry/{entry_id}/event/{gameweek}")
        r.raise_for_status()
        return r.json()

    def get_entry_info(self, entry_id: int) -> dict:
        r = self.session.get(f"{BASE_URL}/entry/{entry_id}/public")
        r.raise_for_status()
        return r.json()

    # ── Player details ───────────────────────────────────────────────────────

    def get_player_history(self, player_id: int) -> dict:
        """Fetches history and recent matches for a player."""
        r = self.session.get(f"{BASE_URL}/element-summary/{player_id}")
        r.raise_for_status()
        return r.json()

    # ── League / waiver ───────────────────────────────────────────────────────

    def get_league_element_status(self, league_id: int) -> dict:
        """Shows which players are free agents in the league, and who owns the rest."""
        r = self.session.get(f"{BASE_URL}/league/{league_id}/element-status")
        r.raise_for_status()
        return r.json()

    def get_league_details(self, league_id: int) -> dict:
        """Fetches managers, standings, and league info."""
        r = self.session.get(f"{BASE_URL}/league/{league_id}/details")
        r.raise_for_status()
        return r.json()

    def get_transactions(self, league_id: int) -> dict:
        """History of completed waivers/free agent pickups/trades."""
        r = self.session.get(f"{BASE_URL}/draft/league/{league_id}/transactions")
        r.raise_for_status()
        return r.json()

    def get_trades(self, league_id: int) -> dict:
        """Pending/proposed trades between managers (before they're accepted/rejected)."""
        r = self.session.get(f"{BASE_URL}/draft/league/{league_id}/trades")
        r.raise_for_status()
        return r.json()
