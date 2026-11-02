"""Verifier, telecharger et lancer une mise a jour, au clic et seulement la.

L'application ne contacte personne d'elle-meme : c'est une promesse du
projet. Ce module ne part donc jamais tout seul -- ni au demarrage, ni a
l'ouverture du panneau. Il interroge GitHub quand on clique sur
"Verifier", et telecharge quand on clique sur "Installer".

Ce qui sort : une requete vers l'API publique des Releases du depot, puis le
telechargement du fichier. Rien de personnel, aucun identifiant de la
machine. Les deux adresses sont ecrites en clair ci-dessous, pour qu'on
puisse verifier ou vont les octets sans deviner.

Deux paquets possibles, du plus leger au plus lourd :

  - MiseAJour_AssistantLocal_<depuis>_vers_<vers>.exe : seulement les
    fichiers qui ont change. Il n'est valable QUE pour la version <depuis> :
    pose sur une autre, il laisserait un melange de deux versions.
  - Installer_AssistantLocal.exe : l'installateur complet, valable partout,
    mais d'environ 1,1 Go.

Un fichier telecharge n'est lance que si son empreinte SHA-256 est celle que
GitHub annonce pour lui. Sinon il est efface et rien ne part.

Depot prive : GitHub ne montre ses versions qu'avec une cle d'acces
(jeton personnel, en lecture seule). Elle est rangee dans le Gestionnaire
d'identification de Windows, chiffree pour la session de l'utilisateur, et
jamais dans un fichier de reglages. Elle ne part que vers api.github.com.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from assistant import __version__, config, safety

DEPOT = "alexis73beloeil100-dev/assistant-local-"
API = f"https://api.github.com/repos/{DEPOT}/releases/latest"
HOTE_TELECHARGEMENT = "https://github.com/"
API_FICHIERS = f"https://api.github.com/repos/{DEPOT}/releases/assets/"
CIBLE_CLE = "AssistantLocal/github"

COMPLET = "Installer_AssistantLocal.exe"
DOSSIER = config.DATA_DIR / "mises_a_jour"
DELAI = 15
MORCEAU = 1 << 20


class Echec(Exception):
    """Une etape a echoue ; le message se lit tel quel."""


@dataclass
class Disponible:
    version: str
    nom: str
    url: str
    taille: int
    sha256: str
    notes: str
    partiel: bool
    url_api: str = ""


def paquet_partiel(depuis: str, vers: str) -> str:
    return f"MiseAJour_AssistantLocal_{depuis}_vers_{vers}.exe"


def version_tuple(texte: str) -> tuple[int, ...]:
    """'v1.0.10' -> (1, 0, 10). Comparer des chaines mettrait 1.0.10 avant 1.0.9."""
    nombres = re.findall(r"\d+", texte)
    if not nombres:
        raise Echec(f"numero de version illisible : {texte!r}")
    return tuple(int(n) for n in nombres)


def choisir(release: dict, locale: str = __version__) -> Disponible | None:
    """Rend la mise a jour a proposer, ou None si on est a jour."""
    tag = str(release.get("tag_name", ""))
    vers = tag.lstrip("vV")
    if version_tuple(vers) <= version_tuple(locale):
        return None

    assets = {a.get("name"): a for a in release.get("assets", [])}
    partiel = paquet_partiel(locale, vers)
    for nom, est_partiel in ((partiel, True), (COMPLET, False)):
        asset = assets.get(nom)
        if asset is None or asset.get("state", "uploaded") != "uploaded":
            continue
        digest = str(asset.get("digest") or "")
        if not digest.startswith("sha256:"):
            # Sans empreinte annoncee, on ne saurait pas verifier ce qu'on
            # lance : on n'en propose pas.
            continue
        url = str(asset.get("browser_download_url", ""))
        url_api = str(asset.get("url", ""))
        if not url.startswith(HOTE_TELECHARGEMENT):
            continue
        if url_api and not url_api.startswith(API_FICHIERS):
            continue
        return Disponible(version=vers, nom=nom, url=url,
                          taille=int(asset.get("size", 0)),
                          sha256=digest.split(":", 1)[1].lower(),
                          notes=str(release.get("body") or "").strip(),
                          partiel=est_partiel, url_api=url_api)
    raise Echec(f"la version {vers} est publiee, mais sans fichier "
                f"d'installation verifiable pour la {locale}")


# --- Cle d'acces au depot prive ---------------------------------------------

def jeton() -> str:
    """La cle d'acces GitHub enregistree, ou "" s'il n'y en a pas."""
    try:
        import win32cred

        cred = win32cred.CredRead(CIBLE_CLE, win32cred.CRED_TYPE_GENERIC)
    except Exception:  # noqa: BLE001 - absente, ou hors Windows
        return ""
    blob = cred.get("CredentialBlob") or b""
    return blob.decode("utf-16-le") if isinstance(blob, bytes) else str(blob)


def enregistrer_jeton(valeur: str) -> str:
    valeur = (valeur or "").strip()
    if not valeur:
        return "Aucune cle saisie."
    if not re.fullmatch(r"(github_pat_|ghp_)[A-Za-z0-9_]{20,}", valeur):
        return ("Ce n'est pas une cle d'acces GitHub : elle commence par "
                "github_pat_ (ou ghp_).")
    try:
        import win32cred

        win32cred.CredWrite({
            "Type": win32cred.CRED_TYPE_GENERIC,
            "TargetName": CIBLE_CLE,
            "UserName": "assistant-local",
            "CredentialBlob": valeur,
            "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
        }, 0)
    except Exception as exc:  # noqa: BLE001
        return f"Cle non enregistree : {exc}"
    return "Cle enregistree dans le Gestionnaire d'identification de Windows."


def oublier_jeton() -> str:
    try:
        import win32cred

        win32cred.CredDelete(CIBLE_CLE, win32cred.CRED_TYPE_GENERIC)
    except Exception:  # noqa: BLE001
        return "Aucune cle enregistree."
    return "Cle effacee."


def _entetes(accept: str) -> dict:
    entetes = {"Accept": accept, "X-GitHub-Api-Version": "2022-11-28"}
    cle = jeton()
    if cle:
        entetes["Authorization"] = f"Bearer {cle}"
    return entetes


def verifier(session=None) -> Disponible | None:
    """Interroge GitHub. Rend None si l'application est a jour."""
    import requests

    session = session or requests
    safety._audit(safety.Action(kind="reseau",
                                summary="verification des mises a jour",
                                targets=[API]), "auto:clic")
    try:
        reponse = session.get(API, timeout=DELAI,
                              headers=_entetes("application/vnd.github+json"))
    except requests.RequestException:
        raise Echec("GitHub injoignable : pas de connexion, ou ligne coupee")
    if reponse.status_code in (401, 403) and jeton():
        raise Echec("GitHub refuse la cle d'acces : elle a expire, ou n'a pas "
                    "le droit de lire ce depot. Remplace-la.")
    if reponse.status_code == 404:
        if not jeton():
            raise Echec("rien de visible sur GitHub. Si le depot est prive, "
                        "enregistre une cle d'acces ci-dessous.")
        raise Echec("aucune version publiee sur GitHub")
    if reponse.status_code != 200:
        raise Echec(f"GitHub a repondu {reponse.status_code}")
    return choisir(reponse.json())


def telecharger(dispo: Disponible,
                progression: Callable[[int, int], None] | None = None,
                session=None) -> Path:
    """Telecharge et verifie l'empreinte. Un fichier faux est efface."""
    import requests

    session = session or requests
    DOSSIER.mkdir(parents=True, exist_ok=True)
    final = DOSSIER / dispo.nom
    partiel = final.with_suffix(".part")
    calcul = hashlib.sha256()
    recu = 0
    try:
        # Avec une cle, par l'API : c'est le seul chemin qui marche sur un
        # depot prive. GitHub renvoie vers son stockage, et requests retire
        # l'en-tete d'autorisation en changeant d'hote : la cle ne part que
        # vers api.github.com.
        if jeton() and dispo.url_api:
            url, entetes = dispo.url_api, _entetes("application/octet-stream")
        else:
            url, entetes = dispo.url, {}
        with session.get(url, stream=True, timeout=DELAI,
                         headers=entetes) as reponse:
            if reponse.status_code != 200:
                raise Echec(f"telechargement refuse ({reponse.status_code})")
            with partiel.open("wb") as fh:
                for bloc in reponse.iter_content(MORCEAU):
                    if not bloc:
                        continue
                    fh.write(bloc)
                    calcul.update(bloc)
                    recu += len(bloc)
                    if progression:
                        progression(recu, dispo.taille)
    except requests.RequestException:
        partiel.unlink(missing_ok=True)
        raise Echec("telechargement interrompu : connexion perdue")
    except Echec:
        partiel.unlink(missing_ok=True)
        raise

    if calcul.hexdigest() != dispo.sha256:
        partiel.unlink(missing_ok=True)
        raise Echec("fichier abime ou modifie : empreinte differente de "
                    "celle annoncee par GitHub. Rien n'a ete lance.")
    os.replace(partiel, final)
    return final


def lancer(chemin: Path, dispo: Disponible, ask=None) -> None:
    """Lance l'installateur verifie. L'appelant ferme ensuite l'application."""
    action = safety.Action(
        kind="mise a jour",
        summary=f"installer la version {dispo.version}",
        targets=[str(chemin)],
        details=f"empreinte verifiee : {dispo.sha256[:16]}...",
    )
    if not safety.guard(action, ask=ask):
        raise Echec("installation annulee")
    # Detache : l'installateur doit survivre a la fermeture de l'application,
    # qu'il remplace justement.
    subprocess.Popen([str(chemin)], close_fds=True,
                     creationflags=0x00000008 | 0x00000200)


def resume(dispo: Disponible | None) -> str:
    if dispo is None:
        return f"Tu as la derniere version ({__version__})."
    taille = dispo.taille / 1e6
    genre = "mise a jour" if dispo.partiel else "installateur complet"
    return (f"Version {dispo.version} disponible ({genre}, {taille:.0f} Mo). "
            f"Tu as la {__version__}.")
