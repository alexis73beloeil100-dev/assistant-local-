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
    """Dossier de l'application : la ou vivent le code et les outils livres.

    En sources, c'est la racine du projet. Dans l'executable packagee,
    __file__ pointe a l'interieur de _internal, le dossier prive de
    PyInstaller : on se place donc a cote de l'executable.

    ATTENTION : ce dossier est jetable. Il est efface et recree a chaque
    reconstruction comme a chaque mise a jour. On n'y ecrit RIEN qu'on veuille
    conserver -- voir DATA_DIR.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _data_dir() -> Path:
    """Dossier des donnees de l'utilisateur, qui doit survivre a tout.

    Il etait a cote de l'executable, et disparaissait donc a chaque
    reconstruction : PyInstaller efface dist/ avant de le remplir, et
    l'installateur remplace le dossier d'installation. Les reglages, le
    journal des actions et les notes repartaient de zero sans un mot.

    Le plus grave etait startup_backup : il conserve la commande exacte des
    programmes desactives au demarrage. Perdue, un programme desactive ne
    peut plus JAMAIS etre reactive autrement qu'en le reinstallant.

    On suit donc la convention de Windows : les donnees d'un utilisateur
    vivent dans son profil, jamais a cote du programme.
    """
    force = os.environ.get("ASSISTANT_DATA")
    if force:
        return Path(force)

    # APPDATA (Roaming) et non LOCALAPPDATA : l'installateur pose le programme
    # dans %LOCALAPPDATA%\AssistantLocal, et son desinstalleur efface ce
    # dossier entier. Y ranger les donnees reviendrait a les faire disparaitre
    # a la premiere desinstallation -- le meme defaut, deplace d'un cran.
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / "AssistantLocal"
    # Sans APPDATA -- cas tres improbable -- on retombe sur le profil.
    return Path.home() / ".assistantlocal"


ROOT = _root()
DATA_DIR = _data_dir()
DB_PATH = DATA_DIR / "index.db"
LOG_DIR = DATA_DIR / "logs"

DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)


def _recuperer_anciennes_donnees() -> list[str]:
    """Rapatrie les donnees laissees a cote de l'executable.

    Sans cette reprise, la correction elle-meme aurait fait perdre les
    reglages qu'elle cherche a proteger : la nouvelle version aurait
    simplement demarre sur un dossier vide.

    On ne remplace jamais un fichier deja present dans le nouvel
    emplacement : celui-ci fait foi.
    """
    import shutil

    repris = []
    for ancien in (ROOT / "data", Path(__file__).resolve().parent.parent / "data"):
        try:
            if not ancien.is_dir() or ancien.resolve() == DATA_DIR.resolve():
                continue
        except OSError:
            continue

        for source in ancien.rglob("*"):
            if not source.is_file():
                continue
            cible = DATA_DIR / source.relative_to(ancien)
            if cible.exists():
                continue
            try:
                cible.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, cible)
                repris.append(str(source.relative_to(ancien)))
            except OSError:
                continue
    return repris


DONNEES_REPRISES = _recuperer_anciennes_donnees()

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
