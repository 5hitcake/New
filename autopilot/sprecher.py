"""Sprecher-Stimme mit Piper (läuft offline auf GitHub, kostenlos).

Stimmen von Thorsten Müller (Thorsten-Voice, CC0: frei, auch kommerziell). "karlsson" stammt aus dem
M-AILABS-Datensatz (Lizenz vor kommerzieller Nutzung selbst prüfen).
Piper und die Stimme werden erst geladen, wenn sie gebraucht werden.
"""
import os
import subprocess
import sys
import wave

from .einstellungen import STIMMEN, KitFehler

# Name in einstellungen.yml → (Piper-Modell, Sprechstil im Modell)
SPRECHER = {
    "thorsten": ("de_DE-thorsten-high", None),
    "thorsten_ruhig": ("de_DE-thorsten_emotional-medium", "neutral"),
    "thorsten_fluestern": ("de_DE-thorsten_emotional-medium", "whisper"),
    "thorsten_muede": ("de_DE-thorsten_emotional-medium", "sleepy"),
    "karlsson": ("de_DE-karlsson-low", None),
}
STIMME = SPRECHER["thorsten"][0]


def _piper_bereit(stimme=STIMME):
    try:
        import piper  # noqa: F401
    except ImportError:
        print("Installiere Piper (Sprecher) …")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "piper-tts==1.8.0"], check=True)
    modell = os.path.join(STIMMEN, stimme + ".onnx")
    if not os.path.exists(modell):
        os.makedirs(STIMMEN, exist_ok=True)
        print(f"Lade die Stimme {stimme} …")
        ergebnis = subprocess.run([sys.executable, "-m", "piper.download_voices", stimme, "--download-dir", STIMMEN],
                                  capture_output=True, text=True, check=False)
        if ergebnis.returncode != 0 or not os.path.exists(modell):
            raise KitFehler("Die Sprecher-Stimme konnte nicht geladen werden. Beim nächsten Lauf wird es "
                            "erneut versucht (oder in einstellungen.yml sprecher: \"aus\").")
    return modell


# Klangfarben: werden nach der Sprachausgabe mit ffmpeg angewendet.
#   duester: Raumhall, wärmere Tiefen, gedämpfte Höhen. Die Tonhöhe bleibt natürlich,
#            langsamer wird es über das Sprechtempo (siehe TEMPO).
STIMMUNGEN = {
    "neutral": None,
    "duester": "aecho=0.8:0.7:60|140:0.22|0.12,bass=g=4:f=120,lowpass=f=7000,"
               "acompressor=threshold=0.12:ratio=2.5:attack=5:release=120,volume=1.4",
    "ruhig": "lowpass=f=9000,aecho=0.8:0.5:30:0.12",
}
# Langsameres Sprechen je Klang (Piper "length_scale": größer = langsamer, klingt natürlich)
TEMPO = {"neutral": 1.0, "duester": 1.28, "ruhig": 1.12}
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
    def __init__(self, tempo=1.0, stimmung="neutral", name="thorsten"):
        self.stimmung = stimmung
        datei, stil = SPRECHER.get(name, SPRECHER["thorsten"])
        modell = _piper_bereit(datei)  # installiert Piper bei Bedarf, darum erst danach importieren
        import importlib

        importlib.invalidate_caches()
        from piper import PiperVoice, SynthesisConfig

        self.stimme = PiperVoice.load(modell)
        sprecher_id = None
        if stil:
            ids = getattr(self.stimme.config, "speaker_id_map", None) or {}
            sprecher_id = ids.get(stil, 0)
        self.config = SynthesisConfig(length_scale=tempo * TEMPO.get(stimmung, 1.0), speaker_id=sprecher_id)

    def sprechen(self, text, ziel):
        """Schreibt eine WAV-Datei und gibt ihre Länge in Sekunden zurück."""
        with wave.open(ziel, "wb") as wav:
            self.stimme.synthesize_wav(text.replace("*", ""), wav, syn_config=self.config)
        klang_anwenden(ziel, self.stimmung)
        return wav_laenge(ziel)


def wav_laenge(pfad):
    with wave.open(pfad, "rb") as w:
        return w.getnframes() / float(w.getframerate())


PROBE_TEXT = ("Um Mitternacht hörst du Schritte im leeren Sanatorium. "
              "Doch als du die Tür öffnest, ist der Flur voller Staub, ohne eine einzige Spur.")
PROBEN = [  # (Dateiname, Sprecher, Klang)
    ("1_thorsten_duester", "thorsten", "duester"),
    ("2_thorsten_ruhig_duester", "thorsten_ruhig", "duester"),
    ("3_thorsten_fluestern", "thorsten_fluestern", "duester"),
    ("4_thorsten_muede", "thorsten_muede", "duester"),
    ("5_karlsson_duester", "karlsson", "duester"),
    ("6_thorsten_normal", "thorsten", "neutral"),
]


def stimmproben(ordner):
    """Spricht denselben Satz mit allen Stimmen, als M4A zum Anhören am Handy."""
    from .video import ffmpeg_bereit

    ffmpeg_bereit()
    os.makedirs(ordner, exist_ok=True)
    fertig = []
    for name, sprecher, klang in PROBEN:
        try:
            wav = os.path.join(ordner, f"stimme_{name}.wav")
            Sprecher(1.0, klang, sprecher).sprechen(PROBE_TEXT, wav)
            m4a = wav[:-4] + ".m4a"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", wav, "-c:a", "aac", "-b:a", "128k", m4a], check=True)
            os.remove(wav)
            fertig.append(m4a)
            print(f"Stimmprobe erstellt: {os.path.basename(m4a)}")
        except Exception as e:  # noqa: BLE001  eine fehlende Stimme soll die anderen nicht aufhalten
            print(f"Stimmprobe {name} fehlgeschlagen: {e}")
    return fertig
