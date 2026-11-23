"""KI-Bilder über Cloudflare Workers AI (kostenloses Tageskontingent).

FLUX-1 Schnell braucht ca. 60 der 10.000 kostenlosen "Neurons" pro Tag und Bild,
ein Story-Reel mit 7 Bildern also ca. 420. Fällt alles aus, gibt es einen Farbverlauf.
"""
import base64
import io
import os
import time

import requests
from PIL import Image

# Wichtig: Diese Bild-KIs kennen keine Verneinung. Was im Text vorkommt ("no blood"), malen sie eher hinein.
# Deshalb nur beschreiben, was man sehen will.

# Bildstile zur Auswahl (account → bildstil). Cloudflare hat keine fertigen Stil-Voreinstellungen,
# der Stil wird über die Bildbeschreibung gesteuert. Bewusst ohne Namen von Studios oder Künstlern.
STILE = {
    "foto": ("Realistisch (Foto)", "realistic photograph, natural light, high detail, 35mm lens"),
    "kino": ("Kinofilm", "cinematic film still, dramatic lighting, shallow depth of field, color graded"),
    "anime": ("Anime, handgezeichnet", ("hand-drawn anime illustration, soft painted backgrounds, gentle pastel "
                                       "colors, whimsical and warm, detailed scenery")),
    "comic": ("Comic", "comic book illustration, bold black ink outlines, flat vibrant colors, halftone shading"),
    "3d": ("3D-Animation", "3D animated movie style, soft rounded shapes, warm global illumination, colorful, cute"),
    "aquarell": ("Aquarell", "watercolor painting, soft washes, visible paper texture, delicate colors"),
    "oelgemaelde": ("Ölgemälde", "classical oil painting, visible brush strokes, rich deep colors, museum quality"),
    "skizze": ("Bleistiftskizze", "detailed pencil sketch, graphite on paper, cross-hatching, monochrome"),
    "pixel": ("Pixel-Art", "8-bit pixel art, large clearly visible square pixels, low resolution retro video game "
                           "scene, limited color palette"),
    "flach": ("Flache Illustration", "flat vector illustration, minimal clean shapes, limited color palette, modern"),
    "vintage": ("Vintage-Foto", "vintage 1970s photograph, film grain, faded warm colors, light leaks"),
    "duester": ("Dunkel und düster", "dark moody photograph, low key lighting, fog, desaturated cold colors"),
    "fantasy": ("Fantasy", "epic fantasy concept art, magical glowing atmosphere, highly detailed, dramatic sky"),
}
STIL_PROBE_MOTIV = "a small cozy house by a lake with mountains behind it, a cat sitting on the porch, evening"

OHNE_TEXT = "clean composition, plain unmarked surfaces, no text"
MODELLE = ["@cf/black-forest-labs/flux-1-schnell", "@cf/black-forest-labs/flux-2-klein-4b"]
BREITE, HOEHE = 768, 1344


def _bild_aus(resp):
    if resp.headers.get("content-type", "").startswith("image/"):
        return resp.content
    bild = (resp.json().get("result") or {}).get("image")
    if not bild:
        raise RuntimeError("Antwort ohne Bild")
    return base64.b64decode(bild)


def erzeugen(prompt, http=requests, schlafen=time.sleep):
    """Gibt ein PIL-Bild zurück oder None, wenn kein Modell geliefert hat."""
    konto = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    if not konto or not token:
        return None
    if "no text" not in prompt:
        prompt = f"{prompt}, {OHNE_TEXT}"
    for modell in MODELLE:
        url = f"https://api.cloudflare.com/client/v4/accounts/{konto}/ai/run/{modell}"
        for versuch in range(3):
            try:
                if "flux-2" in modell:
                    form = {"prompt": prompt, "width": str(BREITE), "height": str(HOEHE)}
                    resp = http.post(url, headers={"Authorization": f"Bearer {token}"},
                                     files={k: (None, v) for k, v in form.items()}, timeout=180)
                else:
                    resp = http.post(url, headers={"Authorization": f"Bearer {token}"},
                                     json={"prompt": prompt, "steps": 4}, timeout=180)
                if resp.ok:
                    return Image.open(io.BytesIO(_bild_aus(resp))).convert("RGB")
                if "daily free allocation" in resp.text:
                    print("Bild-KI: Tageskontingent von Cloudflare aufgebraucht, nehme Farbverlauf.")
                    return None
                if resp.status_code not in (429, 500, 502, 503, 504):
                    print(f"Bild-KI {modell}: HTTP {resp.status_code}")
                    break
            except (requests.RequestException, RuntimeError, OSError) as exc:
                print(f"Bild-KI {modell}: {type(exc).__name__}")
            schlafen(8 * (versuch + 1))
    return None


def stilproben(ordner, motiv=STIL_PROBE_MOTIV, erzeugen_fn=None):
    """Erzeugt dasselbe Motiv in allen Bildstilen, mit Namen im Bild. Gibt die Dateien zurück."""
    from PIL import ImageDraw, ImageFont

    from .design import _schrift

    erzeugen_fn = erzeugen_fn or erzeugen
    os.makedirs(ordner, exist_ok=True)
    fertig = []
    for schluessel, (name, stil) in STILE.items():
        bild = erzeugen_fn(f"{motiv}, {stil}")
        if bild is None:
            print(f"Bildstil {schluessel}: kein Bild")
            continue
        bild.thumbnail((640, 640))
        zeichnen = ImageDraw.Draw(bild)
        try:
            font = _schrift("Poppins-Bold", 30)
        except Exception:  # noqa: BLE001
            font = ImageFont.load_default()
        text = f"{name}  ·  {schluessel}"
        zeichnen.rectangle([0, bild.height - 56, bild.width, bild.height], fill=(0, 0, 0))
        zeichnen.text((16, bild.height - 48), text, fill=(255, 255, 255), font=font)
        ziel = os.path.join(ordner, f"bildstil_{schluessel}.jpg")
        bild.save(ziel, quality=85)
        fertig.append(ziel)
        print(f"Bildstil {schluessel} erstellt")
    return fertig
