"""Neue Quellen: Bibel (Lutherbibel 1912), echte Zitate, Wissens-Reels, Nacherzählungen."""
import json

from autopilot import bibel, geschichten, reels, sprueche

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


def test_zitat_ohne_autor_wird_abgelehnt():
    cfg = {"texte": {"quelle": "zitate", "thema": "", "stil": "", "text_ki": "cloudflare"}, "beschreibung": "Philosophie"}
    antworten = iter([
        json.dumps({"text": "Ich weiß, dass ich nichts weiß.", "autor": "", "kategorie": "x", "hashtags": [], "bild": "x"}),
        json.dumps({"text": "Ich weiß, dass ich nichts weiß.", "autor": "Sokrates", "kategorie": "x", "hashtags": [], "bild": "x"}),
    ])
    e = sprueche.ki_spruch(cfg, {}, chat=lambda n, m: next(antworten))
    assert e["autor"] == "Sokrates"


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
    assert "Hänsel und Gretel" in gesehen[1] and "Brüder Grimm" in gesehen[1]
    assert "Nacherzählt nach Brüder Grimm" in reels.geschichten_caption({"geschichten": {"hashtags": []}}, skript)


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
