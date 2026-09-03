# FPL Draft Helper

Et lite verktøy for Fantasy Premier League **Draft**-ligaer. Henter laget ditt, ledige spillere og
ligadata fra `draft.premierleague.com`, og gir anbefalinger for startoppstilling, waiver/free agent-mål,
bytter og trades.

Tilgjengelig som:
- **CLI** (`main.py`) – tabeller rett i terminalen
- **Nettside** (`app.py`) – Flask-app du åpner i nettleseren

## Oppsett

1. Lag et virtuelt miljø og installer avhengigheter:

   ```bash
   python -m venv .venv
   .venv\Scripts\activate      # Windows
   pip install -r requirements.txt
   ```

2. Kopier `.env.example` til `.env`:

   ```bash
   copy .env.example .env
   ```

3. Fyll inn verdiene i `.env`:

   - **`PL_COOKIE_HEADER`** – hele `Cookie`-headeren fra en innlogget forespørsel mot
     `draft.premierleague.com` (fungerer også for Google/SSO-innlogging):
     1. Logg inn på [draft.premierleague.com](https://draft.premierleague.com)
     2. Åpne DevTools (F12) → fanen **Network**
     3. Last siden på nytt, finn en forespørsel til `api/game` eller `api/element-status`
     4. Under **Request Headers**, kopier hele verdien av `Cookie`
   - **`PL_ENTRY_ID`** – lag-ID-en din, synlig i cookien som `activeEntry`, eller i URL-en på
     "My Team"-siden.

## Kjøre applikasjonen

**CLI:**

```bash
python main.py
```

**Nettside:**

```bash
python app.py
```

Åpne deretter [http://127.0.0.1:5000](http://127.0.0.1:5000) i nettleseren.

## Hva verktøyet viser

- Anbefalt startoppstilling og benk for neste gameweek, basert på form, fixture difficulty (FDR)
  og spilletilgjengelighet
- Ledige spillere (free agents) verdt å hente inn
- Forslag til bytter mellom laget ditt og ledige spillere
- Ligaoversikt med poeng og lagoppsett for alle managere i ligaen
- Waiver/transfer-historikk og foreslåtte trades mellom managere
- Trade-muligheter basert på hva andre managere eier
- Waiver-timing – din prioritet og risiko for å bli forbigått på mål du er interessert i
- Varsel når en spiller har byttet klubb siden forrige kjøring (fanger også bytter internt i
  Premier League, som FPL sitt API ikke flagger direkte)

## Merk

- `PL_COOKIE_HEADER` utløper med jevne mellomrom – hent en ny fra DevTools hvis du får
  innloggingsfeil.
- `team_change_cache.json` er en lokal cache verktøyet bruker for å oppdage klubbytter mellom
  kjøringer. Den er ignorert av git.
