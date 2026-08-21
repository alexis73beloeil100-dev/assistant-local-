"""Eclairage RGB, quelle que soit la marque du materiel.

Pourquoi on ne pilote PAS le logiciel du fabricant. RGB Fusion, Aura, Mystic
Light, iCUE, Chroma : chacun a son format, aucun n'a de ligne de commande, et
tous envoient le reglage DIRECTEMENT au controleur de la carte -- verifie sur
RGB Fusion, dont le fichier de profil n'a pas bouge d'un octet pendant qu'on
changeait de mode a l'ecran. Il n'y a rien a intercepter, et coder pour une
marque ne servirait qu'a une machine.

On passe donc par OpenRGB, qui parle au materiel lui-meme et couvre les
cartes meres, cartes graphiques, barrettes de memoire, claviers, souris et
ventilateurs de la plupart des fabricants, derriere une seule interface.

Rien n'est code en dur ici : ni marque, ni nom de peripherique, ni liste de
modes. Tout est DECOUVERT en interrogeant OpenRGB, exactement comme le releve
materiel decouvre le processeur au lieu de le supposer. Sur une machine
Asus ou Corsair, le meme code fonctionne sans modification.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000
TIMEOUT = 30

# Emplacements ou OpenRGB s'installe, plus une copie portable posee a cote de
# l'assistant. On cherche, on ne suppose pas.
CANDIDATS = [
    Path(os.environ.get("PROGRAMFILES", "")) / "OpenRGB" / "OpenRGB.exe",
    Path(os.environ.get("PROGRAMFILES(X86)", "")) / "OpenRGB" / "OpenRGB.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "OpenRGB" / "OpenRGB.exe",
]

# Logiciels de fabricant qui se disputent le controleur. Deux programmes qui
# ecrivent en meme temps sur le meme bus donnent un eclairage qui clignote au
# hasard, et parfois un peripherique qui ne repond plus jusqu'au redemarrage.
CONCURRENTS = {
    "rgbfusion.exe": "RGB Fusion (Gigabyte)",
    "lightingservice.exe": "Aura Sync (Asus)",
    "armourycrate.exe": "Armoury Crate (Asus)",
    "mysticlight.exe": "Mystic Light (MSI)",
    "icue.exe": "iCUE (Corsair)",
    "razer synapse 3.exe": "Synapse (Razer)",
    "lghub.exe": "G HUB (Logitech)",
    "cam.exe": "CAM (NZXT)",
}


@dataclass
class Peripherique:
    index: int
    nom: str
    genre: str = ""
    modes: list[str] = field(default_factory=list)
    mode_actif: str = ""


def _executable() -> Path | None:
    """Trouve OpenRGB, sans supposer ou il est."""
    from assistant import config

    trouve = shutil.which("OpenRGB")
    if trouve:
        return Path(trouve)
    for chemin in CANDIDATS + [config.ROOT / "OpenRGB" / "OpenRGB.exe"]:
        if chemin.is_file():
            return chemin
    return None


def disponible() -> bool:
    return _executable() is not None


def concurrents_actifs() -> list[str]:
    """Logiciels de fabricant en cours, qui se disputeraient le controleur."""
    try:
        import psutil
    except ImportError:
        return []

    actifs = []
    for proc in psutil.process_iter(["name"]):
        try:
            nom = (proc.info.get("name") or "").lower()
        except Exception:  # noqa: BLE001
            continue
        if nom in CONCURRENTS and CONCURRENTS[nom] not in actifs:
            actifs.append(CONCURRENTS[nom])
    return actifs


def _appeler(arguments: list[str]) -> tuple[bool, str]:
    exe = _executable()
    if exe is None:
        return False, "OpenRGB introuvable."
    try:
        resultat = subprocess.run(
            [str(exe), *arguments], capture_output=True, text=True,
            timeout=TIMEOUT, encoding="utf-8", errors="replace",
            creationflags=CREATE_NO_WINDOW,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    return resultat.returncode == 0, (
        (resultat.stdout or "") + (resultat.stderr or "")).strip()


# La ligne des modes ressemble a :
#   Modes: [Direct] 'Static' 'Breathing' 'Flashing'
# Le mode actif est entre crochets, les autres entre apostrophes. On accepte
# les deux formes plutot que d'imposer un format : la sortie a change entre
# les versions d'OpenRGB, et un analyseur trop strict casserait a la
# prochaine.
_MODE = re.compile(r"\[([^\]]+)\]|'([^']+)'")
_ENTETE = re.compile(r"^\s*(\d+)\s*:\s*(.+?)\s*$")


def peripheriques() -> tuple[list[Peripherique], str]:
    """Ce qui est reellement pilotable sur CETTE machine, et ses modes."""
    ok, sortie = _appeler(["--list-devices"])
    if not ok:
        return [], sortie or "OpenRGB n'a pas repondu."

    trouves: list[Peripherique] = []
    courant: Peripherique | None = None

    for ligne in sortie.splitlines():
        entete = _ENTETE.match(ligne)
        if entete and not ligne.startswith((" ", "\t")):
            courant = Peripherique(int(entete.group(1)), entete.group(2))
            trouves.append(courant)
            continue
        if courant is None:
            continue

        depouille = ligne.strip()
        if depouille.lower().startswith("type:"):
            courant.genre = depouille.split(":", 1)[1].strip()
        elif depouille.lower().startswith("modes:"):
            for actif, autre in _MODE.findall(depouille):
                nom = actif or autre
                courant.modes.append(nom)
                if actif:
                    courant.mode_actif = actif

    if not trouves:
        return [], ("OpenRGB n'a detecte aucun peripherique RGB. "
                    "L'acces au bus demande souvent les droits administrateur.")
    return trouves, ""


def _trouver(nom: str, liste: list[str]) -> str | None:
    """Retrouve un mode par son nom, tolerant sur la casse et les accents."""
    demande = " ".join(str(nom).lower().split())
    for candidat in liste:
        if candidat.lower() == demande:
            return candidat
    for candidat in liste:
        if demande in candidat.lower():
            return candidat
    return None


def liste() -> str:
    """Ce qui est pilotable, avec les modes reellement offerts par chacun."""
    if not disponible():
        return (
            "ECLAIRAGE RGB\n\n"
            "  Le pilotage RGB demande OpenRGB, qui n'est pas installe.\n\n"
            "  Pourquoi lui : les logiciels des fabricants (RGB Fusion, Aura,\n"
            "  Mystic Light, iCUE) n'ont aucune ligne de commande et envoient\n"
            "  leurs reglages directement au controleur de la carte. OpenRGB\n"
            "  parle au materiel lui-meme, et couvre la plupart des marques\n"
            "  derriere une seule interface.\n\n"
            "  C'est un logiciel libre, qui fonctionne hors ligne.\n"
            "  Pose-le dans un dossier OpenRGB a cote de l'assistant, ou\n"
            "  installe-le normalement : il sera trouve tout seul."
        )

    trouves, erreur = peripheriques()
    if erreur:
        return f"ECLAIRAGE RGB\n\n  {erreur}"

    lignes = [f"ECLAIRAGE RGB — {len(trouves)} peripherique(s)", ""]
    for peripherique in trouves:
        lignes.append(f"  [{peripherique.index}] {peripherique.nom}"
                      + (f"  ({peripherique.genre})" if peripherique.genre else ""))
        if peripherique.mode_actif:
            lignes.append(f"       mode actuel : {peripherique.mode_actif}")
        if peripherique.modes:
            lignes.append(f"       modes : {', '.join(peripherique.modes)}")
        lignes.append("")

    concurrents = concurrents_actifs()
    if concurrents:
        lignes.append("  A savoir : " + ", ".join(concurrents) + " tourne(nt) "
                      "en meme temps.")
        lignes.append("  Deux logiciels qui ecrivent sur le meme controleur "
                      "donnent un eclairage")
        lignes.append("  qui clignote au hasard. Ferme-le avant de changer un "
                      "mode.")
    return "\n".join(lignes)


def changer_mode(mode: str, peripherique: str = "", couleur: str = "") -> str:
    """Change le mode d'eclairage, par son nom.

    Sans peripherique, applique a tous ceux qui connaissent ce mode : c'est
    ce qu'on veut en disant "passe le RGB en statique".
    """
    if not disponible():
        return liste()

    trouves, erreur = peripheriques()
    if erreur:
        return erreur

    cibles = trouves
    if peripherique:
        demande = str(peripherique).lower()
        cibles = [p for p in trouves
                  if demande in p.nom.lower() or demande == str(p.index)]
        if not cibles:
            noms = ", ".join(p.nom for p in trouves)
            return f"Aucun peripherique ne correspond a \"{peripherique}\". " \
                   f"Connus : {noms}."

    faits, ignores = [], []
    for cible in cibles:
        exact = _trouver(mode, cible.modes)
        if exact is None:
            ignores.append(f"{cible.nom} (modes : {', '.join(cible.modes)})")
            continue
        arguments = ["--device", str(cible.index), "--mode", exact]
        if couleur:
            arguments += ["--color", couleur.lstrip("#")]
        ok, sortie = _appeler(arguments)
        if ok:
            faits.append(f"{cible.nom} -> {exact}")
        else:
            ignores.append(f"{cible.nom} : {sortie[:80]}")

    lignes = []
    if faits:
        lignes.append("Eclairage change :")
        lignes.extend(f"  {f}" for f in faits)
    if ignores:
        lignes.append("Sans effet :")
        lignes.extend(f"  {i}" for i in ignores)
    if not faits:
        concurrents = concurrents_actifs()
        if concurrents:
            lignes.append("")
            lignes.append(f"{', '.join(concurrents)} tourne : ferme-le, il "
                          "garde la main sur le controleur.")
    return "\n".join(lignes) or "Rien n'a change."
