"""Tests für Story-Reels (Geschichten), Reels aus eigenen Medien und den Gesamtablauf."""
import json
import math
import random
import shutil
import struct
import subprocess
import wave

import pytest
from PIL import Image

from autopilot import __main__ as cli
from autopilot import geschichten, inhalte, instagram, reels, video
from autopilot.einstellungen import KitFehler, pruefen

ffmpeg_fehlt = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg fehlt")

SKRIPT = {
    "geeignet": True,
    "hook": {"text": "Das Schiff war völlig intakt. Nur die *Menschen* waren weg.", "bild": "empty ship at sea"},
    "szenen": [{"text": f"Szene {i}: Im Jahr 1872 trieb die Brigg führerlos über den *Atlantik*.",
                "bild": "old ship in fog"} for i in range(1, 7)],
    "frage": "Meuterei oder Naturgewalt?",
    "hashtags": ["#Geisterschiff", "mary celeste", "#rätsel"],
}


def basis(art, **extra):
    roh = {"instagram_name": "testkonto", "inhaltsart": art, "zeitplan": {
        "zeitzone": "Europe/Berlin",
        "bild": {"aktiv": True, "tage": ["mo"], "uhrzeit": "18:00"},
        "reel": {"aktiv": True, "tage": ["mo", "di", "mi", "do", "fr", "sa", "so"], "uhrzeit": "19:00"},
        "story": {"aktiv": True}},
        "geschichten": {"suchbegriffe": ["Geisterschiff"], "startartikel": ["Mary Celeste"]}}
    roh.update(extra)
    return pruefen(roh)


@pytest.fixture
def ordner(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "AUSGABE", str(tmp_path / "ausgabe"))
    monkeypatch.setattr(cli, "ROOT", str(tmp_path))
    v = str(tmp_path / "verlauf.json")
    monkeypatch.setattr(inhalte.verlauf_laden, "__defaults__", (v,))
    monkeypatch.setattr(inhalte.verlauf_speichern, "__defaults__", (v,))
    csv = tmp_path / "posts.csv"
    csv.write_text("text;autor;kategorie\nSonne im Herzen.;;Mut\nWeiter geht's.;;Fokus\n", encoding="utf-8")
    monkeypatch.setattr(inhalte.posts_laden, "__defaults__", (str(csv),))
    medien = tmp_path / "medien"
    medien.mkdir()
    monkeypatch.setattr(reels, "MEDIEN", str(medien))
    monkeypatch.setattr(cli.reel, "MUSIK", str(tmp_path / "musik"))
    return tmp_path


class FalscheStimme:
    def __init__(self, tempo=1.0):
        self.tempo = tempo

    def sprechen(self, text, ziel):
        sekunden = 0.4 + 0.05 * len(text.split())
        with wave.open(ziel, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(22050)
            w.writeframes(b"".join(struct.pack("<h", int(3000 * math.sin(i / 20)))
                                   for i in range(int(22050 * sekunden))))
        return sekunden


def dauer_von(pfad):
    aus = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", pfad],
                         capture_output=True, text=True, check=True).stdout
    return float(aus)


# ---------------------------------------------------------------- Einstellungen

def test_inhaltsart_wird_geprueft():
    with pytest.raises(KitFehler, match="inhaltsart"):
        basis("videos")
    assert basis("geschichten")["plan"]["bild"]["aktiv"] is False  # Feed-Bilder nur bei Zitaten


def test_geschichten_brauchen_suchbegriffe():
    with pytest.raises(KitFehler, match="Suchbegriff"):
        basis("geschichten", geschichten={"suchbegriffe": []})


def test_story_folgt_dem_reel_bei_geschichten():
    cfg = basis("geschichten")
    jetzt = __import__("datetime").datetime(2026, 11, 18, 19, 30, tzinfo=cfg["zeitzone"])
    assert inhalte.faellig(cfg, {"zuletzt": {}}, jetzt) == ["reel", "story"]


# ---------------------------------------------------------------- Geschichten: Text

class Wiki:
    """Falsche Wikipedia mit zwei Artikeln."""

    def __init__(self):
        self.seiten = {"Mary Celeste": "Die Mary Celeste war eine Brigg. " * 80,
                       "Kurz": "Zu kurz."}

    def get(self, url, params=None, timeout=None):
        class A:
            status_code, ok = 200, True

            def __init__(s, d):
                s.d = d

            def json(s):
                return s.d

            def raise_for_status(s):
                pass
        if params.get("list") == "search":
            return A({"query": {"search": [{"title": "Kurz"}, {"title": "Mary Celeste"}]}})
        titel = params["titles"]
        return A({"query": {"pages": [{"title": titel, "extract": self.seiten.get(titel, ""),
                                       "fullurl": f"https://de.wikipedia.org/wiki/{titel}",
                                       "langlinks": [{"lang": "en", "title": titel}]}]}})


def test_skript_pruefung_und_aufraeumen():
    assert geschichten.pruefen(SKRIPT) == []
    kaputt = json.loads(json.dumps(SKRIPT))
    kaputt["szenen"] = kaputt["szenen"][:2]
    assert any("6 Szenen" in p for p in geschichten.pruefen(kaputt))
    sauber = geschichten.aufraeumen(json.loads(json.dumps(SKRIPT)))
    assert sauber["hashtags"] == ["#geisterschiff", "#maryceleste", "#rätsel"]


def test_neue_geschichte_aus_startartikel():
    g = basis("geschichten")["geschichten"]
    antworten = iter(["kein json", json.dumps(SKRIPT)])
    skript = geschichten.neue_geschichte(g, {}, http=Wiki(), chat=lambda n, m: next(antworten),
                                         zufall=random.Random(1))
    assert skript["titel"] == "Mary Celeste"
    assert "en:Mary Celeste" in skript["merken"]


def test_ki_korrektur_runde():
    g = basis("geschichten")["geschichten"]
    zu_kurz = json.loads(json.dumps(SKRIPT))
    zu_kurz["szenen"] = zu_kurz["szenen"][:3]
    antworten = iter([json.dumps(zu_kurz), json.dumps(SKRIPT)])
    skript, grund = geschichten.skript_schreiben(g, "X", "Text", chat=lambda n, m: next(antworten))
    assert skript and grund is None


def test_benutzte_und_abgelehnte_artikel_kommen_nicht_wieder():
    g = basis("geschichten")["geschichten"]
    verlauf = {"wiki_benutzt": ["Mary Celeste"]}
    with pytest.raises(KitFehler, match="Keine passende Geschichte"):
        geschichten.neue_geschichte(g, verlauf, http=Wiki(), chat=lambda n, m: json.dumps(SKRIPT))


def test_ungeeigneter_artikel_wird_gemerkt():
    g = basis("geschichten")["geschichten"]
    verlauf = {}
    with pytest.raises(KitFehler):
        geschichten.neue_geschichte(g, verlauf, http=Wiki(),
                                    chat=lambda n, m: '{"geeignet": false, "grund": "kein Thema"}')
    assert "Mary Celeste" in verlauf["wiki_abgelehnt"]


def test_ohne_cloudflare_klare_meldung(monkeypatch):
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
    g = basis("geschichten")["geschichten"]
    with pytest.raises(KitFehler, match="CLOUDFLARE"):
        geschichten.skript_schreiben(g, "X", "Text")


# ---------------------------------------------------------------- Geschichten: Video

@ffmpeg_fehlt
def test_story_reel_mit_sprecher(tmp_path):
    cfg = basis("geschichten")
    farben = iter([(90, 30, 30), (30, 90, 30)] * 10)
    quelle = lambda prompt: Image.new("RGB", (768, 1344), next(farben))
    skript = geschichten.aufraeumen(json.loads(json.dumps(SKRIPT)))
    ziel = str(tmp_path / "reel.mp4")
    gesamt, titel, quellen = reels.geschichten_reel(cfg, skript, ziel, sprecher=FalscheStimme(), bild_quelle=quelle)
    assert quellen == ["ki"] * 7
    assert abs(dauer_von(ziel) - gesamt) < 0.3  # Bild und Ton gleich lang
    assert Image.open(titel).size == (1080, 1920)
    streams = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", ziel],
                             capture_output=True, text=True, check=True).stdout.split()
    assert sorted(streams) == ["audio", "video"]


@ffmpeg_fehlt
def test_story_reel_ohne_ki_bilder_und_ohne_sprecher(tmp_path):
    cfg = basis("geschichten")
    skript = geschichten.aufraeumen(json.loads(json.dumps(SKRIPT)))
    _, _, quellen = reels.geschichten_reel(cfg, skript, str(tmp_path / "r.mp4"), bild_quelle=lambda p: None)
    assert set(quellen) == {"farbverlauf"}


def test_caption_nennt_quelle_und_ki():
    cfg = basis("geschichten")
    skript = geschichten.aufraeumen(json.loads(json.dumps(SKRIPT)))
    skript["titel"] = "Mary Celeste"
    text = reels.geschichten_caption(cfg, skript)
    assert "Quelle: Wikipedia (Mary Celeste)" in text and "KI-generiert" in text
    assert "*" not in text


# ---------------------------------------------------------------- eigene Medien

def medien_anlegen(ordner, n_fotos=3, video_dazu=True):
    for i in range(n_fotos):
        Image.new("RGB", (1200, 900), (40 * i, 80, 120)).save(ordner / "medien" / f"foto_{i}.jpg")
    if video_dazu:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=25",
                        "-t", "1", str(ordner / "medien" / "clip.mp4")], check=True)


def test_medien_rotation(ordner):
    for i in range(5):
        (ordner / "medien" / f"m{i}.jpg").write_bytes(b"x")
    cfg = basis("eigene_medien", eigene_medien={"pro_reel": 2})
    verlauf = {"medien_benutzt": ["m0.jpg", "m1.jpg", "m2.jpg", "m3.jpg"]}
    wahl = reels.medien_waehlen(cfg, verlauf, random.Random(0))
    assert "m4.jpg" in wahl and len(wahl) == 2


@ffmpeg_fehlt
def test_medien_reel_mit_foto_und_video(ordner):
    medien_anlegen(ordner)
    cfg = basis("eigene_medien", eigene_medien={"pro_reel": 4, "sekunden_pro_clip": 1.5})
    dateien = reels.medien_waehlen(cfg, {})
    ziel = str(ordner / "r.mp4")
    gesamt, titel = reels.medien_reel(cfg, dateien, ziel, {"text": "Weiter geht's."})
    assert gesamt == 6.0
    assert abs(dauer_von(ziel) - 6.0) < 0.3
    assert Image.open(titel).size == (1080, 1920)


# ---------------------------------------------------------------- Gesamtablauf

class Instagram:
    def __init__(self):
        self.posts = []

    def get(self, url, params=None, timeout=None, headers=None):
        class A:
            ok, status_code = True, 200

            def __init__(s, d):
                s.d, s.text = d, json.dumps(d)

            def json(s):
                return s.d
        if url.endswith("/me"):
            return A({"user_id": "1", "username": "testkonto"})
        return A({"status_code": "FINISHED"})

    def post(self, url, data=None, timeout=None):
        self.posts.append(data)

        class A:
            ok, status_code, text = True, 200, "{}"

            def json(s):
                return {"id": "x"}
        return A()


@ffmpeg_fehlt
def test_lauf_eigene_medien_postet_reel_und_story(ordner, monkeypatch):
    medien_anlegen(ordner, n_fotos=2, video_dazu=False)
    cfg = basis("eigene_medien", eigene_medien={"pro_reel": 2, "sekunden_pro_clip": 1})
    monkeypatch.setattr(cli, "laden", lambda: cfg)
    ig = Instagram()
    monkeypatch.setattr(instagram, "SITZUNG", ig)
    monkeypatch.setenv("IG_ACCESS_TOKEN", "T")
    monkeypatch.setenv("GITHUB_REPOSITORY", "anna/ap")
    bereitgestellt = []
    assert cli.lauf("jetzt-posten", bereitstellen=lambda: bereitgestellt.append(1)) == 0
    arten = [p.get("media_type") for p in ig.posts if "creation_id" not in p]
    assert arten == ["REELS", "STORIES"] and bereitgestellt == [1]
    verlauf = inhalte.verlauf_laden()
    assert sorted(verlauf["medien_benutzt"]) == ["foto_0.jpg", "foto_1.jpg"]


def test_lauf_nichts_dran(ordner, monkeypatch):
    cfg = basis("zitate")
    cfg["plan"]["bild"]["aktiv"] = cfg["plan"]["reel"]["aktiv"] = False
    monkeypatch.setattr(cli, "laden", lambda: cfg)
    assert cli.lauf("automatisch", bereitstellen=lambda: pytest.fail("darf nicht hochladen")) == 0


def test_story_ohne_reel_erklaert_sich(ordner):
    with pytest.raises(KitFehler, match="Titelbild des Reels"):
        cli.erstellen(basis("geschichten"), "story", {})


def test_video_konstanten():
    assert (video.B, video.H) == (1080, 1920)


# ---------------------------------------------------------------- Token-Arten und Quellen

def test_token_art_erkennen():
    from autopilot import instagram
    assert instagram.ist_systemnutzer_token("EAGpAbc")
    assert not instagram.ist_systemnutzer_token("IGAAxyz")
    assert instagram._api("EAGp") == instagram.FB_API and instagram._api("IGAA") == instagram.IG_API


def test_systemnutzer_konto_id_aus_debug_token(monkeypatch):
    from autopilot import instagram
    aufrufe = []

    def falsch_get(pfad, token, **params):
        aufrufe.append(pfad)
        if pfad == "debug_token":
            return {"data": {"granular_scopes": [
                {"scope": "instagram_basic", "target_ids": ["17841474886132946"]},
                {"scope": "instagram_content_publish", "target_ids": ["17841474886132946"]},
                {"scope": "ads_read"}]}}
        return {"username": "mindset_und.motivation"}

    monkeypatch.setattr(instagram, "_get", falsch_get)
    assert instagram.konto("EAGtest") == ("17841474886132946", "mindset_und.motivation")
    assert instagram.konto("EAGtest", "123") == ("123", "mindset_und.motivation")
    assert aufrufe[-1] == "123"


def test_systemnutzer_ohne_id_erklaert(monkeypatch):
    from autopilot import instagram
    monkeypatch.setattr(instagram, "_get", lambda pfad, token, **p: {"data": {}})
    with pytest.raises(KitFehler, match="instagram_konto_id"):
        instagram.konto("EAGtest")


def test_systemnutzer_token_wird_nicht_erneuert():
    from autopilot import instagram
    assert instagram.token_erneuern("EAGtest") == ("EAGtest", None)


def test_caption_kennzeichnet_fiktion():
    cfg = {"geschichten": {"hashtags": ["#grusel"]}}
    skript = {"hook": {"text": "Die Tür war *offen*."}, "frage": "Würdest du reingehen?",
              "hashtags": [], "titel": "Die Tür", "quelle_art": "fiktion"}
    text = reels.geschichten_caption(cfg, skript)
    assert "Fiktive Geschichte" in text and "Wikipedia" not in text


def test_eigene_texte_laden(tmp_path):
    from autopilot import geschichten
    datei = tmp_path / "g.txt"
    datei.write_text("# Kommentar\nTitel A\nText A eins.\n---\n\nTitel B\nText B.\n---\n", encoding="utf-8")
    texte = geschichten.eigene_texte_laden(str(datei))
    assert [t[1] for t in texte] == ["Titel A", "Titel B"]
    assert texte[0][2] == "Text A eins." and texte[0][0].startswith("text:")


def test_fiktion_merkt_titel():
    from autopilot import geschichten
    skript = {"geeignet": True, "titel": "Das Haus am See",
              "hook": {"text": "Niemand wohnte dort seit 40 Jahren.", "bild": "old house by a lake at night"},
              "szenen": [{"text": "Ein Licht brannte jede Nacht im obersten Fenster des alten Hauses.",
                          "bild": "lit window in dark house, fog"}] * 6,
              "frage": "Würdest du hineingehen?", "hashtags": ["#grusel"]}
    gesehen = {}

    def chat(nachrichten, modell):
        gesehen["system"] = nachrichten[0]["content"]
        gesehen["nutzer"] = nachrichten[1]["content"]
        return json.dumps(skript)

    g = {"thema": "Gruselgeschichten", "quelle": "fiktion", "suchbegriffe": ["verlassenes Haus"],
         "suchbegriffe_englisch": [], "text_ki": "cloudflare"}
    verlauf = {"wiki_benutzt": ["fiktion:Der Brunnen"]}
    ergebnis = geschichten.neue_geschichte(g, verlauf, chat=chat)
    assert ergebnis["merken"] == ["fiktion:Das Haus am See"] and ergebnis["quelle_art"] == "fiktion"
    assert "frei erfundene" in gesehen["system"] and "Der Brunnen" in gesehen["nutzer"]
