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
                if resp.status_code not in (429, 500, 502, 503, 504):
                    print(f"Bild-KI {modell}: HTTP {resp.status_code}")
                    break
            except (requests.RequestException, RuntimeError, OSError) as exc:
                print(f"Bild-KI {modell}: {type(exc).__name__}")
            schlafen(8 * (versuch + 1))
    return None
