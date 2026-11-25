"""Eigene Quellen (PDF, Text, Webseiten) und eigene Fotos in Sprecher-Reels."""
import json

from PIL import Image

from autopilot import eigene_quellen, geschichten, reels, sprueche

SKRIPT = {
    "geeignet": True, "titel": "Der Bodensee",
    "hook": {"text": "Der Bodensee liegt an drei Ländern zugleich, wusstest du das?", "bild": "lake"},
    "szenen": [{"text": "Der Bodensee grenzt an Deutschland, Österreich und die Schweiz, mitten in Europa.",
                "bild": "lake"} for _ in range(6)],
    "frage": "Warst du schon einmal dort?", "hashtags": ["#bodensee"],
}


class Web:
    def get(self, url, timeout=None, headers=None):
        class A:
            text = ("<html><nav>Menü</nav><script>x()</script><h1>Bodensee</h1><p>" + "Der Bodensee ist ein See. " * 40
                    + "</p><footer>Impressum</footer></html>")

            def raise_for_status(self):
                pass
        return A()


def _ordner(tmp_path, monkeypatch):
    q = tmp_path / "quellen"
    q.mkdir()
    monkeypatch.setattr(eigene_quellen, "ORDNER", str(q))
    monkeypatch.setattr(eigene_quellen, "LINKS", str(q / "links.txt"))
    return q


def test_textdatei_und_webseite_werden_gelesen(tmp_path, monkeypatch):
    q = _ordner(tmp_path, monkeypatch)
    (q / "LIESMICH.txt").write_text("Anleitung", encoding="utf-8")
    (q / "notizen.txt").write_text("Mein Wissen über Kräuter. " * 30, encoding="utf-8")
    (q / "links.txt").write_text("# Kommentar\nhttps://example.org/bodensee\n", encoding="utf-8")
    assert eigene_quellen.dateien() == ["notizen.txt"]
    quellen = eigene_quellen._quellen_laden(Web())
    assert [n for n, _ in quellen] == ["notizen.txt", "https://example.org/bodensee"]
    web = quellen[1][1]
    assert "Bodensee ist ein See" in web and "Menü" not in web and "Impressum" not in web and "x()" not in web
    assert eigene_quellen.anzeigename("https://www.example.org/a/b") == "example.org"
    assert eigene_quellen.anzeigename("Mein_Buch.pdf") == "Mein Buch"


def test_abschnitte_reihum_und_neustart(tmp_path, monkeypatch):
    q = _ordner(tmp_path, monkeypatch)
    (q / "a.txt").write_text(("Absatz über Thema A. " * 60 + "\n\n") * 4, encoding="utf-8")
    (q / "b.md").write_text("Thema B in kurz. " * 40, encoding="utf-8")
    benutzt, namen = set(), []
    for _ in range(6):
        name, _, kennung = eigene_quellen.naechster_abschnitt(benutzt)
        benutzt.add(kennung)
        namen.append(name)
    assert namen[0] != namen[1]  # beide Quellen kommen früh dran
    assert len(set(namen)) == 2


def test_pdf_wird_gelesen(tmp_path, monkeypatch):
    from pypdf import PdfWriter

    q = _ordner(tmp_path, monkeypatch)
    w = PdfWriter()
    w.add_blank_page(200, 200)
    with open(q / "leer.pdf", "wb") as f:
        w.write(f)
    assert eigene_quellen._quellen_laden() == []  # leere/gescannte PDF wird übersprungen, kein Absturz


def test_sprecher_reel_aus_eigener_quelle(tmp_path, monkeypatch):
    q = _ordner(tmp_path, monkeypatch)
    (q / "Bodensee.txt").write_text("Der Bodensee grenzt an Deutschland, Österreich und die Schweiz. " * 20,
                                    encoding="utf-8")
    gesehen = []
    antworten = iter([json.dumps(SKRIPT), json.dumps({"falsch": []})])

    def chat(n, m):
        gesehen.append(n[-1]["content"])
        return next(antworten)

    g = {"quelle": "eigene_quellen", "thema": "Seen", "beschreibung": "Seen", "szenen": 6, "text_ki": "cloudflare",
         "hashtags": []}
    skript = geschichten.neue_geschichte(g, {}, chat=chat)
    assert "Abschnitt aus der Quelle „Bodensee“" in gesehen[0]
    assert skript["merken"][0].startswith("quelle:")
    assert "Quelle: Bodensee." in reels.geschichten_caption({"geschichten": {"hashtags": []}}, skript)


def test_fakten_post_aus_eigener_quelle(tmp_path, monkeypatch):
    q = _ordner(tmp_path, monkeypatch)
    (q / "Kraeuterbuch.txt").write_text("Salbei wächst gern an sonnigen, trockenen Plätzen. " * 20,
                                        encoding="utf-8")
    cfg = {"texte": {"quelle": "eigene_quellen", "thema": "", "stil": "", "text_ki": "cloudflare"},
           "beschreibung": "Kräuter"}
    antworten = iter([json.dumps({"text": "Salbei wächst am liebsten an sonnigen, trockenen Plätzen.",
                                  "kategorie": "Kräuter", "hashtags": ["#salbei"], "bild": "sage"}),
                      json.dumps({"falsch": []})])
    e = sprueche.naechster_spruch(cfg, {}, "bild", [], chat=lambda n, m: next(antworten))
    assert e["autor"] == "Quelle: Kraeuterbuch" and e["fakten_artikel"].startswith("quelle:")


def test_eigene_fotos_im_sprecher_reel(tmp_path, monkeypatch):
    medien = tmp_path / "medien"
    medien.mkdir()
    for i in range(2):
        Image.new("RGB", (40, 60), (i * 100, 0, 0)).save(medien / f"foto{i}.jpg")
    (medien / "clip.mp4").write_bytes(b"x")
    monkeypatch.setattr(reels, "MEDIEN", str(medien))
    assert len(reels.eigene_fotos()) == 2
    ki = []
    monkeypatch.setattr(reels.ki_bilder, "erzeugen", lambda p: ki.append(p) or Image.new("RGB", (10, 10)))
    quelle = reels._bildquelle("gemischt")
    bilder = [quelle("p") for _ in range(4)]
    assert len(ki) == 2 and bilder[0].size == (40, 60)
    assert reels._bildquelle("ki") is reels.ki_bilder.erzeugen
