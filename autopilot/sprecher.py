"""Sprecher-Stimme mit Piper (läuft offline auf GitHub, kostenlos).

"killian" (Standard) ist eine Microsoft-Neural-Stimme über edge-tts: kostenlos, ohne Konto, braucht Internet.
Fällt sie aus, spricht automatisch Thorsten. Stimmen von Thorsten Müller (Thorsten-Voice, CC0: frei, auch kommerziell). "karlsson" stammt aus dem
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
#   duester: ca. 2 Halbtöne tiefer, leichter Hall, gedämpfte Höhen (für Grusel)
#   hall:    nur Raumhall, Tonhöhe bleibt (für das Flüstern)
STIMMUNGEN = {
    "neutral": None,
    "duester": "asetrate={sr}*0.89,aresample={sr},aecho=0.8:0.6:45|110:0.25|0.15,lowpass=f=6500,"
               "acompressor=threshold=0.1:ratio=3:attack=5:release=80,volume=1.6",
    "hall": "aecho=0.8:0.7:60|140:0.22|0.12,lowpass=f=8000",
    "ruhig": "lowpass=f=9000,aecho=0.8:0.5:30:0.12",
}
# Langsameres Sprechen je Klang (Piper "length_scale": größer = langsamer, klingt natürlich)
TEMPO = {"neutral": 1.0, "duester": 1.25, "hall": 1.15, "ruhig": 1.12}
DUESTER_WOERTER = ("düster", "duester", "grusel", "horror", "spannend", "unheimlich", "mystery", "dunkel", "schaurig")


def sprecher_waehlen(wert, klang):
    """'auto' = Killian (natürliche Microsoft-Stimme, bei Grusel tief mit Hall)."""
    if wert != "auto":
        return wert
    return "killian"


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
    # Lautheit angleichen (Flüstern ist sonst deutlich leiser als Musik und Untertitel-Tempo)
    vorlage = ",".join(f for f in (STIMMUNGEN.get(stimmung), "loudnorm=I=-16:TP=-1.5:LRA=11") if f)
    from .video import ffmpeg_bereit

    ffmpeg_bereit()
    with wave.open(pfad, "rb") as w:
        sr = w.getframerate()
    roh = pfad + ".roh.wav"
    os.replace(pfad, roh)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", roh, "-af", vorlage.format(sr=sr), "-ar", str(sr), pfad],
                   check=True)
    os.remove(roh)


# ---- Killian: Microsoft-Neural-Stimme über edge-tts (kostenlos, kein Konto, braucht Internet)
EDGE_STIMMEN = {"killian": "de-DE-KillianNeural", "conrad": "de-DE-ConradNeural"}
# Klang je Stimmung: Tempo und Tonhöhe direkt bei der Stimme, danach Feinschliff mit ffmpeg.
#   duester: tiefe Erzählerstimme. Tonhöhe ca. 13 % tiefer bei gleichem Tempo, Bass, Hall.
EDGE_KLANG = {
    "duester": {"rate": "+4%", "pitch": "-6Hz", "faktor": 0.87, "bass": 5, "hall": "0.85:0.6:70|140:0.16|0.08"},
    "ruhig": {"rate": "-6%", "pitch": "-2Hz", "faktor": 1.0, "bass": 2, "hall": "0.8:0.5:30:0.1"},
    "neutral": {"rate": "+0%", "pitch": "+0Hz", "faktor": 1.0, "bass": 0, "hall": ""},
}


def _edge_filter(k):
    kette = []
    if abs(k["faktor"] - 1.0) > 1e-3:
        kette.append(f"asetrate=24000*{k['faktor']},aresample=44100,atempo={1 / k['faktor']:.5f}")
    else:
        kette.append("aresample=44100")
    kette += [f"equalizer=f=110:t=q:w=1:g={k['bass']}", "equalizer=f=4000:t=q:w=1.5:g=-3", "highpass=f=50",
              "acompressor=threshold=-20dB:ratio=3:attack=8:release=250:makeup=2"]
    if k["hall"]:
        kette.append(f"aecho={k['hall']}")
    kette.append("loudnorm=I=-16:TP=-1.5:LRA=11")
    return ",".join(kette)


def _rate(basis, tempo):
    """Sprechtempo aus einstellungen.yml (1.1 = langsamer) mit dem Tempo des Klangs verrechnen."""
    prozent = int(basis.rstrip("%")) + round((1 / tempo - 1) * 100)
    return f"{prozent:+d}%"


class EdgeSprecher:
    def __init__(self, tempo=1.0, stimmung="neutral", name="killian"):
        try:
            import edge_tts  # noqa: F401
        except ImportError:
            print("Installiere edge-tts (Sprecher) …")
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "edge-tts==7.3.1"], check=True)
        from .video import ffmpeg_bereit

        ffmpeg_bereit()
        self.stimme = EDGE_STIMMEN.get(name, EDGE_STIMMEN["killian"])
        self.klang = EDGE_KLANG.get(stimmung, EDGE_KLANG["neutral"])
        self.rate = _rate(self.klang["rate"], tempo)

    def sprechen(self, text, ziel):
        import asyncio

        import edge_tts

        roh = ziel + ".mp3"
        com = edge_tts.Communicate(text.replace("*", ""), self.stimme, rate=self.rate, pitch=self.klang["pitch"],
                                   proxy=os.environ.get("HTTPS_PROXY") or None)
        asyncio.run(com.save(roh))
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", roh, "-af", _edge_filter(self.klang),
                        "-ar", "44100", "-ac", "1", ziel], check=True)
        os.remove(roh)
        return wav_laenge(ziel)


def erstellen(tempo=1.0, stimmung="neutral", name="killian"):
    """Baut den passenden Sprecher. Klappt Killian nicht (kein Internet o.ä.), übernimmt Thorsten."""
    if name in EDGE_STIMMEN:
        try:
            s = EdgeSprecher(tempo, stimmung, name)
            os.makedirs(STIMMEN, exist_ok=True)
            s.sprechen("Test.", os.path.join(STIMMEN, "_test.wav"))
            return s
        except Exception as e:  # noqa: BLE001  Rückfall statt Abbruch
            print(f"Sprecher {name} nicht erreichbar ({e}), nehme Thorsten.")
            name = "thorsten"
    return Sprecher(tempo, stimmung, name)


class Sprecher:
    def __init__(self, tempo=1.0, stimmung="neutral", name="thorsten"):
        if name == "thorsten_fluestern" and stimmung == "duester":
            stimmung = "hall"  # Flüstern nicht tiefer stellen, das klingt sonst verzerrt
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
    ("1_killian_duester", "killian", "duester"),
    ("2_killian_ruhig", "killian", "ruhig"),
    ("3_killian_normal", "killian", "neutral"),
    ("4_thorsten_fluestern", "thorsten_fluestern", "duester"),
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
            erstellen(1.0, klang, sprecher).sprechen(PROBE_TEXT, wav)
            m4a = wav[:-4] + ".m4a"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", wav, "-c:a", "aac", "-b:a", "128k", m4a], check=True)
            os.remove(wav)
            fertig.append(m4a)
            print(f"Stimmprobe erstellt: {os.path.basename(m4a)}")
        except Exception as e:  # noqa: BLE001  eine fehlende Stimme soll die anderen nicht aufhalten
            print(f"Stimmprobe {name} fehlgeschlagen: {e}")
    return fertig
