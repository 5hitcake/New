"""Inhalte (posts.csv), Verlauf (was wurde schon gepostet) und Zeitplan."""
import csv
import hashlib
import json
import os
import random
from datetime import date, datetime, timedelta

from .einstellungen import POSTS_CSV, VERLAUF, KitFehler

# ---------------------------------------------------------------- Inhalte

def eintrag_id(text):
    """Stabile ID aus dem Text: Umsortieren oder neue Zeilen bringen den Verlauf nicht durcheinander."""
    return hashlib.sha1(text.strip().encode("utf-8")).hexdigest()[:10]


def posts_laden(pfad=POSTS_CSV):
    if not os.path.exists(pfad):
        raise KitFehler("Die Datei inhalte/posts.csv fehlt.")
    with open(pfad, encoding="utf-8-sig", newline="") as f:
        probe = f.read(4096)
        f.seek(0)
        trenner = ";" if probe.count(";") >= probe.count(",") else ","
        leser = csv.DictReader(f, delimiter=trenner)
        spalten = [s.strip().lower() for s in (leser.fieldnames or [])]
        if "text" not in spalten:
            raise KitFehler("posts.csv braucht in der ersten Zeile die Überschrift 'text' (optional: autor;kategorie).")
        leser.fieldnames = spalten
        eintraege, gesehen = [], set()
        for nr, zeile in enumerate(leser, start=2):
            text = (zeile.get("text") or "").strip()
            if not text:
                continue
            if len(text) > 220:
                raise KitFehler(f"posts.csv Zeile {nr}: Text ist zu lang ({len(text)} Zeichen, max. 220).")
            eid = eintrag_id(text)
            if eid in gesehen:
                continue
            gesehen.add(eid)
            eintraege.append({
                "id": eid,
                "zeile": nr,
                "text": text,
                "autor": (zeile.get("autor") or "").strip(),
                "kategorie": (zeile.get("kategorie") or "").strip(),
            })
    if not eintraege:
        raise KitFehler("posts.csv enthält keine Texte. Trage mindestens einen Spruch ein.")
    return eintraege


# ---------------------------------------------------------------- Verlauf

def verlauf_laden(pfad=VERLAUF):
    leer = {"benutzt": {"bild": [], "reel": []}, "zuletzt": {}, "heute_bild": {}, "token_erneuert": None}
    if not os.path.exists(pfad):
        return leer
    with open(pfad, encoding="utf-8") as f:
        daten = json.load(f)
    for k, v in leer.items():
        daten.setdefault(k, v)
    daten["benutzt"].setdefault("bild", [])
    daten["benutzt"].setdefault("reel", [])
    return daten


def verlauf_speichern(daten, pfad=VERLAUF):
    os.makedirs(os.path.dirname(pfad), exist_ok=True)
    with open(pfad, "w", encoding="utf-8") as f:
        json.dump(daten, f, ensure_ascii=False, indent=2)


def naechster(eintraege, verlauf, liste, reihenfolge, zufall=random):
    """Nächster unbenutzter Eintrag. Sind alle durch, beginnt die Runde von vorn."""
    benutzt = set(verlauf["benutzt"].get(liste, []))
    frei = [e for e in eintraege if e["id"] not in benutzt] or eintraege
    return frei[0] if reihenfolge == "der_reihe_nach" else zufall.choice(frei)


def als_benutzt_markieren(verlauf, liste, eid, alle_ids):
    benutzt = [i for i in verlauf["benutzt"].get(liste, []) if i in alle_ids]
    if set(alle_ids) <= set(benutzt + [eid]):
        benutzt = []  # Runde komplett: neue Runde beginnt
    if eid not in benutzt:
        benutzt.append(eid)
    verlauf["benutzt"][liste] = benutzt


# ---------------------------------------------------------------- Zeitplan

def faellig(cfg, verlauf, jetzt=None):
    """Welche Post-Typen sind jetzt dran? Ein verspäteter Lauf am selben Tag holt nach,
    ein verpasster Tag wird nicht nachgeholt (sonst kämen alte Posts geballt)."""
    jetzt = jetzt or datetime.now(cfg["zeitzone"])
    heute = jetzt.date().isoformat()
    plan, zuletzt = cfg["plan"], verlauf.get("zuletzt", {})

    def dran(typ, uhrzeit, tage):
        return (
            jetzt.weekday() in tage
            and (jetzt.hour, jetzt.minute) >= uhrzeit
            and zuletzt.get(typ) != heute
        )

    # Die Story begleitet den Haupt-Post des Tages: das Bild, wenn heute eins geplant ist, sonst das Reel.
    tag = jetzt.weekday()
    bei = plan["story"].get("bei", "beidem")
    reihenfolge = ("bild", "reel") if bei == "beidem" else (bei,)
    haupt = next((t for t in reihenfolge if plan[t]["aktiv"] and tag in plan[t]["tage"]),
                 "bild" if plan["bild"]["aktiv"] else "reel")
    typen = []
    if plan["bild"]["aktiv"] and dran("bild", plan["bild"]["uhrzeit"], plan["bild"]["tage"]):
        typen.append("bild")
    if plan["reel"]["aktiv"] and dran("reel", plan["reel"]["uhrzeit"], plan["reel"]["tage"]):
        typen.append("reel")
    if plan["story"]["aktiv"] and plan[haupt]["aktiv"] and (bei == "beidem" or haupt == bei) and dran("story", plan[haupt]["uhrzeit"], plan[haupt]["tage"]):
        typen.append("story")  # zuletzt: nutzt das Bild bzw. Titelbild des Haupt-Posts
    return typen


def token_faellig(verlauf, heute):
    """Alle 7 Tage. Beim allerersten Lauf nur merken: Instagram verlängert erst Tokens,
    die älter als 24 Stunden sind."""
    letzte = verlauf.get("token_erneuert")
    if not letzte:
        verlauf["token_erneuert"] = heute.isoformat()
        return False
    return heute - date.fromisoformat(letzte) >= timedelta(days=7)


# ---------------------------------------------------------------- Caption

def caption_bauen(cfg, eintrag, zufall=random):
    eigene = eintrag.get("hashtags") or cfg["hashtags_kategorie"].get(eintrag.get("kategorie", ""), [])
    allgemein = [t for t in cfg["hashtags_allgemein"] if t not in eigene]
    anzahl = max(0, cfg["anzahl_hashtags"])
    aus_kategorie = zufall.sample(eigene, min(len(eigene), (anzahl + 1) // 2))
    rest = zufall.sample(allgemein, min(len(allgemein), anzahl - len(aus_kategorie)))
    tags = aus_kategorie + rest
    zufall.shuffle(tags)
    autor = f"— {eintrag['autor']}" if eintrag.get("autor") else ""
    text = cfg["caption_vorlage"].replace("\\n", "\n")
    text = text.replace("{text}", eintrag["text"]).replace("{autor}", autor).replace("{hashtags}", " ".join(tags))
    while "\n\n\n" in text:  # leere Autor-Zeile nicht als Lücke stehen lassen
        text = text.replace("\n\n\n", "\n\n")
    return text.strip()[:2200]
