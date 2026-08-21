"""Presse-papier, notes rapides, captures d'ecran enregistrees.

Les notes vivent en memoire comme le reste, avec une exception assumee :
une note perdue a la fermeture ne servirait a rien. Elles sont donc ecrites
dans les reglages, qui contiennent deja le choix du modele et du micro.
C'est du texte que l'utilisateur a dicte lui-meme, pas un inventaire de ses
fichiers.
"""
from __future__ import annotations

import subprocess
import time
from datetime import datetime
from pathlib import Path

from assistant import settings

CREATE_NO_WINDOW = 0x08000000
MAX_NOTES = 200


def _powershell(commande: str, timeout: int = 20) -> tuple[bool, str]:
    try:
        resultat = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", commande],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
            creationflags=CREATE_NO_WINDOW,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    return resultat.returncode == 0, (resultat.stdout or "").rstrip("\r\n")


# --- Presse-papier ----------------------------------------------------------

def lire_presse_papier() -> str:
    """Ce qui est actuellement copie."""
    ok, contenu = _powershell("Get-Clipboard -Raw")
    if not ok:
        return f"Presse-papier illisible : {contenu[:120]}"
    if not contenu.strip():
        return "Le presse-papier est vide (ou ne contient pas de texte)."
    apercu = contenu if len(contenu) <= 4000 else contenu[:4000] + "\n[... tronque]"
    lignes = contenu.splitlines()
    return (f"Presse-papier : {len(contenu)} caracteres, {len(lignes)} ligne(s)\n\n"
            f"{apercu}")


def ecrire_presse_papier(texte: str) -> str:
    """Place un texte dans le presse-papier."""
    if not texte:
        return "Rien a copier."
    # On passe par un fichier temporaire : une longue chaine dans la ligne de
    # commande casse sur les guillemets et les retours a la ligne.
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(texte)
        chemin = fh.name
    try:
        ok, sortie = _powershell(
            f"Get-Content -Raw -Encoding UTF8 '{chemin}' | Set-Clipboard")
    finally:
        try:
            Path(chemin).unlink()
        except OSError:
            pass
    if not ok:
        return f"Copie impossible : {sortie[:120]}"
    return f"Copie dans le presse-papier ({len(texte)} caracteres)."


# --- Notes ------------------------------------------------------------------

def noter(texte: str) -> str:
    """Enregistre une note rapide."""
    if not texte.strip():
        return "Note vide."
    notes = list(settings.get("notes", []))
    notes.append({
        "quand": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "texte": texte.strip(),
    })
    settings.set("notes", notes[-MAX_NOTES:])
    return f"Note enregistree ({len(notes)} au total)."


def notes(limite: int = 20, filtre: str = "") -> str:
    enregistrees = list(settings.get("notes", []))
    if filtre:
        besoin = filtre.lower()
        enregistrees = [n for n in enregistrees if besoin in n["texte"].lower()]
    if not enregistrees:
        return ("Aucune note." if not filtre
                else f"Aucune note ne contient \"{filtre}\".")

    lignes = [f"{len(enregistrees)} note(s) :", ""]
    for index, note in enumerate(enregistrees[-limite:], 1):
        lignes.append(f"  {index}. [{note['quand']}] {note['texte']}")
    return "\n".join(lignes)


def effacer_notes(numero: int | None = None) -> str:
    enregistrees = list(settings.get("notes", []))
    if not enregistrees:
        return "Aucune note a effacer."
    if numero is None:
        settings.set("notes", [])
        return f"{len(enregistrees)} note(s) effacee(s)."
    if not 1 <= numero <= len(enregistrees):
        return f"Numero hors de la liste (1 a {len(enregistrees)})."
    retiree = enregistrees.pop(numero - 1)
    settings.set("notes", enregistrees)
    return f"Note effacee : {retiree['texte'][:60]}"


# --- Captures d'ecran -------------------------------------------------------

def capturer(destination: str = "", ecran: int = 0) -> str:
    """Prend une capture et l'enregistre, par defaut sur le Bureau."""
    from assistant.skills import vision

    ok, temporaire = vision.capture(ecran)
    if not ok:
        return temporaire

    if destination:
        cible = Path(destination)
        if cible.is_dir():
            cible = cible / f"capture_{time.strftime('%Y-%m-%d_%Hh%M%S')}.png"
    else:
        from creer_raccourci import desktop  # type: ignore

        cible = desktop() / f"capture_{time.strftime('%Y-%m-%d_%Hh%M%S')}.png"

    try:
        cible.parent.mkdir(parents=True, exist_ok=True)
        Path(temporaire).replace(cible)
    except OSError as exc:
        try:
            Path(temporaire).unlink()
        except OSError:
            pass
        return f"Enregistrement impossible : {exc}"

    from assistant.util import human_size

    return f"Capture enregistree : {cible} ({human_size(cible.stat().st_size)})"
