"""Schreibt Reel-Skripte aus Wikipedia-Artikeln.

Fakten kommen nur aus Wikipedia (deutsch oder englisch). Eine Text-KI macht daraus ein Skript:
Hook + 6 Szenen + Frage an die Zuschauer, jede Szene mit englischer Bildbeschreibung.
Kostenlos über Cloudflare Workers AI; optional über die Claude-API (kostenpflichtig).
"""
import json
import os
import random
import re
import time

import requests

from .einstellungen import KitFehler

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


def kandidaten(g, benutzt, http=HTTP, zufall=random):
    """Erst die Startartikel, dann endlos über die Suchbegriffe."""
    for s in g["startartikel"]:
        if s not in benutzt:
            yield s
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

SYSTEM = """Du schreibst Skripte für ca. 45 Sekunden lange Instagram-Reels auf Deutsch. Ein Sprecher
liest den Text vor, der Text steht auch im Bild. Zu jeder Szene wird ein KI-Bild erzeugt.

Thema des Accounts: {thema}

WICHTIGSTE REGEL: Verwende AUSSCHLIESSLICH Fakten aus dem Wikipedia-Artikel. Erfinde keine Namen,
Zahlen, Daten, Zitate oder Details. Ist etwas ungeklärt oder umstritten, sag das klar.

Lehne den Artikel ab ("geeignet": false), wenn er nicht zum Thema passt, zu wenig Stoff für 6 Szenen
hat, Kinder Opfer von Gewalt sind, sexuelle Gewalt im Mittelpunkt steht, es um lebende Privatpersonen
nach 2010 geht oder er Hass, Terror oder menschenverachtende Verschwörungsmythen fördern könnte.

Antworte NUR mit JSON in genau diesem Format:
{{"geeignet": true, "grund": "kurz",
 "hook": {{"text": "...", "bild": "..."}},
 "szenen": [{{"text": "...", "bild": "..."}}, ... genau 6 Szenen ...],
 "frage": "...",
 "hashtags": ["#...", "#..."]}}

Regeln:
- hook.text: 1 packender Satz, höchstens 14 Wörter. Beginne mit einem konkreten, überraschenden
  Detail, keine Zusammenfassung.
- 6 Szenen mit je 9 bis 16 Wörtern. Bogen: Ort und Zeit, Ereignis, überraschendes Detail,
  Erklärungen oder Theorien, Auflösung oder offenes Ende. Kein Fülltext.
- "frage": kurze Frage an die Zuschauer, höchstens 8 Wörter, endet mit "?".
- Kurze Sätze zum Vorlesen, Zahlen als Ziffern, keine Emojis. Jeder Satz endet mit . ? oder !
- Pro Szene höchstens 1 bis 2 wichtige Wörter in *Sternchen* (werden farbig hervorgehoben).
- Respektvoll, keine blutigen Details.
- "bild": Bildbeschreibung AUF ENGLISCH, 10 bis 25 Wörter: Ort, Stimmung, Licht, Gegenstände.
  Keine erkennbaren realen Personen (lieber Silhouetten), kein Text im Bild, kein Blut.
- "hashtags": 2 bis 3 passende deutsche Hashtags."""


def _json_aus(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b < 0:
        raise ValueError("keine JSON-Antwort")
    return json.loads(text[a:b + 1])


def _woerter(text):
    return len(re.sub(r"[*]", "", text).split())


def pruefen(skript):
    """Liste von Problemen; leer = in Ordnung."""
    p = []
    hook = skript.get("hook") or {}
    if not hook.get("text") or not hook.get("bild"):
        p.append("hook braucht text und bild")
    elif _woerter(hook["text"]) > 16:
        p.append("hook ist zu lang (max. 14 Wörter)")
    szenen = skript.get("szenen") or []
    if not 5 <= len(szenen) <= 8:
        p.append(f"es müssen 6 Szenen sein, nicht {len(szenen)}")
    for i, s in enumerate(szenen, 1):
        if not isinstance(s, dict) or not s.get("text") or not s.get("bild"):
            p.append(f"Szene {i} braucht text und bild")
        elif not 5 <= _woerter(s["text"]) <= 22:
            p.append(f"Szene {i} hat {_woerter(s['text'])} Wörter (9 bis 16)")
    frage = str(skript.get("frage", ""))
    if not frage.endswith("?") or _woerter(frage) > 10:
        p.append("frage muss kurz sein und mit ? enden")
    return p


def aufraeumen(skript):
    def satz(t):
        t = re.sub(r"\s+", " ", str(t)).strip()
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
        raise KitFehler("Für Geschichten fehlen die Secrets CLOUDFLARE_ACCOUNT_ID und CLOUDFLARE_API_TOKEN "
                        "(Anleitung: Cloudflare einrichten).")
    resp = http.post(f"https://api.cloudflare.com/client/v4/accounts/{konto}/ai/run/{modell}",
                     headers={"Authorization": f"Bearer {token}"}, timeout=180,
                     json={"messages": nachrichten, "max_tokens": 2500, "temperature": 0.6})
    if resp.status_code in (401, 403) and "5035" not in resp.text:  # 5035 = Modell nur im Bezahl-Tarif
        raise KitFehler("Cloudflare lehnt den Zugang ab. Prüfe CLOUDFLARE_ACCOUNT_ID und ob der API-Token "
                        "die Berechtigung 'Workers AI' hat.")
    if not resp.ok:
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


def skript_schreiben(g, titel, text, chat=None):
    """Gibt (skript, None) oder (None, Grund) zurück."""
    englisch = bool(re.search(r"\b(the|and|was|were)\b", text[:2000])) and not re.search(
        r"\b(und|der|die|das)\b", text[:2000])
    hinweis = " Der Artikel ist englisch: schreibe trotzdem auf DEUTSCH und übersetze genau." if englisch else ""
    nachrichten = [{"role": "system", "content": SYSTEM.format(thema=g["thema"])},
                   {"role": "user", "content": f'Wikipedia-Artikel "{titel}".{hinweis}\n\n{text}'}]
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
            probleme = pruefen(skript)
            if not probleme:
                return aufraeumen(skript), None
            fehler.append(f"{modell}: {'; '.join(probleme[:2])}")
            nachrichten = nachrichten[:2] + [
                {"role": "assistant", "content": json.dumps(skript, ensure_ascii=False)},
                {"role": "user", "content": "Bitte korrigieren: " + "; ".join(probleme) + ". Nur JSON."}]
    return None, "KI-Fehler: " + " | ".join(fehler[-3:])


def neue_geschichte(g, verlauf, http=HTTP, chat=None, zufall=random):
    """Sucht einen unbenutzten Artikel und schreibt das Skript. Markiert NICHTS als benutzt
    (das passiert erst nach dem Posten); gibt die zu merkenden Artikel-Schlüssel mit."""
    benutzt = set(verlauf.get("wiki_benutzt", [])) | set(verlauf.get("wiki_abgelehnt", []))
    versucht = []
    for schluessel in kandidaten(g, benutzt, http, zufall):
        if len(versucht) >= MAX_ARTIKEL_PRO_LAUF:
            break
        if schluessel in versucht:
            continue
        versucht.append(schluessel)
        a = artikel(schluessel, http)
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
        skript.update(quelle=url, titel=titel, merken=sorted({schluessel, echt} | andere))
        print(f"+ {titel}: Skript geschrieben")
        return skript
    raise KitFehler("Keine passende Geschichte gefunden. Ergänze in einstellungen.yml weitere "
                    "Suchbegriffe oder Startartikel. Beim nächsten Lauf wird es erneut versucht.")
