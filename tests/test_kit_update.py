"""kit-update: nur der Programmteil wird ersetzt, eigene Daten bleiben."""
import os
import subprocess
import zipfile

import pytest

from autopilot import kit_update
from autopilot.einstellungen import KitFehler


def _schreiben(pfad, text):
    os.makedirs(os.path.dirname(pfad), exist_ok=True)
    with open(pfad, "w", encoding="utf-8") as f:
        f.write(text)


def _repo(tmp_path):
    r = tmp_path / "repo"
    _schreiben(str(r / "autopilot/__main__.py"), "alt")
    _schreiben(str(r / "autopilot/veraltet.py"), "weg damit")
    _schreiben(str(r / "einstellungen.yml"), "instagram_name: meins\n")
    _schreiben(str(r / "inhalte/posts.csv"), "text\nmein Spruch\n")
    _schreiben(str(r / "musik/mein_song.mp3"), "musik")
    _schreiben(str(r / "musik/LIESMICH.txt"), "alt")
    _schreiben(str(r / ".github/workflows/autopilot.yml"), "workflow alt")
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    git = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=r,
                                    check=True, capture_output=True, text=True)
    git("add", "-A")
    git("commit", "-qm", "start")
    return r, git


def _zip(pfad, workflow="workflow alt"):
    with zipfile.ZipFile(pfad, "w") as z:
        z.writestr("insta-autopilot/autopilot/__init__.py", 'VERSION = "9.9"\n')
        z.writestr("insta-autopilot/autopilot/__main__.py", "neu")
        z.writestr("insta-autopilot/einstellungen.yml", "instagram_name: vorlage\nneue_option: 1\n")
        z.writestr("insta-autopilot/inhalte/posts.csv", "text\nVorlage\n")
        z.writestr("insta-autopilot/musik/LIESMICH.txt", "neu")
        z.writestr("insta-autopilot/requirements.txt", "pillow\n")
        z.writestr("insta-autopilot/.github/workflows/autopilot.yml", workflow)


def test_update_ersetzt_nur_programm(tmp_path):
    r, git = _repo(tmp_path)
    _zip(str(r / "insta-autopilot-v9.9.zip"))
    git("add", "-A")
    git("commit", "-qm", "zip hochgeladen")
    _alt, neu, workflow_neu = kit_update.aktualisieren(str(r), git)
    assert neu == "9.9" and not workflow_neu
    assert (r / "autopilot/__main__.py").read_text() == "neu"
    assert not (r / "autopilot/veraltet.py").exists()
    assert (r / "einstellungen.yml").read_text() == "instagram_name: meins\n"
    assert "mein Spruch" in (r / "inhalte/posts.csv").read_text()
    assert (r / "musik/mein_song.mp3").exists() and (r / "musik/LIESMICH.txt").read_text() == "neu"
    assert "neue_option" in (r / "hilfe/einstellungen-vorlage.yml").read_text()
    assert not (r / "insta-autopilot-v9.9.zip").exists()
    assert "Kit aktualisiert" in git("log", "-1", "--format=%s").stdout
    assert git("status", "--porcelain").stdout.strip() == ""


def test_update_meldet_neuen_workflow(tmp_path):
    r, git = _repo(tmp_path)
    _zip(str(r / "kit.zip"), workflow="workflow neu")
    assert kit_update.aktualisieren(str(r), git)[2] is True
    assert (r / ".github/workflows/autopilot.yml").read_text() == "workflow alt"  # darf GitHub nicht selbst ändern


def test_update_ohne_oder_mit_zwei_zips(tmp_path):
    r, git = _repo(tmp_path)
    with pytest.raises(KitFehler, match="Keine Kit-ZIP"):
        kit_update.aktualisieren(str(r), git)
    _zip(str(r / "a.zip"))
    _zip(str(r / "b.zip"))
    with pytest.raises(KitFehler, match="Mehrere ZIP"):
        kit_update.aktualisieren(str(r), git)
