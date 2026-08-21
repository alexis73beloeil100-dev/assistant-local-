"""Demarrage automatique avec Windows.

Utilise la cle Run de l'utilisateur courant (HKCU), pas celle de la machine :
aucun droit administrateur necessaire, et la desinstallation se limite a
supprimer une valeur de registre.
"""
from __future__ import annotations

import sys
import winreg
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "AssistantLocal"

ROOT = Path(__file__).resolve().parent.parent

# L'executable packagee est la cible preferee : c'est ce que l'utilisateur
# lance depuis son Bureau, et il n'a besoin d'aucun environnement Python.
EXE = ROOT / "dist" / "AssistantLocal" / "AssistantLocal.exe"

# Repli sur le lancement direct de la fenetre, avec pythonw.exe pour ne pas
# afficher de terminal noir. Utile tant que l'exe n'a pas ete construit.
PYTHONW = ROOT / ".venv" / "Scripts" / "pythonw.exe"
GUI_LAUNCHER = ROOT / "AssistantLocal.py"


def command() -> str:
    """La commande a inscrire au demarrage.

    Elle doit ouvrir la fenetre de l'assistant. Une version anterieure
    pointait sur la boucle vocale sans interface : au demarrage de Windows,
    ca donnait un processus invisible que l'utilisateur ne pouvait ni voir
    ni utiliser.
    """
    if EXE.exists():
        return f'"{EXE}"'
    return f'"{PYTHONW}" "{GUI_LAUNCHER}"'


def status() -> tuple[bool, str]:
    """Le demarrage automatique est-il actif, et avec quelle commande ?"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
        return True, str(value)
    except OSError:
        return False, ""


def enable() -> str:
    if not EXE.exists() and not (PYTHONW.exists() and GUI_LAUNCHER.exists()):
        return (
            "Aucune cible lancable trouvee.\n"
            f"  Ni {EXE}\n  ni {GUI_LAUNCHER}"
        )

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command())

    cible = "l'executable" if EXE.exists() else "la fenetre Python"
    return (
        f"Demarrage automatique active, sur {cible}.\n"
        "  La fenetre de l'assistant s'ouvrira avec ta session Windows et\n"
        "  reconstruira sa connaissance des fichiers en memoire (40 secondes).\n"
        "  Pour l'enlever : double-clic sur DESACTIVER-demarrage-auto.bat"
    )


def disable() -> str:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, VALUE_NAME)
        return "Demarrage automatique desactive."
    except FileNotFoundError:
        return "Le demarrage automatique n'etait pas actif."
    except OSError as exc:
        return f"Echec : {exc}"
