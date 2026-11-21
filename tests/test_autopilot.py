import json
import random
import shutil
import subprocess
from datetime import date, datetime

import pytest
import yaml
from PIL import Image

from autopilot import __main__ as cli
from autopilot import design, einstellungen, inhalte, instagram, reel
from autopilot.einstellungen import KitFehler, pruefen

BASIS = {"instagram_name": "testkonto", "zeitplan": {
    "zeitzone": "Europe/Berlin",
    "bild": {"aktiv": True, "tage": ["mo", "di", "mi", "do", "fr", "sa", "so"], "uhrzeit": "18:00"},
    "reel": {"aktiv": True, "tage": ["so"], "uhrzeit": "17:00"},
    "story": {"aktiv": True},
}}


@pytest.fixture
def cfg():
    return pruefen(json.loads(json.dumps(BASIS)))


@pytest.fixture
def arbeitsordner(tmp_path, monkeypatch):
    """Leitet Ausgabe, Verlauf und posts.csv in einen Temp-Ordner um."""
    monkeypatch.setattr(cli, "AUSGABE", str(tmp_path / "ausgabe"))
    monkeypatch.setattr(cli, "ROOT", str(tmp_path))
    monkeypatch.setattr(inhalte, "VERLAUF", str(tmp_path / "verlauf.json"))
    csv = tmp_path / "posts.csv"
    csv.write_text("text;autor;kategorie\nErster Spruch hier.;Anna;Mut\nZweiter Spruch.;;Fokus\n", encoding="utf-8-sig")
    monkeypatch.setattr(inhalte, "POSTS_CSV", str(csv))
    monkeypatch.setattr(inhalte.posts_laden, "__defaults__", (str(csv),))
    monkeypatch.setattr(inhalte.verlauf_laden, "__defaults__", (str(tmp_path / "verlauf.json"),))
    monkeypatch.setattr(inhalte.verlauf_speichern, "__defaults__", (str(tmp_path / "verlauf.json"),))
    monkeypatch.setattr(design, "HINTERGRUENDE", str(tmp_path / "leer"))
    return tmp_path


# ---------------------------------------------------------------- Einstellungen

def test_mitgelieferte_einstellungen_verlangen_eigenen_namen():
    with pytest.raises(KitFehler, match="instagram_name"):
        einstellungen.laden()


def test_mitgelieferte_einstellungen_sonst_gueltig():
    with open(einstellungen.EINSTELLUNGEN, encoding="utf-8") as f:
        roh = yaml.safe_load(f)
    roh["instagram_name"] = "mein_account"
    with pytest.raises(KitFehler, match="Beschreibe deinen Account"):
        pruefen(roh)
    roh["account"]["beschreibung"] = "Tipps für Hobbygärtner auf dem Balkon, locker und praktisch."
    cfg = pruefen(roh)
    assert cfg["plan"]["reel"]["tage"] == [6] and cfg["texte"]["quelle"] == "ki"
    assert cfg["bildpost"] == "ki_mit_text" and cfg["geschichten"]["szenen"] == 6
    assert len(cfg["farbverlaeufe"]) >= 3


@pytest.mark.parametrize("feld,wert,meldung", [
    (("zeitplan", "bild", "uhrzeit"), "25:00", "Uhrzeit"),
    (("zeitplan", "bild", "tage"), ["montag", "xx"], "Wochentag"),
    (("zeitplan", "zeitzone"), "Mond/Basis", "Zeitzone"),
])
def test_verstaendliche_fehler(feld, wert, meldung):
    roh = json.loads(json.dumps(BASIS))
    ziel = roh
    for teil in feld[:-1]:
        ziel = ziel[teil]
    ziel[feld[-1]] = wert
    with pytest.raises(KitFehler, match=meldung):
        pruefen(roh)


def test_yaml_tippfehler_nennt_zeile(tmp_path):
    datei = tmp_path / "e.yml"
    datei.write_text('instagram_name: "x"\nzeitplan:\n  bild:\n   aktiv: true\n  - kaputt\n', encoding="utf-8")
    with pytest.raises(KitFehler, match="Tippfehler"):
        einstellungen.laden(str(datei))


# ---------------------------------------------------------------- Inhalte

def test_leere_posts_csv_erklaert():
    with pytest.raises(KitFehler, match="keine Texte"):
        inhalte.posts_laden()

def test_csv_mit_komma_und_ohne_optionale_spalten(tmp_path):
    datei = tmp_path / "p.csv"
    datei.write_text('text\n"Hallo, Welt"\n\nNoch einer\n', encoding="utf-8")
    eintraege = inhalte.posts_laden(str(datei))
    assert [e["text"] for e in eintraege] == ["Hallo, Welt", "Noch einer"]


def test_csv_ohne_text_spalte(tmp_path):
    datei = tmp_path / "p.csv"
    datei.write_text("spruch;autor\nx;y\n", encoding="utf-8")
    with pytest.raises(KitFehler, match="text"):
        inhalte.posts_laden(str(datei))


def test_rotation_ohne_wiederholung_dann_neue_runde():
    eintraege = [{"id": str(i), "text": str(i)} for i in range(3)]
    verlauf = inhalte.verlauf_laden("/nicht/vorhanden.json")
    alle = [e["id"] for e in eintraege]
    gesehen = []
    for _ in range(3):
        e = inhalte.naechster(eintraege, verlauf, "bild", "zufall", random.Random(1))
        gesehen.append(e["id"])
        inhalte.als_benutzt_markieren(verlauf, "bild", e["id"], alle)
    assert sorted(gesehen) == alle
    # Runde voll -> neue Runde, der zuletzt gepostete kommt dort aber nicht sofort wieder
    assert verlauf["benutzt"]["bild"] == [gesehen[-1]]


def test_der_reihe_nach():
    eintraege = [{"id": "a", "text": "a"}, {"id": "b", "text": "b"}]
    verlauf = {"benutzt": {"bild": ["a"]}}
    assert inhalte.naechster(eintraege, verlauf, "bild", "der_reihe_nach")["id"] == "b"


def test_caption_ohne_autor_ohne_leerzeilen(cfg):
    cfg["hashtags_allgemein"] = ["#a", "#b", "#c"]
    cfg["hashtags_kategorie"] = {"Mut": ["#mut"]}
    cfg["caption_vorlage"] = "{text}\n\n{autor}\n•\n\n{hashtags}"
    text = inhalte.caption_bauen(cfg, {"text": "Spruch", "autor": "", "kategorie": "Mut"}, random.Random(0))
    assert text.startswith("Spruch\n\n")
    assert "\n\n\n" not in text
    assert "#mut" in text
    mit = inhalte.caption_bauen(cfg, {"text": "Spruch", "autor": "Anna", "kategorie": ""}, random.Random(0))
    assert "— Anna" in mit


# ---------------------------------------------------------------- Zeitplan

def zeit(tag, stunde, minute=0):
    return datetime(2026, 11, tag, stunde, minute, tzinfo=einstellungen.ZoneInfo("Europe/Berlin"))


def test_faellig_ab_uhrzeit_und_nur_einmal_pro_tag(cfg):
    verlauf = {"zuletzt": {}}
    assert inhalte.faellig(cfg, verlauf, zeit(18, 17, 59)) == []  # Mittwoch, zu früh
    assert inhalte.faellig(cfg, verlauf, zeit(18, 18, 17)) == ["bild", "story"]
    verlauf["zuletzt"] = {"bild": "2026-11-18", "story": "2026-11-18"}
    assert inhalte.faellig(cfg, verlauf, zeit(18, 22, 17)) == []


def test_reel_nur_sonntags(cfg):
    verlauf = {"zuletzt": {"bild": "2026-11-22", "story": "2026-11-22"}}
    assert inhalte.faellig(cfg, verlauf, zeit(22, 17, 30)) == ["reel"]  # Sonntag
    assert inhalte.faellig(cfg, {"zuletzt": {}}, zeit(21, 17, 30)) == []  # Samstag vor 18 Uhr


def test_story_folgt_fehlgeschlagener_story_nach(cfg):
    verlauf = {"zuletzt": {"bild": "2026-11-18"}}
    assert inhalte.faellig(cfg, verlauf, zeit(18, 19)) == ["story"]


def test_token_erst_merken_dann_woechentlich():
    verlauf = {"token_erneuert": None}
    assert inhalte.token_faellig(verlauf, date(2026, 11, 1)) is False
    assert verlauf["token_erneuert"] == "2026-11-01"
    assert inhalte.token_faellig(verlauf, date(2026, 11, 7)) is False
    assert inhalte.token_faellig(verlauf, date(2026, 11, 8)) is True


# ---------------------------------------------------------------- Bilder & Reel

def test_bild_und_story_haben_richtige_groesse(cfg, arbeitsordner):
    cli.erstellen(cfg, "bild")
    story = cli.erstellen(cfg, "story")
    bild = json.loads((arbeitsordner / "ausgabe" / "bild.json").read_text(encoding="utf-8"))
    assert story["eintrag_id"] == bild["eintrag_id"]  # Story zeigt denselben Spruch
    assert story["hintergrund"] == bild["hintergrund"]  # und denselben Hintergrund
    assert story["caption"] == ""
    assert Image.open(arbeitsordner / bild["datei"]).size == design.FEED
    assert Image.open(arbeitsordner / story["datei"]).size == design.HOCH


def test_langer_text_passt_ins_bild(cfg, tmp_path):
    eintrag = {"text": " ".join(["Durchhaltevermögen"] * 12), "autor": "Jemand"}
    ziel = design.bild_zeichnen(cfg, eintrag, "verlauf:0", design.FEED, str(tmp_path / "x.jpg"))
    assert Image.open(ziel).size == design.FEED


def test_eigenes_foto_wird_genutzt(cfg, tmp_path, monkeypatch):
    ordner = tmp_path / "hg"
    ordner.mkdir()
    Image.new("RGB", (800, 600), (200, 30, 30)).save(ordner / "rot.jpg")
    monkeypatch.setattr(design, "HINTERGRUENDE", str(ordner))
    verlauf = {}
    assert design.hintergrund_waehlen(cfg, verlauf) == "foto:rot.jpg"
    bild = design.hintergrund(cfg, "foto:rot.jpg", design.FEED)
    r, g, _ = bild.getpixel((10, 10))
    assert r > g and r < 200  # rot, aber abgedunkelt


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg fehlt")
def test_reel_wird_gebaut(cfg, tmp_path):
    ziel = str(tmp_path / "r.mp4")
    sekunden = reel.reel_bauen(cfg, {"text": "Kurz und gut."}, "verlauf:1", ziel)
    info = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0", ziel],
                          capture_output=True, text=True, check=True).stdout.strip()
    assert info == "1080,1920"
    assert sekunden == 6.0


# ---------------------------------------------------------------- Instagram (ohne echtes Netz)

class Antwort:
    def __init__(self, daten, status=200):
        self._daten, self.status_code, self.ok = daten, status, status < 400
        self.text = json.dumps(daten)

    def json(self):
        return self._daten


class FalscheSitzung:
    def __init__(self, username="testkonto"):
        self.posts, self.username = [], username

    def get(self, url, params=None, timeout=None, headers=None):
        if url.endswith("/me"):
            return Antwort({"user_id": "123", "username": self.username})
        if "refresh_access_token" in url:
            return Antwort({"access_token": "NEU", "expires_in": 5184000})
        return Antwort({"status_code": "FINISHED"})

    def post(self, url, data=None, timeout=None):
        self.posts.append((url.rsplit("/", 1)[-1], data))
        return Antwort({"id": "c1"} if url.endswith("/media") else {"id": "m1"})


def test_veroeffentlichen_bild_und_reel(monkeypatch):
    sitzung = FalscheSitzung()
    monkeypatch.setattr(instagram, "SITZUNG", sitzung)
    monkeypatch.setenv("GITHUB_REPOSITORY", "anna/autopilot")
    instagram.veroeffentlichen("T", "123", {"typ": "bild", "datei": "ausgabe/b.jpg", "caption": "Hi"}, lambda s: None)
    instagram.veroeffentlichen("T", "123", {"typ": "reel", "datei": "ausgabe/r.mp4", "caption": "Hi"}, lambda s: None)
    bild, _, video, _ = [d for _, d in sitzung.posts]
    assert bild["image_url"] == "https://raw.githubusercontent.com/anna/autopilot/media/b.jpg"
    assert video["media_type"] == "REELS" and video["video_url"].endswith("/media/r.mp4")


def test_falscher_account_postet_nicht(monkeypatch):
    sitzung = FalscheSitzung(username="anderer")
    monkeypatch.setattr(instagram, "SITZUNG", sitzung)
    with pytest.raises(KitFehler, match="NICHT gepostet"):
        instagram.konto_pruefen("T", "testkonto")
    assert sitzung.posts == []


def test_abgelaufener_token_wird_erklaert(monkeypatch):
    class Kaputt(FalscheSitzung):
        def get(self, *a, **k):
            return Antwort({"error": {"code": 190, "message": "Session expired"}}, 400)
    monkeypatch.setattr(instagram, "SITZUNG", Kaputt())
    with pytest.raises(KitFehler, match="ungültig oder abgelaufen"):
        instagram.konto("T")


def test_secret_speichern_braucht_schreibtoken(monkeypatch):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    with pytest.raises(KitFehler, match="SECRETS_WRITE_TOKEN"):
        instagram.secret_speichern("IG_ACCESS_TOKEN", "x")
    monkeypatch.setenv("GH_TOKEN", "g")
    aufrufe = []

    def ausfuehren(befehl, **kw):
        aufrufe.append((befehl, kw["input"]))
        return subprocess.CompletedProcess(befehl, 0)
    instagram.secret_speichern("IG_ACCESS_TOKEN", "geheim", ausfuehren)
    assert aufrufe[0][1] == "geheim" and "geheim" not in aufrufe[0][0]


def test_posten_aktualisiert_verlauf(cfg, arbeitsordner, monkeypatch):
    monkeypatch.setattr(instagram, "SITZUNG", FalscheSitzung())
    monkeypatch.setattr(instagram.time, "sleep", lambda s: None)
    monkeypatch.setenv("IG_ACCESS_TOKEN", "T")
    monkeypatch.setenv("GITHUB_REPOSITORY", "anna/autopilot")
    post = cli.erstellen(cfg, "bild")
    cli.posten(cfg, "bild")
    verlauf = inhalte.verlauf_laden()
    heute = datetime.now(cfg["zeitzone"]).date().isoformat()
    assert verlauf["zuletzt"]["bild"] == heute
    assert verlauf["benutzt"]["bild"] == [post["eintrag_id"]]
    assert {k: verlauf["heute_bild"][k] for k in ("datum", "id")} == {"datum": heute, "id": post["eintrag_id"]}


# ---------------------------------------------------------------- Workflow

def test_workflow_ist_gueltiges_yaml():
    with open(einstellungen.ROOT + "/.github/workflows/autopilot.yml", encoding="utf-8") as f:
        wf = yaml.safe_load(f)
    schritte = [s.get("name", s.get("uses")) for s in wf["jobs"]["autopilot"]["steps"]]
    assert "Kit auspacken (nur beim ersten Lauf)" in schritte
    optionen = wf[True]["workflow_dispatch"]["inputs"]["aktion"]["options"]  # YAML liest "on" als True
    assert set(optionen) == set(cli.AKTIONEN)
    with open(einstellungen.ROOT + "/hilfe/autopilot.yml", encoding="utf-8") as f, \
            open(einstellungen.ROOT + "/.github/workflows/autopilot.yml", encoding="utf-8") as g:
        assert f.read() == g.read()  # Kopie für die Einrichtung ist aktuell
