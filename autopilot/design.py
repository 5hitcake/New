"""Zeichnet Hintergründe und Text: Feed-Bild 1080x1350, Story/Reel 1080x1920."""
import os
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from .einstellungen import HINTERGRUENDE, ROOT, SCHRIFTEN

FEED = (1080, 1350)
HOCH = (1080, 1920)
BILDENDUNGEN = (".jpg", ".jpeg", ".png", ".webp")
MERKEN = 5  # so viele zuletzt genutzte Hintergründe werden übersprungen


def _rgb(hexwert):
    h = hexwert.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _schrift(name, groesse):
    return ImageFont.truetype(os.path.join(SCHRIFTEN, name + ".ttf"), groesse)


def eigene_hintergruende():
    if not os.path.isdir(HINTERGRUENDE):
        return []
    return sorted(f for f in os.listdir(HINTERGRUENDE) if f.lower().endswith(BILDENDUNGEN))


def hintergrund_waehlen(cfg, verlauf, zufall=random):
    """Eigenes Foto (falls vorhanden) oder Farbverlauf. Gibt einen Schlüssel zurück,
    der in der Vorschau und im Verlauf steht, z.B. 'foto:strand.jpg' oder 'verlauf:2'."""
    fotos = eigene_hintergruende()
    optionen = [f"foto:{f}" for f in fotos] or [f"verlauf:{i}" for i in range(len(cfg["farbverlaeufe"]))]
    zuletzt = verlauf.get("hintergruende", [])
    frei = [o for o in optionen if o not in zuletzt] or optionen
    wahl = zufall.choice(frei)
    verlauf["hintergruende"] = (zuletzt + [wahl])[-MERKEN:]
    return wahl


def _cover(bild, groesse):
    quelle = bild.width / bild.height
    ziel = groesse[0] / groesse[1]
    if quelle > ziel:
        h = groesse[1]
        w = int(h * quelle)
    else:
        w = groesse[0]
        h = int(w / quelle)
    bild = bild.resize((w, h), Image.LANCZOS)
    links, oben = (w - groesse[0]) // 2, (h - groesse[1]) // 2
    return bild.crop((links, oben, links + groesse[0], oben + groesse[1]))


def _farbverlauf(oben, unten, groesse, saat):
    """Weicher Verlauf mit zwei Lichtflecken und leichter Körnung - wirkt hochwertiger als ein flacher Verlauf."""
    w, h = groesse
    a, b = _rgb(oben), _rgb(unten)
    streifen = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / (h - 1)
        streifen.putpixel((0, y), tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3)))
    bild = streifen.resize((w, h))

    zufall = random.Random(saat)
    licht = Image.new("L", (w, h), 0)
    zeichnen = ImageDraw.Draw(licht)
    for _ in range(2):
        r = zufall.randint(w // 3, w // 2)
        x, y = zufall.randint(0, w), zufall.randint(0, h)
        zeichnen.ellipse((x - r, y - r, x + r, y + r), fill=70)
    licht = licht.filter(ImageFilter.GaussianBlur(160))
    bild = Image.composite(Image.new("RGB", (w, h), (255, 255, 255)), bild, licht.point(lambda v: v // 3))

    koernung = Image.effect_noise((w, h), 18).convert("RGB")
    return Image.blend(bild, koernung, 0.04)


def hintergrund(cfg, schluessel, groesse):
    art, _, wert = schluessel.partition(":")
    if art in ("foto", "datei"):
        pfad = os.path.join(HINTERGRUENDE, wert) if art == "foto" else os.path.join(ROOT, wert)
        bild = _cover(ImageOps.exif_transpose(Image.open(pfad)).convert("RGB"), groesse)
        dunkel = Image.new("RGB", groesse, (0, 0, 0))
        return Image.blend(bild, dunkel, cfg["abdunkeln"] / 100)
    oben, unten = cfg["farbverlaeufe"][int(wert) % len(cfg["farbverlaeufe"])]
    return _farbverlauf(oben, unten, groesse, saat=schluessel + str(groesse))


def _umbrechen(zeichnen, text, schrift, breite):
    zeilen, aktuell = [], ""
    for wort in text.split():
        probe = f"{aktuell} {wort}".strip()
        if zeichnen.textlength(probe, font=schrift) <= breite or not aktuell:
            aktuell = probe
        else:
            zeilen.append(aktuell)
            aktuell = wort
    if aktuell:
        zeilen.append(aktuell)
    return zeilen


def _passend(zeichnen, cfg, text, breite, hoehe, start, minimum=40):
    groesse = start
    while True:
        schrift = _schrift(cfg["schrift"], groesse)
        zeilen = _umbrechen(zeichnen, text, schrift, breite)
        zeilenhoehe = int(groesse * 1.3)
        zu_breit = any(zeichnen.textlength(z, font=schrift) > breite for z in zeilen)
        if (zeilenhoehe * len(zeilen) <= hoehe and not zu_breit) or groesse <= minimum:
            return schrift, zeilen, zeilenhoehe
        groesse -= 4


def text_ebene(cfg, eintrag, groesse, mit_band=False):
    """Transparente Ebene mit Spruch, Autor und Account-Name. mit_band=True legt ein
    halbtransparentes Band hinter den Text (für Reels, damit er über dem Zoom lesbar bleibt)."""
    w, h = groesse
    ebene = Image.new("RGBA", groesse, (0, 0, 0, 0))
    zeichnen = ImageDraw.Draw(ebene)
    farbe = _rgb(cfg["textfarbe"])

    start = 88 if h == FEED[1] else 96
    schrift, zeilen, zh = _passend(zeichnen, cfg, eintrag["text"], int(w * 0.82), int(h * 0.5), start)
    autor = eintrag.get("autor") or ""
    autor_schrift = _schrift("Poppins-Regular", max(30, int(schrift.size * 0.45)))
    autor_h = int(autor_schrift.size * 2.2) if autor else 0

    block = zh * len(zeilen) + autor_h
    y = (h - block) // 2
    if mit_band:
        rand = 60
        zeichnen.rectangle([(0, y - rand), (w, y + block + rand)], fill=(0, 0, 0, 110))

    for zeile in zeilen:
        x = (w - zeichnen.textlength(zeile, font=schrift)) // 2
        zeichnen.text((x + 3, y + 3), zeile, font=schrift, fill=(0, 0, 0, 150))
        zeichnen.text((x, y), zeile, font=schrift, fill=farbe + (255,))
        y += zh
    if autor:
        zeile = f"— {autor}"
        x = (w - zeichnen.textlength(zeile, font=autor_schrift)) // 2
        zeichnen.text((x, y + int(autor_schrift.size * 0.6)), zeile, font=autor_schrift, fill=farbe + (210,))

    if cfg["name_im_bild"]:
        name_schrift = _schrift("Poppins-Regular", 32)
        x = (w - zeichnen.textlength(cfg["name_im_bild"], font=name_schrift)) // 2
        abstand = 90 if h == FEED[1] else 260  # Story/Reel: oberhalb der Instagram-Bedienelemente
        zeichnen.text((x, h - abstand), cfg["name_im_bild"], font=name_schrift, fill=farbe + (200,))
    return ebene


def bild_zeichnen(cfg, eintrag, hintergrund_schluessel, groesse, ziel, mit_text=True):
    if not mit_text:
        cfg = {**cfg, "abdunkeln": min(cfg["abdunkeln"], 10)}
    basis = hintergrund(cfg, hintergrund_schluessel, groesse).convert("RGBA")
    fertig = Image.alpha_composite(basis, text_ebene(cfg, eintrag, groesse)) if mit_text else basis
    fertig.convert("RGB").save(ziel, "JPEG", quality=92)
    return ziel


# ---------------------------------------------------------------- Untertitel für Story- und Medien-Reels

def _markiert(text):
    """'Das *Schiff* war leer.' -> [('Das', False), ('Schiff', True), ('war', False), ('leer.', False)]"""
    woerter, an = [], False
    for teil in text.split():
        start, ende = teil.startswith("*"), teil.rstrip(".,!?;:").endswith("*")
        wort = teil.replace("*", "")
        woerter.append((wort, an or start))
        if start and not ende:
            an = True
        elif ende:
            an = False
    return woerter


def untertitel_ebene(text, akzent="#E5484D", gross=False, unterzeile="", textfarbe="#FFFFFF"):
    """Transparente 1080x1920-Ebene mit Untertitel im unteren Drittel. *Wörter* in Akzentfarbe."""
    ebene = Image.new("RGBA", HOCH, (0, 0, 0, 0))
    zeichnen = ImageDraw.Draw(ebene)
    breite = int(HOCH[0] * 0.84)
    groesse = 84 if gross else 66
    woerter = _markiert(text)
    while True:
        schrift = _schrift("Poppins-Bold", groesse)
        zeilen, aktuell, w_aktuell = [], [], 0
        luecke = zeichnen.textlength(" ", font=schrift)
        for wort, an in woerter:
            w = zeichnen.textlength(wort, font=schrift)
            if aktuell and w_aktuell + luecke + w > breite:
                zeilen.append(aktuell)
                aktuell, w_aktuell = [], 0
            w_aktuell += (luecke if aktuell else 0) + w
            aktuell.append((wort, an, w))
        if aktuell:
            zeilen.append(aktuell)
        if len(zeilen) <= (5 if gross else 4) or groesse <= 44:
            break
        groesse -= 4
    zh = int(groesse * 1.25)
    unter_schrift = _schrift("Poppins-SemiBold", 40)
    unter_h = 70 if unterzeile else 0
    block = zh * len(zeilen) + unter_h
    mitte = 1060 if gross else 1250
    y = mitte - block // 2
    rand = 44
    zeichnen.rounded_rectangle([(40, y - rand), (HOCH[0] - 40, y + block + rand - 10)], radius=28,
                               fill=(0, 0, 0, 120))
    weiss, farbe = _rgb(textfarbe) + (255,), _rgb(akzent) + (255,)
    for zeile in zeilen:
        gesamt = sum(w for _, _, w in zeile) + luecke * (len(zeile) - 1)
        x = (HOCH[0] - gesamt) / 2
        for wort, an, w in zeile:
            zeichnen.text((x + 3, y + 3), wort, font=schrift, fill=(0, 0, 0, 170))
            zeichnen.text((x, y), wort, font=schrift, fill=farbe if an else weiss)
            x += w + luecke
        y += zh
    if unterzeile:
        x = (HOCH[0] - zeichnen.textlength(unterzeile, font=unter_schrift)) / 2
        zeichnen.text((x, y + 18), unterzeile, font=unter_schrift, fill=_rgb(textfarbe) + (220,))
    return ebene


def ki_bild_vorbereiten(bild, ziel):
    """KI-Bild auf 1080x1920 bringen, leicht abdunkeln und Ränder weich verdunkeln (Vignette)."""
    bild = _cover(bild.convert("RGB"), HOCH)
    bild = Image.blend(bild, Image.new("RGB", HOCH, (0, 0, 0)), 0.18)
    maske = Image.new("L", HOCH, 0)
    ImageDraw.Draw(maske).ellipse((-260, -200, HOCH[0] + 260, HOCH[1] + 200), fill=255)
    maske = maske.filter(ImageFilter.GaussianBlur(180))
    bild = Image.composite(bild, Image.new("RGB", HOCH, (0, 0, 0)), maske)
    bild.save(ziel, "PNG")
    return ziel
