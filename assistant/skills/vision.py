"""Lecture des images : captures d'ecran, photos de menus, documents scannes.

Deux chemins, et l'assistant prend le meilleur disponible :

  1. Un modele de vision installe dans Ollama comprend reellement l'image --
     la disposition, les curseurs, les cases cochees, pas seulement le texte.
  2. A defaut, la reconnaissance de caracteres (RapidOCR, local, sans binaire
     externe) extrait le texte. Suffisant pour un menu de reglages, qui est
     surtout des libelles et des valeurs.

Rien ne part sur Internet dans les deux cas. Aucune image n'est conservee :
elle est lue puis oubliee, comme le contenu des fichiers.
"""
from __future__ import annotations

import base64
import io
import os
import tempfile
import threading
from pathlib import Path

import requests

from assistant import config

IMAGE_EXT = {"png", "jpg", "jpeg", "bmp", "webp", "gif", "tiff", "tif"}

# Modeles de vision reconnus, du plus leger au plus capable. On utilise le
# premier trouve : inutile d'imposer un telechargement de plus.
VISION_MODELS = ["qwen3-vl:4b", "qwen2.5vl:7b", "llava:7b", "moondream"]

_ocr = None
_ocr_lock = threading.Lock()


def is_image(path: str) -> bool:
    return Path(path).suffix.lower().lstrip(".") in IMAGE_EXT


# --- Reconnaissance de texte ------------------------------------------------

def _engine():
    """Charge le moteur OCR une seule fois : son initialisation coute 2 s."""
    global _ocr
    with _ocr_lock:
        if _ocr is None:
            from rapidocr_onnxruntime import RapidOCR

            _ocr = RapidOCR()
        return _ocr


def read_text(path: str) -> tuple[bool, str]:
    """Extrait le texte d'une image, ligne par ligne, de haut en bas."""
    if not os.path.isfile(path):
        return False, f"{path} n'existe pas."

    try:
        resultat, _elapsed = _engine()(path)
    except Exception as exc:  # noqa: BLE001
        return False, f"Lecture d'image impossible ({type(exc).__name__}: {exc})."

    if not resultat:
        return False, "Aucun texte lisible dans cette image."

    # Chaque entree est (boite, texte, confiance). On garde l'ordre vertical
    # pour que la structure d'un menu reste comprehensible.
    lignes = []
    for entree in resultat:
        try:
            boite, texte, confiance = entree[0], entree[1], entree[2]
        except (IndexError, TypeError):
            continue
        if confiance < 0.4 or not str(texte).strip():
            continue
        y = min(point[1] for point in boite)
        x = min(point[0] for point in boite)
        lignes.append((y, x, str(texte).strip()))

    if not lignes:
        return False, "Texte detecte mais illisible."

    lignes.sort(key=lambda item: (round(item[0] / 12), item[1]))
    return True, "\n".join(texte for _y, _x, texte in lignes)


# --- Modele de vision -------------------------------------------------------

def vision_model() -> str | None:
    """Modele de vision installe, s'il y en a un."""
    try:
        from assistant import backend

        presents = {m.split(":")[0] for m in backend.models()}
        for candidat in VISION_MODELS:
            if candidat.split(":")[0] in presents:
                return candidat
    except Exception:  # noqa: BLE001
        pass
    return None


def describe(path: str, question: str = "") -> tuple[bool, str]:
    """Fait decrire l'image par un modele de vision, s'il y en a un."""
    modele = vision_model()
    if modele is None:
        return False, "aucun modele de vision installe"

    try:
        donnees = Path(path).read_bytes()
    except OSError as exc:
        return False, f"Image illisible : {exc}"

    invite = question or (
        "Decris cette capture d'ecran en francais : de quel logiciel ou menu "
        "s'agit-il, et quels reglages y sont visibles avec leurs valeurs ?"
    )

    try:
        reponse = requests.post(
            f"{config.OLLAMA_URL}/api/chat",
            json={
                "model": modele,
                "messages": [{
                    "role": "user",
                    "content": invite,
                    "images": [base64.b64encode(donnees).decode("ascii")],
                }],
                "stream": False,
                "options": {"temperature": 0.2},
            },
            timeout=300,
        )
        reponse.raise_for_status()
        return True, reponse.json()["message"]["content"].strip()
    except (requests.RequestException, KeyError, ValueError) as exc:
        return False, f"Le modele de vision n'a pas repondu : {exc}"


# --- Capture d'ecran --------------------------------------------------------

def capture(ecran: int = 0) -> tuple[bool, str]:
    """Photographie l'ecran et rend le chemin d'un fichier temporaire.

    L'image part dans le dossier temporaire du systeme et est supprimee par
    l'appelant apres lecture : on ne garde pas de trace de ce qui etait
    affiche.
    """
    try:
        import mss

        with mss.mss() as capteur:
            moniteurs = capteur.monitors
            # monitors[0] est la surface totale, les suivants sont les ecrans.
            index = ecran if 0 < ecran < len(moniteurs) else 1
            if index >= len(moniteurs):
                index = 0
            image = capteur.grab(moniteurs[index])

        from PIL import Image

        photo = Image.frombytes("RGB", image.size, image.bgra, "raw", "BGRX")
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as fh:
            chemin = fh.name
        photo.save(chemin, "PNG")
        return True, chemin
    except Exception as exc:  # noqa: BLE001
        return False, f"Capture impossible ({type(exc).__name__}: {exc})."


def screens() -> int:
    try:
        import mss

        with mss.mss() as capteur:
            return max(len(capteur.monitors) - 1, 1)
    except Exception:  # noqa: BLE001
        return 1


# --- Outils exposes ---------------------------------------------------------

def read_image(path: str, question: str = "") -> str:
    """Lit une image : par le modele de vision si possible, sinon par OCR."""
    if not os.path.isfile(path):
        return f"{path} n'existe pas."
    if not is_image(path):
        return (f"{Path(path).name} n'est pas une image. "
                "Utilise lire_fichier pour les documents.")

    ok, texte = describe(path, question)
    if ok:
        return f"--- {Path(path).name} (modele de vision) ---\n{texte}"

    ok, texte = read_text(path)
    if not ok:
        return texte
    return (
        f"--- {Path(path).name} (texte reconnu dans l'image) ---\n{texte}\n\n"
        "[Seul le texte a ete extrait. Pour que l'assistant comprenne aussi "
        "la disposition et les curseurs, installe un modele de vision depuis "
        "l'ecran Composants.]"
    )


def read_screen(question: str = "", ecran: int = 0) -> str:
    """Photographie l'ecran et le lit. L'image est supprimee juste apres."""
    ok, chemin = capture(ecran)
    if not ok:
        return chemin
    try:
        return read_image(chemin, question).replace(
            Path(chemin).name, "capture de l'ecran"
        )
    finally:
        try:
            os.unlink(chemin)
        except OSError:
            pass
