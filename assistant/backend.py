"""Demarrage et surveillance du moteur local (Ollama).

Ollama est un serveur separe. Son installateur le lance une fois mais
n'inscrit rien au demarrage de Windows : apres un redemarrage, il ne tourne
plus et l'assistant se retrouvait sans cerveau, avec pour seul symptome un
"Ollama ne repond pas" que l'utilisateur n'avait aucune raison de savoir
corriger.

L'application le demarre donc elle-meme et attend qu'il reponde. C'est ce qui
la rend reellement autonome : un seul raccourci a cliquer, rien d'autre.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import requests

from assistant import config

# Emplacements ou l'installateur Ollama depose son binaire.
CANDIDATES = [
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
    Path(os.environ.get("PROGRAMFILES", "")) / "Ollama" / "ollama.exe",
    Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Ollama" / "ollama.exe",
]

# Le serveur met quelques secondes a ouvrir son port ; le premier demarrage
# apres un redemarrage de Windows est le plus lent.
STARTUP_TIMEOUT = 45.0
POLL_INTERVAL = 0.7

# Lancement sans fenetre de console : l'utilisateur ne doit pas voir clignoter
# un terminal noir quand il ouvre l'assistant.
CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008


def find_ollama() -> Path | None:
    found = shutil.which("ollama")
    if found:
        return Path(found)
    for path in CANDIDATES:
        if path.is_file():
            return path
    return None


def is_up(timeout: float = 2.0) -> bool:
    try:
        response = requests.get(f"{config.OLLAMA_URL}/api/version", timeout=timeout)
        return response.ok
    except requests.RequestException:
        return False


def models() -> list[str]:
    try:
        response = requests.get(f"{config.OLLAMA_URL}/api/tags", timeout=5)
        response.raise_for_status()
        return [m["name"] for m in response.json().get("models", [])]
    except (requests.RequestException, ValueError, KeyError):
        return []


def start(on_progress=None) -> tuple[bool, str]:
    """Demarre le serveur s'il ne tourne pas, et attend qu'il reponde.

    Renvoie (succes, message). Ne leve jamais : un echec ici doit laisser
    l'assistant utilisable pour tout ce qui ne demande pas le modele
    (diagnostic machine, lancement de jeux, recherche de fichiers).
    """
    if is_up():
        return True, "moteur deja actif"

    exe = find_ollama()
    if exe is None:
        return False, (
            "Ollama n'est pas installe. Sans lui, l'assistant repond quand meme "
            "pour la machine, les jeux et les fichiers, mais pas en langage "
            "naturel.\n"
            "Installation : winget install --id Ollama.Ollama -e"
        )

    if on_progress:
        on_progress("demarrage du moteur local ...")

    try:
        subprocess.Popen(
            [str(exe), "serve"],
            # cwd est essentiel : sans lui, Ollama herite du dossier de
            # l'application, et Windows fait charger a ses sous-processus
            # (llama-server) les DLL trouvees dans notre bundle. Resultat :
            # un processus etranger verrouille nos propres fichiers et toute
            # reconstruction de l'executable echoue sur un WinError 5.
            cwd=str(exe.parent),
            creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
    except OSError as exc:
        return False, f"Impossible de lancer {exe.name} : {exc}"

    deadline = time.time() + STARTUP_TIMEOUT
    while time.time() < deadline:
        if is_up(timeout=1.5):
            waited = STARTUP_TIMEOUT - (deadline - time.time())
            return True, f"moteur demarre en {waited:.0f} s"
        time.sleep(POLL_INTERVAL)

    return False, (
        f"Le moteur n'a pas repondu apres {STARTUP_TIMEOUT:.0f} s. "
        "Ouvre Ollama manuellement et relance l'assistant."
    )


def ensure(on_progress=None) -> tuple[bool, str]:
    """Moteur demarre ET modele present : la condition complete."""
    ok, message = start(on_progress)
    if not ok:
        return False, message

    present = models()
    if config.LLM_MODEL not in present:
        return False, (
            f"Le modele {config.LLM_MODEL} est absent.\n"
            "Telechargement (9 Go) : "
            f"ollama pull {config.LLM_MODEL}\n"
            + (f"Modeles presents : {', '.join(present)}" if present else "")
        )
    return True, f"{config.LLM_MODEL} pret ({message})"
