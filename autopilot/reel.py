"""Baut ein Reel (1080x1920, MP4): langsamer Zoom auf den Hintergrund, Text blendet ein,
optional Musik aus dem Ordner 'musik'. Braucht ffmpeg."""
import os
import random
import subprocess

from . import video
from .design import HOCH, hintergrund, text_ebene
from .einstellungen import MUSIK

FPS = 30
MUSIKENDUNGEN = (".mp3", ".wav", ".m4a", ".aac")


def dauer(text, mindestens=0.0):
    """Lesezeit: ca. 2,5 Wörter pro Sekunde plus Puffer, zwischen 6 und 14 Sekunden,
    mindestens so lang wie in einstellungen.yml (reel → mindestdauer)."""
    return round(max(6.0, mindestens, min(14.0, len(text.split()) / 2.5 + 3.0)), 1)


def _titel_in(ordner):
    if not os.path.isdir(ordner):
        return []
    return sorted(os.path.join(ordner, f) for f in os.listdir(ordner) if f.lower().endswith(MUSIKENDUNGEN))


def musik_waehlen(zufall=random, stimmung=None):
    """Nimmt bevorzugt Musik aus dem Unterordner zur Stimmung (z.B. musik/duester),
    sonst aus dem Ordner musik selbst."""
    titel = (_titel_in(os.path.join(MUSIK, stimmung)) if stimmung else []) or _titel_in(MUSIK)
    return zufall.choice(titel) if titel else None


def reel_bauen(cfg, eintrag, hintergrund_schluessel, ziel, musik=None):
    video.ffmpeg_bereit()
    basis = os.path.splitext(ziel)[0]
    hg_pfad, text_pfad = basis + "_hg.png", basis + "_text.png"
    hintergrund(cfg, hintergrund_schluessel, HOCH).save(hg_pfad)
    text_ebene(cfg, eintrag, HOCH, mit_band=True).save(text_pfad)

    sekunden = dauer(eintrag["text"], cfg.get("mindestdauer", 0))
    frames = int(sekunden * FPS)
    w, h = HOCH
    bild = (
        f"[0:v]scale={w * 2}:{h * 2},"
        f"zoompan=z='1+0.12*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d={frames}:s={w}x{h}:fps={FPS}[hg];"
        f"[1:v]format=rgba,fade=in:st=0.4:d=0.8:alpha=1[txt];"
        f"[hg][txt]overlay=0:0,format=yuv420p[v]"
    )
    befehl = ["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", hg_pfad, "-loop", "1", "-i", text_pfad]
    if musik:
        befehl += ["-stream_loop", "-1", "-i", musik]
        ton = (
            f";[2:a]volume={cfg['musik_lautstaerke']},"
            f"afade=t=in:d=0.5,afade=t=out:st={max(0.0, sekunden - 1.2)}:d=1.2[a]"
        )
        befehl += ["-filter_complex", bild + ton, "-map", "[v]", "-map", "[a]", "-c:a", "aac", "-b:a", "160k"]
    else:
        befehl += ["-filter_complex", bild, "-map", "[v]"]
    befehl += [
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(FPS),
        "-t", str(sekunden), "-movflags", "+faststart", ziel,
    ]
    subprocess.run(befehl, check=True)
    for datei in (hg_pfad, text_pfad):
        os.remove(datei)
    return sekunden
