"""Account-Profil: Aus der freien Beschreibung in einstellungen.yml (account → beschreibung) leitet
die Text-KI einmalig Thema, Ton, Bildstil, Bildmotiv, Hashtags und Suchbegriffe ab.

Das Ergebnis wird im Verlauf gespeichert und erst neu erzeugt, wenn sich die Beschreibung ändert.
Alles, was in einstellungen.yml ausdrücklich eingetragen ist, hat Vorrang vor dem Profil.
"""
import hashlib
import re

from .einstellungen import KitFehler

SYSTEM = """Du richtest einen automatischen Instagram-Account ein. Lies die Beschreibung des Nutzers und
leite daraus die Einstellungen ab. Alles auf Deutsch, außer bildstil, bildmotiv und suchbegriffe_englisch.

Antworte NUR mit JSON in genau diesem Format:
{"thema": "ein Satz, worum es auf dem Account geht",
 "stil": "Ton der Texte in wenigen Worten, z.B. locker und humorvoll, Du-Form",
 "bildstil": "englisch: Bildstil für KI-Bilder, z.B. cinematic photo, warm light, muted colors",
 "bildmotiv": "englisch: typisches Motiv passend zum Thema, 8 bis 15 Wörter",
 "hashtags": ["#...", 8 passende deutsche Hashtags, klein geschrieben],
 "suchbegriffe": ["5 deutsche Wikipedia-Suchbegriffe zum Thema"],
 "suchbegriffe_englisch": ["3 englische Wikipedia-Suchbegriffe zum Thema"]}

Halte dich an das, was der Nutzer schreibt. Erfinde kein anderes Thema."""


def _hash(text):
    return hashlib.sha1(text.strip().encode("utf-8")).hexdigest()[:12]


def _liste(werte, tags=False):
    aus = []
    for w in werte or []:
        w = str(w).strip()
        if tags:
            w = "#" + re.sub(r"[^\wäöüß]", "", w.lower())
            if len(w) < 3:
                continue
        if w and w not in aus:
            aus.append(w)
    return aus


def ableiten(beschreibung, text_ki="cloudflare", chat=None):
    from . import geschichten

    nachrichten = [{"role": "system", "content": SYSTEM},
                   {"role": "user", "content": f"Beschreibung des Accounts:\n{beschreibung.strip()}"}]
    if chat is None:
        if text_ki == "claude":
            modelle, chat = ["claude"], lambda n, _m: geschichten._claude_chat(n)
        else:
            modelle, chat = geschichten.CF_TEXT_MODELLE, geschichten._cloudflare_chat
    else:
        modelle = ["test"]
    fehler = []
    for modell in modelle:
        for _ in range(2):
            try:
                d = geschichten._json_aus(chat(nachrichten, modell))
                p = {
                    "thema": str(d.get("thema", "")).strip(),
                    "stil": str(d.get("stil", "")).strip(),
                    "bildstil": str(d.get("bildstil", "")).strip(),
                    "bildmotiv": str(d.get("bildmotiv", "")).strip(),
                    "hashtags": _liste(d.get("hashtags"), tags=True)[:10],
                    "suchbegriffe": _liste(d.get("suchbegriffe"))[:8],
                    "suchbegriffe_englisch": _liste(d.get("suchbegriffe_englisch"))[:5],
                }
                if not p["thema"] or not p["bildstil"]:
                    raise ValueError("unvollständig")
                return p
            except KitFehler:
                raise
            except Exception as exc:  # noqa: BLE001 - nochmal bzw. nächstes Modell
                fehler.append(f"{modell}: {exc}")
                if "HTTP 4" in str(exc) and "429" not in str(exc):
                    break
    raise KitFehler("Aus deiner Beschreibung konnte die KI gerade kein Profil ableiten ("
                    + " | ".join(fehler[-2:]) + "). Beim nächsten Lauf wird es erneut versucht.")


def holen(cfg, verlauf, chat=None):
    """Profil aus dem Verlauf oder neu von der KI. None, wenn es keine Beschreibung gibt."""
    beschreibung = cfg.get("beschreibung", "")
    if not beschreibung:
        return None
    gespeichert = verlauf.get("profil") or {}
    if gespeichert.get("hash") == _hash(beschreibung):
        return gespeichert
    p = ableiten(beschreibung, cfg["texte"]["text_ki"], chat)
    p["hash"] = _hash(beschreibung)
    verlauf["profil"] = p
    return p


def anwenden(cfg, p):
    """Füllt leere Einstellungen aus dem Profil. Eingetragene Werte bleiben."""
    if not p:
        return cfg
    t, g = cfg["texte"], cfg["geschichten"]
    t["thema"] = t["thema"] or p["thema"]
    t["stil"] = t["stil"] or p["stil"]
    g["thema"] = g["thema"] or p["thema"]
    g["bildstil"] = g["bildstil"] or p["bildstil"]
    if not g["suchbegriffe"] and not g["suchbegriffe_englisch"] and not g["startartikel"]:
        g["suchbegriffe"], g["suchbegriffe_englisch"] = p["suchbegriffe"], p["suchbegriffe_englisch"]
    if not g["hashtags"]:
        g["hashtags"] = p["hashtags"][:4]
    if not cfg["hashtags_allgemein"]:
        cfg["hashtags_allgemein"] = p["hashtags"]
    cfg["bildstil"] = cfg["bildstil"] or p["bildstil"]
    cfg["bildmotiv"] = cfg["bildmotiv"] or p["bildmotiv"]
    return cfg


def zusammenfassung(cfg):
    return (f"So versteht die KI deinen Account: Thema „{cfg['texte']['thema']}“, Ton „{cfg['texte']['stil']}“, "
            f"Bildstil „{cfg['bildstil']}“, Hashtags {' '.join(cfg['hashtags_allgemein'][:8])}")
