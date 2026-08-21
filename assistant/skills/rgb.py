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
    Path(os.environ.get("LOCALAPPDATA", "")) / "OpenRGB" / "OpenRGB.exe",
    Path(os.environ.get("APPDATA", "")) / "OpenRGB" / "OpenRGB.exe",
    Path.home() / "OpenRGB" / "OpenRGB.exe",
    Path.home() / "Downloads" / "OpenRGB" / "OpenRGB.exe",
    Path("C:/OpenRGB/OpenRGB.exe"),
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


# Outil EMBARQUE avec l'application. C'est l'emplacement prioritaire.
#
# L'utilisateur ne veut rien installer sur sa machine : ni entree dans
# Program Files, ni cle de registre, ni desinstalleur de plus. L'outil vit
# donc DANS l'application, part avec elle, et s'en va avec elle.
#
# Le chemin est relatif au paquet, pas au dossier courant : dans l'executable
# packagee, les fichiers de donnees atterrissent dans _MEIPASS.
OUTIL_EMBARQUE = Path("outils") / "OpenRGB" / "OpenRGB.exe"


def _embarque() -> Path | None:
    """L'OpenRGB livre avec l'assistant, en sources comme en packagee."""
    import sys

    from assistant import config

    candidats = [config.ROOT / OUTIL_EMBARQUE]
    base = getattr(sys, "_MEIPASS", None)
    if base:
        candidats.insert(0, Path(base) / OUTIL_EMBARQUE)
    for chemin in candidats:
        try:
            if chemin.is_file():
                return chemin
        except OSError:
            continue
    return None


def _executable() -> Path | None:
    """Trouve OpenRGB. L'exemplaire embarque passe avant tout le reste.

    Ordre voulu :
      1. celui livre avec l'application -- il est de la version attendue, et
         il ne demande aucune installation ;
      2. un chemin explicitement enregistre par l'utilisateur ;
      3. une installation deja presente sur la machine, s'il y en a une.

    Chercher sur l'ensemble des disques n'est jamais fait : ca couterait plus
    cher que de demander une fois ou se trouve le fichier.
    """
    from assistant import settings

    integre = _embarque()
    if integre is not None:
        return integre

    force = settings.get("openrgb_chemin", "")
    if force and Path(force).is_file():
        return Path(force)

    trouve = shutil.which("OpenRGB")
    if trouve:
        return Path(trouve)

    for chemin in CANDIDATS:
        try:
            if chemin.is_file():
                return chemin
        except OSError:      # chemin invalide sur cette machine
            continue
    return None


def source() -> str:
    """D'ou vient l'OpenRGB utilise : embarque, enregistre, ou du systeme."""
    if _embarque() is not None:
        return "livre avec l'assistant"
    exe = _executable()
    if exe is None:
        return "absent"
    from assistant import settings

    if settings.get("openrgb_chemin", "") == str(exe):
        return "chemin enregistre"
    return "installe sur la machine"


def definir_chemin(chemin: str) -> str:
    """Enregistre l'emplacement d'OpenRGB, pour une installation portable."""
    from assistant import settings

    cible = Path(chemin.strip('"'))
    if cible.is_dir():
        cible = cible / "OpenRGB.exe"
    if not cible.is_file():
        return f"Introuvable : {cible}"

    settings.set("openrgb_chemin", str(cible))
    trouves, erreur = peripheriques()
    if erreur:
        return f"OpenRGB enregistre, mais : {erreur}"
    return (f"OpenRGB enregistre. {len(trouves)} peripherique(s) RGB "
            "detecte(s).")


def disponible() -> bool:
    return _executable() is not None


# Services qui gardent la main sur un controleur RGB, meme quand la fenetre du
# logiciel est fermee. C'est eux qui comptent : tuer un programme qu'un service
# relance ne sert a rien.
#
# Liste blanche stricte, et rien d'autre. Arreter un service au hasard parce
# que son nom contient "RGB" est le genre de chose qui fait tomber une session
# Windows.
SERVICES_CONCURRENTS = {
    "MyService1": "GIGABYTE Adjust",
    "GvLedService": "Gigabyte LED",
    "Razer Chroma SDK Server": "Razer Chroma (serveur)",
    "Razer Chroma SDK Service": "Razer Chroma",
    "Razer Chroma Stream Server": "Razer Chroma (flux)",
    "RzActionSvc": "Razer Synapse",
    "CorsairDeviceControlService": "Corsair iCUE",
    "CorsairGamingAudioConfig": "Corsair audio",
    "LightingService": "Asus Aura",
    "asComSvc": "Asus Armoury Crate",
    "MSI_Center_Service": "MSI Center",
    "Micro Star SCM": "MSI Mystic Light",
    "LGHUBUpdaterService": "Logitech G HUB",
}


def conflits() -> tuple[list[str], list[str]]:
    """Ce qui tient actuellement le controleur : programmes et services."""
    programmes = concurrents_actifs()

    services = []
    try:
        resultat = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             "Get-Service | Where-Object { $_.Status -eq 'Running' } | "
             "Select-Object -ExpandProperty Name"],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
            creationflags=CREATE_NO_WINDOW,
        )
        actifs = {l.strip() for l in (resultat.stdout or "").splitlines()}
    except (subprocess.SubprocessError, OSError):
        actifs = set()

    for nom, libelle in SERVICES_CONCURRENTS.items():
        if nom in actifs:
            services.append(nom)
    return programmes, services


def liberer(ask=None) -> str:
    """Ferme tout ce qui dispute le controleur RGB a l'assistant.

    Deux logiciels qui ecrivent sur le meme controleur donnent un eclairage
    qui ne repond a personne : la commande est acceptee, et le concurrent la
    recouvre aussitot. C'est ce qui se passait ici -- le mode changeait dans
    OpenRGB, les LED ne bougeaient pas.

    Les services comptent plus que les fenetres : fermer un programme qu'un
    service relance ne sert a rien.

    Reversible : les services sont seulement ARRETES, pas desactives. Ils
    repartiront au prochain demarrage de Windows, ou tout de suite avec
    rendre_le_controleur().
    """
    from assistant import safety

    programmes, services = conflits()
    if not programmes and not services:
        return "Rien ne dispute le controleur : l'assistant a deja la main."

    action = safety.Action(
        kind="service",
        summary="Reprendre la main sur l'eclairage RGB",
        targets=[f"programme: {p}" for p in programmes]
                + [f"service: {SERVICES_CONCURRENTS.get(s, s)}" for s in services],
        reversible=True,
        details="Ces logiciels gardent le controleur et recouvrent chaque "
                "commande. Ils sont arretes, pas desactives : ils repartiront "
                "au prochain demarrage de Windows.",
    )
    try:
        safety.guard(action, ask=ask)
    except safety.Refused as exc:
        return str(exc)

    return _arreter_eleve(services)


def _arreter_eleve(services: list[str]) -> str:
    """Arrete les concurrents, en demandant l'elevation une seule fois.

    RGB Fusion tourne en administrateur, et les services aussi : un processus
    normal ne peut arreter ni l'un ni l'autre. On demande donc les droits UNE
    fois pour tout le lot, plutot qu'une fenetre par element.

    Le resultat est constate en RELISANT l'etat de la machine, pas en lisant
    un compte-rendu ecrit par le processus eleve. D'abord parce qu'un fichier
    ecrit par un administrateur n'est pas toujours relisible ensuite -- c'est
    ce qui est arrive au premier essai. Ensuite et surtout parce qu'un rapport
    dit ce qu'on a demande, pas ce qui s'est produit.
    """
    import tempfile
    from pathlib import Path as _Path

    avant_programmes, avant_services = conflits()

    lignes = [
        "foreach ($nom in @(" + ",".join(f"'{p}'" for p in CONCURRENTS) + ")) {",
        "  $court = [IO.Path]::GetFileNameWithoutExtension($nom)",
        "  Get-Process $court -ErrorAction SilentlyContinue | "
        "Stop-Process -Force -ErrorAction SilentlyContinue",
        "}",
    ]
    for service in services:
        lignes.append(
            f"Stop-Service -Name '{service}' -Force "
            "-ErrorAction SilentlyContinue")

    with tempfile.TemporaryDirectory() as dossier:
        script = _Path(dossier) / "liberer.ps1"
        script.write_text("\n".join(lignes), encoding="utf-8")
        try:
            subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-Command",
                 "Start-Process powershell -Verb RunAs -Wait -WindowStyle "
                 "Hidden -ArgumentList "
                 "'-NoProfile','-ExecutionPolicy','Bypass','-File',"
                 f"'{script}'"],
                capture_output=True, text=True, timeout=180,
                creationflags=CREATE_NO_WINDOW,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            return f"Elevation impossible : {type(exc).__name__}: {exc}"

    apres_programmes, apres_services = conflits()

    arretes = ([p for p in avant_programmes if p not in apres_programmes]
               + [SERVICES_CONCURRENTS.get(s, s) for s in avant_services
                  if s not in apres_services])
    restants = apres_programmes + [SERVICES_CONCURRENTS.get(s, s)
                                   for s in apres_services]

    if not arretes and restants:
        return ("Rien n'a pu etre arrete : l'elevation a probablement ete "
                "refusee. Sans les droits administrateur, ni le logiciel du "
                "fabricant ni ses services ne peuvent lacher le controleur.\n"
                "Tiennent encore : " + ", ".join(restants))

    lignes_finales = ["Reprise du controleur RGB :", ""]
    for nom in arretes:
        lignes_finales.append(f"  arrete : {nom}")
    lignes_finales.append("")
    if restants:
        lignes_finales.append("Tiennent encore : " + ", ".join(restants))
    else:
        lignes_finales.append("Plus rien ne dispute le controleur.")
    lignes_finales.append("")
    lignes_finales.append("Reversible : ils repartiront au prochain demarrage "
                          "de Windows.")
    return "\n".join(lignes_finales)


def rendre_le_controleur() -> str:
    """Relance les services d'eclairage arretes, sans attendre un redemarrage."""
    _programmes, actifs = conflits()
    a_relancer = [s for s in SERVICES_CONCURRENTS if s not in actifs]
    if not a_relancer:
        return "Tous les services d'eclairage tournent deja."

    commandes = "; ".join(
        f"Start-Service -Name '{s}' -ErrorAction SilentlyContinue"
        for s in a_relancer)
    try:
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-Command",
             f"Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden "
             f"-ArgumentList '-NoProfile','-Command','{commandes}'"],
            capture_output=True, text=True, timeout=180,
            creationflags=CREATE_NO_WINDOW,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return f"Impossible : {type(exc).__name__}: {exc}"
    return ("Services d'eclairage relances. Le logiciel du fabricant reprendra "
            "la main sur le controleur.")


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


def _serveur_actif(timeout: float = 0.6) -> bool:
    import socket

    from assistant.skills.rgb_client import HOTE, PORT

    try:
        with socket.create_connection((HOTE, PORT), timeout=timeout):
            return True
    except OSError:
        return False


def demarrer_serveur(attente: float = 20.0) -> tuple[bool, str]:
    """Lance le serveur OpenRGB si besoin, et attend qu'il reponde.

    Meme raison que pour Ollama : exiger de l'utilisateur qu'il lance un
    programme avant l'assistant, c'est garantir qu'il oubliera, et que la
    fonction paraitra cassee sans que rien n'explique pourquoi.

    --noautoconnect empeche le serveur de se connecter a un autre serveur
    OpenRGB : sans lui, deux instances se renvoient la balle.
    """
    import time

    if _serveur_actif():
        return True, "serveur deja actif"

    exe = _executable()
    if exe is None:
        return False, "OpenRGB introuvable."

    try:
        subprocess.Popen(
            [str(exe), "--server", "--noautoconnect"],
            cwd=str(exe.parent),
            creationflags=CREATE_NO_WINDOW | 0x00000008,   # detache
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
    except OSError as exc:
        return False, f"Lancement impossible : {exc}"

    limite = time.time() + attente
    while time.time() < limite:
        if _serveur_actif():
            return True, "serveur demarre"
        time.sleep(0.5)
    return False, (f"Le serveur OpenRGB n'a pas repondu apres {attente:.0f} s.")


# Il y avait ici deux expressions regulieres qui analysaient la sortie texte
# d'OpenRGB. Elles sont parties avec la ligne de commande : cette sortie
# n'arrive dans aucun tuyau, on passe desormais par le serveur.


def peripheriques() -> tuple[list, str]:
    """Ce qui est reellement pilotable sur CETTE machine, et ses modes."""
    from assistant.skills import rgb_client

    if not disponible():
        return [], "OpenRGB n'est pas livre avec l'assistant."

    ok, message = demarrer_serveur()
    if not ok:
        return [], message

    try:
        with rgb_client.Connexion() as lien:
            trouves = lien.peripheriques()
    except rgb_client.Erreur as exc:
        return [], str(exc)

    if not trouves:
        concurrents = concurrents_actifs()
        detail = ""
        if concurrents:
            detail = (f" {', '.join(concurrents)} tourne et garde la main sur "
                      "le controleur : ferme-le.")
        return [], ("Aucun peripherique RGB detecte." + detail)
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


# Bibliotheques de pilotage livrees AVEC les logiciels de fabricant. Elles
# sont deja sur la machine des qu'on a installe le logiciel du constructeur --
# il n'y a donc rien a telecharger pour les utiliser.
#
# On les cherche pour pouvoir dire a l'utilisateur ce qui est reellement
# atteignable chez lui, plutot que de repondre "installe OpenRGB" sans
# expliquer ce qu'il a deja sous la main.
SDK_FABRICANTS = [
    ("GvLedLib.dll", "Gigabyte RGB Fusion",
     ["Program Files (x86)/GIGABYTE/RGBFusion"]),
    ("iCUESDK.x64_2019.dll", "Corsair iCUE",
     ["Program Files/Corsair/CORSAIR iCUE5 Software",
      "Program Files/Corsair/CORSAIR iCUE4 Software"]),
    ("RzChromaSDK64.dll", "Razer Chroma",
     ["Program Files/Razer Chroma SDK/bin",
      "Program Files (x86)/Razer Chroma SDK/bin"]),
    ("AURA_SDK.dll", "Asus Aura", ["Program Files (x86)/LightingService"]),
    ("MysticLight_SDK.dll", "MSI Mystic Light", ["Program Files (x86)/MSI"]),
]


def sdk_presents() -> list[tuple[str, Path, str]]:
    """SDK de fabricants trouves sur cette machine, avec leur architecture.

    L'architecture compte : une bibliotheque 32 bits ne peut pas etre chargee
    par un processus 64 bits. GvLedLib de Gigabyte est en 32 bits, et
    l'assistant en 64 -- la piste demande un pont, elle n'est pas gratuite.
    """
    import struct

    trouves = []
    for fichier, libelle, dossiers in SDK_FABRICANTS:
        for dossier in dossiers:
            chemin = Path("C:/") / dossier / fichier
            if not chemin.is_file():
                continue
            try:
                donnees = chemin.read_bytes()[:1024]
                debut = struct.unpack_from("<I", donnees, 0x3C)[0]
                machine = struct.unpack_from("<H", donnees, debut + 4)[0]
                arch = {0x14c: "32 bits", 0x8664: "64 bits"}.get(machine, "?")
            except Exception:  # noqa: BLE001
                arch = "?"
            trouves.append((libelle, chemin, arch))
            break
    return trouves


def _ce_qui_existe_deja() -> str:
    """Ce que la machine possede deja, meme sans OpenRGB."""
    trouves = sdk_presents()
    if not trouves:
        return ""
    lignes = ["", "  Ce qui est deja installe ici :"]
    for libelle, _chemin, arch in trouves:
        note = ""
        if arch == "32 bits":
            note = "  (32 bits : inutilisable directement depuis l'assistant)"
        lignes.append(f"    {libelle}  —  {arch}{note}")
    return "\n".join(lignes)


def liste() -> str:
    """Ce qui est pilotable, avec les modes reellement offerts par chacun."""
    if not disponible():
        return (
            "ECLAIRAGE RGB\n\n"
            "  Le pilotage RGB demande OpenRGB, qui n'est pas installe.\n\n"
            "  Pourquoi lui, et pas le logiciel du fabricant : verifie sur\n"
            "  cette machine, RGB Fusion n'ecrit rien sur le disque quand on\n"
            "  change de mode (son fichier de profil n'a pas bouge en dix\n"
            "  minutes d'essais), n'expose aucune ligne de commande sur ses\n"
            "  quatorze executables, et sa fenetre ne publie aucun bouton a\n"
            "  l'automatisation Windows : ses commandes sont des images\n"
            "  dessinees. Il n'y a rien a piloter de l'exterieur.\n\n"
            "  OpenRGB parle au materiel lui-meme et couvre la plupart des\n"
            "  marques derriere une seule interface. Il est libre, portable\n"
            "  et fonctionne hors ligne.\n\n"
            "  RIEN N'EST A INSTALLER SUR LE PC. L'outil se pose DANS\n"
            "  l'application :\n\n"
            f"      {OUTIL_EMBARQUE}\n\n"
            "  Depuis cet emplacement il part avec l'assistant, se retrouve\n"
            "  dans l'executable a la reconstruction, et s'en va avec lui :\n"
            "  aucune entree dans Program Files, aucune cle de registre,\n"
            "  aucun desinstalleur de plus.\n\n"
            "  Ferme le logiciel du fabricant avant de t'en servir : deux\n"
            "  programmes sur le meme controleur font clignoter l'eclairage."
            + _ce_qui_existe_deja()
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

    from assistant.skills import rgb_client

    faits, ignores = [], []
    try:
        with rgb_client.Connexion() as lien:
            for cible in cibles:
                exact = _trouver(mode, cible.modes)
                if exact is None:
                    ignores.append(
                        f"{cible.nom} (modes : {', '.join(cible.modes)})")
                    continue
                try:
                    lien.changer_mode(cible, cible.modes.index(exact))
                    faits.append(f"{cible.nom} -> {exact}")
                except (rgb_client.Erreur, OSError, IndexError) as exc:
                    ignores.append(f"{cible.nom} : {type(exc).__name__}")
    except rgb_client.Erreur as exc:
        return str(exc)

    lignes = []
    if faits:
        # "Commande envoyee", et non "eclairage change".
        #
        # Le serveur accepte le mode et le rend ensuite quand on l'interroge --
        # il repete simplement ce qu'on lui a dit. Sur cette machine, les LED
        # ne suivent pas : carte mere, carte graphique et souris sont restees
        # comme avant, concurrents arretes ou non.
        #
        # Annoncer un succes qu'on n'a pas constate est pire que de ne rien
        # annoncer : l'utilisateur cherche ailleurs un probleme qui est ici.
        lignes.append("Commande envoyee au controleur :")
        lignes.extend(f"  {f}" for f in faits)
        lignes.append("")
        lignes.append("Regarde tes LED : si elles n'ont pas bouge, le "
                      "controleur a accepte l'ordre sans l'appliquer.")
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
