"""Client du serveur OpenRGB : le seul canal qui marche vraiment.

Pourquoi pas la ligne de commande. OpenRGB.exe est une application Qt
graphique : sa sortie console n'arrive dans aucun tuyau. Mesure sur cette
machine, avec et sans droits administrateur, avec et sans console attachee --
zero caractere a chaque fois, en 5,4 secondes. `--list-devices` est donc
inutilisable depuis un programme.

Le serveur, lui, est l'interface prevue pour ca : un port TCP et un protocole
documente, la meme voie qu'utilisent les greffons officiels.

Rien de proprietaire ici : le protocole est celui d'OpenRGB, pas celui d'un
fabricant. Ce module ne connait ni Gigabyte, ni Razer, ni Corsair -- il
demande au serveur ce qui existe, et le serveur repond avec ce que la machine
porte reellement.
"""
from __future__ import annotations

import socket
import struct
from dataclasses import dataclass, field

HOTE = "127.0.0.1"
PORT = 6742
MAGIQUE = b"ORGB"

# Types de paquets du protocole OpenRGB.
DEMANDE_NOMBRE = 0
DEMANDE_DONNEES = 1
DEMANDE_VERSION = 40
NOM_CLIENT = 50
CHANGER_MODE = 1101

# Version du protocole qu'on sait parler. Le serveur repond avec la sienne, et
# on prend la plus basse des deux : c'est ainsi qu'un client reste compatible
# avec un serveur plus recent.
VERSION_MAX = 5

# Familles de peripheriques, telles que le protocole les numerote. Le
# tableau vient d'OpenRGB, pas d'une supposition : une premiere version
# decalee d'un cran annoncait une carte graphique comme "memoire" et une
# souris comme "boitier".
FAMILLES = {
    0: "carte mere", 1: "memoire", 2: "carte graphique", 3: "ventirad",
    4: "bandeau", 5: "clavier", 6: "souris", 7: "tapis", 8: "casque",
    9: "support de casque", 10: "manette", 11: "lampe", 12: "haut-parleur",
    13: "virtuel", 14: "disque", 15: "boitier", 16: "microphone",
    17: "accessoire", 18: "pave numerique", 19: "inconnu",
}


@dataclass
class Peripherique:
    index: int
    nom: str
    genre: str = ""
    detail: str = ""
    modes: list[str] = field(default_factory=list)
    mode_actif: str = ""
    # Octets bruts de chaque mode, tels que le serveur les a envoyes.
    #
    # On les renvoie tels quels pour changer de mode, au lieu de reconstruire
    # la structure champ par champ. Le format a evolue entre les versions du
    # protocole -- la luminosite est apparue en version 3 -- et un client qui
    # reserialise se casse a chaque evolution. Renvoyer l'original ne se casse
    # jamais.
    modes_bruts: list[bytes] = field(default_factory=list)


class Erreur(Exception):
    """Le serveur est injoignable ou a repondu quelque chose d'inattendu."""


def _envoyer(sock, appareil: int, type_paquet: int, corps: bytes = b"") -> None:
    sock.sendall(MAGIQUE + struct.pack("<III", appareil, type_paquet,
                                       len(corps)) + corps)


def _recevoir(sock) -> tuple[int, int, bytes]:
    entete = b""
    while len(entete) < 16:
        morceau = sock.recv(16 - len(entete))
        if not morceau:
            raise Erreur("le serveur a coupe la connexion")
        entete += morceau
    if entete[:4] != MAGIQUE:
        raise Erreur(f"reponse inattendue : {entete[:4]!r}")

    appareil, type_paquet, taille = struct.unpack("<III", entete[4:])
    corps = b""
    while len(corps) < taille:
        morceau = sock.recv(taille - len(corps))
        if not morceau:
            break
        corps += morceau
    return appareil, type_paquet, corps


def _lire_texte(donnees: bytes, position: int) -> tuple[str, int]:
    """Chaine prefixee de sa longueur sur 16 bits, terminee par un zero."""
    (longueur,) = struct.unpack_from("<H", donnees, position)
    position += 2
    brut = donnees[position:position + longueur]
    return brut.split(b"\0")[0].decode("utf-8", "replace"), position + longueur


def _taille_mode(donnees: bytes, position: int, version: int) -> int:
    """Longueur en octets d'une entree de mode, a partir de son debut."""
    debut = position
    _nom, position = _lire_texte(donnees, position)
    position += 4 * 2            # value, flags
    position += 4 * 2            # speed_min, speed_max
    if version >= 3:
        position += 4 * 2        # brightness_min, brightness_max
    position += 4 * 2            # colors_min, colors_max
    position += 4                # speed
    if version >= 3:
        position += 4            # brightness
    position += 4 * 2            # direction, color_mode
    (nb_couleurs,) = struct.unpack_from("<H", donnees, position)
    position += 2 + 4 * nb_couleurs
    return position - debut


def _decoder(donnees: bytes, index: int, version: int) -> Peripherique:
    position = 4                                   # taille totale, connue
    (famille,) = struct.unpack_from("<i", donnees, position)
    position += 4

    nom, position = _lire_texte(donnees, position)
    # Le fabricant est apparu en version 1. L'oublier decale TOUT ce qui suit,
    # et les modes ressortent en charabia plutot qu'en erreur franche.
    if version >= 1:
        _fabricant, position = _lire_texte(donnees, position)
    detail, position = _lire_texte(donnees, position)
    _version, position = _lire_texte(donnees, position)
    _serie, position = _lire_texte(donnees, position)
    _lieu, position = _lire_texte(donnees, position)

    (nb_modes,) = struct.unpack_from("<H", donnees, position)
    position += 2
    (actif,) = struct.unpack_from("<i", donnees, position)
    position += 4

    modes, bruts = [], []
    for _ in range(nb_modes):
        taille = _taille_mode(donnees, position, version)
        bruts.append(donnees[position:position + taille])
        nom_mode, _ = _lire_texte(donnees, position)
        modes.append(nom_mode)
        position += taille

    return Peripherique(
        index=index, nom=nom, genre=FAMILLES.get(famille, "inconnu"),
        detail=detail, modes=modes, modes_bruts=bruts,
        mode_actif=modes[actif] if 0 <= actif < len(modes) else "",
    )


class Connexion:
    """Une session avec le serveur OpenRGB, refermee proprement."""

    def __init__(self, timeout: float = 10.0):
        try:
            self.sock = socket.create_connection((HOTE, PORT), timeout=timeout)
        except OSError as exc:
            raise Erreur(f"serveur OpenRGB injoignable : {exc}") from exc
        self.sock.settimeout(timeout)
        self.version = VERSION_MAX

        _envoyer(self.sock, 0, NOM_CLIENT, b"AssistantLocal\0")
        _envoyer(self.sock, 0, DEMANDE_VERSION, struct.pack("<I", VERSION_MAX))
        try:
            _a, _t, corps = _recevoir(self.sock)
            (serveur,) = struct.unpack("<I", corps[:4])
            self.version = min(serveur, VERSION_MAX)
        except (Erreur, struct.error):
            self.version = 0        # serveur ancien : format d'origine

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.fermer()

    def fermer(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def peripheriques(self) -> list[Peripherique]:
        _envoyer(self.sock, 0, DEMANDE_NOMBRE)
        _a, _t, corps = _recevoir(self.sock)
        (nombre,) = struct.unpack("<I", corps[:4])

        trouves = []
        for index in range(nombre):
            _envoyer(self.sock, index, DEMANDE_DONNEES,
                     struct.pack("<I", self.version))
            _a, _t, donnees = _recevoir(self.sock)
            try:
                trouves.append(_decoder(donnees, index, self.version))
            except (struct.error, IndexError) as exc:
                raise Erreur(
                    f"peripherique {index} illisible : {type(exc).__name__}"
                ) from exc
        return trouves

    def changer_mode(self, peripherique: Peripherique, index_mode: int) -> None:
        """Active un mode en renvoyant ses octets d'origine."""
        brut = peripherique.modes_bruts[index_mode]
        corps = struct.pack("<II", 8 + len(brut), index_mode) + brut
        _envoyer(self.sock, peripherique.index, CHANGER_MODE, corps)
