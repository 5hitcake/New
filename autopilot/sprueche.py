"""Sprüche für Zitat-Posts und Medien-Reels.

Zwei Quellen (einstellungen.yml → texte → quelle):
- "datei": aus inhalte/posts.csv (mitgeliefert oder eigene Sprüche)
- "ki":    eine Text-KI schreibt jeden Tag einen neuen Spruch zum Thema (Cloudflare kostenlos,
           optional Claude). Bereits gepostete Sprüche werden nicht wiederholt.
"""
import re

from . import inhalte
from .einstellungen import KitFehler

SYSTEM = """Du schreibst die Texte für Bild-Posts eines deutschsprachigen Instagram-Accounts.

Beschreibung des Accounts: {beschreibung}
Thema: {thema}
Ton: {stil}

Regeln:
- Ein eigener, neu formulierter kurzer Text, der zum Account passt: je nach Thema ein Spruch, ein
  überraschender Fakt, ein Tipp oder ein Gedanke. 6 bis 22 Wörter, höchstens 150 Zeichen.
- Kein Zitat einer realen Person, kein Autor, keine Anführungszeichen, keine Emojis, keine Hashtags im Text.
- Muss als Bild ohne weitere Erklärung verständlich sein.
- Nichts Beleidigendes, keine Gesundheits- oder Finanzversprechen.
- Nicht ähnlich zu den bisherigen Sprüchen.

Antworte NUR mit JSON: {{"text": "...", "kategorie": "ein Wort", "hashtags": ["#...", "#...", "#...", "#..."],
 "bild": "englische Bildbeschreibung passend zum Text, 10 bis 20 Wörter, ohne Text im Bild, keine realen Personen"}}
Die hashtags: 4 bis 6 passende deutsche Hashtags, klein geschrieben."""

MERKEN = 400


def _pruefen(daten):
    text = re.sub(r"\s+", " ", str(daten.get("text", ""))).strip().strip('"„“').strip()
    if not 3 <= len(text.split()) <= 26 or len(text) > 170:
        raise ValueError(f"Spruch hat die falsche Länge ({len(text)} Zeichen)")
    if "#" in text:
        raise ValueError("Hashtags im Text")
    tags = []
    for t in daten.get("hashtags") or []:
        t = "#" + re.sub(r"[^\wäöüß]", "", str(t).lower())
        if len(t) > 2 and t not in tags:
            tags.append(t)
    return {"id": inhalte.eintrag_id(text), "text": text, "autor": "",
            "kategorie": str(daten.get("kategorie", "")).strip()[:30], "hashtags": tags[:6], "ki": True,
            "bild": re.sub(r"\s+", " ", str(daten.get("bild", ""))).strip()[:300]}


def ki_spruch(cfg, verlauf, chat=None):
    from . import geschichten

    t = cfg["texte"]
    bisher = verlauf.get("ki_sprueche", [])
    gesehen = {inhalte.eintrag_id(s) for s in bisher}
    nachrichten = [{"role": "system", "content": SYSTEM.format(beschreibung=cfg.get("beschreibung") or t["thema"], thema=t["thema"],
                                                                 stil=t["stil"] or "kurz, direkt, in der Du-Form")},
                   {"role": "user", "content": "Bisherige Sprüche (nicht wiederholen):\n- "
                    + "\n- ".join(bisher[-60:]) if bisher else "Schreibe den ersten Spruch."}]
    if chat is None:
        if t["text_ki"] == "claude":
            modelle, chat = ["claude"], lambda n, _m: geschichten._claude_chat(n)
        else:
            modelle, chat = geschichten.CF_TEXT_MODELLE, geschichten._cloudflare_chat
    else:
        modelle = ["test"]
    fehler = []
    for modell in modelle:
        for _ in range(3):
            try:
                eintrag = _pruefen(geschichten._json_aus(chat(nachrichten, modell)))
            except KitFehler:
                raise
            except Exception as exc:  # noqa: BLE001 - nochmal bzw. nächstes Modell
                fehler.append(f"{modell}: {exc}")
                if "HTTP 4" in str(exc) and "429" not in str(exc):
                    break
                continue
            if eintrag["id"] in gesehen:
                fehler.append(f"{modell}: Wiederholung")
                continue
            return eintrag
    raise KitFehler("Die KI konnte gerade keinen Spruch schreiben (" + " | ".join(fehler[-2:])
                    + "). Beim nächsten Lauf wird es erneut versucht.")


def naechster_spruch(cfg, verlauf, liste, eintraege=None, chat=None):
    """Nächster Spruch aus der Datei oder von der KI."""
    if cfg["texte"]["quelle"] == "ki":
        return ki_spruch(cfg, verlauf, chat)
    eintraege = eintraege or inhalte.posts_laden()
    return inhalte.naechster(eintraege, verlauf, liste, cfg["reihenfolge"])


def merken(verlauf, text):
    verlauf["ki_sprueche"] = (verlauf.get("ki_sprueche", []) + [text])[-MERKEN:]
