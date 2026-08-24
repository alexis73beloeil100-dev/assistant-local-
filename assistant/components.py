"""Composants installables, et ce que la machine peut reellement supporter.

L'executable seul sait deja lire les fichiers, diagnostiquer le materiel et
lancer les jeux. Tout le reste -- comprendre le langage naturel, ecouter au
micro -- demande des modeles qui pesent des giga-octets et qu'on ne peut pas
embarquer dans le programme.

Chaque composant sait donc se detecter, s'installer, et dire s'il convient a
CETTE machine. Un modele de 9 Go proposé sur une carte de 4 Go de VRAM
tournerait sur le processeur, dix fois plus lentement, sans que l'utilisateur
comprenne pourquoi.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

CREATE_NO_WINDOW = 0x08000000


def _run(args: list[str], timeout: int = 3600) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
            creationflags=CREATE_NO_WINDOW,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    sortie = (result.stdout or "") + (result.stderr or "")
    return result.returncode == 0, sortie[-400:]


# --- Ce que la machine peut supporter ---------------------------------------

def vram_gb() -> float:
    """VRAM de la carte graphique principale, 0 si aucune carte dediee."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return 0.0
    ok, sortie = _run([exe, "--query-gpu=memory.total",
                       "--format=csv,noheader,nounits"], timeout=15)
    if not ok:
        return 0.0
    try:
        return float(sortie.strip().splitlines()[0]) / 1024
    except (ValueError, IndexError):
        return 0.0


def ram_gb() -> float:
    try:
        import psutil

        return psutil.virtual_memory().total / 1024**3
    except Exception:  # noqa: BLE001
        return 0.0


def cpu_threads() -> int:
    import os

    return os.cpu_count() or 4


# Modeles de langage classes par exigence. On propose le meilleur qui tient
# dans la VRAM disponible, avec de la marge pour la transcription.
LLM_CHOICES = [
    # (identifiant ollama, libelle, telechargement Go, VRAM necessaire Go)
    ("qwen3.5:14b",  "Qwen 3.5 14B - le plus capable",        9.0, 10.5),
    ("qwen3.5:8b",   "Qwen 3.5 8B - intermediaire",           5.0, 6.8),
    ("qwen3.5:4b",   "Qwen 3.5 4B - rapide",                  3.4, 6.1),
    ("qwen3.5:1.7b", "Qwen 3.5 1.7B - machines modestes",     1.4, 2.5),
]

# Marge laissee a la transcription vocale. Volontairement faible : quand la
# VRAM manque, Whisper bascule tout seul sur le processeur (voir stt.load).
# Reserver 2 Go faisait rejeter le 4B sur une carte de 8 Go, ou il tient
# pourtant sans probleme.
VRAM_RESERVE = 1.2

WHISPER_CHOICES = [
    ("medium", "Whisper medium - meilleure precision",  1.5, 4.0),
    ("small",  "Whisper small - rapide",                0.5, 2.0),
    ("base",   "Whisper base - machines modestes",      0.15, 1.0),
]


# Le modele vise en priorite, quelle que soit la machine, des qu'elle peut le
# porter. Mesure sur cette application : il choisit le bon outil 6 fois sur 6
# et repond en 3 secondes. Le 14B, teste dans les memes conditions, etait plus
# lent et enchainait les outils sans conclure. Pour un assistant qui
# selectionne des outils plutot qu'il ne redige, plus gros n'est pas meilleur.
PREFERRED_LLM = "qwen3.5:4b"


def model_options() -> list[dict]:
    """Tous les modeles, avec ce que chacun coute sur CETTE machine.

    On ne cache aucun choix : un modele trop lourd pour la carte reste
    proposable, mais on dit clairement qu'il tournera sur le processeur et
    ce que ca implique. C'est a l'utilisateur de trancher, pas au logiciel.
    """
    vram = vram_gb()
    disponible = max(vram - VRAM_RESERVE, 0)
    conseille, _raison = recommend_llm()

    options = []
    for identifiant, libelle, taille, besoin in LLM_CHOICES:
        tient = besoin <= disponible
        if tient:
            impact = f"tient sur ta carte ({besoin:.1f} Go de VRAM)"
            vitesse = "rapide"
        elif vram > 0:
            manque = besoin - disponible
            impact = (f"depasse ta carte de {manque:.1f} Go : une partie "
                      "tournera sur le processeur")
            vitesse = "nettement plus lent"
        else:
            impact = "aucune carte dediee : tournera entierement sur le processeur"
            vitesse = "lent" if besoin > 3 else "acceptable"

        options.append({
            "id": identifiant,
            "label": libelle,
            "download_gb": taille,
            "vram_gb": besoin,
            "fits": tient,
            "impact": impact,
            "speed": vitesse,
            "recommended": identifiant == conseille,
        })
    return options


def fitting_models(reserve_gb: float = VRAM_RESERVE) -> list[tuple[str, str, float, float]]:
    """Modeles qui tiennent sur cette machine, du plus capable au plus leger.

    La reserve laisse de la place a la transcription vocale, qui occupe le
    GPU en meme temps que le modele de langage.
    """
    vram = vram_gb()
    if vram <= 0:
        # Sans carte dediee, tout tourne sur le processeur : seuls les petits
        # modeles restent utilisables.
        return [c for c in LLM_CHOICES if c[3] <= 3.0]
    disponible = vram - reserve_gb
    return [c for c in LLM_CHOICES if c[3] <= disponible] or [LLM_CHOICES[-1]]


def recommend_llm() -> tuple[str, str]:
    """Modele conseille pour cette machine, et la raison en clair."""
    vram = vram_gb()
    possibles = fitting_models()
    identifiants = [c[0] for c in possibles]

    if PREFERRED_LLM in identifiants:
        plus_gros = [i for i in identifiants if i != PREFERRED_LLM]
        raison = (
            f"{vram:.0f} Go de VRAM : le 4B est le meilleur compromis. Il "
            "repond en quelques secondes et choisit ses outils aussi bien "
            "que les modeles plus lourds."
        ) if vram else (
            "Aucune carte graphique dediee : le 4B tourne sur le processeur, "
            "plus lentement mais correctement."
        )
        if plus_gros:
            raison += (
                f" Ta machine pourrait porter plus gros ({', '.join(plus_gros)}), "
                "mais tu y gagnerais surtout de l'attente."
            )
        return PREFERRED_LLM, raison

    # Machine trop juste pour le 4B : on prend le plus capable qui passe.
    # LLM_CHOICES est trie du plus lourd au plus leger, donc c'est le premier.
    identifiant, libelle, _taille, besoin = possibles[0]
    return identifiant, (
        f"{vram:.0f} Go de VRAM : le 4B demande 6,1 Go, il ne tient pas. "
        f"{libelle.split(' - ')[0]} est le mieux adapte ici."
    )


def recommend_whisper() -> tuple[str, str]:
    vram = vram_gb()
    if vram >= 6:
        return "medium", (
            f"{vram:.0f} Go de VRAM : la transcription tourne sur le GPU, "
            "le modele le plus precis ne coute presque rien."
        )
    if cpu_threads() >= 8:
        return "small", (
            f"{cpu_threads()} threads processeur : la transcription tournera "
            "sur le CPU, le modele moyen serait trop lent."
        )
    return "base", "Machine modeste : le plus petit modele de transcription."


# --- Composants -------------------------------------------------------------

@dataclass
class Component:
    key: str
    label: str
    description: str
    size_gb: float
    detect: Callable[[], bool]
    install: Callable[[Callable[[str], None]], tuple[bool, str]]
    required: bool = False
    # Coche par defaut a l'ouverture de l'installateur.
    default: bool = True
    note: str = ""


# --- Ollama

def _ollama_exe() -> Path | None:
    from assistant import backend

    return backend.find_ollama()


def _ollama_installed() -> bool:
    return _ollama_exe() is not None


def _install_ollama(progress) -> tuple[bool, str]:
    if _ollama_installed():
        return True, "deja installe"

    if not shutil.which("winget"):
        return False, (
            "winget est absent de cette machine. Installe Ollama a la main "
            "depuis https://ollama.com puis relance l'installateur."
        )

    progress("Telechargement et installation d'Ollama (environ 600 Mo) ...")
    ok, sortie = _run([
        "winget", "install", "--id", "Ollama.Ollama", "-e",
        "--accept-source-agreements", "--accept-package-agreements",
        "--disable-interactivity",
    ], timeout=1800)

    if not ok and not _ollama_installed():
        return False, f"Echec de l'installation : {sortie[-200:]}"
    return True, "Ollama installe"


# --- Modele de langage

def _model_installed(name: str) -> bool:
    from assistant import backend

    if not _ollama_installed():
        return False
    backend.start()
    # Comparaison exacte : qwen3.5:4b et qwen3.5:14b partagent la meme
    # famille mais ne sont pas le meme modele. Comparer les familles faisait
    # croire que le 14B etait deja la alors que seul le 4B etait installe.
    presents = {m.strip() for m in backend.models()}
    return name in presents or f"{name}:latest" in presents


def _install_model(name: str):
    def run(progress) -> tuple[bool, str]:
        from assistant import backend

        exe = _ollama_exe()
        if exe is None:
            return False, "Ollama doit etre installe avant le modele."

        progress("Demarrage du moteur ...")
        ok, message = backend.start()
        if not ok:
            return False, message

        progress(f"Telechargement du modele {name} ... "
                 "(cela peut prendre plusieurs minutes)")
        ok, sortie = _run([str(exe), "pull", name], timeout=7200)
        if not ok:
            return False, f"Echec du telechargement : {sortie[-200:]}"

        # Sans cet enregistrement, l'application continuerait a reclamer le
        # modele par defaut et le telechargement n'aurait servi a rien.
        from assistant import settings

        settings.set("llm_model", name)
        return True, f"{name} installe et selectionne"

    return run


# --- Whisper

def _whisper_installed(size: str) -> bool:
    cache = Path.home() / ".cache" / "huggingface" / "hub"
    return (cache / f"models--Systran--faster-whisper-{size}").is_dir()


def _install_whisper(size: str):
    def run(progress) -> tuple[bool, str]:
        progress(f"Telechargement du modele de transcription {size} ...")
        try:
            from faster_whisper import WhisperModel

            # Le simple chargement declenche le telechargement et le cache.
            model = WhisperModel(size, device="cpu", compute_type="int8")
            del model
        except Exception as exc:  # noqa: BLE001
            return False, f"Echec : {type(exc).__name__}: {exc}"
        return True, f"Whisper {size} installe"

    return run


# --- Mot-cle

def _wake_installed() -> bool:
    try:
        import openwakeword

        from assistant.voice.wake import WAKE_MODEL

        base = Path(openwakeword.__file__).parent / "resources" / "models"
        return any(base.glob(f"{WAKE_MODEL}*"))
    except Exception:  # noqa: BLE001
        return False


def _install_wake(progress) -> tuple[bool, str]:
    progress("Telechargement du detecteur de mot-cle ...")
    try:
        import openwakeword

        from assistant.voice.wake import WAKE_MODEL

        openwakeword.utils.download_models([WAKE_MODEL])
    except Exception as exc:  # noqa: BLE001
        return False, f"Echec : {type(exc).__name__}: {exc}"
    return True, "Mot-cle installe"


# --- Raccourci et demarrage

def _shortcut_installed() -> bool:
    from creer_raccourci import NAME, desktop  # type: ignore

    return (desktop() / NAME).exists()


def _install_shortcut(progress) -> tuple[bool, str]:
    progress("Creation du raccourci sur le Bureau ...")
    try:
        import creer_raccourci  # type: ignore

        return True, creer_raccourci.create()
    except Exception as exc:  # noqa: BLE001
        return False, f"Echec : {type(exc).__name__}: {exc}"


def _autostart_installed() -> bool:
    from assistant import startup

    return startup.status()[0]


def _install_autostart(progress) -> tuple[bool, str]:
    from assistant import startup

    progress("Inscription au demarrage de Windows ...")
    return True, startup.enable()


# --- Catalogue --------------------------------------------------------------

def _install_vision(progress) -> tuple[bool, str]:
    """Modele de vision : meme mecanique que le modele de langage, mais il ne
    remplace pas le modele principal -- les deux cohabitent."""
    from assistant import backend

    exe = _ollama_exe()
    if exe is None:
        return False, "Ollama doit etre installe avant le modele de vision."

    progress("Demarrage du moteur ...")
    ok, message = backend.start()
    if not ok:
        return False, message

    progress("Telechargement du modele de vision (3,2 Go) ...")
    ok, sortie = _run([str(exe), "pull", "qwen3-vl:4b"], timeout=7200)
    if not ok:
        return False, f"Echec du telechargement : {sortie[-200:]}"
    return True, "Modele de vision installe"


# Noms publics : l'installateur doit pouvoir reconstruire le composant
# "modele" quand l'utilisateur change de choix dans la liste.
install_model = _install_model
model_installed = _model_installed


def catalogue() -> list[Component]:
    """Les composants proposes, adaptes a cette machine."""
    modele, _raison_llm = recommend_llm()
    taille_modele = next((t for i, _l, t, _v in LLM_CHOICES if i == modele), 3.4)
    whisper, _raison_whisper = recommend_whisper()
    taille_whisper = next((t for i, _l, t, _v in WHISPER_CHOICES if i == whisper), 1.5)

    return [
        Component(
            key="ollama",
            label="Moteur d'intelligence artificielle (Ollama)",
            description="Fait tourner le modele de langage en local. Sans lui, "
                        "l'assistant fonctionne pour les fichiers, le materiel "
                        "et les jeux, mais ne comprend pas les phrases libres.",
            size_gb=0.6,
            detect=_ollama_installed,
            install=_install_ollama,
        ),
        Component(
            key="modele",
            label=f"Modele de langage ({modele})",
            description="Le cerveau : comprend tes demandes et choisit quoi "
                        "faire. Choisi d'apres la memoire de ta carte graphique.",
            size_gb=taille_modele,
            detect=lambda m=modele: _model_installed(m),
            install=_install_model(modele),
        ),
        Component(
            key="whisper",
            label=f"Reconnaissance vocale (Whisper {whisper})",
            description="Transcrit ce que tu dis au micro. Necessaire pour le "
                        "bouton Parler et le mot-cle.",
            size_gb=taille_whisper,
            detect=lambda w=whisper: _whisper_installed(w),
            install=_install_whisper(whisper),
        ),
        Component(
            key="vision",
            label="Comprehension des images (Qwen 3 VL 4B)",
            description="Permet de comprendre une capture d'ecran : la "
                        "disposition, les curseurs, les cases cochees. Sans "
                        "lui, seul le texte de l'image est lu.",
            size_gb=3.2,
            detect=lambda: _model_installed("qwen3-vl:4b"),
            install=_install_vision,
            # FACULTATIF, decide par l'utilisateur le 24/08/2026.
            #
            # Il a d'abord ete coche par defaut, puis decoche de nouveau : 3,2
            # Go imposes a tout le monde pour une fonction que beaucoup
            # n'utiliseront pas. L'installation de base reste a 5,5 Go.
            #
            # La contrepartie est tenue AILLEURS : les notes de version ne
            # promettent plus que l'assistant voit les images, elles disent
            # qu'il en lit le texte et qu'un composant facultatif ajoute la
            # comprehension. Une fonction facultative doit etre annoncee comme
            # telle, sinon elle devient une promesse non tenue.
            default=False,
            note="Facultatif. Sans lui, seul le TEXTE des images est lu, et "
                 "il se deforme parfois.",
        ),
        Component(
            key="motcle",
            label="Mot-cle \"alexa\"",
            description="Permet de declencher l'assistant a la voix, sans "
                        "toucher au clavier.",
            size_gb=0.01,
            detect=_wake_installed,
            install=_install_wake,
        ),
        Component(
            key="raccourci",
            label="Raccourci sur le Bureau",
            description="Pour lancer l'assistant d'un double-clic.",
            size_gb=0.0,
            detect=_shortcut_installed,
            install=_install_shortcut,
        ),
        Component(
            key="demarrage",
            label="Lancer au demarrage de Windows",
            description="L'assistant s'ouvre avec ta session et connait deja "
                        "ta machine quand tu en as besoin.",
            size_gb=0.0,
            detect=_autostart_installed,
            install=_install_autostart,
            default=False,
            note="Decoche par defaut : a toi de voir.",
        ),
    ]
