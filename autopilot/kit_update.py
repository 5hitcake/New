"""Aktualisiert das Kit auf eine neue Version, ohne deine Daten anzufassen.

So geht's: neue Kit-ZIP ins Repository hochladen (Add file → Upload files), dann die Aktion
"kit-update" starten. Ersetzt wird nur der Programmteil. Unverändert bleiben:
einstellungen.yml, inhalte/, medien/, hintergruende/, deine Musik und der Verlauf (daten/verlauf.json).
"""
import filecmp
import os
import shutil
import subprocess
import tempfile
import zipfile

from . import VERSION
from .einstellungen import ROOT, KitFehler

# Programmteile, die bei einem Update komplett ersetzt werden
ORDNER = ("autopilot", "schriften", "hilfe")
# Ordner mit Programm- UND Nutzerdaten (z.B. daten/verlauf.json): neue Dateien kommen dazu, nichts wird gelöscht
ERGAENZEN = ("daten",)
NIE_UEBERSCHREIBEN = ("daten/verlauf.json",)
DATEIEN = ("requirements.txt", "pyproject.toml", "README.md", "LIZENZ.md", ".gitignore")
# Nur diese Erklärdateien werden in deinen Ordnern aktualisiert, nie deine eigenen Dateien
ERKLAERUNGEN = ("musik/LIESMICH.txt", "musik/duester/LIESMICH.txt", "musik/ruhig/LIESMICH.txt",
                "musik/neutral/LIESMICH.txt", "medien/LIESMICH.txt", "hintergruende/LIESMICH.txt",
                "quellen/LIESMICH.txt")
WORKFLOW = os.path.join(".github", "workflows", "autopilot.yml")


def _zip_finden(root):
    zips = sorted(f for f in os.listdir(root) if f.lower().endswith(".zip"))
    if not zips:
        raise KitFehler("Keine Kit-ZIP im Repository gefunden. Lade die neue ZIP hoch (Code → Add file → "
                        "Upload files, nicht entpacken) und starte die Aktion kit-update erneut.")
    if len(zips) > 1:
        raise KitFehler(f"Mehrere ZIP-Dateien im Repository ({', '.join(zips)}). Bitte nur die neue behalten.")
    return zips[0]


def _neue_version(quelle):
    pfad = os.path.join(quelle, "autopilot", "__init__.py")
    with open(pfad, encoding="utf-8") as f:
        for zeile in f:
            if zeile.startswith("VERSION"):
                return zeile.split("=", 1)[1].strip().strip("\"'")
    return "?"


def _war_im_repo(git, pfad):
    try:
        return bool(git("ls-files", pfad).stdout.strip())
    except Exception:  # noqa: BLE001
        return False


def aktualisieren(root=ROOT, git=None):
    """Spielt die neue Version ein. Gibt (alte Version, neue Version, Workflow geändert?) zurück."""
    git = git or (lambda *a: subprocess.run(["git", *a], cwd=root, check=True, capture_output=True, text=True))
    name = _zip_finden(root)
    tmp = tempfile.mkdtemp(prefix="kit_update_")
    try:
        with zipfile.ZipFile(os.path.join(root, name)) as z:
            z.extractall(tmp)
    except zipfile.BadZipFile as exc:
        raise KitFehler(f"{name} ist keine gültige ZIP-Datei. Bitte neu herunterladen und hochladen.") from exc
    quelle = next((d for d, _, dateien in os.walk(tmp) if "__main__.py" in dateien and d.endswith("autopilot")), None)
    if not quelle:
        raise KitFehler(f"{name} enthält kein Insta-Autopilot-Kit.")
    quelle = os.path.dirname(quelle)
    neu = _neue_version(quelle)

    for ordner in ORDNER:
        if os.path.isdir(os.path.join(quelle, ordner)):
            shutil.rmtree(os.path.join(root, ordner), ignore_errors=True)
            shutil.copytree(os.path.join(quelle, ordner), os.path.join(root, ordner))
    for ordner in ERGAENZEN:
        for pfad, _, dateien in os.walk(os.path.join(quelle, ordner)):
            for d in dateien:
                rel = os.path.relpath(os.path.join(pfad, d), quelle)
                if rel.replace(os.sep, "/") in NIE_UEBERSCHREIBEN and os.path.exists(os.path.join(root, rel)):
                    continue
                os.makedirs(os.path.dirname(os.path.join(root, rel)), exist_ok=True)
                shutil.copy2(os.path.join(pfad, d), os.path.join(root, rel))
    for datei in DATEIEN + ERKLAERUNGEN:
        if os.path.exists(os.path.join(quelle, datei)):
            os.makedirs(os.path.dirname(os.path.join(root, datei)) or root, exist_ok=True)
            shutil.copy2(os.path.join(quelle, datei), os.path.join(root, datei))
    # Neue Vorlage zum Nachschlagen. Deine einstellungen.yml bleibt, neue Optionen haben Standardwerte.
    if os.path.exists(os.path.join(quelle, "einstellungen.yml")):
        os.makedirs(os.path.join(root, "hilfe"), exist_ok=True)
        shutil.copy2(os.path.join(quelle, "einstellungen.yml"), os.path.join(root, "hilfe", "einstellungen-vorlage.yml"))

    neuer_workflow = os.path.join(quelle, WORKFLOW)
    workflow_neu = os.path.exists(neuer_workflow) and not (
        os.path.exists(os.path.join(root, WORKFLOW)) and filecmp.cmp(neuer_workflow, os.path.join(root, WORKFLOW),
                                                                     shallow=False))
    shutil.rmtree(tmp, ignore_errors=True)

    git("rm", "-q", "--ignore-unmatch", name)
    if os.path.exists(os.path.join(root, name)):
        os.remove(os.path.join(root, name))
    git("add", "-A", *[o for o in ORDNER + ERGAENZEN + DATEIEN if os.path.exists(os.path.join(root, o))
                         or _war_im_repo(git, o)])
    for d in ERKLAERUNGEN:
        if os.path.exists(os.path.join(root, d)):
            git("add", d)
    git("-c", "user.name=autopilot", "-c", "user.email=autopilot@users.noreply.github.com",
        "commit", "-qm", f"Kit aktualisiert: {VERSION} → {neu}")
    return VERSION, neu, workflow_neu
