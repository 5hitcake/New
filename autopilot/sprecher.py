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


class Sprecher:
    def __init__(self, tempo=1.0):
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
        return wav_laenge(ziel)


def wav_laenge(pfad):
    with wave.open(pfad, "rb") as w:
        return w.getnframes() / float(w.getframerate())
