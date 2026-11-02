"""Sauvegarder et restaurer ses donnees : rien a perdre a une reinitialisation.

Une seule archive, a poser ou l'on veut (cle USB, disque externe,
OneDrive), qui contient :
  - le dossier des donnees de l'application (reglages, notes, journal,
    historique des modifications de code, essai) ;
  - la cle maitre du mode Dev, si elle est sur ce PC ;
  - la cle d'acces (dans les reglages).

Ce qui se retelecharge n'y est pas : modeles, bibliotheque locale, index
des fichiers, captures.

L'archive est CHIFFREE avec un mot de passe, parce qu'elle contient la cle
maitre : ChaCha20 (RFC 8439) pour le contenu, HMAC-SHA256 pour verifier
qu'elle n'a ete ni abimee ni modifiee (chiffrer puis signer), cle tiree du
mot de passe par scrypt. Un mauvais mot de passe est refuse avant d'ecrire
quoi que ce soit.
"""
from __future__ import annotations

import hashlib
import hmac
import io
import os
import secrets
import shutil
import struct
import time
import zipfile
from pathlib import Path

from assistant import config, licence

MAGIE = b"ALSAUV1\n"
EXCLUS = {"bibliotheque", "captures_editeur", "index.db", "index.db-wal",
          "index.db-shm", "mises_a_jour"}
NOM_MAITRE = "cle_maitre/cle_maitre_SECRETE.txt"


class MotDePasseFaux(Exception):
    """L'archive ne s'ouvre pas avec ce mot de passe, ou elle a ete modifiee."""


# --- ChaCha20 (RFC 8439, section 2.4) ------------------------------------------

def _rotl(v: int, c: int) -> int:
    return ((v << c) & 0xFFFFFFFF) | (v >> (32 - c))


def _quart(e, a, b, c, d):
    e[a] = (e[a] + e[b]) & 0xFFFFFFFF; e[d] = _rotl(e[d] ^ e[a], 16)  # noqa: E702
    e[c] = (e[c] + e[d]) & 0xFFFFFFFF; e[b] = _rotl(e[b] ^ e[c], 12)  # noqa: E702
    e[a] = (e[a] + e[b]) & 0xFFFFFFFF; e[d] = _rotl(e[d] ^ e[a], 8)   # noqa: E702
    e[c] = (e[c] + e[d]) & 0xFFFFFFFF; e[b] = _rotl(e[b] ^ e[c], 7)   # noqa: E702


def _bloc(cle: bytes, compteur: int, nonce: bytes) -> bytes:
    etat = ([0x61707865, 0x3320646E, 0x79622D32, 0x6B206574]
            + list(struct.unpack("<8L", cle)) + [compteur]
            + list(struct.unpack("<3L", nonce)))
    travail = etat[:]
    for _ in range(10):
        _quart(travail, 0, 4, 8, 12); _quart(travail, 1, 5, 9, 13)   # noqa: E702
        _quart(travail, 2, 6, 10, 14); _quart(travail, 3, 7, 11, 15)  # noqa: E702
        _quart(travail, 0, 5, 10, 15); _quart(travail, 1, 6, 11, 12)  # noqa: E702
        _quart(travail, 2, 7, 8, 13); _quart(travail, 3, 4, 9, 14)    # noqa: E702
    return struct.pack("<16L", *((x + y) & 0xFFFFFFFF for x, y in zip(travail, etat)))


def chacha20(cle: bytes, nonce: bytes, donnees: bytes, compteur: int = 1) -> bytes:
    sortie = bytearray(len(donnees))
    for i in range(0, len(donnees), 64):
        flux = _bloc(cle, compteur + i // 64, nonce)
        morceau = donnees[i:i + 64]
        sortie[i:i + len(morceau)] = bytes(a ^ b for a, b in zip(morceau, flux))
    return bytes(sortie)


# --- Chiffrer une archive ------------------------------------------------------------

def _cles(mot_de_passe: str, sel: bytes) -> tuple[bytes, bytes]:
    brut = hashlib.scrypt(mot_de_passe.encode("utf-8"), salt=sel,
                          n=2 ** 15, r=8, p=1, maxmem=64 * 1024 * 1024, dklen=64)
    return brut[:32], brut[32:]


def chiffrer(donnees: bytes, mot_de_passe: str) -> bytes:
    sel, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    cle, cle_mac = _cles(mot_de_passe, sel)
    corps = chacha20(cle, nonce, donnees)
    entete = MAGIE + sel + nonce
    return entete + corps + hmac.new(cle_mac, entete + corps, hashlib.sha256).digest()


def dechiffrer(paquet: bytes, mot_de_passe: str) -> bytes:
    if not paquet.startswith(MAGIE) or len(paquet) < len(MAGIE) + 28 + 32:
        raise MotDePasseFaux("ce n'est pas une sauvegarde de l'Assistant local")
    sel = paquet[len(MAGIE):len(MAGIE) + 16]
    nonce = paquet[len(MAGIE) + 16:len(MAGIE) + 28]
    corps, signature = paquet[len(MAGIE) + 28:-32], paquet[-32:]
    cle, cle_mac = _cles(mot_de_passe, sel)
    attendu = hmac.new(cle_mac, paquet[:-32], hashlib.sha256).digest()
    if not hmac.compare_digest(signature, attendu):
        raise MotDePasseFaux("mot de passe faux, ou archive abimee ou modifiee")
    return chacha20(cle, nonce, corps)


# --- Sauvegarder, restaurer ----------------------------------------------------------

def _fichiers_donnees() -> list[Path]:
    base = config.DATA_DIR
    if not base.is_dir():
        return []
    return [f for f in base.rglob("*")
            if f.is_file() and not (set(f.relative_to(base).parts) & EXCLUS)]


def sauvegarder(destination: str, mot_de_passe: str) -> str:
    if len(mot_de_passe or "") < 8:
        return "Mot de passe trop court : 8 caracteres au moins."
    tampon = io.BytesIO()
    nombre = 0
    with zipfile.ZipFile(tampon, "w", zipfile.ZIP_DEFLATED) as archive:
        for f in _fichiers_donnees():
            archive.write(f, "donnees/" + f.relative_to(config.DATA_DIR).as_posix())
            nombre += 1
        maitre = licence.fichier_maitre()
        if maitre.is_file():
            archive.write(maitre, NOM_MAITRE)
        archive.writestr("sauvegarde.txt",
                         f"Assistant local, sauvegarde du {time.strftime('%d/%m/%Y %H:%M')}\n")
    dossier = Path(destination)
    dossier.mkdir(parents=True, exist_ok=True)
    fichier = dossier / f"AssistantLocal_sauvegarde_{time.strftime('%Y%m%d_%H%M')}.alsauv"
    fichier.write_bytes(chiffrer(tampon.getvalue(), mot_de_passe))
    avec = "avec" if licence.fichier_maitre().is_file() else "sans"
    return (f"Sauvegarde ecrite : {fichier} ({fichier.stat().st_size / 1e6:.1f} Mo, "
            f"{nombre} fichiers de donnees, {avec} la cle maitre). Garde le mot de "
            "passe : sans lui, l'archive ne s'ouvre pas.")


def restaurer(fichier: str, mot_de_passe: str) -> str:
    try:
        contenu = dechiffrer(Path(fichier).read_bytes(), mot_de_passe)
    except OSError as exc:
        return f"Archive illisible : {exc}"
    except MotDePasseFaux as exc:
        return f"Restauration refusee : {exc}. Rien n'a ete modifie."
    base = config.DATA_DIR
    if base.exists():
        # Ce qui etait la avant reste recuperable.
        copie = base.with_name(base.name + f"_avant_restauration_{time.strftime('%Y%m%d_%H%M%S')}")
        shutil.copytree(base, copie, ignore=shutil.ignore_patterns(*EXCLUS))
    restaures, maitre = 0, False
    with zipfile.ZipFile(io.BytesIO(contenu)) as archive:
        for nom in archive.namelist():
            if nom.startswith("donnees/") and not nom.endswith("/"):
                cible = (base / nom[len("donnees/"):]).resolve()
                if base.resolve() not in cible.parents:
                    continue
                cible.parent.mkdir(parents=True, exist_ok=True)
                cible.write_bytes(archive.read(nom))
                restaures += 1
            elif nom == NOM_MAITRE and not licence.fichier_maitre().exists():
                licence.dossier_maitre().mkdir(parents=True, exist_ok=True)
                licence.fichier_maitre().write_bytes(archive.read(nom))
                maitre = True
    message = f"{restaures} fichiers restaures."
    if maitre:
        message += f" Cle maitre remise dans {licence.fichier_maitre()}."
    message += " " + recreer_cle_si_besoin()
    return message.strip()


def recreer_cle_si_besoin() -> str:
    """Nouveau PC : l'ancienne cle ne vaut plus, la cle maitre en refait une."""
    from assistant import settings

    if licence.examiner(licence.cle_enregistree())[0]:
        return "Cle d'acces Dev valide."
    graine = licence.graine_maitre()
    if graine is None or licence.publique_depuis_graine(graine).hex() != licence.CLE_PUBLIQUE:
        return "Cle d'acces Dev a refaire (pas de cle maitre sur ce PC)."
    nom = os.environ.get("USERNAME", "proprietaire")
    settings.set(licence.CLE_REGLAGE,
                 licence.fabriquer_cle(graine, nom, licence.identifiant_pc()))
    return "Nouvelle cle d'acces Dev fabriquee pour ce PC."
