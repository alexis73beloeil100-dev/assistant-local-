"""Cle d'acces au mode Dev : signee par le proprietaire, verifiee ici.

Le principe tient en une phrase : une cle n'est valable que si elle porte une
signature Ed25519 faite avec la cle MAITRE, que seul le proprietaire possede.
L'application ne contient que la partie PUBLIQUE : elle sait verifier une
signature, jamais en fabriquer une. Le code a beau etre public, personne ne
peut s'inventer une cle.

Une cle peut etre liee a un PC (son identifiant, tire du MachineGuid de
Windows) : copiee sur une autre machine, elle ne vaut rien. Elle peut aussi
porter une date de fin, pour les abonnements a venir.

La cle maitre se cree UNE fois, sur le PC du proprietaire, depuis la
fenetre de cle (bouton visible tant qu'aucune cle publique n'est inscrite
ci-dessous). Elle est ecrite dans ses Documents, hors du depot, et ne doit
jamais en sortir.

Ed25519 est ecrit ici en Python pur (RFC 8032), sans bibliotheque : une
verification par demarrage, la lenteur relative n'a aucune importance.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from datetime import date
from pathlib import Path

# La cle PUBLIQUE du proprietaire, en hexadecimal. Vide tant que la cle
# maitre n'a pas ete creee : le mode Dev reste alors ferme pour tout le monde.
CLE_PUBLIQUE = ""

PREFIXE = "ALDEV-"
ENTETE_SECRET = "ALDEV-SECRET-NE-JAMAIS-PARTAGER"
CLE_REGLAGE = "cle_dev"

# --- Ed25519 (RFC 8032, section 5.1) -----------------------------------------

_P = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_I = pow(2, (_P - 1) // 4, _P)


def _xrecover(y: int) -> int:
    xx = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P)
    x = pow(xx, (_P + 3) // 8, _P)
    if (x * x - xx) % _P:
        x = x * _I % _P
    if x % 2:
        x = _P - x
    return x


_BY = 4 * pow(5, _P - 2, _P) % _P
_B = (_xrecover(_BY), _BY, 1, _xrecover(_BY) * _BY % _P)


def _add(a, b):
    x1, y1, z1, t1 = a
    x2, y2, z2, t2 = b
    aa = (y1 - x1) * (y2 - x2) % _P
    bb = (y1 + x1) * (y2 + x2) % _P
    cc = 2 * t1 * t2 * _D % _P
    dd = 2 * z1 * z2 % _P
    e, f, g, h = bb - aa, dd - cc, dd + cc, bb + aa
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _mul(s: int, point):
    resultat = (0, 1, 1, 0)
    while s:
        if s & 1:
            resultat = _add(resultat, point)
        point = _add(point, point)
        s >>= 1
    return resultat


def _encoder(point) -> bytes:
    x, y, z, _t = point
    zi = pow(z, _P - 2, _P)
    x, y = x * zi % _P, y * zi % _P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _decoder(octets: bytes):
    if len(octets) != 32:
        raise ValueError("point de 32 octets attendu")
    y = int.from_bytes(octets, "little")
    signe = y >> 255
    y &= (1 << 255) - 1
    if y >= _P:
        raise ValueError("point hors du corps")
    x = _xrecover(y)
    if (x * x * _D * y * y - y * y + x * x + 1) % _P:
        raise ValueError("point hors de la courbe")
    if (x & 1) != signe:
        x = _P - x
    return (x, y, 1, x * y % _P)


def _h(*morceaux: bytes) -> int:
    return int.from_bytes(hashlib.sha512(b"".join(morceaux)).digest(), "little")


def _scalaire(graine: bytes) -> tuple[int, bytes]:
    condense = hashlib.sha512(graine).digest()
    a = int.from_bytes(condense[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, condense[32:]


def publique_depuis_graine(graine: bytes) -> bytes:
    a, _prefixe = _scalaire(graine)
    return _encoder(_mul(a, _B))


def signer(graine: bytes, message: bytes) -> bytes:
    a, prefixe = _scalaire(graine)
    publique = _encoder(_mul(a, _B))
    r = _h(prefixe, message) % _L
    rr = _encoder(_mul(r, _B))
    s = (r + _h(rr, publique, message) * a) % _L
    return rr + s.to_bytes(32, "little")


def verifier_signature(publique: bytes, message: bytes, signature: bytes) -> bool:
    if len(signature) != 64 or len(publique) != 32:
        return False
    try:
        a = _decoder(publique)
        r = _decoder(signature[:32])
    except ValueError:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _L:
        return False
    h = _h(signature[:32], publique, message) % _L
    return _encoder(_mul(s, _B)) == _encoder(_add(r, _mul(h, a)))


# --- Identifiant du PC -----------------------------------------------------------

def identifiant_pc() -> str:
    """16 caracteres tires du MachineGuid de Windows ; "" hors Windows.

    Le MachineGuid est cree a l'installation de Windows et ne change pas
    d'une session a l'autre. On n'en garde qu'une empreinte : la cle n'a pas
    a transporter l'identifiant brut de la machine.
    """
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\Cryptography") as cle:
            guid, _type = winreg.QueryValueEx(cle, "MachineGuid")
    except (ImportError, OSError):
        return ""
    return hashlib.sha256(f"assistant-local:{guid}".encode()).hexdigest()[:16]


# --- Cles d'acces -------------------------------------------------------------------

def _b64(octets: bytes) -> str:
    return base64.urlsafe_b64encode(octets).decode().rstrip("=")


def _deb64(texte: str) -> bytes:
    return base64.urlsafe_b64decode(texte + "=" * (-len(texte) % 4))


def fabriquer_cle(graine: bytes, nom: str, pc: str = "", fin: str = "") -> str:
    """Une cle d'acces signee. `fin` au format AAAA-MM-JJ, vide = sans fin."""
    if fin:
        date.fromisoformat(fin)
    contenu = json.dumps({"v": 1, "n": nom, "pc": pc, "fin": fin},
                         ensure_ascii=False, separators=(",", ":")).encode()
    return f"{PREFIXE}{_b64(contenu)}.{_b64(signer(graine, contenu))}"


def examiner(cle: str, publique_hex: str | None = None,
             pc: str | None = None, aujourd_hui: date | None = None
             ) -> tuple[bool, str]:
    """(valide, explication). Ne leve jamais : une cle invalide se dit."""
    publique_hex = CLE_PUBLIQUE if publique_hex is None else publique_hex
    if not publique_hex:
        return False, ("le mode Dev n'est pas encore activé : la clé maître "
                       "du propriétaire n'est pas installée.")
    cle = (cle or "").strip()
    if not cle.startswith(PREFIXE) or "." not in cle:
        return False, "ce n'est pas une clé d'accès développeur."
    corps, _point, signature = cle[len(PREFIXE):].partition(".")
    try:
        contenu = _deb64(corps)
        sig = _deb64(signature)
        publique = bytes.fromhex(publique_hex)
    except ValueError:
        return False, "clé illisible."
    if not verifier_signature(publique, contenu, sig):
        return False, "signature invalide : cette clé n'a pas été délivrée."
    try:
        donnees = json.loads(contenu)
    except ValueError:
        return False, "clé illisible."
    attendu = identifiant_pc() if pc is None else pc
    if donnees.get("pc") and donnees["pc"] != attendu:
        return False, "cette clé appartient à un autre PC."
    fin = donnees.get("fin") or ""
    if fin and (aujourd_hui or date.today()) > date.fromisoformat(fin):
        return False, f"clé expirée le {date.fromisoformat(fin):%d/%m/%Y}."
    qui = donnees.get("n") or "?"
    return True, f"clé de {qui}" + (f", valable jusqu'au {fin}" if fin else ", sans fin")


def cle_enregistree() -> str:
    from assistant import settings

    return str(settings.get(CLE_REGLAGE, "") or "")


def dev_autorise() -> bool:
    return examiner(cle_enregistree())[0]


def enregistrer_cle(cle: str) -> tuple[bool, str]:
    from assistant import settings

    valide, raison = examiner(cle)
    if valide:
        settings.set(CLE_REGLAGE, cle.strip())
    return valide, raison


# --- La cle maitre, sur le PC du proprietaire ---------------------------------------

def dossier_maitre() -> Path:
    base = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Documents"
    return base / "Assistant local - cle maitre"


def fichier_maitre() -> Path:
    return dossier_maitre() / "cle_maitre_SECRETE.txt"


def graine_maitre() -> bytes | None:
    """La graine de la cle maitre, si elle est sur CE PC."""
    try:
        lignes = fichier_maitre().read_text(encoding="utf-8").split()
    except OSError:
        return None
    if len(lignes) < 2 or lignes[0] != ENTETE_SECRET:
        return None
    try:
        graine = bytes.fromhex(lignes[1])
    except ValueError:
        return None
    return graine if len(graine) == 32 else None


def creer_cle_maitre() -> str:
    """Cree la cle maitre et rend la cle PUBLIQUE a inscrire dans le code.

    Refuse d'ecraser une cle maitre existante : la perdre, c'est ne plus
    pouvoir delivrer une seule cle valable pour cette version.
    """
    if fichier_maitre().exists():
        raise FileExistsError(f"une cle maitre existe deja : {fichier_maitre()}")
    graine = secrets.token_bytes(32)
    publique = publique_depuis_graine(graine).hex()
    dossier_maitre().mkdir(parents=True, exist_ok=True)
    fichier_maitre().write_text(
        f"{ENTETE_SECRET}\n{graine.hex()}\n\n"
        "Cette cle fabrique les cles d'acces au mode Dev de l'Assistant local.\n"
        "Ne la donne a personne, ne la mets jamais sur GitHub.\n"
        "Fais-en une copie sur une cle USB : perdue, elle ne se recree pas.\n"
        f"\nCle publique correspondante : {publique}\n",
        encoding="utf-8")
    (dossier_maitre() / "cle_publique.txt").write_text(publique + "\n",
                                                      encoding="utf-8")
    return publique
