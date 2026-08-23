"""Client du serveur OpenRGB, ecrit pour ce projet.

Pourquoi ce fichier existe
--------------------------

L'assistant parlait a OpenRGB par la bibliotheque `openrgb-python`. Elle
marche tres bien, mais elle est sous GPLv3 : l'importer, c'est lier, et le
programme distribue devait alors se transmettre sous GPLv3 avec son code
source. Ici, on parle au serveur directement.

C'est le meme dialogue qu'avant, au meme endroit : OpenRGB tourne dans son
propre processus et ecoute en TCP sur le port 6742. On lui envoie les memes
messages ; personne n'est lie a personne.

Le protocole, en trois phrases
------------------------------

Chaque message commence par seize octets : les quatre lettres ORGB, l'index
du peripherique concerne, l'identifiant du message, puis la taille de ce qui
suit. Tous les nombres sont en petit-boutiste.

Les chaines de caracteres sont precedees de leur longueur sur deux octets,
et comptent le zero final. C'est le piege classique du format : oublier ce
zero decale toute la lecture qui suit, et le decalage ne se voit qu'a la
premiere valeur absurde, bien plus loin.

Le format de la description d'un peripherique a change avec les versions du
protocole. On negocie la version au debut et on ne lit un champ que si la
version qui l'a introduit est atteinte.

Le choix qui evite le plus d'ennuis
-----------------------------------

Changer de mode demande de RENVOYER la description complete du mode. Plutot
que de la reconstruire champ par champ -- ou chaque erreur d'ordre ou de
taille donnerait un materiel qui refuse de changer, sans message --, on garde
les octets bruts recus a la lecture et on les renvoie tels quels. Ce qui
revient au serveur est exactement ce qu'il a envoye.
"""
from __future__ import annotations

import socket
import struct
from dataclasses import dataclass, field

HOTE = "127.0.0.1"
PORT = 6742

# Les quatre lettres qui ouvrent chaque message.
MAGIE = b"ORGB"
TAILLE_ENTETE = 16

# La version du protocole que ce client sait lire. On prend le minimum entre
# celle-ci et celle du serveur : un serveur plus recent envoie alors la forme
# ancienne, qu'on sait analyser.
VERSION_CLIENT = 4

# Identifiants des messages, tels que les nomme OpenRGB.
NB_CONTROLEURS = 0
DONNEES_CONTROLEUR = 1
VERSION_PROTOCOLE = 40
NOM_DU_CLIENT = 50
MAJ_LEDS = 1050
MAJ_MODE = 1101


class ErreurOpenRGB(RuntimeError):
    """Le serveur est injoignable, ou repond autre chose que prevu."""


@dataclass
class Couleur:
    """Une couleur, en composantes de 0 a 255.

    Remplace le RGBColor du SDK. Meme role, meme ordre des arguments : les
    appels existants n'ont pas eu a changer.
    """
    rouge: int = 0
    vert: int = 0
    bleu: int = 0

    def octets(self) -> bytes:
        """Les quatre octets attendus sur le fil : R, V, B, et un de bourrage."""
        return bytes((self.rouge & 0xFF, self.vert & 0xFF, self.bleu & 0xFF, 0))

    def __iter__(self):
        return iter((self.rouge, self.vert, self.bleu))


@dataclass
class Mode:
    """Un mode d'eclairage, tel que le materiel le declare."""
    index: int
    nom: str
    drapeaux: int
    vitesse_min: int | None
    vitesse_max: int | None
    vitesse: int | None
    luminosite_min: int | None
    luminosite_max: int | None
    luminosite: int | None
    mode_couleur: int
    couleurs_max: int = 1
    couleurs: list[Couleur] = field(default_factory=list)
    # Les octets exacts recus pour ce mode, renvoyes tels quels au changement.
    brut: bytes = b""
    # Ou vivent la vitesse et la luminosite DANS ces octets. Regler l'un des
    # deux avant d'envoyer le mode oblige a corriger les octets aussi : sans
    # ca on renverrait l'ancienne valeur, et le reglage n'aurait aucun effet
    # visible -- le materiel obeirait, simplement pas a ce qu'on croit lui
    # avoir demande.
    decalage_vitesse: int = -1
    decalage_luminosite: int = -1

    def _patcher(self, decalage: int, valeur: int) -> None:
        octets = bytearray(self.brut)
        octets[decalage:decalage + 4] = struct.pack("<I", int(valeur) & 0xFFFFFFFF)
        self.brut = bytes(octets)

    def regler_vitesse(self, valeur: int) -> None:
        if self.decalage_vitesse < 0:
            raise ErreurOpenRGB(f"le mode {self.nom} n'a pas de vitesse")
        self.vitesse = int(valeur)
        self._patcher(self.decalage_vitesse, valeur)

    def regler_luminosite(self, valeur: int) -> None:
        if self.decalage_luminosite < 0:
            raise ErreurOpenRGB(f"le mode {self.nom} n'a pas de luminosite")
        self.luminosite = int(valeur)
        self._patcher(self.decalage_luminosite, valeur)


@dataclass
class Materiel:
    """Un peripherique pilotable et ce qu'il sait faire."""
    index: int
    nom: str
    genre: str
    modes: list[Mode]
    mode_actif: int
    nb_leds: int
    couleurs: list[Couleur] = field(default_factory=list)


# Les genres de peripheriques, dans l'ordre ou OpenRGB les numerote. Le SDK
# exposait un nom ; l'assistant s'en sert pour dire "clavier" plutot que "3".
GENRES = [
    "motherboard", "dram", "gpu", "cooler", "ledstrip", "keyboard", "mouse",
    "mousemat", "headset", "headset_stand", "gamepad", "light", "speaker",
    "virtual", "storage", "case", "microphone", "accessory", "keypad",
    "unknown",
]

# Drapeaux de capacite d'un mode, tels que les definit OpenRGB. Les valeurs
# ont ete relevees sur l'enumeration du SDK, pas ecrites de memoire : la
# luminosite est au bit 4, et le bit 7 est la couleur aleatoire. Se tromper
# ici ne plante rien -- ca rend juste un curseur de luminosite la ou il n'y
# en a pas, et ca en cache un la ou il en faudrait un.
A_VITESSE = 1 << 0
A_LUMINOSITE = 1 << 4
A_COULEUR_PAR_LED = 1 << 5
A_COULEUR_DE_MODE = 1 << 6

# Facons dont un mode traite la couleur.
COULEUR_PAR_LED = 1
COULEUR_DE_MODE = 2


class _Lecteur:
    """Avance dans un bloc d'octets en gardant sa position.

    Ecrit a la main plutot qu'avec un flux memoire : il faut pouvoir relever
    la position avant et apres un morceau pour en garder les octets bruts.
    """

    def __init__(self, donnees: bytes):
        self.donnees = donnees
        self.i = 0

    def _prendre(self, combien: int) -> bytes:
        if self.i + combien > len(self.donnees):
            raise ErreurOpenRGB(
                f"description tronquee : {combien} octets demandes a la "
                f"position {self.i}, il n'en reste que "
                f"{len(self.donnees) - self.i}")
        morceau = self.donnees[self.i:self.i + combien]
        self.i += combien
        return morceau

    def u8(self) -> int:
        return self._prendre(1)[0]

    def u16(self) -> int:
        return struct.unpack("<H", self._prendre(2))[0]

    def u32(self) -> int:
        return struct.unpack("<I", self._prendre(4))[0]

    def i32(self) -> int:
        return struct.unpack("<i", self._prendre(4))[0]

    def texte(self) -> str:
        """Longueur sur deux octets, zero final compris."""
        taille = self.u16()
        brut = self._prendre(taille)
        return brut.split(b"\x00", 1)[0].decode("utf-8", errors="replace")

    def couleur(self) -> Couleur:
        rouge, vert, bleu, _bourrage = self._prendre(4)
        return Couleur(rouge, vert, bleu)


class Client:
    """Une session avec le serveur OpenRGB.

    S'utilise comme un gestionnaire de contexte : la fermeture est garantie
    meme si la lecture echoue en cours de route.
    """

    def __init__(self, nom: str = "AssistantLocal", delai: float = 5.0):
        self.nom = nom
        self.version = VERSION_CLIENT
        try:
            self.prise = socket.create_connection((HOTE, PORT), timeout=delai)
        except OSError as souci:
            raise ErreurOpenRGB(
                f"serveur OpenRGB injoignable sur {HOTE}:{PORT} ({souci})"
            ) from souci
        self._negocier_version()
        self._annoncer_le_nom()

    # ------------------------------------------------------------ transport

    def _envoyer(self, identifiant: int, donnees: bytes = b"",
                 peripherique: int = 0) -> None:
        entete = struct.pack("<4sIII", MAGIE, peripherique, identifiant,
                             len(donnees))
        self.prise.sendall(entete + donnees)

    def _recevoir_exactement(self, combien: int) -> bytes:
        morceaux = []
        recus = 0
        while recus < combien:
            bout = self.prise.recv(combien - recus)
            if not bout:
                raise ErreurOpenRGB(
                    "le serveur OpenRGB a ferme la connexion en cours de "
                    "reponse")
            morceaux.append(bout)
            recus += len(bout)
        return b"".join(morceaux)

    def _lire_reponse(self, attendu: int) -> bytes:
        entete = self._recevoir_exactement(TAILLE_ENTETE)
        magie, _peripherique, identifiant, taille = struct.unpack(
            "<4sIII", entete)
        if magie != MAGIE:
            raise ErreurOpenRGB(
                f"reponse inattendue : en-tete {magie!r} au lieu de {MAGIE!r}")
        if identifiant != attendu:
            raise ErreurOpenRGB(
                f"reponse inattendue : message {identifiant} au lieu de "
                f"{attendu}")
        return self._recevoir_exactement(taille) if taille else b""

    # ------------------------------------------------------------- ouverture

    def _negocier_version(self) -> None:
        """On garde la plus basse des deux versions.

        Un serveur ancien ne repond pas du tout a cette demande : c'est
        normal, et ca veut dire version 0. On ne traite donc pas l'absence de
        reponse comme une panne.
        """
        self._envoyer(VERSION_PROTOCOLE, struct.pack("<I", VERSION_CLIENT))
        ancien = self.prise.gettimeout()
        self.prise.settimeout(2.0)
        try:
            donnees = self._lire_reponse(VERSION_PROTOCOLE)
            serveur = struct.unpack("<I", donnees[:4])[0]
            self.version = min(VERSION_CLIENT, serveur)
        except (OSError, ErreurOpenRGB):
            self.version = 0
        finally:
            self.prise.settimeout(ancien)

    def _annoncer_le_nom(self) -> None:
        """OpenRGB affiche ce nom dans sa liste de clients connectes."""
        self._envoyer(NOM_DU_CLIENT, self.nom.encode("utf-8") + b"\x00")

    # -------------------------------------------------------------- lecture

    def nombre(self) -> int:
        self._envoyer(NB_CONTROLEURS)
        return struct.unpack("<I", self._lire_reponse(NB_CONTROLEURS)[:4])[0]

    @property
    def peripheriques(self) -> list[Materiel]:
        return [self.peripherique(i) for i in range(self.nombre())]

    def peripherique(self, index: int) -> Materiel:
        self._envoyer(DONNEES_CONTROLEUR, struct.pack("<I", self.version),
                      peripherique=index)
        return self._lire_peripherique(
            self._lire_reponse(DONNEES_CONTROLEUR), index)

    def _lire_peripherique(self, donnees: bytes, index: int) -> Materiel:
        l = _Lecteur(donnees)
        l.u32()                             # taille totale, deja connue
        genre = l.i32()
        nom = l.texte()
        if self.version >= 1:
            l.texte()                       # fabricant
        l.texte()                           # description
        l.texte()                           # version
        l.texte()                           # numero de serie
        l.texte()                           # emplacement

        nb_modes = l.u16()
        mode_actif = l.i32()
        modes = [self._lire_mode(l, i) for i in range(nb_modes)]

        nb_leds = self._sauter_les_zones(l)

        nb_couleurs = l.u16()
        couleurs = [l.couleur() for _ in range(nb_couleurs)]

        return Materiel(
            index=index,
            nom=nom,
            genre=GENRES[genre] if 0 <= genre < len(GENRES) else "unknown",
            modes=modes,
            mode_actif=mode_actif,
            nb_leds=nb_leds,
            couleurs=couleurs,
        )

    def _lire_mode(self, l: _Lecteur, index: int) -> Mode:
        depart = l.i
        nom = l.texte()
        l.i32()                             # valeur propre au materiel
        drapeaux = l.u32()
        vitesse_min = l.u32()
        vitesse_max = l.u32()
        luminosite_min = l.u32() if self.version >= 3 else None
        luminosite_max = l.u32() if self.version >= 3 else None
        l.u32()                             # nombre minimal de couleurs
        couleurs_max = l.u32()
        decalage_vitesse = l.i - depart
        vitesse = l.u32()
        decalage_luminosite = (l.i - depart) if self.version >= 3 else -1
        luminosite = l.u32() if self.version >= 3 else None
        l.u32()                             # direction
        mode_couleur = l.u32()
        nb_couleurs = l.u16()
        couleurs = [l.couleur() for _ in range(nb_couleurs)]

        # Un materiel remplit ces champs meme quand le mode ne s'en sert pas :
        # on lit alors des zeros qui ressemblent a une vraie valeur basse. On
        # rend None, comme le faisait le SDK, pour que l'appelant ne puisse pas
        # afficher un curseur de vitesse sur un mode qui n'en a pas.
        a_vitesse = bool(drapeaux & A_VITESSE)
        a_luminosite = bool(drapeaux & A_LUMINOSITE)

        return Mode(
            index=index,
            nom=nom,
            drapeaux=drapeaux,
            vitesse_min=vitesse_min if a_vitesse else None,
            vitesse_max=vitesse_max if a_vitesse else None,
            vitesse=vitesse if a_vitesse else None,
            luminosite_min=luminosite_min if a_luminosite else None,
            luminosite_max=luminosite_max if a_luminosite else None,
            luminosite=luminosite if a_luminosite else None,
            mode_couleur=mode_couleur,
            couleurs_max=couleurs_max,
            couleurs=couleurs,
            brut=l.donnees[depart:l.i],
            decalage_vitesse=decalage_vitesse if a_vitesse else -1,
            decalage_luminosite=decalage_luminosite if a_luminosite else -1,
        )

    def _sauter_les_zones(self, l: _Lecteur) -> int:
        """Traverse zones et LEDs, et rend le nombre de LEDs.

        L'assistant ne se sert pas des zones, mais il faut les traverser
        exactement pour arriver aux couleurs qui les suivent. Une matrice
        annoncee et non lue, et tout ce qui vient apres est du bruit.
        """
        for _ in range(l.u16()):
            l.texte()                       # nom de la zone
            l.i32()                         # type
            l.u32()                         # LEDs au minimum
            l.u32()                         # LEDs au maximum
            l.u32()                         # LEDs presentes
            taille_matrice = l.u16()
            if taille_matrice:
                l._prendre(taille_matrice)  # disposition en grille
            if self.version >= 4:
                for _segment in range(l.u16()):
                    l.texte()
                    l.i32()
                    l.u32()
                    l.u32()

        nb_leds = l.u16()
        for _ in range(nb_leds):
            l.texte()                       # nom de la LED
            l.u32()                         # valeur propre au materiel
        return nb_leds

    # -------------------------------------------------------------- ecriture

    def changer_de_mode(self, peripherique: int, mode: Mode) -> None:
        """Renvoie la description du mode telle qu'elle a ete recue."""
        corps = struct.pack("<I", mode.index) + mode.brut
        donnees = struct.pack("<I", len(corps) + 4) + corps
        self._envoyer(MAJ_MODE, donnees, peripherique=peripherique)

    def ecrire_les_couleurs(self, peripherique: int,
                            couleurs: list[Couleur]) -> None:
        corps = struct.pack("<H", len(couleurs))
        corps += b"".join(c.octets() for c in couleurs)
        donnees = struct.pack("<I", len(corps) + 4) + corps
        self._envoyer(MAJ_LEDS, donnees, peripherique=peripherique)

    # ------------------------------------------------------------ fermeture

    def fermer(self) -> None:
        try:
            self.prise.close()
        except OSError:
            pass

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *_oubli) -> None:
        self.fermer()
