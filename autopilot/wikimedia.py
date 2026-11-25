"""Freie Wikimedia-Quellen neben Wikipedia (alle kostenlos, ohne Konto, offene Lizenz):

- Wikiquote:   belegte Zitate. Prüft, ob ein Zitat wirklich von der Person stammt, und übernimmt den
               belegten Wortlaut. Abschnitte wie "Falsch zugeschrieben" werden nie verwendet.
- Wikisource:  Originaltexte gemeinfreier Werke (Grimms Märchen, Sagen, Fabeln, Gedichte) als Vorlage
               für Nacherzählungen.
- Wikivoyage:  Reiseführer-Artikel als Faktenquelle für Wissens-Reels über Reiseziele.
"""
import difflib
import random
import re
import time

import requests

from .einstellungen import KitFehler

API = "https://de.{projekt}.org/w/api.php"
NAMEN = {"wikiquote": "Wikiquote", "wikisource": "Wikisource", "wikivoyage": "Wikivoyage"}

HTTP = requests.Session()
HTTP.headers["User-Agent"] = "Insta-Autopilot/2.0 (Zitate und Texte aus Wikimedia-Projekten)"

# Abschnitte auf Wikiquote, die KEINE belegten Zitate der Person enthalten
NICHT_VON_DER_PERSON = re.compile(r"zugeschrieben|über |zitate mit bezug|über ihn|über sie|weblinks|quellen|"
                                  r"einzelnachweise|literatur|siehe auch|anmerkung|nachweis", re.IGNORECASE)


def _api(projekt, params, http=None):
    params = {"format": "json", "formatversion": 2, **params}
    http = http or HTTP
    for versuch in range(3):
        try:
            resp = http.get(API.format(projekt=projekt), params=params, timeout=30)
        except requests.RequestException:
            time.sleep(4 * (versuch + 1))
            continue
        if resp.status_code == 429 or resp.status_code >= 500:
            time.sleep(4 * (versuch + 1))
            continue
        resp.raise_for_status()
        return resp.json()
    raise KitFehler(f"{NAMEN.get(projekt, projekt)} ist gerade nicht erreichbar. Beim nächsten Lauf neuer Versuch.")


def seite(projekt, titel, http=None):
    """(Titel, Text, URL) einer Seite oder None. Folgt Weiterleitungen, keine Begriffsklärungen."""
    if not titel or len(titel) > 150:
        return None
    daten = _api(projekt, {"action": "query", "prop": "extracts|pageprops|info", "explaintext": 1,
                           "exsectionformat": "wiki", "redirects": 1, "titles": titel, "inprop": "url",
                           "ppprop": "disambiguation"}, http)
    seiten = daten.get("query", {}).get("pages", [])
    if not seiten or seiten[0].get("missing") or "disambiguation" in seiten[0].get("pageprops", {}):
        return None
    s = seiten[0]
    text = re.sub(r"\n{3,}", "\n\n", s.get("extract", "")).strip()
    return (s["title"], text, s.get("fullurl", "")) if text else None


def suchen(projekt, begriff, http=None, anzahl=5):
    daten = _api(projekt, {"action": "query", "list": "search", "srsearch": begriff, "srnamespace": 0,
                           "srlimit": anzahl}, http)
    return [t["title"] for t in daten.get("query", {}).get("search", [])]


def _norm(t):
    t = t.lower().replace("ß", "ss")
    t = re.sub(r"[„“”\"‚‘’'»«]", "", t)
    return " ".join(re.sub(r"[^a-zäöü0-9 ]", " ", t).split())


def _aehnlich(a, b):
    return difflib.SequenceMatcher(None, _norm(a), _norm(b)).ratio()


# ---------------------------------------------------------------- Wikiquote

def belegte_zitate(autor, http=None):
    """(Seitentitel, [belegte Zitate]) einer Person auf Wikiquote, oder None, wenn es keine Seite gibt."""
    s = seite("wikiquote", autor, http)
    if not s:  # z.B. "Goethe" -> "Johann Wolfgang von Goethe"
        nachname = _norm(autor).split()[-1:] or [""]
        treffer = [t for t in suchen("wikiquote", autor, http, 3) if nachname[0] and nachname[0] in _norm(t)]
        s = seite("wikiquote", treffer[0], http) if treffer else None
    if not s:
        return None
    titel, text, _ = s
    zitate, aktiv = [], True
    for zeile in text.split("\n"):
        z = zeile.strip()
        kopf = re.match(r"^=+\s*(.*?)\s*=+$", z)
        if kopf:
            aktiv = not NICHT_VON_DER_PERSON.search(kopf.group(1))
            continue
        if not aktiv or not 15 <= len(z) <= 260:
            continue
        if re.match(r"^(-|–|—)?\s*(Quelle|Original|aus:|in:|zitiert|Brief|Vers|S\. |Seite|Kapitel)", z, re.IGNORECASE):
            continue
        # Quellenangabe hinter dem Zitat abschneiden: „Zitat." - Werk, S. 12
        m = re.match(r'^[„"»‚]?(.+?[.!?…]?)[“"«‘]\s*(?:[-–—(\[].*)?$', z)
        z = (m.group(1) if m else z).strip("„“\"»«").strip()
        if len(z.split()) >= 4 and not z.endswith(":"):
            zitate.append(z)
    return titel, zitate


def zitat_pruefen(text, autor, http=None):
    """Prüft ein Zitat auf Wikiquote.
    Rückgabe: ("ok", belegter Wortlaut, Seitentitel) | ("falsch", [Auswahl belegter Zitate], Seitentitel)
              | ("unbekannt", None, None) wenn es zur Person keine Wikiquote-Seite gibt."""
    erg = belegte_zitate(autor, http)
    if not erg:
        return "unbekannt", None, None
    titel, zitate = erg
    if not zitate:
        return "unbekannt", None, titel
    ziel = _norm(text)
    best, wert = None, 0.0
    for z in zitate:
        nz = _norm(z)
        if ziel and ziel in nz and len(ziel) >= 0.6 * len(nz):
            return "ok", z, titel
        r = difflib.SequenceMatcher(None, ziel, nz).ratio()
        if r > wert:
            best, wert = z, r
    if wert >= 0.82:
        return "ok", best, titel
    kurz = [z for z in zitate if len(z.split()) <= 30]
    random.shuffle(kurz)
    return "falsch", kurz[:25], titel


# ---------------------------------------------------------------- Wikisource

def originaltext(titel, herkunft="", http=None, min_zeichen=600):
    """Sucht den Originaltext einer überlieferten Geschichte auf Wikisource.
    (Seitentitel, Text, URL) oder None."""
    kern = re.sub(r"^(Die|Der|Das)\s+", "", titel.strip())
    kandidaten = [titel, kern] + suchen("wikisource", f"{kern} {herkunft}".strip(), http) + suchen(
        "wikisource", kern, http)
    gesehen = set()
    for k in kandidaten:
        if k in gesehen:
            continue
        gesehen.add(k)
        ohne_klammer = re.sub(r"\s*\(.*?\)\s*", " ", k).strip()
        if max(_aehnlich(ohne_klammer, titel), _aehnlich(ohne_klammer, kern)) < 0.6:
            continue
        s = seite("wikisource", k, http)
        if s and len(s[1]) >= min_zeichen:
            return s
    return None


# ---------------------------------------------------------------- Wikivoyage

def reiseartikel(ort, http=None, min_zeichen=800):
    s = seite("wikivoyage", ort, http)
    if not s:
        treffer = suchen("wikivoyage", ort, http, 1)
        s = seite("wikivoyage", treffer[0], http) if treffer else None
    return s if s and len(s[1]) >= min_zeichen else None
