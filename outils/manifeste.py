"""Empreinte du dossier livre, pour savoir ce qui a reellement change.

Une mise a jour ne doit embarquer que ce qui bouge. Encore faut-il le savoir :
sur 2,68 Go livres, 1 986 Mo sont des bibliotheques CUDA qui ne changent
jamais, et l'executable qui porte tout le travail en pese 24.

Se fier aux dates de modification ne marche pas : PyInstaller reecrit
l'integralite de dist/ a chaque construction, donc tout parait modifie. On
compare donc les contenus, par empreinte SHA-256.

Le manifeste d'une version publiee est versionne dans manifestes/. C'est lui
qui sert de reference a la mise a jour suivante : sans lui, impossible de
savoir ce qui a change depuis ce que les gens ont reellement installe.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
LIVRE = RACINE / "dist" / "AssistantLocal"
MANIFESTES = RACINE / "manifestes"

# 1 Mo : au-dela le gain disparait, en deca on multiplie les appels systeme
# sur des fichiers qui pesent parfois 400 Mo.
TAILLE_LECTURE = 1024 * 1024


def empreinte(chemin: Path) -> str:
    """SHA-256 d'un fichier, lu par morceaux.

    Les bibliotheques CUDA depassent le demi-gigaoctet : les charger en
    memoire d'un bloc ferait tomber la machine sur laquelle on construit.
    """
    calcul = hashlib.sha256()
    with chemin.open("rb") as f:
        while morceau := f.read(TAILLE_LECTURE):
            calcul.update(morceau)
    return calcul.hexdigest()


def construire(racine: Path = LIVRE, version: str = "") -> dict:
    """Releve chaque fichier du dossier livre, avec son empreinte et sa taille.

    Les chemins sont relatifs et en barres obliques : un manifeste produit ici
    doit rester lisible et comparable ailleurs.
    """
    if not racine.is_dir():
        raise FileNotFoundError(f"dossier livre introuvable : {racine}")

    fichiers = {}
    for chemin in sorted(racine.rglob("*")):
        if not chemin.is_file():
            continue
        relatif = chemin.relative_to(racine).as_posix()
        fichiers[relatif] = {
            "sha256": empreinte(chemin),
            "taille": chemin.stat().st_size,
        }

    return {
        "version": version,
        "genere": datetime.now().isoformat(timespec="seconds"),
        "fichiers": fichiers,
    }


def ecrire(manifeste: dict, destination: Path | None = None) -> Path:
    """Enregistre le manifeste, par defaut sous manifestes/<version>.json."""
    if destination is None:
        version = manifeste.get("version") or "sans-version"
        MANIFESTES.mkdir(exist_ok=True)
        destination = MANIFESTES / f"{version}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(manifeste, indent=2, ensure_ascii=False), encoding="utf-8")
    return destination


def lire(chemin: Path) -> dict:
    return json.loads(Path(chemin).read_text(encoding="utf-8"))


def differences(ancien: dict, nouveau: dict) -> dict:
    """Ce qui separe deux versions livrees.

    "supprimes" compte autant que le reste : un fichier retire du bundle mais
    laisse sur la machine cible peut etre charge a la place du bon. Une mise a
    jour qui ajoute sans jamais retirer finit par livrer un melange de deux
    versions.
    """
    avant = ancien.get("fichiers", {})
    apres = nouveau.get("fichiers", {})

    ajoutes = sorted(set(apres) - set(avant))
    supprimes = sorted(set(avant) - set(apres))
    modifies = sorted(
        nom for nom in set(avant) & set(apres)
        if avant[nom]["sha256"] != apres[nom]["sha256"])
    inchanges = sorted(
        nom for nom in set(avant) & set(apres)
        if avant[nom]["sha256"] == apres[nom]["sha256"])

    a_livrer = ajoutes + modifies
    return {
        "ajoutes": ajoutes,
        "modifies": modifies,
        "supprimes": supprimes,
        "inchanges": inchanges,
        "poids_livre": sum(apres[nom]["taille"] for nom in a_livrer),
        "poids_total": sum(item["taille"] for item in apres.values()),
    }


def resume(ecart: dict) -> str:
    """Une ligne lisible : c'est ce qu'on relit avant de publier."""
    mo = ecart["poids_livre"] / 1048576
    total = ecart["poids_total"] / 1048576
    part = (100 * mo / total) if total else 0
    return (f"{len(ecart['ajoutes'])} ajoutes, {len(ecart['modifies'])} "
            f"modifies, {len(ecart['supprimes'])} supprimes, "
            f"{len(ecart['inchanges'])} inchanges -- "
            f"{mo:.1f} Mo a livrer sur {total:.0f} ({part:.1f} %)")


def main() -> int:
    from assistant import __version__

    print(f"  Empreinte de {LIVRE} ...")
    manifeste = construire(version=__version__)
    chemin = ecrire(manifeste)
    poids = sum(f["taille"] for f in manifeste["fichiers"].values())
    print(f"  {len(manifeste['fichiers'])} fichiers, {poids / 1048576:.0f} Mo")
    print(f"  Manifeste : {chemin}")
    return 0


if __name__ == "__main__":
    import sys

    if str(RACINE) not in sys.path:
        sys.path.insert(0, str(RACINE))
    raise SystemExit(main())
