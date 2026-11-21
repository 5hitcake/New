"""Sprecher-Stimme mit Piper (läuft offline auf GitHub, kostenlos).

Stimme "Thorsten" von Thorsten Müller, Datensatz unter CC0 (frei, auch kommerziell).
Piper und die Stimme werden erst geladen, wenn sie gebraucht werden.
"""
import os
import subprocess
import sys
import wave

from .einstellungen import STIMMEN, KitFehler

STIMME = "de_DE-thorsten-high"


def _piper_bereit():
    try:
        import piper  # noqa: F401
    except ImportError:
        print("Installiere Piper (Sprecher) …")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "piper-tts==1.8.0"], check=True)
    modell = os.path.join(STIMMEN, STIMME + ".onnx")
    if not os.path.exists(modell):
        os.makedirs(STIMMEN, exist_ok=True)
        print("Lade die Stimme Thorsten …")
        ergebnis = subprocess.run([sys.executable, "-m", "piper.download_voices", STIMME, "--download-dir", STIMMEN],
                                  capture_output=True, text=True, check=False)
        if ergebnis.returncode != 0 or not os.path.exists(modell):
            raise KitFehler("Die Sprecher-Stimme konnte nicht geladen werden. Beim nächsten Lauf wird es "
                            "erneut versucht (oder in einstellungen.yml sprecher: \"aus\").")
    return modell


# Klangfarben: werden nach der Sprachausgabe mit ffmpeg angewendet.
#   duester: ca. 2 Halbtöne tiefer und etwas langsamer, leichter Hall, gedämpfte Höhen
STIMMUNGEN = {
    "neutral": None,
    "duester": "asetrate={sr}*0.89,aresample={sr},aecho=0.8:0.6:45|110:0.25|0.15,lowpass=f=6500,"
               "acompressor=threshold=0.1:ratio=3:attack=5:release=80,volume=1.6",
    "ruhig": "lowpass=f=9000,aecho=0.8:0.5:30:0.12",
}
DUESTER_WOERTER = ("düster", "duester", "grusel", "horror", "spannend", "unheimlich", "mystery", "dunkel", "schaurig")


def stimmung_waehlen(wert, stil=""):
    """'auto' leitet die Klangfarbe aus dem Ton des Accounts ab."""
    if wert != "auto":
        return wert
    stil = (stil or "").lower()
    if any(w in stil for w in DUESTER_WOERTER):
        return "duester"
    if any(w in stil for w in ("ruhig", "nachdenklich", "poetisch")):
        return "ruhig"
    return "neutral"


def klang_anwenden(pfad, stimmung):
    """Wendet die Klangfarbe auf eine WAV-Datei an (in place)."""
    vorlage = STIMMUNGEN.get(stimmung)
    if not vorlage:
        return
    from .video import ffmpeg_bereit

    ffmpeg_bereit()
    with wave.open(pfad, "rb") as w:
        sr = w.getframerate()
    roh = pfad + ".roh.wav"
    os.replace(pfad, roh)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", roh, "-af", vorlage.format(sr=sr), "-ar", str(sr), pfad],
                   check=True)
    os.remove(roh)


class Sprecher:
    def __init__(self, tempo=1.0, stimmung="neutral"):
        self.stimmung = stimmung
        modell = _piper_bereit()  # installiert Piper bei Bedarf, darum erst danach importieren
        import importlib

        importlib.invalidate_caches()
        from piper import PiperVoice, SynthesisConfig

        self.stimme = PiperVoice.load(modell)
        self.config = SynthesisConfig(length_scale=tempo)

    def sprechen(self, text, ziel):
        """Schreibt eine WAV-Datei und gibt ihre Länge in Sekunden zurück."""
        with wave.open(ziel, "wb") as wav:
            self.stimme.synthesize_wav(text.replace("*", ""), wav, syn_config=self.config)
        klang_anwenden(ziel, self.stimmung)
        return wav_laenge(ziel)


def wav_laenge(pfad):
    with wave.open(pfad, "rb") as w:
        return w.getnframes() / float(w.getframerate())
