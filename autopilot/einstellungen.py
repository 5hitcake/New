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
QUELLEN = ("wissen", "wikipedia", "nacherzaehlung", "fiktion", "eigene_texte")
BILDSTILE = ("ki_mit_text", "ki_ohne_text", "text", "eigene_fotos")
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
    st = zp.get("story") or {}
    bei = str(st.get("bei", "beidem")).strip().lower()
    if bei not in ("beidem", "bild", "reel"):
        raise KitFehler("zeitplan → story → bei muss \"beidem\", \"bild\" oder \"reel\" sein.")
    plan["story"] = {"aktiv": bool(st.get("aktiv", False)), "bei": bei}

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
    g = roh.get("geschichten") or {}
    sprecher = str(g.get("sprecher", "auto")).strip().lower()
    sprecher = sprecher.replace("ü", "ue").replace("flüstern", "fluestern")
    erlaubt = ("auto", "killian", "conrad", "thorsten", "thorsten_ruhig", "thorsten_fluestern", "thorsten_muede", "karlsson", "aus")
    if sprecher not in erlaubt:
        raise KitFehler("geschichten → sprecher muss einer von diesen sein: " + ", ".join(erlaubt) + ".")
    text_ki = str(g.get("text_ki", "cloudflare")).strip().lower()
    if text_ki not in ("cloudflare", "claude"):
        raise KitFehler("geschichten → text_ki muss \"cloudflare\" oder \"claude\" sein.")
    quelle = str(g.get("quelle", "wikipedia")).strip().lower()
    if quelle not in QUELLEN:
        raise KitFehler(f"geschichten → quelle '{quelle}' gibt es nicht. Erlaubt: {', '.join(QUELLEN)}.")
    beschreibung = str((roh.get("account") or {}).get("beschreibung") or "").strip()
    if art == "geschichten" and quelle == "wikipedia" and not beschreibung and not (g.get("suchbegriffe") or g.get("suchbegriffe_englisch") or g.get("startartikel")):
        raise KitFehler("geschichten: Trage mindestens einen Suchbegriff oder Startartikel ein.")
    stimmung = str(g.get("stimmung", "auto")).strip().lower().replace("ü", "ue")
    if stimmung not in ("auto", "neutral", "duester", "ruhig"):
        raise KitFehler("geschichten → stimmung muss \"auto\", \"neutral\", \"düster\" oder \"ruhig\" sein.")
    tempo = float(g.get("sprechtempo", 1.0))
    if not 0.6 <= tempo <= 1.5:
        raise KitFehler("geschichten → sprechtempo muss zwischen 0.6 und 1.5 liegen.")
    t = roh.get("texte") or {}
    texte_quelle = str(t.get("quelle", "datei")).strip().lower()
    if texte_quelle not in ("datei", "ki", "zitate"):
        raise KitFehler("texte → quelle muss \"ki\", \"zitate\" oder \"datei\" sein.")
    texte_ki = str(t.get("text_ki", "cloudflare")).strip().lower()
    if texte_ki not in ("cloudflare", "claude"):
        raise KitFehler("texte → text_ki muss \"cloudflare\" oder \"claude\" sein.")
    if texte_quelle in ("ki", "zitate") and not str(t.get("thema", "")).strip() and not beschreibung:
        raise KitFehler("Beschreibe deinen Account in einstellungen.yml unter account → beschreibung "
                        "(oder trag bei texte → thema ein Thema ein). Daraus schreibt die KI die Texte.")
    bp = roh.get("bildpost") or {}
    from .ki_bilder import STILE

    look = str((roh.get("account") or {}).get("bildstil", "auto") or "auto").strip().lower()
    look = look.replace("ö", "oe").replace("ü", "ue").replace("ä", "ae").replace("3d-animation", "3d")
    if look != "auto" and look not in STILE:
        raise KitFehler(f"account → bildstil '{look}' gibt es nicht. Erlaubt: auto, {', '.join(STILE)}.")
    look_prompt = STILE[look][1] if look != "auto" else ""
    bildstil_post = str(bp.get("stil", "text")).strip().lower()
    if bildstil_post not in BILDSTILE:
        raise KitFehler(f"bildpost → stil '{bildstil_post}' gibt es nicht. Erlaubt: {', '.join(BILDSTILE)}.")
    mindestdauer = float(reel.get("mindestdauer", 0) or 0)
    if not 0 <= mindestdauer <= 60:
        raise KitFehler("reel → mindestdauer muss zwischen 0 und 60 Sekunden liegen.")
    szenen = int(g.get("szenen", 6))
    if not 3 <= szenen <= 10:
        raise KitFehler("geschichten → szenen muss zwischen 3 und 10 liegen.")
    m = roh.get("eigene_medien") or {}
    pro_reel = int(m.get("pro_reel", 4))
    sek = float(m.get("sekunden_pro_clip", 2.5))
    if not 1 <= pro_reel <= 12 or not 1 <= sek <= 10:
        raise KitFehler("eigene_medien: pro_reel 1 bis 12, sekunden_pro_clip 1 bis 10.")

    return {
        "inhaltsart": art,
        "geschichten": {
            "quelle": quelle,
            "beschreibung": beschreibung,
            "thema": str(g.get("thema", "")).strip(),
            "szenen": szenen,
            "suchbegriffe": [str(x) for x in g.get("suchbegriffe") or []],
            "suchbegriffe_englisch": [str(x) for x in g.get("suchbegriffe_englisch") or []],
            "startartikel": [str(x) for x in g.get("startartikel") or []],
            "bildstil": str(g.get("bildstil", "")).strip() or look_prompt,
            "akzentfarbe": _farbe(g.get("akzentfarbe", "#E5484D"), "geschichten → akzentfarbe"),
            "sprecher": sprecher,
            "sprechtempo": tempo,
            "stimmung": stimmung,
            "text_ki": text_ki,
            "hashtags": [str(x) for x in g.get("hashtags") or []],
        },
        "texte": {
            "quelle": texte_quelle,
            "thema": str(t.get("thema", "")).strip(),
            "stil": str(t.get("stil", "")).strip(),
            "text_ki": texte_ki,
        },
        "eigene_medien": {
            "pro_reel": pro_reel,
            "sekunden_pro_clip": sek,
            "text_einblenden": bool(m.get("text_einblenden", True)),
        },
        "beschreibung": beschreibung,
        "bildpost": bildstil_post,
        "bildstil": str(bp.get("bildstil", "")).strip() or look_prompt,
        "bild_look": look,
        "bildmotiv": str(bp.get("motiv", "")).strip(),
        "mindestdauer": mindestdauer,
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


def fehlende_cloudflare_secrets():
    """Namen der fehlenden Cloudflare-Secrets, leer wenn beide da sind."""
    return [n for n in ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN") if not os.environ.get(n, "").strip()]


def cloudflare_hinweis():
    fehlt = fehlende_cloudflare_secrets()
    return (f"Auf GitHub fehlt das Secret {' und '.join(fehlt)} (oder es ist leer). Name genau so schreiben, "
            "ohne Leerzeichen, und den Wert einfügen. Anleitung: Rubrik 07 Cloudflare.")



KONTINGENT_HINWEIS = ("Das kostenlose Tageskontingent der Cloudflare-KI ist für heute aufgebraucht (meist durch viele "
                      "Testläufe am selben Tag). Es wird um 0 Uhr UTC zurückgesetzt (1 Uhr deutscher Zeit). "
                      "Der Autopilot versucht es danach automatisch erneut.")


def kontingent_leer(antwort_text):
    return "daily free allocation" in (antwort_text or "")
