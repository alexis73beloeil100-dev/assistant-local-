"""Configuration centrale de l'assistant.

Tout ce qui depend de la machine se regle ici, pas ailleurs dans le code.

Convention : tous les fragments de chemin sont ecrits en minuscules avec des
slashs avants. Le code normalise les chemins Windows avant de comparer
(voir assistant.util.norm), ce qui evite tout probleme d'echappement.
"""
from __future__ import annotations

import os
from pathlib import Path

# --- Emplacements -----------------------------------------------------------

import sys


def _root() -> Path:
    """Dossier de travail de l'application.

    En sources, c'est la racine du projet. Dans l'executable packagee,
    __file__ pointe a l'interieur de _internal (le dossier prive de
    PyInstaller) : y ranger les reglages et les journaux les rendrait
    introuvables pour l'utilisateur et effacables a la moindre mise a jour.
    On se place donc a cote de l'executable.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


ROOT = _root()
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "index.db"
LOG_DIR = DATA_DIR / "logs"

DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# --- Indexation -------------------------------------------------------------

def fixed_drives(min_size_gb: int = 20) -> list[str]:
    """Disques fixes reellement exploitables de CETTE machine.

    Rien n'est code en dur : le logiciel doit fonctionner sur n'importe quel
    PC. On ecarte les lecteurs amovibles et reseau, ainsi que les partitions
    minuscules (reserve au demarrage, recuperation) dont le contenu n'a
    aucun interet et dont l'espace libre ne veut rien dire.
    """
    import ctypes
    import string

    DRIVE_FIXED = 3
    roots = []
    try:
        mask = ctypes.windll.kernel32.GetLogicalDrives()
    except (AttributeError, OSError):
        return ["C:\\"]

    for i, letter in enumerate(string.ascii_uppercase):
        if not mask & (1 << i):
            continue
        root = f"{letter}:\\"
        try:
            if ctypes.windll.kernel32.GetDriveTypeW(root) != DRIVE_FIXED:
                continue
            total = ctypes.c_ulonglong(0)
            ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                ctypes.c_wchar_p(root), None, ctypes.byref(total), None
            )
            if total.value >= min_size_gb * 1024**3:
                roots.append(root)
        except OSError:
            continue

    return roots or ["C:\\"]


# Racines scannees, detectees au demarrage. Surchargeable pour les tests.
SCAN_ROOTS = fixed_drives()

# Dossiers entierement ignores : bruit systeme sans valeur pour toi.
EXCLUDED_DIRS = (
    "$recycle.bin",
    "system volume information",
    "$windows.~bt",
    "$windows.~ws",
    "/windows/winsxs",
    "/windows/servicing",
    "/windows/system32/driverstore",
    "/windows/softwaredistribution",
    "/windows/assembly",
    "/windows/installer",
    "/appdata/local/packages",   # conteneurs UWP, illisibles
    "/config.msi",
)

# Dossiers indexes mais marques "cache" : ils comptent pour l'espace disque,
# pas pour la recherche de tes fichiers.
CACHE_MARKERS = (
    "/node_modules/",
    # Dependances installees : ce sont des fichiers de bibliotheques, jamais
    # les tiens. Sans cette exclusion ils noyaient toute recherche dans les
    # contenus -- 400 fichiers d'openpyxl passaient avant ton config.py.
    "/site-packages/",
    "/.venv/",
    "/venv/",
    "/lib/python3",
    "/.nuget/packages/",
    "/.cargo/registry/",
    "/deriveddatacache/",
    "/intermediate/",
    "/saved/autosaves/",
    "/.git/objects/",
    "/__pycache__/",
    "/appdata/local/temp/",
    "/windows/temp/",
    "/nv_cache/",
    "/d3dscache/",
    "/appdata/local/crashdumps/",
)

# Nombre de lignes envoyees a SQLite par transaction pendant le scan.
INSERT_BATCH = 20_000

# False = l'index vit uniquement en memoire vive et disparait a la fermeture.
# Rien n'est ecrit sur le disque, aucune liste de fichiers ne subsiste.
# Contrepartie : il est reconstruit a chaque demarrage (environ 80 secondes,
# en tache de fond, pendant que le reste de l'assistant est deja utilisable).
#
# True = l'index est conserve dans data/index.db et le demarrage est immediat.
PERSIST_INDEX = False

# --- Modele local -----------------------------------------------------------

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")

# Qwen 3.5 4B : ~6,1 Go de VRAM et 131K jetons de contexte. Sur une RTX
# 5060 Ti de 16 Go qui porte aussi Whisper, il laisse assez de place pour
# qu'un jeu tourne en meme temps -- ce que le 14B (9 Go) ne permettait pas.
DEFAULT_LLM_MODEL = "qwen3.5:4b"

def _vram_gb() -> float:
    """Memoire de la carte graphique, en Go. 0 si aucune carte dediee.

    Sonde autonome, volontairement : config est importe par tout le reste, et
    dependre ici d'un module qui depend de config creerait un cycle.
    """
    import shutil
    import subprocess

    exe = shutil.which("nvidia-smi")
    if not exe:
        return 0.0
    try:
        sortie = subprocess.run(
            [exe, "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=15,
            creationflags=0x08000000,
        ).stdout.strip().splitlines()
        return float(sortie[0]) / 1024 if sortie else 0.0
    except (subprocess.SubprocessError, OSError, ValueError, IndexError):
        return 0.0


def context_for_vram(vram: float | None = None) -> int:
    """Taille de fenetre de contexte tenable sur CETTE carte.

    Le contexte se paie en memoire graphique. Mesure sur une RTX 5060 Ti,
    modele Qwen 3.5 4B charge, en retirant ce qui etait deja occupe :

        8 192 jetons  ->  4,1 Go   (l'ancien reglage, herite du 14B)
       32 768 jetons  ->  4,9 Go
       65 536 jetons  ->  6,2 Go
      131 072 jetons  ->  8,5 Go

    Une carte de 8 Go ne peut donc pas porter 65 536 jetons : il faut aussi
    de la place pour l'affichage du bureau et pour la transcription vocale.
    On choisit selon ce qui est reellement installe, plutot que de figer une
    valeur qui ne conviendrait qu'a une seule machine.
    """
    if vram is None:
        vram = _vram_gb()

    # (VRAM minimale, contexte)
    paliers = [
        (14.0, 65_536),
        (11.0, 49_152),
        (7.5,  32_768),   # une carte annoncee 8 Go en expose environ 7,8
        (5.5,  16_384),
        (0.0,   8_192),   # petite carte, ou tout sur le processeur
    ]
    for minimum, contexte in paliers:
        if vram >= minimum:
            return contexte
    return 8_192


# Taille de la fenetre de contexte, en jetons. Detectee, surchargeable.
LLM_CONTEXT = int(os.environ.get("ASSISTANT_CONTEXT", "0")) or context_for_vram()

# Part du contexte qu'on autorise l'historique a occuper. Le reste est la
# marge dont le modele a besoin pour raisonner et repondre.
CONTEXT_USAGE = 0.65


def llm_model() -> str:
    """Le modele reellement utilise.

    Priorite : variable d'environnement (pour les tests), puis le choix fait
    a l'installation, puis le defaut. Sans ce chainage, l'installateur
    pouvait telecharger un modele que l'application n'utilisait jamais.
    """
    forced = os.environ.get("ASSISTANT_MODEL")
    if forced:
        return forced
    try:
        from assistant import settings

        return settings.get("llm_model") or DEFAULT_LLM_MODEL
    except Exception:  # noqa: BLE001
        return DEFAULT_LLM_MODEL


LLM_MODEL = llm_model()

# --- Securite ---------------------------------------------------------------

# Lecture libre, ecriture confirmee : toute action qui modifie la machine
# passe par assistant.safety.confirm().
REQUIRE_CONFIRMATION = True

def protected_paths() -> tuple[str, ...]:
    """Chemins jamais modifies, deduits de CETTE installation de Windows.

    Ecrire "c:/users/asuna/..." en dur ne protegeait que cette machine : sur
    un autre PC, le chemin n'existe pas et la protection ne s'applique a rien.
    On lit donc les variables d'environnement, qui sont justes partout.
    """
    from assistant.util import norm

    bruts = [
        os.environ.get("SystemRoot", r"C:\Windows"),
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        os.environ.get("ProgramData", r"C:\ProgramData"),
    ]
    return tuple(norm(p) for p in bruts if p)


PROTECTED_PATHS = protected_paths()
