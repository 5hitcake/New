"""Reels für die Inhaltsarten "geschichten" (KI-Story-Reel) und "eigene_medien" (eigene Fotos/Videos)."""
import os
import random
import re
import shutil
import tempfile

from PIL import Image

from . import design, ki_bilder, video
from .einstellungen import MEDIEN

BILDENDUNGEN = (".jpg", ".jpeg", ".png", ".webp", ".heic")

try:  # iPhone-Fotos (HEIC) lesen können
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:  # pragma: no cover
    pass
PAUSE = 0.35  # kurze Pause nach jedem gesprochenen Satz


def lesezeit(text):
    return max(2.5, len(text.replace("*", "").split()) / 2.6 + 1.0)


def _titelbild(hintergrund_png, text_ebene, ziel):
    basis = Image.open(hintergrund_png).convert("RGBA")
    Image.alpha_composite(basis, text_ebene).convert("RGB").save(ziel, "JPEG", quality=90)
    return ziel


# ---------------------------------------------------------------- Story-Reel

def segmente(cfg, skript):
    name = cfg["name_im_bild"] or f"@{cfg['instagram_name']}"
    teile = [{"text": skript["hook"]["text"], "bild": 0, "gross": True}]
    teile += [{"text": s["text"], "bild": i + 1, "gross": False} for i, s in enumerate(skript["szenen"])]
    teile.append({"text": skript["frage"], "bild": 0, "gross": True, "unterzeile": f"Folge {name} für mehr",
                  "sprechen": f"{skript['frage'].replace('*', '')} Schreib es in die Kommentare."})
    return teile


def geschichten_reel(cfg, skript, ziel, musik=None, sprecher=None, bild_quelle=None, zufall=random):
    """Baut das Reel. Gibt (dauer, titelbild_jpg, bildquellen) zurück."""
    g = cfg["geschichten"]
    bild_quelle = bild_quelle or ki_bilder.erzeugen
    video.ffmpeg_bereit()
    arbeit = tempfile.mkdtemp(prefix="reel_")
    try:
        prompts = [skript["hook"]["bild"]] + [s["bild"] for s in skript["szenen"]]
        bilder, quellen = [], []
        for i, prompt in enumerate(prompts):
            bild = bild_quelle(f"{prompt}, {g['bildstil'] or 'cinematic painting, dramatic light'}, vertical 9:16, no text")
            if bild is None:
                bild = design.hintergrund(cfg, f"verlauf:{zufall.randrange(len(cfg['farbverlaeufe']))}", design.HOCH)
                quellen.append("farbverlauf")
            else:
                quellen.append("ki")
            bilder.append(design.ki_bild_vorbereiten(bild, os.path.join(arbeit, f"bild_{i}.png")))

        teile = segmente(cfg, skript)
        stimmen, dauern = [], []
        for i, t in enumerate(teile):
            if sprecher:
                wav = os.path.join(arbeit, f"stimme_{i}.wav")
                d = sprecher.sprechen(t.get("sprechen", t["text"]), wav) + PAUSE
                stimmen.append(wav)
            else:
                d = lesezeit(t["text"])
                stimmen.append(None)
            dauern.append(round(max(2.0, d), 2))

        clips, titelbild = [], None
        for i, t in enumerate(teile):
            ebene = design.untertitel_ebene(t["text"], g["akzentfarbe"], t["gross"], t.get("unterzeile", ""),
                                            cfg["textfarbe"])
            ebene_png = os.path.join(arbeit, f"text_{i}.png")
            ebene.save(ebene_png)
            if i == 0:
                titelbild = _titelbild(bilder[0], ebene, os.path.splitext(ziel)[0] + "_titel.jpg")
            letzter = i == len(teile) - 1
            dauer = dauern[i] + (0 if letzter else video.UEBERBLENDUNG)
            c = os.path.join(arbeit, f"clip_{i}.mp4")
            video.clip(bilder[t["bild"]], dauer, c, ebene_png, zoom_rein=i % 2 == 0)
            clips.append(c)

        stumm = os.path.join(arbeit, "stumm.mp4")
        video.zusammenfuegen(clips, dauern, stumm)
        stimme = None
        if sprecher:
            stimme = os.path.join(arbeit, "stimme.wav")
            video.tonspur(stimmen, dauern, stimme)
        gesamt = sum(dauern)
        video.fertigstellen(stumm, ziel, gesamt, stimme, musik, cfg["musik_lautstaerke"])
        return round(gesamt, 1), titelbild, quellen
    finally:
        shutil.rmtree(arbeit, ignore_errors=True)


HERKUNFT = {
    "wissen": "Bilder KI-generiert.",
    "nacherzaehlung": "Nacherzählt nach {quelle}. Bilder KI-generiert.",
    "wikipedia": "Quelle: Wikipedia ({titel}). Bilder KI-generiert.",
    "fiktion": "Fiktive Geschichte, frei erfunden. Bilder KI-generiert.",
    "eigene_texte": "Bilder KI-generiert.",
}


def _herkunft(skript):
    art = skript.get("quelle_art", "wikipedia")
    if art == "nacherzaehlung":
        q = skript.get("quelle") or ""
        if skript.get("quelle_projekt") == "wikisource":
            zusatz = q if q and q.lower() not in skript.get("titel", "").lower() else skript.get("titel", "")
            return HERKUNFT["nacherzaehlung"].format(quelle=f"{zusatz} (Originaltext: Wikisource)")
        if q and q.lower() not in skript.get("titel", "").lower():
            from . import bibel
            q = f"{q} ({bibel.UEBERSETZUNG})" if bibel.ist_stelle(q) else q
            return HERKUNFT["nacherzaehlung"].format(quelle=q)
        return "Nacherzählt nach der Überlieferung. Bilder KI-generiert."
    if art == "wissen" and skript.get("quelle"):
        if skript.get("quelle_projekt") == "wikivoyage":
            return f"Infos: Wikivoyage ({skript['quelle']}). Bilder KI-generiert."
        return f"Fakten: Wikipedia ({skript['quelle']}). Bilder KI-generiert."
    return HERKUNFT.get(art, "").format(titel=skript.get("titel", ""))


def geschichten_caption(cfg, skript, zufall=random):
    hook = skript["hook"]["text"].replace("*", "")
    tags = list(dict.fromkeys(skript.get("hashtags", []) + cfg["geschichten"]["hashtags"]))[:8]
    teile = [hook, "", skript["frage"].replace("*", "") + " 👇", "",
             _herkunft(skript),
             "", " ".join(tags)]
    return "\n".join(teile).strip()[:2200]


# ---------------------------------------------------------------- Reel aus eigenen Fotos/Videos

def eigene_medien_liste():
    if not os.path.isdir(MEDIEN):
        return []
    endungen = BILDENDUNGEN + video.VIDEOENDUNGEN
    return sorted(f for f in os.listdir(MEDIEN) if f.lower().endswith(endungen) and not f.startswith("."))


def medien_waehlen(cfg, verlauf, zufall=random):
    """N unbenutzte Dateien; sind nicht genug übrig, beginnt eine neue Runde."""
    alle = eigene_medien_liste()
    n = cfg["eigene_medien"]["pro_reel"]
    benutzt = [m for m in verlauf.get("medien_benutzt", []) if m in alle]
    frei = [m for m in alle if m not in benutzt]
    if len(frei) >= n:
        wahl = zufall.sample(frei, n)
    else:  # Rest der Runde plus die am längsten nicht genutzten
        wahl = frei + benutzt[: n - len(frei)]
    return sorted(wahl, key=alle.index)


def _foto_vorbereiten(pfad, ziel):
    """Handy-Fotos richtig drehen (EXIF) und als PNG speichern, damit ffmpeg sie sicher liest."""
    from PIL import ImageOps

    ImageOps.exif_transpose(Image.open(pfad)).convert("RGB").save(ziel, "PNG")
    return ziel


def medien_reel(cfg, dateien, ziel, eintrag=None, musik=None):
    """Clips aus eigenen Fotos/Videos mit Überblendung, optional ein Spruch darüber."""
    m = cfg["eigene_medien"]
    video.ffmpeg_bereit()
    arbeit = tempfile.mkdtemp(prefix="medien_")
    try:
        ebene_png, titel_ebene = None, None
        if eintrag and m["text_einblenden"]:
            titel_ebene = design.untertitel_ebene(eintrag["text"], "#FFFFFF", True,
                                                  cfg["name_im_bild"], cfg["textfarbe"])
            ebene_png = os.path.join(arbeit, "text.png")
            titel_ebene.save(ebene_png)
        dauern = [m["sekunden_pro_clip"]] * len(dateien)
        clips = []
        quellen = []
        for i, datei in enumerate(dateien):
            pfad = os.path.join(MEDIEN, datei)
            if not video.ist_video(pfad):
                pfad = _foto_vorbereiten(pfad, os.path.join(arbeit, f"foto_{i}.png"))
            quellen.append(pfad)
            letzter = i == len(dateien) - 1
            c = os.path.join(arbeit, f"clip_{i}.mp4")
            video.clip(pfad, dauern[i] + (0 if letzter else video.UEBERBLENDUNG), c, ebene_png, zoom_rein=i % 2 == 0)
            clips.append(c)
        stumm = os.path.join(arbeit, "stumm.mp4")
        video.zusammenfuegen(clips, dauern, stumm)
        gesamt = sum(dauern)
        video.fertigstellen(stumm, ziel, gesamt, None, musik, cfg["musik_lautstaerke"])

        # Titelbild: erstes Foto (bzw. erstes Bild aus dem ersten Video) mit Text
        titel_png = os.path.join(arbeit, "titel.png")
        erstes = quellen[0]
        if video.ist_video(erstes):
            video._ff(["-i", erstes, "-frames:v", "1", os.path.join(arbeit, "frame.png")])
            erstes = os.path.join(arbeit, "frame.png")
        design._cover(Image.open(erstes).convert("RGB"), design.HOCH).save(titel_png)
        ebene = titel_ebene or Image.new("RGBA", design.HOCH, (0, 0, 0, 0))
        titelbild = _titelbild(titel_png, ebene, os.path.splitext(ziel)[0] + "_titel.jpg")
        return round(gesamt, 1), titelbild
    finally:
        shutil.rmtree(arbeit, ignore_errors=True)


def text_ohne_markierung(text):
    return re.sub(r"\*", "", text)
