"""Petits utilitaires partages."""
from __future__ import annotations

from datetime import datetime

BACKSLASH = "\\"


def norm(path: str) -> str:
    """Chemin en minuscules avec des slashs avants, pour comparaison.

    Exemple : C:/Users/Asuna/Documents -> c:/users/asuna/documents
    Les antislashs Windows sont convertis, ce qui permet d'ecrire tous les
    fragments de config.py en slashs avants sans souci d'echappement.
    """
    return path.replace(BACKSLASH, "/").lower()


def matches(path: str, fragments) -> bool:
    """Vrai si un des fragments apparait dans le chemin normalise.

    Le chemin est encadre de slashs avant comparaison pour qu'un fragment
    comme "/node_modules/" matche aussi un dossier en fin de chemin.
    """
    p = "/" + norm(path).strip("/") + "/"
    return any(frag in p for frag in fragments)


def human_size(n: int | float) -> str:
    n = float(n or 0)
    for unit in ("o", "Ko", "Mo", "Go"):
        if abs(n) < 1024:
            return f"{n:,.1f} {unit}".replace(",", " ")
        n /= 1024
    return f"{n:,.1f} To".replace(",", " ")


def human_date(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except (ValueError, OSError, OverflowError):
        return "?"
