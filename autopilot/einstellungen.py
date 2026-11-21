"""Liest einstellungen.yml und prüft sie mit verständlichen Fehlermeldungen."""
import os
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
EINSTELLUNGEN = os.path.join(ROOT, "einstellungen.yml")
POSTS_CSV = os.path.join(ROOT, "inhalte", "posts.csv")
HINTERGRUENDE = os.path.join(ROOT, "hintergruende")
MUSIK = os.path.join(ROOT, "musik")
SCHRIFTEN = os.path.join(ROOT, "schriften")
AUSGABE = os.path.join(ROOT, "ausgabe")
VERLAUF = os.path.join(ROOT, "daten", "verlauf.json")
MEDIEN = os.path.join(ROOT, "medien")
STIMMEN = os.path.join(ROOT, ".stimmen")  # Download-Ordner für die Sprecher-Stimme (nicht im Repo)

WOCHENTAGE = ["mo", "di", "mi", "do", "fr", "sa", "so"]
TYPEN = ("bild", "reel", "story")
INHALTSARTEN = ("zitate", "geschichten", "eigene_medien")
QUELLEN = ("wikipedia", "fiktion", "eigene_texte")
EIGENE_TEXTE = os.path.join(ROOT, "inhalte", "geschichten.txt")


class KitFehler(Exception):
    """Fehler, den ein Anfänger selbst beheben kann. Die Meldung erklärt, wie."""


def _farbe(wert, wo):
    if not isinstance(wert, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", wert.strip()):
        raise KitFehler(f"{wo}: '{wert}' ist keine gültige Farbe. Format: \"#RRGGBB\", z.B. \"#FFFFFF\".")
    return wert.strip()


def _uhrzeit(wert, wo):
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", str(wert).strip())
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise KitFehler(f"{wo}: '{wert}' ist keine gültige Uhrzeit. Format: \"18:00\" (mit Anführungszeichen).")
    return int(m.group(1)), int(m.group(2))


def _tage(wert, wo):
    if not isinstance(wert, list) or not wert:
        raise KitFehler(f"{wo}: Bitte die Tage als Liste angeben, z.B. [mo, mi, fr].")
    tage = []
    for t in wert:
        t = str(t).strip().lower()[:2]
        if t not in WOCHENTAGE:
            raise KitFehler(f"{wo}: '{t}' ist kein Wochentag. Erlaubt: {', '.join(WOCHENTAGE)}.")
        tage.append(WOCHENTAGE.index(t))
    return sorted(set(tage))


def laden(pfad=EINSTELLUNGEN):
    try:
        with open(pfad, encoding="utf-8") as f:
            roh = yaml.safe_load(f) or {}
    except FileNotFoundError as exc:
        raise KitFehler("Die Datei einstellungen.yml fehlt im Hauptordner.") from exc
    except yaml.YAMLError as exc:
        zeile = getattr(getattr(exc, "problem_mark", None), "line", None)
        wo = f" (ungefähr Zeile {zeile + 1})" if zeile is not None else ""
        raise KitFehler(
            f"einstellungen.yml hat einen Tippfehler{wo}. Häufige Ursachen: Einrückung verändert, "
            "Anführungszeichen vergessen oder ein Doppelpunkt fehlt."
        ) from exc
    return pruefen(roh)


def pruefen(roh):
    name = str(roh.get("instagram_name", "")).strip().lstrip("@")
    if not name or name == "dein_account_name":
        raise KitFehler("Trage in einstellungen.yml bei instagram_name deinen Instagram-Namen ein (ohne @).")

    konto_id = str(roh.get("instagram_konto_id") or "").strip()
    if konto_id and not konto_id.isdigit():
        raise KitFehler("instagram_konto_id darf nur aus Ziffern bestehen (oder leer bleiben).")

    zp = roh.get("zeitplan") or {}
    try:
        zone = ZoneInfo(str(zp.get("zeitzone", "Europe/Berlin")))
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise KitFehler(f"Zeitzone '{zp.get('zeitzone')}' unbekannt. Beispiel: \"Europe/Berlin\".") from exc

    plan = {}
    for typ in ("bild", "reel"):
        teil = zp.get(typ) or {}
        plan[typ] = {
            "aktiv": bool(teil.get("aktiv", False)),
            "tage": _tage(teil.get("tage", WOCHENTAGE), f"zeitplan → {typ} → tage"),
            "uhrzeit": _uhrzeit(teil.get("uhrzeit", "18:00"), f"zeitplan → {typ} → uhrzeit"),
        }
    plan["story"] = {"aktiv": bool((zp.get("story") or {}).get("aktiv", False))}

    reihenfolge = str(roh.get("reihenfolge", "zufall")).strip()
    if reihenfolge not in ("zufall", "der_reihe_nach"):
        raise KitFehler("reihenfolge muss \"zufall\" oder \"der_reihe_nach\" sein.")

    d = roh.get("design") or {}
    schrift = str(d.get("schrift", "Poppins-Bold")).removesuffix(".ttf")
    if not os.path.exists(os.path.join(SCHRIFTEN, schrift + ".ttf")):
        raise KitFehler(f"Schrift '{schrift}' nicht gefunden. Lege {schrift}.ttf in den Ordner schriften.")
    abdunkeln = d.get("abdunkeln", 40)
    if not isinstance(abdunkeln, (int, float)) or not 0 <= abdunkeln <= 100:
        raise KitFehler("design → abdunkeln muss eine Zahl zwischen 0 und 100 sein.")
    verlaeufe = []
    for paar in d.get("farbverlaeufe") or [["#0F2027", "#2C5364"]]:
        if not isinstance(paar, list) or len(paar) != 2:
            raise KitFehler("design → farbverlaeufe: jedes Paar braucht genau 2 Farben, z.B. [\"#000000\", \"#333333\"].")
        verlaeufe.append((_farbe(paar[0], "design → farbverlaeufe"), _farbe(paar[1], "design → farbverlaeufe")))

    cap = roh.get("caption") or {}
    tags = roh.get("hashtags") or {}
    reel = roh.get("reel") or {}
    lautstaerke = float(reel.get("musik_lautstaerke", 0.3))
    if not 0 <= lautstaerke <= 1:
        raise KitFehler("reel → musik_lautstaerke muss zwischen 0.0 und 1.0 liegen.")

    art = str(roh.get("inhaltsart", "zitate")).strip().lower()
    if art not in INHALTSARTEN:
        raise KitFehler(f"inhaltsart '{art}' gibt es nicht. Erlaubt: {', '.join(INHALTSARTEN)}.")
    if art != "zitate":
        plan["bild"]["aktiv"] = False  # Feed-Bilder gibt es nur bei Zitaten
    g = roh.get("geschichten") or {}
    sprecher = str(g.get("sprecher", "thorsten")).strip().lower()
    if sprecher not in ("thorsten", "aus"):
        raise KitFehler("geschichten → sprecher muss \"thorsten\" oder \"aus\" sein.")
    text_ki = str(g.get("text_ki", "cloudflare")).strip().lower()
    if text_ki not in ("cloudflare", "claude"):
        raise KitFehler("geschichten → text_ki muss \"cloudflare\" oder \"claude\" sein.")
    quelle = str(g.get("quelle", "wikipedia")).strip().lower()
    if quelle not in QUELLEN:
        raise KitFehler(f"geschichten → quelle '{quelle}' gibt es nicht. Erlaubt: {', '.join(QUELLEN)}.")
    if art == "geschichten" and quelle == "wikipedia" and not (g.get("suchbegriffe") or g.get("suchbegriffe_englisch") or g.get("startartikel")):
        raise KitFehler("geschichten: Trage mindestens einen Suchbegriff oder Startartikel ein.")
    tempo = float(g.get("sprechtempo", 1.0))
    if not 0.6 <= tempo <= 1.5:
        raise KitFehler("geschichten → sprechtempo muss zwischen 0.6 und 1.5 liegen.")
    t = roh.get("texte") or {}
    texte_quelle = str(t.get("quelle", "datei")).strip().lower()
    if texte_quelle not in ("datei", "ki"):
        raise KitFehler("texte → quelle muss \"datei\" oder \"ki\" sein.")
    texte_ki = str(t.get("text_ki", "cloudflare")).strip().lower()
    if texte_ki not in ("cloudflare", "claude"):
        raise KitFehler("texte → text_ki muss \"cloudflare\" oder \"claude\" sein.")
    if texte_quelle == "ki" and not str(t.get("thema", "")).strip():
        raise KitFehler("texte → thema: Bei quelle \"ki\" bitte ein Thema eintragen, z.B. \"Fitness und gesunde Gewohnheiten\".")
    m = roh.get("eigene_medien") or {}
    pro_reel = int(m.get("pro_reel", 4))
    sek = float(m.get("sekunden_pro_clip", 2.5))
    if not 1 <= pro_reel <= 12 or not 1 <= sek <= 10:
        raise KitFehler("eigene_medien: pro_reel 1 bis 12, sekunden_pro_clip 1 bis 10.")

    return {
        "inhaltsart": art,
        "geschichten": {
            "quelle": quelle,
            "thema": str(g.get("thema", "")).strip() or "Wahre, spannende Geschichten",
            "suchbegriffe": [str(x) for x in g.get("suchbegriffe") or []],
            "suchbegriffe_englisch": [str(x) for x in g.get("suchbegriffe_englisch") or []],
            "startartikel": [str(x) for x in g.get("startartikel") or []],
            "bildstil": str(g.get("bildstil", "cinematic painting")).strip(),
            "akzentfarbe": _farbe(g.get("akzentfarbe", "#E5484D"), "geschichten → akzentfarbe"),
            "sprecher": sprecher,
            "sprechtempo": tempo,
            "text_ki": text_ki,
            "hashtags": [str(x) for x in g.get("hashtags") or []],
        },
        "texte": {
            "quelle": texte_quelle,
            "thema": str(t.get("thema", "")).strip(),
            "stil": str(t.get("stil", "")).strip() or "kurz, positiv, direkt, in der Du-Form",
            "text_ki": texte_ki,
        },
        "eigene_medien": {
            "pro_reel": pro_reel,
            "sekunden_pro_clip": sek,
            "text_einblenden": bool(m.get("text_einblenden", True)),
        },
        "instagram_name": name,
        "instagram_konto_id": konto_id or None,
        "name_im_bild": str(roh.get("name_im_bild", f"@{name}") or ""),
        "zeitzone": zone,
        "plan": plan,
        "reihenfolge": reihenfolge,
        "schrift": schrift,
        "textfarbe": _farbe(d.get("textfarbe", "#FFFFFF"), "design → textfarbe"),
        "abdunkeln": float(abdunkeln),
        "farbverlaeufe": verlaeufe,
        "caption_vorlage": str(cap.get("vorlage", "{text}\n\n{hashtags}")),
        "anzahl_hashtags": int(cap.get("anzahl_hashtags", 7)),
        "hashtags_allgemein": list(tags.get("allgemein") or []),
        "hashtags_kategorie": {str(k): list(v or []) for k, v in (tags.get("nach_kategorie") or {}).items()},
        "musik_lautstaerke": lautstaerke,
    }
