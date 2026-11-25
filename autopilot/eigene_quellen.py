"""Eigene Quellen: PDFs, Textdateien und Webseiten aus dem Ordner quellen/.

- PDF, TXT, MD direkt in den Ordner quellen/ hochladen
- Webseiten: je eine Adresse pro Zeile in quellen/links.txt

Das Kit liest daraus Abschnitte und lässt die KI nur aus diesem Inhalt Reels oder Fakten-Posts
schreiben (mit Faktencheck). Bereits genutzte Abschnitte kommen erst wieder dran, wenn alle durch sind.
"""
import hashlib
import html
import os
import re
from html.parser import HTMLParser

import requests

from .einstellungen import ROOT, KitFehler

ORDNER = os.path.join(ROOT, "quellen")
LINKS = os.path.join(ORDNER, "links.txt")
ABSCHNITT = 6000  # Zeichen pro Abschnitt, passt gut in eine KI-Anfrage
ENDUNGEN = (".pdf", ".txt", ".md")


class _NurText(HTMLParser):
    """Holt den lesbaren Text aus einer Webseite (ohne Menüs, Skripte, Fußzeilen)."""

    WEG = frozenset({"script", "style", "nav", "footer", "header", "aside", "form", "noscript", "svg"})

    def __init__(self):
        super().__init__()
        self.teile, self.tiefe = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.WEG:
            self.tiefe += 1
        elif tag in ("p", "br", "li", "h1", "h2", "h3", "h4", "tr"):
            self.teile.append("\n")

    def handle_endtag(self, tag):
        if tag in self.WEG and self.tiefe:
            self.tiefe -= 1

    def handle_data(self, data):
        if not self.tiefe:
            self.teile.append(data)


def _sauber(text):
    text = html.unescape(text).replace("\r", "")
    text = re.sub(r"[ \t ]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def _pdf_text(pfad):
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise KitFehler("Zum Lesen von PDFs fehlt das Paket pypdf (requirements.txt).") from exc
    seiten = PdfReader(pfad).pages
    return "\n\n".join((s.extract_text() or "") for s in seiten)


def _webseite(url, http=requests):
    resp = http.get(url, timeout=30, headers={"User-Agent": "Insta-Autopilot/2.0 (eigene Quellen)"})
    resp.raise_for_status()
    p = _NurText()
    p.feed(resp.text)
    return "".join(p.teile)


def links():
    if not os.path.exists(LINKS):
        return []
    with open(LINKS, encoding="utf-8") as f:
        return [z.strip() for z in f if z.strip().startswith(("http://", "https://"))]


def dateien():
    if not os.path.isdir(ORDNER):
        return []
    return sorted(f for f in os.listdir(ORDNER) if f.lower().endswith(ENDUNGEN)
                  and f.lower() not in ("liesmich.txt", "links.txt"))


def vorhanden():
    return bool(dateien() or links())


def _quellen_laden(http=requests):
    """Liste von (Name, Text). Nicht lesbare Quellen werden übersprungen und gemeldet."""
    ergebnis = []
    for name in dateien():
        pfad = os.path.join(ORDNER, name)
        try:
            if name.lower().endswith(".pdf"):
                text = _pdf_text(pfad)
            else:
                with open(pfad, encoding="utf-8", errors="replace") as f:
                    text = f.read()
        except KitFehler:
            raise
        except Exception as exc:  # noqa: BLE001
            print(f"  Quelle {name} nicht lesbar ({type(exc).__name__}), übersprungen")
            continue
        text = _sauber(text)
        if len(text) >= 300:
            ergebnis.append((name, text))
        else:
            print(f"  Quelle {name}: kaum Text gefunden (bei gescannten PDFs fehlt der Text), übersprungen")
    for url in links():
        try:
            text = _sauber(_webseite(url, http))
        except Exception as exc:  # noqa: BLE001
            print(f"  Webseite {url} nicht erreichbar ({type(exc).__name__}), übersprungen")
            continue
        if len(text) >= 300:
            ergebnis.append((url, text))
    return ergebnis


def _abschnitte(text):
    """Teilt einen langen Text an Absatzgrenzen in Stücke von etwa ABSCHNITT Zeichen."""
    stuecke, aktuell = [], ""
    for absatz in text.split("\n\n"):
        if aktuell and len(aktuell) + len(absatz) > ABSCHNITT:
            stuecke.append(aktuell)
            aktuell = ""
        aktuell += absatz + "\n\n"
    if aktuell.strip():
        stuecke.append(aktuell)
    return [s.strip()[:ABSCHNITT + 2000] for s in stuecke if len(s.strip()) >= 300]


def naechster_abschnitt(benutzt, http=requests):
    """(Quellenname, Abschnittstext, Merk-ID). Wechselt reihum durch alle Quellen und Abschnitte.
    benutzt: Menge bereits verwendeter Merk-IDs."""
    quellen = _quellen_laden(http)
    if not quellen:
        raise KitFehler("Im Ordner quellen liegen keine lesbaren Dateien oder Links. Lade PDFs oder Textdateien "
                        "hoch oder trage Webseiten in quellen/links.txt ein (Anleitung in der App, Rubrik 09).")
    alle = []
    for name, text in quellen:
        for i, stueck in enumerate(_abschnitte(text)):
            kennung = hashlib.sha1(f"{name}|{i}|{stueck[:200]}".encode()).hexdigest()[:12]
            alle.append((name, stueck, kennung))
    benutzt = set(benutzt)
    frei = [a for a in alle if a[2] not in benutzt] or alle  # alles durch: wieder von vorn
    # gleichmäßig über die Quellen verteilen: die Quelle mit den wenigsten genutzten Abschnitten zuerst
    zaehler = {}
    for name, _, kennung in alle:
        zaehler[name] = zaehler.get(name, 0) + (kennung in benutzt)
    frei.sort(key=lambda a: zaehler[a[0]])
    return frei[0]


def anzeigename(name):
    if name.startswith(("http://", "https://")):
        return re.sub(r"^https?://(www\.)?", "", name).split("/")[0]
    return os.path.splitext(name)[0].replace("_", " ")
