"""Gemeinsamer Video-Baukasten (ffmpeg): einzelne Clips aus Bildern oder Videos, Text-Ebene darüber,
weiche Überblendungen, Sprecher und Musik. Ausgabe immer 1080x1920, 30 fps, H.264 + AAC."""
import os
import shutil
import subprocess

from .einstellungen import KitFehler

B, H = 1080, 1920
FPS = 30
UEBERBLENDUNG = 0.4
VIDEOENDUNGEN = (".mp4", ".mov", ".m4v", ".webm")


def ffmpeg_bereit():
    if shutil.which("ffmpeg"):
        return
    if shutil.which("apt-get") and os.environ.get("GITHUB_ACTIONS"):
        print("Installiere ffmpeg …")
        subprocess.run("sudo apt-get update -qq && sudo apt-get install -y -qq ffmpeg", shell=True, check=True)
        return
    raise KitFehler("ffmpeg fehlt. Auf GitHub wird es automatisch installiert; lokal bitte ffmpeg installieren.")


def _ff(args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def ist_video(pfad):
    return pfad.lower().endswith(VIDEOENDUNGEN)


def clip(quelle, dauer, ziel, text_png=None, zoom_rein=True):
    """Ein stummer Clip mit genau `dauer` Sekunden. Bilder bekommen einen langsamen Zoom,
    Videos werden auf Hochformat zugeschnitten (zu kurze Videos bleiben am Ende stehen)."""
    frames = max(1, round(dauer * FPS))
    if ist_video(quelle):
        eingang = ["-i", quelle]
        basis = (f"[0:v]scale={B}:{H}:force_original_aspect_ratio=increase,crop={B}:{H},setsar=1,fps={FPS},"
                 f"tpad=stop_mode=clone:stop_duration={dauer}[b]")
    else:
        eingang = ["-loop", "1", "-i", quelle]
        z = f"1+0.10*on/{frames}" if zoom_rein else f"1.10-0.10*on/{frames}"
        basis = (f"[0:v]scale={int(B * 1.25)}:{int(H * 1.25)}:force_original_aspect_ratio=increase,"
                 f"crop={int(B * 1.25)}:{int(H * 1.25)},"
                 f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={B}x{H}:fps={FPS},"
                 f"setsar=1[b]")
    if text_png:
        eingang += ["-loop", "1", "-i", text_png]
        filt = basis + ";[1:v]format=rgba,fade=in:st=0.15:d=0.35:alpha=1[t];[b][t]overlay=0:0,format=yuv420p[v]"
    else:
        filt = basis + ";[b]format=yuv420p[v]"
    _ff([*eingang, "-filter_complex", filt, "-map", "[v]", "-an", "-t", f"{dauer:.3f}", "-r", str(FPS),
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", ziel])


def zusammenfuegen(clips, dauern, ziel):
    """Clips mit Überblendung verbinden. Jeder Clip außer dem letzten muss UEBERBLENDUNG Sekunden
    länger sein als seine sichtbare Dauer, damit Bild und Ton synchron bleiben."""
    if len(clips) == 1:
        shutil.copy(clips[0], ziel)
        return
    eingang = []
    for c in clips:
        eingang += ["-i", c]
    teile, vorher, versatz = [], "[0:v]", 0.0
    for k in range(1, len(clips)):
        versatz += dauern[k - 1]
        aus = f"[x{k}]" if k < len(clips) - 1 else "[v]"
        teile.append(f"{vorher}[{k}:v]xfade=transition=fade:duration={UEBERBLENDUNG}:offset={versatz:.3f}{aus}")
        vorher = aus
    _ff([*eingang, "-filter_complex", ";".join(teile), "-map", "[v]", "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "20", "-pix_fmt", "yuv420p", ziel])


def tonspur(stimmen, dauern, ziel):
    """Sprecher-Dateien (oder None für Stille) hintereinander, jede auf ihre Segmentlänge gebracht."""
    eingang, teile = [], []
    for i, (wav, d) in enumerate(zip(stimmen, dauern)):
        if wav:
            eingang += ["-i", wav]
        else:
            eingang += ["-f", "lavfi", "-t", f"{d:.3f}", "-i", "anullsrc=r=44100:cl=mono"]
        teile.append(f"[{i}:a]aresample=44100,aformat=channel_layouts=mono,apad,atrim=0:{d:.3f}[a{i}]")
    kette = "".join(f"[a{i}]" for i in range(len(dauern)))
    filt = ";".join(teile) + f";{kette}concat=n={len(dauern)}:v=0:a=1[a]"
    _ff([*eingang, "-filter_complex", filt, "-map", "[a]", "-c:a", "pcm_s16le", ziel])


def fertigstellen(video, ziel, gesamt, stimme=None, musik=None, musik_lautstaerke=0.3):
    """Video + optional Sprecher + optional Musik (gedämpft, Ende ausgeblendet)."""
    args, filter_teile, n = ["-i", video], [], 1
    if stimme:
        args += ["-i", stimme]
        filter_teile.append(f"[{n}:a]aresample=44100[s]")
        n += 1
    if musik:
        args += ["-stream_loop", "-1", "-i", musik]
        laut = musik_lautstaerke * (0.6 if stimme else 1.0)
        filter_teile.append(f"[{n}:a]aresample=44100,volume={laut},"
                            f"afade=t=out:st={max(0.0, gesamt - 1.5):.2f}:d=1.5[m]")
    if stimme and musik:
        args += ["-filter_complex", ";".join(filter_teile) + ";[s][m]amix=inputs=2:duration=first:normalize=0[a]",
                 "-map", "0:v", "-map", "[a]"]
    elif filter_teile:
        args += ["-filter_complex", filter_teile[0], "-map", "0:v", "-map", "[s]" if stimme else "[m]"]
    else:
        args += ["-map", "0:v"]
    if filter_teile:
        args += ["-c:a", "aac", "-b:a", "160k"]
    args += ["-c:v", "copy", "-t", f"{gesamt:.3f}", "-movflags", "+faststart", ziel]
    _ff(args)
