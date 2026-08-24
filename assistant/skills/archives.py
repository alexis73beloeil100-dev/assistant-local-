"""Compresser et decompresser, sans laisser une archive ecrire ou elle veut.

content.py savait deja LIRE une archive -- lister ce qu'elle contient, en
sortir le texte. Ce module ajoute les deux gestes qui manquaient : en
fabriquer une, et en extraire le contenu sur le disque.

Extraire est l'operation dangereuse, et pas pour la raison qu'on croit. Un
fichier d'archive porte un chemin ECRIT DANS L'ARCHIVE, et rien n'oblige ce
chemin a rester dans le dossier de destination. Une entree nommee
`..\\..\\Windows\\System32\\quelque.dll` remonte l'arborescence et ecrit ou
elle veut ; une entree en chemin absolu ignore la destination purement et
simplement. C'est une faille connue -- "Zip Slip" -- et zipfile.extractall()
la neutralise depuis Python 3.6 pour les chemins absolus, mais l'erreur se
reintroduit des qu'on ecrit sa propre boucle d'extraction, ce qu'on fait ici
pour compter et filtrer.

On verifie donc, pour CHAQUE entree, que la destination reelle reste sous le
dossier demande. Une seule entree hors des clous fait echouer l'extraction
entiere : extraire a moitie une archive piegee laisserait la moitie piegee.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

from assistant import safety
from assistant.util import human_size

# Au-dela, on demande confirmation meme pour une lecture : une archive de
# quelques kilo-octets qui se deploie en dizaines de giga-octets est un
# procede connu pour saturer un disque.
DEPLOIEMENT_SUSPECT = 100
TAILLE_ALERTE = 2 * 1024 ** 3


def _resoudre(destination: Path, nom: str) -> Path | None:
    """Ou cette entree atterrirait vraiment, ou None si elle sort du dossier.

    resolve() applique les `..` et les liens : c'est la seule facon de savoir
    ou le systeme ecrirait pour de bon, plutot que ce que le nom laisse
    croire.
    """
    cible = (destination / nom).resolve()
    racine = destination.resolve()
    try:
        cible.relative_to(racine)
    except ValueError:
        return None
    return cible


def inspecter(archive: str) -> str:
    """Ce que contient une archive, sans rien extraire."""
    chemin = Path(archive).expanduser()
    if not chemin.is_file():
        return f"Archive introuvable : {chemin}"
    try:
        with zipfile.ZipFile(chemin) as zip_:
            entrees = zip_.infolist()
            compresse = sum(e.compress_size for e in entrees)
            reel = sum(e.file_size for e in entrees)
    except (zipfile.BadZipFile, OSError) as exc:
        return f"Archive illisible : {type(exc).__name__}: {exc}"

    lignes = [f"{chemin.name}", "",
              f"  {len(entrees)} entrees",
              f"  {human_size(compresse)} compresse, "
              f"{human_size(reel)} une fois deploye"]

    suspects = [e.filename for e in entrees
                if _resoudre(chemin.parent, e.filename) is None]
    if suspects:
        lignes.append("")
        lignes.append(f"  ATTENTION : {len(suspects)} entrees ecriraient hors "
                      "du dossier de destination.")
        lignes.extend(f"    {n}" for n in suspects[:5])

    lignes.append("")
    for entree in entrees[:20]:
        lignes.append(f"    {entree.filename}")
    if len(entrees) > 20:
        lignes.append(f"    ... et {len(entrees) - 20} autres")
    return "\n".join(lignes)


def decompresser(archive: str, destination: str = "", ask=None) -> str:
    """Extrait une archive, en refusant toute entree qui sort du dossier."""
    chemin = Path(archive).expanduser()
    if not chemin.is_file():
        return f"Archive introuvable : {chemin}"

    cible = (Path(destination).expanduser() if destination
             else chemin.parent / chemin.stem)

    try:
        with zipfile.ZipFile(chemin) as zip_:
            entrees = [e for e in zip_.infolist() if not e.is_dir()]
            reel = sum(e.file_size for e in entrees)
            compresse = sum(e.compress_size for e in entrees) or 1

            # Verifier AVANT d'ecrire quoi que ce soit. Extraire a moitie une
            # archive piegee laisserait la moitie piegee sur le disque.
            hors_dossier = [e.filename for e in entrees
                            if _resoudre(cible, e.filename) is None]
            if hors_dossier:
                return (
                    f"Extraction refusee : {len(hors_dossier)} entrees de "
                    "cette archive ecriraient EN DEHORS du dossier de "
                    "destination.\n  "
                    + "\n  ".join(hors_dossier[:5])
                    + "\nC'est le procede par lequel une archive remplace des "
                      "fichiers du systeme. Rien n'a ete extrait.")

            if safety.is_protected(str(cible)):
                return (f"{cible} est dans les chemins proteges. Je n'y "
                        "extrais rien, meme sur confirmation.")

            details = [f"{len(entrees)} fichiers, {human_size(reel)} une fois "
                       "deployes"]
            if reel / compresse > DEPLOIEMENT_SUSPECT or reel > TAILLE_ALERTE:
                details.append(
                    f"ATTENTION : l'archive gonfle {reel // compresse} fois en "
                    "se deployant. Verifie l'espace libre.")

            action = safety.Action(
                kind="fichier",
                summary=f"Extraire {chemin.name} vers {cible}",
                targets=[str(cible)],
                reversible=False,
                details="  ".join(details),
            )
            try:
                safety.guard(action, ask=ask)
            except safety.Refused as exc:
                return str(exc)

            ecrits = 0
            for entree in entrees:
                ou = _resoudre(cible, entree.filename)
                if ou is None:          # deja verifie, mais on ne parie pas
                    continue
                ou.parent.mkdir(parents=True, exist_ok=True)
                with zip_.open(entree) as source, ou.open("wb") as sortie:
                    sortie.write(source.read())
                ecrits += 1
    except (zipfile.BadZipFile, OSError) as exc:
        return f"Extraction impossible : {type(exc).__name__}: {exc}"

    return f"{ecrits} fichiers extraits dans {cible}."


def compresser(chemins: list[str] | str, destination: str = "",
               ask=None) -> str:
    """Fabrique une archive zip a partir de fichiers ou de dossiers."""
    if isinstance(chemins, str):
        chemins = [chemins]
    sources = [Path(c).expanduser() for c in chemins if str(c).strip()]
    if not sources:
        return "Rien a compresser : aucun chemin fourni."

    manquants = [str(s) for s in sources if not s.exists()]
    if manquants:
        return "Introuvable : " + ", ".join(manquants)

    if destination:
        archive = Path(destination).expanduser()
    else:
        base = sources[0]
        archive = base.parent / f"{base.stem or base.name}.zip"
    if archive.suffix.lower() != ".zip":
        archive = archive.with_suffix(".zip")

    if archive.exists():
        return (f"{archive} existe deja. Donne-moi un autre nom : je ne "
                "remplace pas une archive sans qu'on me le demande.")

    fichiers: list[tuple[Path, str]] = []
    for source in sources:
        if source.is_file():
            fichiers.append((source, source.name))
        else:
            for enfant in source.rglob("*"):
                if enfant.is_file():
                    fichiers.append(
                        (enfant, str(Path(source.name)
                                     / enfant.relative_to(source))))
    if not fichiers:
        return "Rien a compresser : les chemins donnes ne contiennent aucun fichier."

    poids = sum(f.stat().st_size for f, _ in fichiers)
    action = safety.Action(
        kind="fichier",
        summary=f"Creer l'archive {archive.name}",
        targets=[str(archive)],
        reversible=True,
        details=f"{len(fichiers)} fichiers, {human_size(poids)} avant "
                "compression",
        # Ecrire une archive n'efface rien : le nom deja pris est refuse plus
        # haut, et supprimer le zip suffit a revenir en arriere.
        routine=True,
    )
    try:
        safety.guard(action, ask=ask)
    except safety.Refused as exc:
        return str(exc)

    try:
        archive.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zip_:
            for fichier, nom in fichiers:
                zip_.write(fichier, nom)
    except OSError as exc:
        return f"Creation impossible : {type(exc).__name__}: {exc}"

    final = archive.stat().st_size
    # Le gain n'a de sens que s'il y en a un. Sur quelques fichiers minuscules,
    # l'en-tete du zip pese plus que leur contenu : la formule brute annoncait
    # "-941 % de gagne", un chiffre qui ne veut rien dire et fait douter du
    # reste du message.
    if final < poids:
        mesure = f"{100 - (final * 100 // max(poids, 1))} % de gagne"
    else:
        mesure = ("pas de gain : la structure du zip pese plus que ces "
                  "fichiers")
    return (f"{archive} cree : {len(fichiers)} fichiers, "
            f"{human_size(final)} ({mesure}).")
