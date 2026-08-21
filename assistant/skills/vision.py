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


# En dessous de cette largeur, on agrandit avant de lire.
#
# Le texte d'une interface Windows fait 12 a 16 pixels de haut sur une capture
# a taille reelle. C'est sous le seuil ou la reconnaissance devient fiable :
# elle rendait "Assistant local toutrete sur cett macire" pour "tout reste sur
# cette machine". Agrandir avant de lire coute quelques dixiemes de seconde et
# change tout, parce que le modele a ete entraine sur du texte de document,
# beaucoup plus gros qu'un libelle de menu.
LARGEUR_CIBLE = 2600

# Au-dela, on n'agrandit plus : la lecture deviendrait plus lente sans gagner
# en justesse, et un ecran 4K est deja au-dessus du seuil.
AGRANDISSEMENT_MAX = 3.0

# En dessous de cette confiance, un passage est marque comme incertain.
#
# Mesure sur cette machine : la confiance moyenne d'une capture d'ecran est
# de 0,84. Les mots reellement mal lus tombent nettement en dessous. Le seuil
# separe donc ce qu'on peut citer de ce qu'il faut signaler comme douteux --
# sans jeter le texte, qui reste souvent utile en contexte.
SEUIL_SUR = 0.75


def _preparer(path: str):
    """Agrandit et adoucit l'image pour que le texte d'interface soit lisible.

    Rend un tableau numpy, ou None si la preparation echoue -- dans ce cas
    l'appelant lit le fichier tel quel plutot que de renoncer.
    """
    try:
        import numpy as np
        from PIL import Image, ImageOps

        image = Image.open(path)
        image = ImageOps.exif_transpose(image).convert("RGB")

        facteur = min(max(LARGEUR_CIBLE / max(image.width, 1), 1.0),
                      AGRANDISSEMENT_MAX)
        if facteur > 1.05:
            image = image.resize(
                (round(image.width * facteur), round(image.height * facteur)),
                Image.LANCZOS,
            )

        # Le texte clair sur fond sombre d'une interface est le cas le plus
        # difficile : etaler le contraste ramene les deux extremes ou le
        # modele les attend.
        image = ImageOps.autocontrast(image, cutoff=1)
        return np.array(image)
    except Exception:  # noqa: BLE001
        return None


def read_text(path: str) -> tuple[bool, str]:
    """Extrait le texte d'une image, ligne par ligne, de haut en bas."""
    if not os.path.isfile(path):
        return False, f"{path} n'existe pas."

    entree = _preparer(path)
    try:
        resultat, _elapsed = _engine()(entree if entree is not None else path)
    except Exception as exc:  # noqa: BLE001
        return False, f"Lecture d'image impossible ({type(exc).__name__}: {exc})."

    if not resultat:
        return False, "Aucun texte lisible dans cette image."

    # Chaque entree est (boite, texte, confiance). On garde l'ordre vertical
    # pour que la structure d'un menu reste comprehensible.
    lignes = []
    incertaines = 0
    for entree in resultat:
        try:
            boite, texte, confiance = entree[0], entree[1], entree[2]
        except (IndexError, TypeError):
            continue
        if confiance < 0.4 or not str(texte).strip():
            continue
        y = min(point[1] for point in boite)
        x = min(point[0] for point in boite)

        # Un mot mal lu presente comme certain est pire qu'un mot manquant :
        # le modele batit alors un raisonnement sur du charabia. Mesure reelle
        # sur cette machine : "tout reste sur cette machine" est ressorti
        # "toutrete sur cett macire", et l'assistant l'a cite tel quel comme
        # s'il en etait sur.
        marque = str(texte).strip()
        if confiance < SEUIL_SUR:
            marque = f"{marque}(?)"
            incertaines += 1
        lignes.append((y, x, marque))

    if not lignes:
        return False, "Texte detecte mais illisible."

    lignes.sort(key=lambda item: (round(item[0] / 12), item[1]))
    texte = "\n".join(t for _y, _x, t in lignes)

    if incertaines:
        texte += (
            f"\n\n[{incertaines} passage(s) marque(s) (?) : la reconnaissance "
            "n'en est pas sure. Ne les cite pas comme certains, et si le sens "
            "en depend, demande a l'utilisateur plutot que de deviner.]"
        )
    return True, texte


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

    # Repondre a la question posee, meme sans modele de vision.
    #
    # L'ancienne version rendait le texte reconnu tel quel. Demander "quelles
    # fenetres sont ouvertes ?" renvoyait donc une liste de fragments d'OCR,
    # a l'utilisateur de faire le tri -- alors que c'est exactement le travail
    # du modele de langage, qui est deja charge. L'OCR deforme beaucoup
    # ("Asseto Corsa", "Eure Truck Simuletor") : on le dit au modele pour
    # qu'il corrige au lieu de recopier.
    if question.strip():
        reponse = _repondre_sur_le_texte(question, texte)
        if reponse:
            return (
                f"--- {Path(path).name} (lu par reconnaissance de texte) ---\n"
                f"{reponse}\n\n"
                "[Reponse deduite du seul texte reconnu, sans modele de "
                "vision : la disposition, les images et les curseurs ne sont "
                "pas vus. Installe un modele de vision depuis l'ecran "
                "Composants pour qu'il regarde vraiment l'image.]"
            )

    return (
        f"--- {Path(path).name} (texte reconnu dans l'image) ---\n{texte}\n\n"
        "[Seul le texte a ete extrait. Pour que l'assistant comprenne aussi "
        "la disposition et les curseurs, installe un modele de vision depuis "
        "l'ecran Composants.]"
    )


def _repondre_sur_le_texte(question: str, texte: str) -> str:
    """Fait repondre le modele de langage a partir du texte reconnu.

    Rend une chaine vide si le modele n'est pas joignable : l'appelant
    retombe alors sur le texte brut, qui vaut mieux que rien.
    """
    from assistant import llm

    # 3000 caracteres, pas 6000 : au-dela, l'OCR d'un ecran charge n'apporte
    # plus que du bruit, et le temps de reponse double.
    extrait = texte[:3000]
    invite = (
        "Tu lis le texte reconnu automatiquement sur une capture d'ecran. La "
        "reconnaissance deforme les mots (\"Asseto Corsa\" pour \"Assetto "
        "Corsa\").\n\n"
        "Regles absolues :\n"
        "- ne cite QUE ce qui figure litteralement dans le texte ci-dessous ;\n"
        "- corrige une deformation seulement si le mot d'origine est evident, "
        "et signale-le entre parentheses ;\n"
        "- tu n'as AUCUN autre moyen de verification : n'ecris jamais qu'une "
        "chose est \"verifiee\", \"installee\" ou \"presente sur la machine\" ;\n"
        "- quand un fragment est trop abime pour etre identifie, dis "
        "\"illisible\" plutot que de deviner ;\n"
        "- si la reponse ne se trouve pas dans ce texte, dis-le et arrete-toi.\n\n"
        f"--- texte reconnu ---\n{extrait}\n--- fin ---\n\n"
        f"Question : {question}\n"
        "Reponds en francais, brievement."
    )
    try:
        # Sans reflexion : recopier des noms d'applications depuis un texte
        # n'en demande aucune, et le modele y passait plus de 40 secondes.
        message = llm._call([{"role": "user", "content": invite}],
                            with_tools=False, think=False)
        return str(message.get("content", "")).strip()
    except Exception:  # noqa: BLE001
        return ""


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
