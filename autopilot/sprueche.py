"""Sprüche für Zitat-Posts und Medien-Reels.

Drei Quellen (einstellungen.yml → texte → quelle):
- "datei":  aus inhalte/posts.csv (mitgeliefert oder eigene Sprüche)
- "ki":     eine Text-KI schreibt jeden Tag einen neuen Spruch zum Thema (Cloudflare kostenlos,
            optional Claude). Bereits gepostete Sprüche werden nicht wiederholt.
- "zitate": echte Zitate mit Quelle. Die KI wählt nur aus, sie erfindet nichts. Bei Bibelversen
            kommt der Wortlaut immer aus der Lutherbibel 1912, die dem Kit beiliegt.
"""
import re

from . import inhalte
from .einstellungen import KitFehler

SYSTEM = """Du schreibst die Texte für Bild-Posts eines deutschsprachigen Instagram-Accounts.

Beschreibung des Accounts: {beschreibung}
Thema: {thema}
Ton: {stil}

Regeln:
- Keine Zahlen, Rekorde, Jahreszahlen oder Tatsachenbehauptungen über Natur, Geschichte, Technik oder
  Wissenschaft (dafür gibt es die Quelle "Fakten"). Schreibe Gedanken, Tipps, Fragen oder Motivation.
- Ein eigener, neu formulierter kurzer Text, der zum Account passt: je nach Thema ein Spruch, ein Tipp,
  eine Frage oder ein Gedanke. 6 bis 22 Wörter, höchstens 150 Zeichen.
- Kein Zitat einer realen Person, kein Autor, keine Anführungszeichen, keine Emojis, keine Hashtags im Text.
- Muss als Bild ohne weitere Erklärung verständlich sein.
- Nichts Beleidigendes, keine Gesundheits- oder Finanzversprechen.
- Nicht ähnlich zu den bisherigen Sprüchen.

Antworte NUR mit JSON: {{"text": "...", "kategorie": "ein Wort", "hashtags": ["#...", "#...", "#...", "#..."],
 "bild": "englische Bildbeschreibung passend zum Text, 10 bis 20 Wörter, ohne Text im Bild, keine realen Personen"}}
Die hashtags: 4 bis 6 passende deutsche Hashtags, klein geschrieben."""

SYSTEM_ZITATE = """Du wählst für einen deutschsprachigen Instagram-Account jeden Tag ein ECHTES Zitat aus.

Beschreibung des Accounts: {beschreibung}
Thema: {thema}
Ton: {stil}

Regeln:
- Das Zitat muss genau zum Thema und Ton des Accounts passen. Bibelverse NUR, wenn es im Account um
  Glauben, Bibel oder Christentum geht. Sonst Zitate von Dichtern, Denkern, Schriftstellern, Forschern
  oder Sprichwörter, die zum Thema passen.
- Nur echte, sicher belegte Texte. Nichts erfinden, nichts umformulieren, keine Zitate zuschreiben, bei
  denen du unsicher bist.
- Bibelverse: trage in "stelle" die genaue Stelle ein (z.B. "Psalm 23,1", "Römer 8,28", "Jesaja 41,10"),
  am besten 1 Vers, höchstens 2. Der Wortlaut wird automatisch aus der Lutherbibel 1912 übernommen.
- Andere Zitate: nur von Personen, die vor mehr als 70 Jahren gestorben sind, oder bekannte Sprichwörter.
  Name in "autor" (bei Sprichwörtern: "Sprichwort"), Text in der bekannten deutschen Fassung.
- Höchstens 25 Wörter, kurze Zitate wirken auf Bildern am besten. Wähle Texte, die allein, ohne Zusammenhang, verständlich und berührend sind.
- Abwechslungsreich, nicht ähnlich zu den bisherigen.

Antworte NUR mit JSON: {{"text": "...", "stelle": "Bibelstelle oder leer", "autor": "Name oder leer",
 "kategorie": "ein Wort", "hashtags": ["#...", "#...", "#...", "#..."],
 "bild": "englische Bildbeschreibung passend zum Text, 10 bis 20 Wörter, ohne Text im Bild, keine realen Personen"}}
Die hashtags: 4 bis 6 passende deutsche Hashtags, klein geschrieben."""

SYSTEM_FAKTEN = """Du schreibst für einen deutschsprachigen Instagram-Account jeden Tag EINEN überraschenden Fakt
für ein Bild.

Beschreibung des Accounts: {beschreibung}
Ton: {stil}

WICHTIGSTE REGEL: Der Fakt stammt ausschließlich aus diesem Wikipedia-Artikel ("{artikel}"). Zahlen, Namen
und Daten genau wie im Artikel. Nichts dazuerfinden, nichts runden, was nicht gerundet ist.

Artikel:
{text}

Regeln: 6 bis 22 Wörter, ein ganzer Satz, überraschend oder staunenswert. Der Satz muss ohne jeden
Zusammenhang verständlich sein: Nenne das Thema im Satz (z.B. "Der Urvogel Archaeopteryx ..." statt "Bis heute
folgten ..."). Kein Fachjargon, keine Inventarnummern.
Antworte NUR mit JSON: {{"text": "...", "kategorie": "ein Wort", "hashtags": ["#...", "#...", "#...", "#..."],
 "bild": "englische Bildbeschreibung passend zum Fakt, 10 bis 20 Wörter, ohne Text im Bild, keine realen Personen"}}"""

MERKEN = 400


SPRICHWORT = ("sprichwort", "volksmund", "deutsches sprichwort", "redensart")


def _wikiquote(text, autor, http):
    """Belegten Wortlaut von Wikiquote holen. Gibt (text, autor) zurück oder wirft ValueError mit
    einer Auswahl echter Zitate, aus der die KI neu wählen soll."""
    import requests

    from . import wikimedia

    seite = "Deutsche Sprichwörter" if autor.lower() in SPRICHWORT else autor
    try:
        status, wert, titel = wikimedia.zitat_pruefen(text, seite, http)
    except (KitFehler, requests.RequestException) as exc:
        print(f"  Wikiquote nicht erreichbar ({type(exc).__name__}), Zitat ungeprüft übernommen")
        return text, autor
    if status == "ok":
        return wert, ("Sprichwort" if autor.lower() in SPRICHWORT else titel)
    if status == "falsch":
        auswahl = "\n- ".join(wert)
        raise ValueError(f"Dieses Zitat ist auf Wikiquote für {titel} nicht belegt (oder falsch zugeschrieben). "
                         f"Wähle WÖRTLICH eines dieser belegten Zitate von {titel} (oder eine andere Person):\n- {auswahl}")
    raise ValueError(f"Zu \"{autor}\" gibt es auf Wikiquote keine belegten Zitate. Wähle ein bekanntes Zitat "
                     "einer bekannten Person (oder einen Bibelvers).")


def _pruefen(daten, zitat=False, http=None):
    text = re.sub(r"\s+", " ", str(daten.get("text", ""))).strip().strip('"„“').strip()
    autor = ""
    if zitat:
        from . import bibel

        stelle = str(daten.get("stelle") or "").strip()
        if not stelle and bibel.ist_stelle(str(daten.get("autor") or "")):
            stelle = str(daten["autor"])
        if stelle:
            echt = bibel.wortlaut(stelle, text)
            if not echt:
                raise ValueError(f"Bibelstelle {stelle} gibt es nicht, bitte eine andere wählen")
            autor, text = echt
        else:
            autor = re.sub(r"\s+", " ", str(daten.get("autor") or "")).strip().lstrip("—–- ").strip()[:60]
            if not autor:
                raise ValueError("autor fehlt (Name oder 'Sprichwort')")
            text, autor = _wikiquote(text, autor, http)
            text = text.strip().strip('"„“').strip()
    grenze = (30, 200) if zitat else (26, 170)
    if not 3 <= len(text.split()) <= grenze[0] or len(text) > grenze[1]:
        raise ValueError(f"Text hat die falsche Länge ({len(text.split())} Wörter), bitte kürzer")
    if "#" in text:
        raise ValueError("Hashtags im Text")
    tags = []
    for t in daten.get("hashtags") or []:
        t = "#" + re.sub(r"[^\wäöüß]", "", str(t).lower())
        if len(t) > 2 and t not in tags:
            tags.append(t)
    return {"id": inhalte.eintrag_id(text), "text": text, "autor": autor,
            "kategorie": str(daten.get("kategorie", "")).strip()[:30], "hashtags": tags[:6], "ki": True,
            "bild": re.sub(r"\s+", " ", str(daten.get("bild", ""))).strip()[:300]}


def fakt(cfg, verlauf, chat=None, http=None, zufall=None):
    """Ein Fakt aus einem passenden Wikipedia-Artikel, mit Faktencheck. Quelle steht im Bild."""
    import random as _random

    from . import geschichten

    zufall = zufall or _random
    t = cfg["texte"]
    g = {"beschreibung": cfg.get("beschreibung") or t["thema"], "thema": t["thema"], "text_ki": t["text_ki"]}
    benutzt = verlauf.get("fakten_artikel", [])
    vorschlaege = geschichten.ideen(g, "wikipedia", benutzt, chat, n=8, zufall=zufall)
    if chat is None:
        modelle, chat = ((["claude"], lambda n, _m: geschichten._claude_chat(n)) if t["text_ki"] == "claude"
                         else (geschichten.textmodelle(), geschichten._cf_oder_pollinations))
    else:
        modelle = ["test"]
    gesehen = {inhalte.eintrag_id(x) for x in verlauf.get("ki_sprueche", [])}
    fehler = []
    for idee in vorschlaege[:3]:
        a = geschichten._wissensartikel(str(idee["titel"]).strip(), http or geschichten.HTTP)
        if not a or a[1] in benutzt:
            continue
        system = SYSTEM_FAKTEN.format(beschreibung=g["beschreibung"], stil=t["stil"] or "staunend, einfach",
                                      artikel=a[1], text=a[2][:7000])
        nachrichten = [{"role": "system", "content": system}, {"role": "user", "content": "Schreibe den Fakt."}]
        for modell in [m for m in modelle[:2] for _ in range(2)]:
            try:
                antwort = chat(nachrichten, modell)
                eintrag = _pruefen(geschichten._json_aus(antwort))
            except KitFehler:
                raise
            except Exception as exc:  # noqa: BLE001
                fehler.append(f"{modell}: {exc}")
                continue
            falsch = geschichten.faktencheck({"hook": {"text": eintrag["text"]}, "szenen": []}, a[2], chat, modell)
            if falsch or eintrag["id"] in gesehen:
                fehler.append(f"{a[1]}: Faktencheck" if falsch else f"{a[1]}: Wiederholung")
                grund = ("Das steht so nicht im Artikel: " + "; ".join(falsch)) if falsch else "Das gab es schon."
                nachrichten = nachrichten[:2] + [{"role": "assistant", "content": antwort},
                                                 {"role": "user", "content": grund + " Bitte einen anderen Fakt, "
                                                  "nur aus dem Artikel. Nur JSON."}]
                continue
            eintrag["autor"] = f"Quelle: Wikipedia ({a[1]})"
            eintrag["fakten_artikel"] = a[1]
            return eintrag
    raise KitFehler("Gerade ließ sich kein geprüfter Fakt finden. Beim nächsten Lauf neuer Versuch. "
                    + " | ".join(fehler[-3:]))


def ki_spruch(cfg, verlauf, chat=None, http=None):
    from . import geschichten

    t = cfg["texte"]
    zitat = t["quelle"] == "zitate"
    bisher = verlauf.get("ki_sprueche", [])
    gesehen = {inhalte.eintrag_id(s) for s in bisher}
    nachrichten = [{"role": "system", "content": (SYSTEM_ZITATE if zitat else SYSTEM).format(beschreibung=cfg.get("beschreibung") or t["thema"], thema=t["thema"],
                                                                 stil=t["stil"] or "kurz, direkt, in der Du-Form")},
                   {"role": "user", "content": "Bisherige Sprüche (nicht wiederholen):\n- "
                    + "\n- ".join(bisher[-60:]) if bisher else "Schreibe den ersten Spruch."}]
    if zitat:
        nachrichten[1]["content"] = nachrichten[1]["content"].replace("Schreibe den ersten Spruch.", "Wähle das erste Zitat.")
    if chat is None:
        if t["text_ki"] == "claude":
            modelle, chat = ["claude"], lambda n, _m: geschichten._claude_chat(n)
        else:
            modelle, chat = geschichten.textmodelle(), geschichten._cf_oder_pollinations
    else:
        modelle = ["test"]
    fehler = []
    for modell in modelle:
        for _ in range(3):
            antwort = None
            try:
                antwort = chat(nachrichten, modell)
                eintrag = _pruefen(geschichten._json_aus(antwort), zitat, http)
            except KitFehler:
                raise
            except Exception as exc:  # noqa: BLE001 - nochmal bzw. nächstes Modell
                fehler.append(f"{modell}: {exc}")
                if "HTTP 4" in str(exc) and "429" not in str(exc):
                    break
                if isinstance(exc, ValueError) and antwort:
                    nachrichten = nachrichten[:2] + [{"role": "assistant", "content": antwort},
                                                     {"role": "user", "content": f"Bitte korrigieren: {exc}. Nur JSON."}]
                continue
            if eintrag["id"] in gesehen:
                fehler.append(f"{modell}: Wiederholung")
                nachrichten = nachrichten[:2] + [{"role": "assistant", "content": antwort},
                                                 {"role": "user", "content": "Das gab es schon. Bitte ein anderes. Nur JSON."}]
                continue
            return eintrag
    raise KitFehler("Die KI konnte gerade keinen Spruch schreiben (" + " | ".join(fehler[-2:])
                    + "). Beim nächsten Lauf wird es erneut versucht.")


def naechster_spruch(cfg, verlauf, liste, eintraege=None, chat=None):
    """Nächster Spruch aus der Datei oder von der KI."""
    if cfg["texte"]["quelle"] == "fakten":
        return fakt(cfg, verlauf, chat)
    if cfg["texte"]["quelle"] in ("ki", "zitate"):
        return ki_spruch(cfg, verlauf, chat)
    eintraege = eintraege or inhalte.posts_laden()
    return inhalte.naechster(eintraege, verlauf, liste, cfg["reihenfolge"])


def merken(verlauf, text, artikel=""):
    verlauf["ki_sprueche"] = (verlauf.get("ki_sprueche", []) + [text])[-MERKEN:]
    if artikel:
        verlauf["fakten_artikel"] = (verlauf.get("fakten_artikel", []) + [artikel])[-MERKEN:]
