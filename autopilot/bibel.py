"""Bibeltexte im genauen Wortlaut: Lutherbibel 1912 (gemeinfrei), liegt dem Kit bei.

Die KI schlägt nur die Stelle vor (z.B. "Psalm 23,1"), der Text kommt immer aus der Lutherbibel.
So wird kein Vers falsch zitiert.
"""
import difflib
import gzip
import json
import os
import re
from functools import lru_cache

from .einstellungen import ROOT

DATEI = os.path.join(ROOT, "daten", "luther1912.json.gz")
UEBERSETZUNG = "Luther 1912"

# (Kürzel in der Datei, Anzeigename, weitere Schreibweisen)
BUECHER = [
    ("Gen", "1. Mose", "genesis 1mose 1mo gen"), ("Exod", "2. Mose", "exodus 2mose 2mo ex"),
    ("Lev", "3. Mose", "levitikus 3mose 3mo lev"), ("Num", "4. Mose", "numeri 4mose 4mo num"),
    ("Deut", "5. Mose", "deuteronomium 5mose 5mo dtn"), ("Josh", "Josua", "jos"), ("Judg", "Richter", "ri"),
    ("Ruth", "Rut", "ruth"), ("1Sam", "1. Samuel", "1sam 1sa"), ("2Sam", "2. Samuel", "2sam 2sa"),
    ("1Kgs", "1. Könige", "1kön 1koenige 1kon 1kö"), ("2Kgs", "2. Könige", "2kön 2koenige 2kon 2kö"),
    ("1Chr", "1. Chronik", "1chr 1chronika"), ("2Chr", "2. Chronik", "2chr 2chronika"), ("Ezra", "Esra", "esr"),
    ("Neh", "Nehemia", "neh"), ("Esth", "Ester", "esther est"), ("Job", "Hiob", "ijob hi"),
    ("Ps", "Psalm", "psalmen ps psalter"), ("Prov", "Sprüche", "sprichwörter spr sprueche"),
    ("Eccl", "Prediger", "kohelet pred koh"), ("Song", "Hohelied", "hld hoheslied"), ("Isa", "Jesaja", "jes"),
    ("Jer", "Jeremia", "jer"), ("Lam", "Klagelieder", "klgl klagelied"), ("Ezek", "Hesekiel", "ezechiel hes ez"),
    ("Dan", "Daniel", "dan"), ("Hos", "Hosea", "hos"), ("Joel", "Joel", "joe"), ("Amos", "Amos", "am"),
    ("Obad", "Obadja", "obd ob"), ("Jonah", "Jona", "jonas jon"), ("Mic", "Micha", "mi"), ("Nah", "Nahum", "nah"),
    ("Hab", "Habakuk", "hab"), ("Zeph", "Zefanja", "zephanja zef"), ("Hag", "Haggai", "hag"),
    ("Zech", "Sacharja", "sach"), ("Mal", "Maleachi", "mal"), ("Matt", "Matthäus", "matthaeus mt matth"),
    ("Mark", "Markus", "mk mark"), ("Luke", "Lukas", "lk luk"), ("John", "Johannes", "joh johannesevangelium"),
    ("Acts", "Apostelgeschichte", "apg"), ("Rom", "Römer", "roemer röm rom"),
    ("1Cor", "1. Korinther", "1kor 1korinther"), ("2Cor", "2. Korinther", "2kor 2korinther"),
    ("Gal", "Galater", "gal"), ("Eph", "Epheser", "eph"), ("Phil", "Philipper", "phil"), ("Col", "Kolosser", "kol"),
    ("1Thess", "1. Thessalonicher", "1thess 1th"), ("2Thess", "2. Thessalonicher", "2thess 2th"),
    ("1Tim", "1. Timotheus", "1tim"), ("2Tim", "2. Timotheus", "2tim"), ("Titus", "Titus", "tit"),
    ("Phlm", "Philemon", "phlm phm"), ("Heb", "Hebräer", "hebraeer hebr"), ("Jas", "Jakobus", "jak"),
    ("1Pet", "1. Petrus", "1petr 1pt"), ("2Pet", "2. Petrus", "2petr 2pt"), ("1John", "1. Johannes", "1joh"),
    ("2John", "2. Johannes", "2joh"), ("3John", "3. Johannes", "3joh"), ("Jude", "Judas", "jud"),
    ("Rev", "Offenbarung", "offb offenbarung des johannes apokalypse"),
]


def _schluessel(name):
    """'1. Mose' / '1 Mose' / '1.Mo' -> '1mose' bzw. '1mo'."""
    n = name.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return re.sub(r"[^a-z0-9]", "", n)


@lru_cache(maxsize=1)
def _namen():
    karte = {}
    for kurz, anzeige, weitere in BUECHER:
        for n in [anzeige, kurz] + weitere.split():
            karte[_schluessel(n)] = (kurz, anzeige)
    return karte


@lru_cache(maxsize=1)
def _bibel():
    with gzip.open(DATEI, "rt", encoding="utf-8") as f:
        return json.load(f)["buecher"]


STELLE = re.compile(r"^\s*(?P<buch>(?:[1-3]\s*\.?\s*)?[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß. ]*?)\s*"
                    r"(?P<kap>\d+)(?:\s*[,:]\s*(?P<von>\d+)(?:\s*[-–]\s*(?P<bis>\d+))?|\s*[-–]\s*(?P<kapbis>\d+))?\s*$")


def stelle_lesen(stelle):
    """'Psalm 23,1-4' -> (Kürzel, Anzeigename, Kapitel, Vers von, Vers bis, Kapitel bis) oder None.
    Ohne Vers: das ganze Kapitel (bzw. Kapitel 6-9)."""
    stelle = re.sub(r"\(.*?\)", "", str(stelle or "")).strip().rstrip(".")
    stelle = re.sub(r"\b(?:Luther|Lutherbibel)\b.*$", "", stelle, flags=re.IGNORECASE).strip()
    m = STELLE.match(stelle)
    if not m:
        return None
    buch = _namen().get(_schluessel(m["buch"]))
    if not buch:
        return None
    kap = int(m["kap"])
    von = int(m["von"]) if m["von"] else None
    bis = int(m["bis"]) if m["bis"] else von
    kapbis = int(m["kapbis"]) if m["kapbis"] else kap
    return buch[0], buch[1], kap, von, bis, kapbis


def ist_stelle(text):
    return stelle_lesen(text) is not None


def text(stelle, max_zeichen=9000):
    """(schöne Stelle, Text) im Wortlaut der Lutherbibel 1912, oder None wenn es die Stelle nicht gibt."""
    s = stelle_lesen(stelle)
    if not s:
        return None
    kurz, anzeige, kap, von, bis, kapbis = s
    kapitel = _bibel().get(kurz, [])
    if not 1 <= kap <= len(kapitel):
        return None
    if von is None:  # ganze Kapitel, z.B. für Geschichten
        kapbis = min(max(kap, kapbis), len(kapitel), kap + 4)
        teile = []
        for k in range(kap, kapbis + 1):
            teile.append(" ".join(f"{i}. {v}" for i, v in enumerate(kapitel[k - 1], 1) if v))
        schoen = f"{anzeige} {kap}" + (f"–{kapbis}" if kapbis > kap else "")
        return schoen, "\n\n".join(teile)[:max_zeichen]
    verse = kapitel[kap - 1]
    bis = max(von, min(bis or von, len(verse), von + 40))
    if not 1 <= von <= len(verse):
        return None
    inhalt = " ".join(v for v in verse[von - 1:bis] if v).strip()
    schoen = f"{anzeige} {kap},{von}" + (f"–{bis}" if bis > von else "")
    return schoen, inhalt[:max_zeichen]


def _norm(t):
    return re.sub(r"[^a-zäöüß ]", "", t.lower().replace("ß", "ss")).split()


VORSPANN = re.compile(r"^(Ein Psalm Davids?|Ein Psalm|Ein Lied[^.;:]*|Ein Gebet[^.;:]*|Dem Vorsänger[^.;:]*|"
                      r"Eine Unterweisung[^.;:]*)[.;:,]\s*", re.IGNORECASE)


def wortlaut(stelle, vorschlag="", max_woerter=30):
    """Genauer Bibeltext zu einer Stelle, ohne Psalm-Überschrift. Ist der Vers zu lang für ein Bild,
    wird der Teil des echten Verses genommen, den die KI gemeint hat.
    Gibt (Stelle, Text) oder None zurück."""
    t = text(stelle, 2000)
    if not t:
        return None
    schoen, inhalt = t
    inhalt = VORSPANN.sub("", inhalt).strip()
    if vorschlag and len(inhalt.split()) > max_woerter:  # nur kürzen, wenn der Vers zu lang ist
        teile = [x.strip() for x in re.split(r"(?<=[.;:!?])\s+", inhalt) if x.strip()]
        ziel = " ".join(_norm(vorschlag))
        best, wert = inhalt, 0.0
        for i in range(len(teile)):
            for j in range(i, len(teile)):
                stueck = " ".join(teile[i:j + 1])
                r = difflib.SequenceMatcher(None, ziel, " ".join(_norm(stueck))).ratio()
                if r > wert:
                    best, wert = stueck, r
        if wert >= 0.55:
            inhalt = best
    inhalt = inhalt[0].upper() + inhalt[1:] if inhalt else inhalt
    if inhalt and inhalt[-1] in ",;:":
        inhalt = inhalt[:-1] + "."
    return schoen, inhalt
