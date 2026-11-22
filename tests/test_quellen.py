"""Neue Quellen: Bibel (Lutherbibel 1912), echte Zitate, Wissens-Reels, Nacherzählungen."""
import json

import pytest

from autopilot import bibel, geschichten, reels, sprueche, wikimedia


class Wikimedia:
    """Falsches Wikiquote/Wikisource/Wikivoyage."""

    SEITEN = {  # noqa: RUF012
        "wikiquote": {
            "Johann Wolfgang von Goethe": (
                "Johann Wolfgang von Goethe war ein deutscher Dichter.\n\n== Zitate ==\n"
                "Edel sei der Mensch, hilfreich und gut!\n- Das Göttliche, 1783\n"
                "Es irrt der Mensch, solang er strebt.\n- Faust I, Prolog im Himmel\n\n"
                "== Falsch zugeschrieben ==\nWer immer strebend sich bemüht, dem gehört die ganze Welt.\n"),
            "Deutsche Sprichwörter": "== A ==\nAller Anfang ist schwer.\nAuge um Auge, Zahn um Zahn.\n",
        },
        "wikisource": {"Hänsel und Gretel (1857)": "Vor einem großen Walde wohnte ein armer Holzhacker. " * 30},
        "wikivoyage": {"Lissabon": "Lissabon ist die Hauptstadt Portugals. Die Altstadt Alfama ist hügelig. " * 20},
    }

    def get(self, url, params=None, timeout=None):
        projekt = url.split("//de.")[1].split(".org")[0]
        seiten = self.SEITEN.get(projekt, {})

        class A:
            status_code, ok = 200, True

            def __init__(s, d):
                s.d = d

            def json(s):
                return s.d

            def raise_for_status(s):
                pass
        if params.get("list") == "search":
            treffer = [t for t in seiten if params["srsearch"].split(" ")[0].lower() in t.lower()]
            return A({"query": {"search": [{"title": t} for t in treffer]}})
        titel = params["titles"]
        if titel not in seiten:
            return A({"query": {"pages": [{"title": titel, "missing": True}]}})
        return A({"query": {"pages": [{"title": titel, "extract": seiten[titel],
                                       "fullurl": f"https://de.{projekt}.org/wiki/{titel}"}]}})


@pytest.fixture(autouse=True)
def _kein_internet(monkeypatch):
    monkeypatch.setattr(wikimedia, "HTTP", Wikimedia())

SKRIPT = {
    "geeignet": True, "titel": "Der verlorene Sohn",
    "hook": {"text": "Er verprasste alles und kam trotzdem *nach Hause*.", "bild": "lonely road at dawn"},
    "szenen": [{"text": "Ein junger Mann verlangt von seinem Vater sein Erbe und zieht in die *Ferne*.",
                "bild": "young man leaving a farm"} for _ in range(6)],
    "frage": "Hättest du ihm verziehen?",
    "hashtags": ["#bibel"],
}


def test_bibelstellen_werden_erkannt_und_gelesen():
    assert bibel.wortlaut("Psalm 23,1") == ("Psalm 23,1", "Der HERR ist mein Hirte; mir wird nichts mangeln.")
    assert bibel.wortlaut("Joh 3:16")[0] == "Johannes 3,16"
    assert bibel.wortlaut("1. Kor 13,13")[1].startswith("Nun aber bleibt Glaube, Hoffnung, Liebe")
    assert bibel.text("1. Mose 6-9")[0] == "1. Mose 6–9"
    assert bibel.wortlaut("Psalm 151,1") is None
    assert not bibel.ist_stelle("Brüder Grimm")
    assert not bibel.ist_stelle("Friedrich Schiller")


def test_zitate_nehmen_bibeltext_im_wortlaut():
    cfg = {"texte": {"quelle": "zitate", "thema": "", "stil": "", "text_ki": "cloudflare"}, "beschreibung": "Bibelverse"}
    antwort = {"text": "Der Herr ist mein Hirte, nichts wird mir fehlen", "stelle": "Psalm 23,1", "autor": "",
               "kategorie": "Vertrauen", "hashtags": ["#bibel"], "bild": "green pasture"}
    e = sprueche.ki_spruch(cfg, {}, chat=lambda n, m: json.dumps(antwort))
    assert e["text"] == "Der HERR ist mein Hirte; mir wird nichts mangeln."
    assert e["autor"] == "Psalm 23,1" and e["ki"]


def test_zitate_falsche_stelle_wird_korrigiert():
    cfg = {"texte": {"quelle": "zitate", "thema": "", "stil": "", "text_ki": "cloudflare"}, "beschreibung": "Bibel"}
    antworten = iter([
        json.dumps({"text": "Erfunden", "stelle": "Psalm 200,1", "kategorie": "x", "hashtags": [], "bild": "x"}),
        json.dumps({"text": "Gott ist Liebe", "stelle": "1. Johannes 4,16", "kategorie": "x", "hashtags": [], "bild": "x"}),
    ])
    gesehen = []

    def chat(n, m):
        gesehen.append(n[-1]["content"])
        return next(antworten)

    e = sprueche.ki_spruch(cfg, {}, chat=chat)
    assert e["autor"] == "1. Johannes 4,16" and "Gott ist die Liebe" in e["text"]
    assert "gibt es nicht" in gesehen[-1]


def _zitat(text, autor):
    return json.dumps({"text": text, "autor": autor, "kategorie": "x", "hashtags": [], "bild": "x"})


ZITAT_CFG = {"texte": {"quelle": "zitate", "thema": "", "stil": "", "text_ki": "cloudflare"}, "beschreibung": "Dichtung"}


def test_zitat_ohne_autor_wird_abgelehnt():
    antworten = iter([_zitat("Es irrt der Mensch, solang er strebt.", ""),
                      _zitat("Es irrt der Mensch, solang er strebt.", "Goethe")])
    gesehen = []

    def chat(n, m):
        gesehen.append(n[-1]["content"])
        return next(antworten)

    e = sprueche.ki_spruch(ZITAT_CFG, {}, chat=chat)
    assert "autor fehlt" in gesehen[1]
    assert e["autor"] == "Johann Wolfgang von Goethe"  # Wikiquote-Titel (Weiterleitung im echten Wikiquote)


def test_falsch_zugeschriebenes_zitat_wird_durch_belegtes_ersetzt():
    antworten = iter([_zitat("Wer immer strebend sich bemüht, dem gehört die ganze Welt.", "Johann Wolfgang von Goethe"),
                      _zitat("Edel sei der Mensch, hilfreich und gut", "Johann Wolfgang von Goethe")])
    gesehen = []

    def chat(n, m):
        gesehen.append(n[-1]["content"])
        return next(antworten)

    e = sprueche.ki_spruch(ZITAT_CFG, {}, chat=chat)
    assert "nicht belegt" in gesehen[1] and "Edel sei der Mensch" in gesehen[1]
    assert "dem gehört die ganze Welt" not in gesehen[1]  # Abschnitt "Falsch zugeschrieben" nie anbieten
    assert e["text"] == "Edel sei der Mensch, hilfreich und gut!"


def test_sprichwort_und_unbekannte_person():
    antworten = iter([_zitat("Ein Zitat", "Max Mustermann"), _zitat("Aller Anfang ist schwer", "Sprichwort")])
    gesehen = []

    def chat(n, m):
        gesehen.append(n[-1]["content"])
        return next(antworten)

    e = sprueche.ki_spruch(ZITAT_CFG, {}, chat=chat)
    assert "keine belegten Zitate" in gesehen[1]
    assert e["text"] == "Aller Anfang ist schwer." and e["autor"] == "Sprichwort"


def test_wissen_holt_ideen_und_merkt_titel():
    antworten = iter([json.dumps({"ideen": [{"titel": "3 Fehler beim Planken"}]}),
                      json.dumps({**SKRIPT, "titel": "3 Fehler beim Planken"})])
    gesehen = []

    def chat(n, m):
        gesehen.append(n[0]["content"])
        return next(antworten)

    g = {"quelle": "wissen", "thema": "Fitness zu Hause", "beschreibung": "Fitness", "szenen": 6,
         "suchbegriffe": [], "text_ki": "cloudflare"}
    skript = geschichten.neue_geschichte(g, {}, chat=chat)
    assert skript["merken"] == ["wissen:3 Fehler beim Planken"] and skript["quelle_art"] == "wissen"
    assert "Tipp" in gesehen[1]


def test_nacherzaehlung_bibel_nutzt_originaltext():
    gesehen = []
    antworten = iter([json.dumps({"ideen": [{"titel": "Der verlorene Sohn", "stelle": "Lukas 15,11-32"}]}),
                      json.dumps(SKRIPT)])

    def chat(n, m):
        gesehen.append(n[-1]["content"])
        return next(antworten)

    g = {"quelle": "nacherzaehlung", "thema": "Bibel", "beschreibung": "Bibelgeschichten", "szenen": 6,
         "suchbegriffe": [], "text_ki": "cloudflare", "hashtags": []}
    skript = geschichten.neue_geschichte(g, {}, chat=chat)
    assert "Ein Mensch hatte zwei Söhne" in gesehen[1]
    assert skript["quelle"] == "Lukas 15,11–32" and skript["merken"] == ["erz:Der verlorene Sohn"]
    caption = reels.geschichten_caption({"geschichten": {"hashtags": []}}, skript)
    assert "Nacherzählt nach Lukas 15,11–32 (Luther 1912)" in caption


def test_nacherzaehlung_ohne_bibel_aus_wissen_der_ki():
    gesehen = []
    antworten = iter([json.dumps({"ideen": [{"titel": "Hänsel und Gretel", "stelle": "Brüder Grimm"}]}),
                      json.dumps({**SKRIPT, "titel": "Hänsel und Gretel"})])

    def chat(n, m):
        gesehen.append(n[-1]["content"])
        return next(antworten)

    g = {"quelle": "nacherzaehlung", "thema": "Märchen", "beschreibung": "Märchen", "szenen": 6,
         "suchbegriffe": [], "text_ki": "cloudflare", "hashtags": []}
    skript = geschichten.neue_geschichte(g, {"wiki_benutzt": ["erz:Rotkäppchen"]}, chat=chat)
    assert "Rotkäppchen" in gesehen[0]
    assert "Vor einem großen Walde wohnte ein armer Holzhacker" in gesehen[1]  # Originaltext von Wikisource
    assert skript["quelle_projekt"] == "wikisource"
    caption = reels.geschichten_caption({"geschichten": {"hashtags": []}}, skript)
    assert "Nacherzählt nach Brüder Grimm (Originaltext: Wikisource)" in caption


def test_nacherzaehlung_ohne_originaltext_aus_wissen_der_ki():
    gesehen = []
    antworten = iter([json.dumps({"ideen": [{"titel": "Der Rattenfänger von Hameln", "stelle": "deutsche Sage"}]}),
                      json.dumps({**SKRIPT, "titel": "Der Rattenfänger von Hameln"})])

    def chat(n, m):
        gesehen.append(n[-1]["content"])
        return next(antworten)

    g = {"quelle": "nacherzaehlung", "thema": "Sagen", "beschreibung": "Sagen", "szenen": 6,
         "suchbegriffe": [], "text_ki": "cloudflare", "hashtags": []}
    skript = geschichten.neue_geschichte(g, {}, chat=chat)
    assert "Erzähle diese Geschichte nach: Der Rattenfänger von Hameln" in gesehen[1]
    assert "Nacherzählt nach deutsche Sage" in reels.geschichten_caption({"geschichten": {"hashtags": []}}, skript)


def test_wissen_reiseziel_nutzt_wikivoyage():
    gesehen = []
    antworten = iter([json.dumps({"ideen": [{"titel": "Lissabon in 48 Stunden", "reiseziel": "Lissabon"}]}),
                      json.dumps({**SKRIPT, "titel": "Lissabon"})])

    def chat(n, m):
        gesehen.append(n[-1]["content"])
        return next(antworten)

    g = {"quelle": "wissen", "thema": "Städtereisen", "beschreibung": "Reisen", "szenen": 6,
         "suchbegriffe": [], "text_ki": "cloudflare", "hashtags": []}
    skript = geschichten.neue_geschichte(g, {}, chat=chat)
    assert "Die Altstadt Alfama" in gesehen[1]
    assert "Infos: Wikivoyage (Lissabon)" in reels.geschichten_caption({"geschichten": {"hashtags": []}}, skript)


def test_wissen_mit_sachthema_nutzt_wikipedia():
    from tests.test_inhaltsarten import Wiki

    gesehen = []
    antworten = iter([json.dumps({"ideen": [{"titel": "Das Rätsel der Mary Celeste", "wikipedia": "Mary Celeste"}]}),
                      json.dumps({**SKRIPT, "titel": "Mary Celeste"})])

    def chat(n, m):
        gesehen.append(n[-1]["content"])
        return next(antworten)

    g = {"quelle": "wissen", "thema": "Seefahrt", "beschreibung": "Fakten über Schiffe", "szenen": 6,
         "suchbegriffe": [], "text_ki": "cloudflare", "hashtags": []}
    skript = geschichten.neue_geschichte(g, {}, http=Wiki(), chat=chat)
    assert "Die Mary Celeste war eine Brigg" in gesehen[1]
    assert skript["quelle"] == "Mary Celeste"
    assert "Fakten: Wikipedia (Mary Celeste)" in reels.geschichten_caption({"geschichten": {"hashtags": []}}, skript)
