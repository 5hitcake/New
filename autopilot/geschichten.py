"""Schreibt Reel-Skripte für gesprochene Reels. Quellen (einstellungen.yml → geschichten → quelle):

- wissen:         Tipps, Anleitungen und Fakten zu deinem Thema (für fast jeden Account passend)
- wikipedia:      wahre Geschichten, Fakten nur aus Wikipedia. Die KI schlägt passende Artikel vor.
- nacherzaehlung: bekannte überlieferte Geschichten nacherzählt (Bibel, Sagen, Märchen, Mythen, Fabeln).
                  Bibelgeschichten werden aus dem Originaltext der Lutherbibel 1912 erzählt.
- fiktion:        die KI erfindet die Geschichte frei zum Thema (wird als fiktiv gekennzeichnet)
- eigene_texte:   aus deinen eigenen Texten in inhalte/geschichten.txt

Eine Text-KI macht daraus ein Skript: Hook + Szenen + Frage an die Zuschauer, jede Szene mit
englischer Bildbeschreibung. Kostenlos über Cloudflare Workers AI; optional über die Claude-API.
"""
import hashlib
import json
import os
import random
import re
import time

import requests

from .einstellungen import EIGENE_TEXTE, KitFehler

WIKI_API = "https://{lang}.wikipedia.org/w/api.php"
CF_TEXT_MODELLE = [
    "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
    "@cf/zai-org/glm-4.7-flash",
    "@cf/google/gemma-4-26b-a4b-it",
]
CLAUDE_MODELL = "claude-haiku-5-5"
MAX_ZEICHEN = 9000
MIN_ZEICHEN = 1500
MAX_ARTIKEL_PRO_LAUF = 6

HTTP = requests.Session()
HTTP.headers["User-Agent"] = "Insta-Autopilot/2.0 (Story-Reels aus Wikipedia)"


# ---------------------------------------------------------------- Wikipedia

def _sprache(schluessel):
    """'en:Mary Celeste' -> ('en', 'Mary Celeste'); ohne Präfix Deutsch."""
    lang, sep, titel = schluessel.partition(":")
    return (lang, titel) if sep and lang in ("de", "en") else ("de", schluessel)


def _wiki(params, lang, http=HTTP):
    params = {"format": "json", "formatversion": 2, **params}
    for versuch in range(4):
        resp = http.get(WIKI_API.format(lang=lang), params=params, timeout=30)
        if resp.status_code == 429 or resp.status_code >= 500:
            time.sleep(5 * (versuch + 1))
            continue
        resp.raise_for_status()
        return resp.json()
    raise KitFehler("Wikipedia ist gerade nicht erreichbar. Beim nächsten Lauf wird es erneut versucht.")


def suchen(begriff, lang="de", http=HTTP, zufall=random):
    daten = _wiki({"action": "query", "list": "search", "srsearch": begriff, "srnamespace": 0,
                   "sroffset": zufall.choice([0, 0, 20, 40]), "srlimit": 20}, lang, http)
    praefix = "" if lang == "de" else f"{lang}:"
    return [praefix + t["title"] for t in daten.get("query", {}).get("search", [])]


def artikel(schluessel, http=HTTP):
    """(Schlüssel, Titel, Text, URL, Schlüssel in anderen Sprachen) oder None."""
    lang, titel = _sprache(schluessel)
    daten = _wiki({"action": "query", "prop": "extracts|pageprops|info|langlinks", "explaintext": 1,
                   "redirects": 1, "titles": titel, "inprop": "url", "ppprop": "disambiguation",
                   "lllimit": 50}, lang, http)
    seiten = daten.get("query", {}).get("pages", [])
    if not seiten or seiten[0].get("missing") or "disambiguation" in seiten[0].get("pageprops", {}):
        return None
    seite = seiten[0]
    text = re.sub(r"\n{3,}", "\n\n", seite.get("extract", "")).strip()
    text = re.split(r"\n== (Literatur|Weblinks|Einzelnachweise|Rezeption|References|External links|"
                    r"Further reading|See also|In popular culture|Notes)", text)[0]
    praefix = "" if lang == "de" else f"{lang}:"
    andere = {(f"{ll['lang']}:" if ll["lang"] != "de" else "") + ll["title"]
              for ll in seite.get("langlinks", []) if ll.get("lang") in ("de", "en")}
    return praefix + seite["title"], seite["title"], text[:MAX_ZEICHEN], seite.get("fullurl", ""), andere


def kandidaten(g, benutzt, http=HTTP, zufall=random, vorschlaege=None):
    """Erst die Startartikel, dann die Artikel-Vorschläge der KI, dann über die Suchbegriffe."""
    for s in g["startartikel"]:
        if s not in benutzt:
            yield s
    for titel in (vorschlaege() if vorschlaege else []):
        if titel not in benutzt:
            yield titel
    suchen_liste = [(b, "de") for b in g["suchbegriffe"]] + [(b, "en") for b in g["suchbegriffe_englisch"]]
    for _ in range(8):
        if not suchen_liste:
            return
        begriff, lang = zufall.choice(suchen_liste)
        for s in suchen(begriff, lang, http, zufall):
            titel = _sprache(s)[1]
            if s not in benutzt and not titel.startswith(("Liste ", "List of ")) and "Begriffsklärung" not in titel:
                yield s


# ---------------------------------------------------------------- Text-KI

KOPF = """Du schreibst Skripte für kurze Instagram-Reels auf Deutsch. Ein Sprecher
liest den Text vor, der Text steht auch im Bild. Zu jeder Szene wird ein KI-Bild erzeugt.

Thema des Accounts: {thema}
{beschreibung}"""

QUELLEN_REGELN = {
    "wissen_text": """
Das Reel vermittelt Wissen zum angegebenen Thema. WICHTIGSTE REGEL: Alle Fakten, Zahlen und Namen stammen
aus dem mitgelieferten Wikipedia-Artikel. Nichts dazuerfinden. Wähle die überraschendsten, anschaulichsten
Fakten aus und erkläre sie einfach. Gib dem Reel einen kurzen "titel".
""",
    "wissen": """
Das Reel vermittelt nützliches Wissen zum Thema des Nutzers: Tipps, eine kurze Anleitung, überraschende
Fakten oder "Mythos und Wahrheit". Nur korrekte, allgemein anerkannte Informationen. Erfinde keine Studien,
Zahlen oder Zitate. Keine Heilversprechen, keine Finanz- oder Rechtsberatung, nichts Gefährliches.
Konkret und praktisch statt allgemein: lieber "Stell dein Handy abends auf Graustufen" als "Achte auf dich".
Gib dem Reel einen kurzen "titel".
""",
    "nacherzaehlung": """
Erzähle eine bekannte, überlieferte Geschichte nach (z.B. aus der Bibel, aus Sagen, Märchen, Mythen,
Fabeln oder Legenden). Bleib nah an der überlieferten Fassung: gleiche Figuren, gleiche Handlung, gleiches
Ende. Erfinde nichts Wesentliches dazu. Erzähle in heutigem, lebendigem Deutsch, respektvoll gegenüber
Glauben und Kultur. Bist du dir bei der Handlung nicht sicher, antworte mit "geeignet": false.
Gib der Geschichte einen kurzen "titel".
""",
    "nacherzaehlung_text": """
Erzähle die Geschichte aus dem mitgelieferten Originaltext nach. WICHTIGSTE REGEL: Nur Inhalte aus diesem
Text, nichts dazuerfinden. Erzähle in heutigem, lebendigem Deutsch (nicht in altertümlicher Sprache),
respektvoll. Eine kurze, bekannte Formulierung aus dem Original darf als wörtliches Zitat vorkommen.
Gib der Geschichte einen kurzen "titel".
""",
    "wikipedia": """
WICHTIGSTE REGEL: Verwende AUSSCHLIESSLICH Fakten aus dem Wikipedia-Artikel. Erfinde keine Namen,
Zahlen, Daten, Zitate oder Details. Ist etwas ungeklärt oder umstritten, sag das klar.

Lehne den Artikel ab ("geeignet": false), wenn er nicht zum Thema passt, zu wenig Stoff für {szenen} Szenen
hat, Kinder Opfer von Gewalt sind, sexuelle Gewalt im Mittelpunkt steht, es um lebende Privatpersonen
nach 2010 geht oder er Hass, Terror oder menschenverachtende Verschwörungsmythen fördern könnte.
""",
    "eigene_texte": """
WICHTIGSTE REGEL: Verwende AUSSCHLIESSLICH die Inhalte aus dem Text des Nutzers. Erfinde keine Namen,
Zahlen, Daten, Zitate oder Details dazu. Ist der Text kurz, bleib nah am Text.

Lehne den Text nur ab ("geeignet": false), wenn er Hass, Gewaltverherrlichung oder sexuelle Inhalte
enthält oder echte Privatpersonen bloßstellt.
""",
    "fiktion": """
Erfinde eine NEUE, frei erfundene Geschichte, die genau zum Thema und zur Beschreibung des Accounts passt
(Ort, Zeit, Stimmung). Sie darf nicht wie ein echtes Ereignis wirken: keine echten Personen, keine echten
Firmen, keine echten Verbrechen, keine konkreten echten Daten. Erfundene Orte und Namen sind erlaubt.
So wird sie gut: EIN konkreter Ort mit Namen, EINE Hauptfigur (oder "du"), sinnliche Details (Geräusche,
Gerüche, Licht), jede Szene steigert die Spannung, die letzte Szene bringt eine überraschende Wendung.
Keine allgemeinen Sätze wie "In alten Zeiten …" oder "Heute spuken noch Geister". Gruselig oder spannend ja, aber ohne Splatter, ohne
Gewalt an Kindern, ohne sexuelle Inhalte. Gib der Geschichte zusätzlich einen kurzen "titel".
""",
}

FORMAT = """
Antworte NUR mit JSON in genau diesem Format:
{"geeignet": true, "grund": "kurz", "titel": "...",
 "hook": {"text": "...", "bild": "..."},
 "szenen": [{"text": "...", "bild": "..."}, ... genau {szenen} Szenen ...],
 "frage": "...",
 "hashtags": ["#...", "#..."]}

"""

REGELN = """Regeln:
- hook.text: 1 packender Satz, höchstens 14 Wörter, aus DERSELBEN Geschichte (gleicher Ort, gleiche
  Figur). Am besten ein Detail aus der Wendung, das neugierig macht, ohne sie zu verraten.
- {szenen} Szenen mit je 12 bis 18 Wörtern, jede Szene ein ganzer, bildhafter Satz. {bogen}
  Kein Fülltext. Nur einfache, natürliche deutsche Wörter, die man so auch sagen würde.
- "frage": kurze Frage an die Zuschauer, höchstens 8 Wörter, endet mit "?". Sie bezieht sich auf etwas,
  das in den Szenen wirklich vorkommt. Alles, was Hook und Frage ankündigen (z.B. ein Schrei, ein Fluch),
  muss in der Geschichte auch auftauchen.
- Kurze Sätze zum Vorlesen, Zahlen als Ziffern, keine Emojis. Jeder Satz endet mit . ? oder !
- Pro Szene genau 1 Schlüsselwort in *Sternchen* (wird farbig hervorgehoben): das wichtigste
  Substantiv oder die Überraschung, kein Adjektiv wie "dunkel" oder "kalt".
- Respektvoll, keine blutigen Details.
- "bild": Bildbeschreibung AUF ENGLISCH, 10 bis 25 Wörter: Ort, Stimmung, Licht, Gegenstände.
  Keine erkennbaren realen Personen (lieber Silhouetten), kein Text im Bild, kein Blut.
- "hashtags": 2 bis 3 passende deutsche Hashtags."""


BOGEN = {
    "wissen": ("Aufbau: jede Szene EIN Tipp, Schritt oder Fakt, in sinnvoller Reihenfolge. Die letzte Szene "
               "fasst zusammen oder bringt den wichtigsten Tipp. Der Hook macht neugierig (überraschende "
               "Aussage oder Frage). Die Frage lädt zum Mitmachen ein, z.B. welchen Tipp man zuerst ausprobiert."),
    "nacherzaehlung": ("Bogen wie im Original: Ausgangslage, Wendepunkt, Höhepunkt, Ende. Die letzte Szene "
                       "bringt das Ende oder die Lehre der Geschichte."),
    "geschichte": ("Bogen: Ort und Zeit, Ereignis, überraschendes Detail, Erklärungen oder Theorien, Auflösung "
                   "oder offenes Ende. Die LETZTE Szene ist die Wendung: etwas Unerwartetes, das alles davor "
                   "in neuem Licht zeigt."),
}


def system_prompt(thema, quelle="wikipedia", szenen=6, beschreibung=""):
    zusatz = f"Beschreibung des Accounts: {beschreibung}\n" if beschreibung else ""
    bogen = BOGEN["wissen"] if quelle.startswith("wissen") else (
        BOGEN["nacherzaehlung"] if quelle.startswith("nacherzaehlung") else BOGEN["geschichte"])
    text = KOPF.format(thema=thema, beschreibung=zusatz) + QUELLEN_REGELN[quelle] + FORMAT + REGELN
    return text.replace("{szenen}", str(szenen)).replace("{bogen}", bogen)


def _json_aus(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b < 0:
        raise ValueError("keine JSON-Antwort")
    return json.loads(text[a:b + 1])


def _woerter(text):
    return len(re.sub(r"[*]", "", text).split())


def pruefen(skript, soll=6):
    """Liste von Problemen; leer = in Ordnung."""
    p = []
    hook = skript.get("hook") or {}
    if not hook.get("text") or not hook.get("bild"):
        p.append("hook braucht text und bild")
    elif _woerter(hook["text"]) > 16:
        p.append("hook ist zu lang (max. 14 Wörter)")
    szenen = skript.get("szenen") or []
    if not max(3, soll - 1) <= len(szenen) <= soll + 2:
        p.append(f"es müssen {soll} Szenen sein, nicht {len(szenen)}")
    for i, s in enumerate(szenen, 1):
        if not isinstance(s, dict) or not s.get("text") or not s.get("bild"):
            p.append(f"Szene {i} braucht text und bild")
        elif not 9 <= _woerter(s["text"]) <= 24:
            p.append(f"Szene {i} hat {_woerter(s['text'])} Wörter, nötig sind 12 bis 18")
    frage = str(skript.get("frage", ""))
    if not frage.endswith("?") or _woerter(frage) > 10:
        p.append("frage muss kurz sein und mit ? enden")
    return p


def nur_ein_schluesselwort(t):
    """Lässt nur das erste *Wort* hervorgehoben, weitere Sternchen fallen weg."""
    teile = re.split(r"(\*[^*]+\*)", t)
    gesehen = False
    for i, teil in enumerate(teile):
        if teil.startswith("*") and teil.endswith("*") and len(teil) > 2:
            if gesehen:
                teile[i] = teil[1:-1]
            gesehen = True
    return "".join(teile)


def aufraeumen(skript):
    def satz(t):
        t = nur_ein_schluesselwort(re.sub(r"\s+", " ", str(t)).strip())
        return t if not t or t[-1] in ".?!" else t + "."
    skript["hook"]["text"] = satz(skript["hook"]["text"])
    for s in skript["szenen"]:
        s["text"] = satz(s["text"])
        s["bild"] = re.sub(r"[*]", "", str(s["bild"])).strip()
    skript["hook"]["bild"] = re.sub(r"[*]", "", str(skript["hook"]["bild"])).strip()
    tags = []
    for t in skript.get("hashtags") or []:
        t = "#" + re.sub(r"[^\wäöüß]", "", str(t).lower())
        if len(t) > 2 and t not in tags:
            tags.append(t)
    skript["hashtags"] = tags[:3]
    return skript


def _cloudflare_chat(nachrichten, modell, http=HTTP):
    konto = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    if not konto or not token:
        from .einstellungen import cloudflare_hinweis
        raise KitFehler(cloudflare_hinweis())
    resp = http.post(f"https://api.cloudflare.com/client/v4/accounts/{konto}/ai/run/{modell}",
                     headers={"Authorization": f"Bearer {token}"}, timeout=180,
                     json={"messages": nachrichten, "max_tokens": 2500, "temperature": 0.6})
    if resp.status_code in (401, 403) and "5035" not in resp.text:  # 5035 = Modell nur im Bezahl-Tarif
        raise KitFehler("Cloudflare lehnt den Zugang ab. Prüfe CLOUDFLARE_ACCOUNT_ID und ob der API-Token "
                        "die Berechtigung 'Workers AI' hat.")
    if not resp.ok:
        from .einstellungen import KONTINGENT_HINWEIS, kontingent_leer
        if kontingent_leer(resp.text):
            raise KitFehler(KONTINGENT_HINWEIS)
        raise RuntimeError(f"{modell}: HTTP {resp.status_code} {resp.text[:200]}")
    ergebnis = resp.json().get("result", {})
    aus = ergebnis.get("response")
    if aus is None and ergebnis.get("choices"):
        aus = ergebnis["choices"][0]["message"]["content"]
    return json.dumps(aus, ensure_ascii=False) if isinstance(aus, (dict, list)) else (aus or "")


def _claude_chat(nachrichten, http=HTTP):
    schluessel = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not schluessel:
        raise KitFehler("text_ki ist \"claude\", aber das Secret ANTHROPIC_API_KEY fehlt.")
    system = nachrichten[0]["content"]
    resp = http.post("https://api.anthropic.com/v1/messages", timeout=180,
                     headers={"x-api-key": schluessel, "anthropic-version": "2023-06-01"},
                     json={"model": CLAUDE_MODELL, "max_tokens": 2500, "system": system,
                           "messages": nachrichten[1:]})
    if resp.status_code in (401, 403):
        raise KitFehler("Die Claude-API lehnt den Schlüssel ab (ANTHROPIC_API_KEY prüfen).")
    if not resp.ok:
        raise RuntimeError(f"Claude: HTTP {resp.status_code} {resp.text[:200]}")
    return "".join(b.get("text", "") for b in resp.json().get("content", []))


def skript_schreiben(g, titel, text, chat=None, quelle="wikipedia"):
    """Gibt (skript, None) oder (None, Grund) zurück. Bei quelle="fiktion" ist text die Anregung."""
    englisch = bool(re.search(r"\b(the|and|was|were)\b", text[:2000])) and not re.search(
        r"\b(und|der|die|das)\b", text[:2000])
    hinweis = " Der Text ist englisch: schreibe trotzdem auf DEUTSCH und übersetze genau." if englisch else ""
    if quelle in ("fiktion", "wissen", "nacherzaehlung"):
        nutzer = text
    elif quelle == "wissen_text":
        nutzer = f'Thema des Reels: {titel}\n\nWikipedia-Artikel:\n\n{text}'
    elif quelle == "nacherzaehlung_text":
        nutzer = f'Originaltext "{titel}":\n\n{text}'
    elif quelle == "eigene_texte":
        nutzer = f'Text des Nutzers "{titel}".{hinweis}\n\n{text}'
    else:
        nutzer = f'Wikipedia-Artikel "{titel}".{hinweis}\n\n{text}'
    nachrichten = [{"role": "system", "content": system_prompt(g["thema"] or "Spannende Geschichten", quelle,
                                                               g.get("szenen", 6), g.get("beschreibung", ""))},
                   {"role": "user", "content": nutzer}]
    if chat is None:
        if g["text_ki"] == "claude":
            modelle, chat = ["claude"], lambda n, _m: _claude_chat(n)
        else:
            modelle, chat = CF_TEXT_MODELLE, _cloudflare_chat
    else:
        modelle = ["test"]
    fehler = []
    for modell in modelle:
        for _ in range(2):
            try:
                skript = _json_aus(chat(nachrichten, modell))
            except KitFehler:
                raise
            except Exception as exc:  # noqa: BLE001 - nochmal bzw. nächstes Modell versuchen
                fehler.append(f"{modell}: {exc}")
                if "HTTP 4" in str(exc) and "429" not in str(exc):
                    break  # Modell nicht verfügbar
                continue
            if not skript.get("geeignet", True):
                return None, f"passt nicht: {skript.get('grund', '')}"
            probleme = pruefen(skript, g.get("szenen", 6))
            if not probleme:
                return aufraeumen(skript), None
            fehler.append(f"{modell}: {'; '.join(probleme[:2])}")
            nachrichten = nachrichten[:2] + [
                {"role": "assistant", "content": json.dumps(skript, ensure_ascii=False)},
                {"role": "user", "content": "Bitte korrigieren: " + "; ".join(probleme) + ". Nur JSON."}]
    return None, "KI-Fehler: " + " | ".join(fehler[-3:])


IDEEN = {
    "wikipedia": ('Nenne {n} konkrete Titel von DEUTSCHEN Wikipedia-Artikeln (genau wie der Artikeltitel), über die '
                  'man eine spannende kurze, wahre Geschichte erzählen kann und die genau zum Account passen. '
                  'Nur einzelne Ereignisse, Orte, Fälle, Entdeckungen oder Erzählungen, keine Oberbegriffe '
                  '(z.B. nicht "Bibel", sondern "Arche Noah"), keine Listen, keine lebenden Privatpersonen. '
                  'JSON: {{"ideen": [{{"titel": "..."}}]}}'),
    "nacherzaehlung": ('Nenne {n} bekannte, überlieferte Geschichten, die genau zum Account passen (z.B. aus der '
                       'Bibel, aus Sagen, Märchen, Mythen, Fabeln oder Legenden). Bei Bibelgeschichten in "stelle" '
                       'die genaue Bibelstelle (z.B. "Lukas 15,11-32" oder "1. Mose 6-9"), sonst die Herkunft '
                       '(z.B. "Brüder Grimm", "griechische Mythologie", "Äsop"). '
                       'JSON: {{"ideen": [{{"titel": "...", "stelle": "..."}}]}}'),
    "wissen": ('Nenne {n} konkrete Themen für je ein kurzes Wissens-Reel, die genau zum Account passen: Tipps, '
               'kleine Anleitungen, überraschende Fakten oder "Mythos und Wahrheit". Konkret, z.B. "3 Fehler beim '
               'Kartoffeln kochen" statt "Kochen". Geht es um Sachwissen (z.B. Tiere, Geschichte, Natur, Technik, '
               'Weltraum), trage in "wikipedia" den Titel des DEUTSCHEN Wikipedia-Artikels ein, in dem die Fakten '
               'stehen (z.B. "Tyrannosaurus"). Bei praktischen Tipps ohne passenden Artikel leer lassen. '
               'JSON: {{"ideen": [{{"titel": "...", "wikipedia": "Artikeltitel oder leer"}}]}}'),
}


def ideen(g, art, bisher, chat=None, n=8, zufall=random):
    """Lässt die KI passende Ideen vorschlagen (Artikel, Geschichten oder Themen). Liste von Dicts, ggf. leer."""
    system = ("Du hilfst bei der Planung eines deutschsprachigen Instagram-Accounts.\n"
              f"Beschreibung des Accounts: {g.get('beschreibung') or g.get('thema')}\n"
              f"Thema: {g.get('thema', '')}\nAntworte NUR mit JSON.")
    auftrag = IDEEN[art].format(n=n)
    if bisher:
        auftrag += " Diese gab es schon, schlage andere vor: " + "; ".join(list(bisher)[-60:])
    nachrichten = [{"role": "system", "content": system}, {"role": "user", "content": auftrag}]
    if chat is None:
        if g.get("text_ki") == "claude":
            modelle, chat = ["claude"], lambda nn, _m: _claude_chat(nn)
        else:
            modelle, chat = CF_TEXT_MODELLE, _cloudflare_chat
    else:
        modelle = ["test"]
    for modell in modelle:
        try:
            daten = _json_aus(chat(nachrichten, modell))
        except KitFehler:
            raise
        except Exception as exc:  # noqa: BLE001 - nächstes Modell
            print(f"  Ideen von {modell} fehlgeschlagen: {exc}")
            continue
        liste = [i for i in (daten.get("ideen") or []) if isinstance(i, dict) and str(i.get("titel", "")).strip()]
        if liste:
            zufall.shuffle(liste)
            return liste
    return []


def _bisherige_titel(verlauf, praefix):
    return [m.removeprefix(praefix) for m in verlauf.get("wiki_benutzt", []) + verlauf.get("wiki_abgelehnt", [])
            if m.startswith(praefix)]


def _wissensartikel(titel, http=HTTP):
    """Wikipedia-Artikel als Faktenquelle für ein Wissens-Reel, oder None."""
    if not titel or len(titel) > 120:
        return None
    try:
        a = artikel(titel, http)
        if not a:
            treffer = suchen(titel, "de", http, random.Random(0))[:1]
            a = artikel(treffer[0], http) if treffer else None
    except Exception as exc:  # noqa: BLE001 - dann eben ohne Artikel
        print(f"  Wikipedia nicht erreichbar ({type(exc).__name__}), schreibe ohne Artikel")
        return None
    return a if a and len(a[2]) >= 800 else None


def _wissen(g, verlauf, http=HTTP, chat=None, zufall=random):
    bisher = _bisherige_titel(verlauf, "wissen:")
    vorschlaege = ideen(g, "wissen", bisher, chat, zufall=zufall)
    if not vorschlaege:
        vorschlaege = [{"titel": zufall.choice(g["suchbegriffe"] or [g["thema"] or "Tipps zum Thema"])}]
    for idee in vorschlaege[:3]:
        titel = str(idee["titel"]).strip()[:120]
        if titel in bisher:
            continue
        a = _wissensartikel(str(idee.get("wikipedia") or "").strip(), http)
        if a:  # Sachwissen: Fakten aus Wikipedia statt aus dem Gedächtnis der KI
            skript, grund = skript_schreiben(g, titel, a[2][:9000], chat, quelle="wissen_text")
            quelle = a[1]
        else:
            skript, grund = skript_schreiben(g, titel, f"Schreibe ein Wissens-Reel zum Thema: {titel}.", chat,
                                             quelle="wissen")
            quelle = ""
        if skript:
            skript.update(quelle_art="wissen", quelle=quelle, titel=titel, merken=[f"wissen:{titel}"])
            print(f"+ {titel}: Skript geschrieben")
            return skript
        print(f"- {titel}: {grund}")
    raise KitFehler("Die KI konnte gerade kein Wissens-Reel schreiben. Beim nächsten Lauf neuer Versuch.")


def _nacherzaehlung(g, verlauf, chat=None, zufall=random):
    from . import bibel

    bisher = _bisherige_titel(verlauf, "erz:")
    vorschlaege = ideen(g, "nacherzaehlung", bisher, chat, zufall=zufall)
    if not vorschlaege:
        raise KitFehler("Die KI hat gerade keine passende Geschichte vorgeschlagen. Beim nächsten Lauf neuer Versuch.")
    for idee in vorschlaege[:4]:
        titel = str(idee["titel"]).strip()[:120]
        stelle = str(idee.get("stelle") or "").strip()[:80]
        if titel in bisher:
            continue
        original = bibel.text(stelle) if bibel.ist_stelle(stelle) else None
        if original:
            stelle, text = original
            skript, grund = skript_schreiben(g, f"{titel} ({stelle})", text, chat, quelle="nacherzaehlung_text")
        else:
            auftrag = f"Erzähle diese Geschichte nach: {titel}" + (f" (Herkunft: {stelle})." if stelle else ".")
            skript, grund = skript_schreiben(g, titel, auftrag, chat, quelle="nacherzaehlung")
        if skript:
            skript.update(quelle_art="nacherzaehlung", quelle=stelle, titel=titel, merken=[f"erz:{titel}"])
            print(f"+ {titel} ({stelle or 'überliefert'}): Skript geschrieben")
            return skript
        print(f"- {titel}: {grund}")
        if grund.startswith("passt nicht"):
            verlauf["wiki_abgelehnt"] = (verlauf.get("wiki_abgelehnt", []) + [f"erz:{titel}"])[-500:]
    raise KitFehler("Gerade ließ sich keine Geschichte nacherzählen. Beim nächsten Lauf neuer Versuch.")


def neue_geschichte(g, verlauf, http=HTTP, chat=None, zufall=random):
    """Wählt je nach Einstellung die Quelle."""
    if g.get("quelle") == "wissen":
        return _wissen(g, verlauf, http, chat, zufall)
    if g.get("quelle") == "nacherzaehlung":
        return _nacherzaehlung(g, verlauf, chat, zufall)
    if g.get("quelle") == "fiktion":
        return _fiktion(g, verlauf, chat, zufall)
    if g.get("quelle") == "eigene_texte":
        return _eigener_text(g, verlauf, chat)
    return _wikipedia(g, verlauf, http, chat, zufall)


def _fiktion(g, verlauf, chat=None, zufall=random):
    bisher = [m.removeprefix("fiktion:") for m in verlauf.get("wiki_benutzt", []) if m.startswith("fiktion:")]
    motiv = zufall.choice(g["suchbegriffe"] + g["suchbegriffe_englisch"] or [g["thema"]])
    auftrag = f"Schreibe eine neue, frei erfundene Geschichte. Anregung: {motiv}."
    if bisher:
        auftrag += " Diese Geschichten gab es schon, schreibe etwas deutlich anderes: " + "; ".join(bisher[-40:])
    skript, grund = skript_schreiben(g, "", auftrag, chat, quelle="fiktion")
    if not skript:
        raise KitFehler(f"Die KI konnte keine Geschichte schreiben ({grund}). Beim nächsten Lauf neuer Versuch.")
    titel = str(skript.get("titel") or skript["hook"]["text"]).replace("*", "").strip()[:80]
    skript.update(quelle_art="fiktion", quelle="", titel=titel, merken=[f"fiktion:{titel}"])
    print(f"+ {titel}: fiktive Geschichte geschrieben")
    return skript


def eigene_texte_laden(pfad=EIGENE_TEXTE):
    """Liest inhalte/geschichten.txt: Texte getrennt durch eine Zeile mit ---, erste Zeile = Titel.
    Zeilen, die mit # beginnen, sind Kommentare. Gibt Liste von (id, titel, text) zurück."""
    if not os.path.exists(pfad):
        return []
    with open(pfad, encoding="utf-8-sig") as f:
        zeilen = [z.rstrip() for z in f if not z.lstrip().startswith("#")]
    texte, block = [], []
    for z in zeilen + ["---"]:
        if z.strip() == "---":
            inhalt = "\n".join(block).strip()
            if inhalt:
                titel, _, rest = inhalt.partition("\n")
                texte.append(("text:" + hashlib.sha1(inhalt.encode()).hexdigest()[:12], titel.strip(),
                              (rest.strip() or titel.strip())))
            block = []
        else:
            block.append(z)
    return texte


def _eigener_text(g, verlauf, chat=None):
    texte = eigene_texte_laden()
    if not texte:
        raise KitFehler("quelle ist \"eigene_texte\", aber in inhalte/geschichten.txt steht noch kein Text. "
                        "Schreib dort deine Geschichten hinein (getrennt durch eine Zeile mit ---).")
    benutzt = set(verlauf.get("wiki_benutzt", [])) | set(verlauf.get("wiki_abgelehnt", []))
    offen = [t for t in texte if t[0] not in benutzt]
    if not offen:
        raise KitFehler("Alle Texte aus inhalte/geschichten.txt wurden schon gepostet. Füge neue hinzu.")
    for tid, titel, text in offen[:MAX_ARTIKEL_PRO_LAUF]:
        skript, grund = skript_schreiben(g, titel, text, chat, quelle="eigene_texte")
        if skript:
            skript.update(quelle_art="eigene_texte", quelle="", titel=titel, merken=[tid])
            print(f"+ {titel}: Skript geschrieben")
            return skript
        print(f"- {titel}: {grund}")
        if grund.startswith("passt nicht"):
            verlauf["wiki_abgelehnt"] = (verlauf.get("wiki_abgelehnt", []) + [tid])[-500:]
    raise KitFehler("Aus deinen Texten ließ sich gerade kein Skript schreiben. Beim nächsten Lauf neuer Versuch.")


def _wikipedia(g, verlauf, http=HTTP, chat=None, zufall=random):
    """Sucht einen unbenutzten Artikel und schreibt das Skript. Markiert NICHTS als benutzt
    (das passiert erst nach dem Posten); gibt die zu merkenden Artikel-Schlüssel mit."""
    benutzt = set(verlauf.get("wiki_benutzt", [])) | set(verlauf.get("wiki_abgelehnt", []))
    versucht = []

    def vorschlaege():
        bisher = [b for b in benutzt if ":" not in b or b.startswith("en:")][-60:]
        return [str(i["titel"]).strip() for i in ideen(g, "wikipedia", bisher, chat, n=10, zufall=zufall)]

    for schluessel in kandidaten(g, benutzt, http, zufall, vorschlaege):
        if len(versucht) >= MAX_ARTIKEL_PRO_LAUF:
            break
        if schluessel in versucht:
            continue
        versucht.append(schluessel)
        a = artikel(schluessel, http)
        if not a and _sprache(schluessel)[0] == "de":  # kein exakter Titel (z.B. KI-Vorschlag): suchen
            treffer = suchen(schluessel, "de", http, random.Random(0))[:1]
            a = artikel(treffer[0], http) if treffer and treffer[0] not in benutzt else None
        if not a or len(a[2]) < MIN_ZEICHEN:
            print(f"- {schluessel}: übersprungen (zu kurz)")
            continue
        echt, titel, text, url, andere = a
        if andere & benutzt or echt in benutzt:
            continue
        skript, grund = skript_schreiben(g, titel, text, chat)
        if not skript:
            print(f"- {titel}: {grund}")
            benutzt.add(echt)  # in diesem Lauf nicht noch einmal
            verlauf["wiki_abgelehnt"] = (verlauf.get("wiki_abgelehnt", []) + [echt])[-500:]
            continue
        skript.update(quelle_art="wikipedia", quelle=url, titel=titel, merken=sorted({schluessel, echt} | andere))
        print(f"+ {titel}: Skript geschrieben")
        return skript
    raise KitFehler("Keine passende Wikipedia-Geschichte gefunden. Beim nächsten Lauf wird es erneut versucht. "
                    "Passiert das öfter: in einstellungen.yml unter geschichten → startartikel konkrete Artikel "
                    "eintragen oder eine andere Quelle wählen (z.B. \"wissen\" oder \"nacherzaehlung\").")
