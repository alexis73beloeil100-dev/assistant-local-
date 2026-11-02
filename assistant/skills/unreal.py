"""Atelier Unreal, etape 1 : connaitre le projet, compiler, lire les erreurs.

Tout est deduit du projet lui-meme, pour marcher avec n'importe quelle
version d'Unreal Engine 5 sans rien coder en dur :

  - le projet : choisi une fois (bouton, ou phrase), sinon propose parmi les
    projets recents qu'Unreal a lui-meme memorises ;
  - le moteur : la version est ecrite dans le .uproject (EngineAssociation) ;
    son dossier se retrouve dans le registre ou dans la liste du Launcher,
    qu'il s'agisse d'une version installee ou compilee depuis les sources ;
  - la compilation : Build.bat du moteur, avec la cible "Editor" du projet,
    lue dans ses fichiers .Target.cs.

Cette etape LIT et COMPILE. Elle n'ecrit pas une ligne de code du projet.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from assistant import safety, settings

CREATE_NO_WINDOW = 0x08000000
CLE_PROJET = "projet_unreal"

# Une compilation complete d'un gros projet depasse facilement le quart
# d'heure ; au-dela d'une heure, quelque chose est bloque.
DUREE_MAX_COMPILATION = 3600
ERREURS_AFFICHEES = 25

# Le compte-rendu de la derniere compilation, pour le panneau Projet.
derniere_compilation = ""


class Echec(Exception):
    """Une etape a echoue ; le message se lit tel quel."""


# --- Le projet ---------------------------------------------------------------

def _dossiers_reglages_editeur() -> list[Path]:
    """Les dossiers ou chaque version de l'editeur range ses reglages."""
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "UnrealEngine"
    if not base.is_dir():
        return []
    return [d / "Saved" / "Config" / "WindowsEditor"
            for d in sorted(base.iterdir()) if d.is_dir()]


_RECENT = re.compile(r"^RecentlyOpenedProjectFiles=(.+)$", re.M)
_RECENT_STRUCT = re.compile(
    r'ProjectName="(?P<chemin>[^"]+)"(?:,LastOpenTime=(?P<date>[\d.\-]+))?')


def lire_projets_recents(texte_ini: str) -> list[tuple[str, str]]:
    """(chemin, date) depuis EditorSettings.ini, les deux formats d'Unreal.

    UE5 recent : RecentlyOpenedProjectFiles=(ProjectName="C:/x.uproject",
    LastOpenTime=2026.10.30-18.02.11). Plus ancien : la valeur est le chemin.
    """
    trouves = []
    for valeur in _RECENT.findall(texte_ini):
        valeur = valeur.strip()
        m = _RECENT_STRUCT.search(valeur)
        if m:
            trouves.append((m.group("chemin"), m.group("date") or ""))
        elif valeur.lower().endswith(".uproject"):
            trouves.append((valeur.strip('"'), ""))
    return trouves


def projets_recents() -> list[Path]:
    """Les projets ouverts recemment dans l'editeur, du plus recent au plus
    ancien, sans doublon et seulement s'ils existent encore."""
    vus: dict[str, tuple[str, Path]] = {}
    for dossier in _dossiers_reglages_editeur():
        ini = dossier / "EditorSettings.ini"
        try:
            texte = ini.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for chemin, date in lire_projets_recents(texte):
            p = Path(chemin)
            cle = str(p).lower()
            if p.is_file() and (cle not in vus or date > vus[cle][0]):
                vus[cle] = (date, p)
    return [p for _d, p in sorted(vus.values(), key=lambda v: v[0],
                                  reverse=True)]


def projet_actuel() -> Path | None:
    chemin = settings.get(CLE_PROJET)
    if chemin and Path(chemin).is_file():
        return Path(chemin)
    return None


def choisir_projet(chemin: str) -> str:
    """Retient le projet sur lequel on travaille.

    Accepte le .uproject, ou le dossier qui le contient.
    """
    p = Path(str(chemin).strip().strip('"'))
    if p.is_dir():
        candidats = sorted(p.glob("*.uproject"))
        if not candidats:
            return f"Aucun fichier .uproject dans {p}."
        p = candidats[0]
    if p.suffix.lower() != ".uproject" or not p.is_file():
        return f"{p} n'est pas un projet Unreal (.uproject) existant."
    settings.set(CLE_PROJET, str(p))
    return f"Projet retenu : {p.stem} ({p})."


def _projet_ou_echec() -> Path:
    p = projet_actuel()
    if p is not None:
        return p
    recents = projets_recents()
    if recents:
        # Le plus recemment ouvert dans Unreal est celui sur lequel on
        # travaille : demander « quel projet ? » a chaque fois exasperait.
        settings.set(CLE_PROJET, str(recents[0]))
        return recents[0]
    if recents:
        liste = "\n".join(f"  - {r}" for r in recents[:8])
        raise Echec("Aucun projet choisi. Projets ouverts recemment dans "
                    f"Unreal :\n{liste}\nDis lequel, ou utilise le bouton "
                    "Choisir le projet.")
    raise Echec("Aucun projet choisi, et Unreal n'en a memorise aucun. "
                "Utilise le bouton Choisir le projet, ou donne le chemin du "
                ".uproject.")


def lire_uproject(chemin: Path) -> dict:
    try:
        return json.loads(chemin.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Echec(f"{chemin.name} illisible : {exc}")


# --- Le moteur ---------------------------------------------------------------

def _registre(racine: str, cle: str) -> dict[str, str]:
    """Les valeurs d'une cle du registre, {} hors Windows ou si absente."""
    try:
        import winreg
    except ImportError:
        return {}
    ruche = {"HKLM": winreg.HKEY_LOCAL_MACHINE,
             "HKCU": winreg.HKEY_CURRENT_USER}[racine]
    valeurs = {}
    try:
        with winreg.OpenKey(ruche, cle) as k:
            i = 0
            while True:
                try:
                    nom, valeur, _type = winreg.EnumValue(k, i)
                except OSError:
                    break
                valeurs[nom] = str(valeur)
                i += 1
    except OSError:
        return {}
    return valeurs


def _launcher_installes() -> dict[str, Path]:
    """{"5.4": dossier} d'apres la liste du Epic Games Launcher."""
    fichier = (Path(os.environ.get("ProgramData", r"C:\ProgramData"))
               / "Epic" / "UnrealEngineLauncher" / "LauncherInstalled.dat")
    try:
        donnees = json.loads(fichier.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    trouves = {}
    for entree in donnees.get("InstallationList", []):
        nom = str(entree.get("AppName", ""))
        m = re.fullmatch(r"UE_(\d+\.\d+)", nom)
        if m and entree.get("InstallLocation"):
            trouves[m.group(1)] = Path(entree["InstallLocation"])
    return trouves


def dossier_moteur(projet: Path, association: str) -> Path:
    """Le dossier racine du moteur (celui qui contient Engine/)."""
    association = (association or "").strip()

    if not association:
        # Projet range DANS l'arborescence d'un moteur compile.
        for parent in projet.parents:
            if (parent / "Engine" / "Build" / "BatchFiles").is_dir():
                return parent
        raise Echec("Le projet ne precise pas sa version d'Unreal "
                    "(EngineAssociation vide) et n'est pas dans le dossier "
                    "d'un moteur.")

    if association.startswith("{"):
        # Moteur compile depuis les sources, enregistre sous un identifiant.
        builds = _registre("HKCU", r"Software\Epic Games\Unreal Engine\Builds")
        chemin = builds.get(association)
        if chemin and Path(chemin).is_dir():
            return Path(chemin)
        raise Echec(f"Moteur compile {association} introuvable dans le "
                    "registre : il a peut-etre ete deplace ou supprime.")

    cle = rf"SOFTWARE\EpicGames\Unreal Engine\{association}"
    chemin = _registre("HKLM", cle).get("InstalledDirectory")
    if chemin and Path(chemin).is_dir():
        return Path(chemin)
    lanceur = _launcher_installes().get(association)
    if lanceur and lanceur.is_dir():
        return lanceur
    raise Echec(f"Unreal Engine {association} n'est pas installe sur ce PC "
                "(ni dans le registre, ni dans le Epic Games Launcher).")


# --- Resume du projet ----------------------------------------------------------

# Les types reflechis par Unreal : UCLASS, USTRUCT, UENUM, UINTERFACE. On ne
# comptait que les classes exportees (MODULE_API), et un projet de 129
# fichiers s'annoncait avec "1 classe".
_TYPE_UNREAL = re.compile(
    r"\b(UCLASS|USTRUCT|UENUM|UINTERFACE)\s*\([^)]*\)\s*"
    r"(?:class|struct|enum(?:\s+class)?)\s+(?:\w+_API\s+)?(\w+)", re.S)


@dataclass
class Projet:
    chemin: Path
    nom: str
    association: str
    modules: list[str]
    plugins: list[str]
    cibles: list[str]
    fichiers_code: int
    classes: list[str]
    structures: list[str] = None
    enumerations: list[str] = None


def analyser(chemin: Path) -> Projet:
    donnees = lire_uproject(chemin)
    racine = chemin.parent
    source = racine / "Source"
    classes: list[str] = []
    structures: list[str] = []
    enumerations: list[str] = []
    nb = 0
    if source.is_dir():
        for f in source.rglob("*"):
            if f.suffix.lower() in (".h", ".cpp"):
                nb += 1
                if f.suffix.lower() == ".h":
                    try:
                        texte = f.read_text(encoding="utf-8", errors="replace")
                        for genre, nom in _TYPE_UNREAL.findall(texte):
                            if genre in ("UCLASS", "UINTERFACE"):
                                classes.append(nom)
                            elif genre == "USTRUCT":
                                structures.append(nom)
                            else:
                                enumerations.append(nom)
                    except OSError:
                        pass
    cibles = sorted(f.name[:-len(".Target.cs")]
                    for f in source.glob("*.Target.cs")) if source.is_dir() else []
    return Projet(
        chemin=chemin,
        nom=chemin.stem,
        association=str(donnees.get("EngineAssociation", "")),
        modules=[m.get("Name", "?") for m in donnees.get("Modules", [])],
        plugins=[p.get("Name", "?") for p in donnees.get("Plugins", [])
                 if p.get("Enabled", True)],
        cibles=cibles,
        fichiers_code=nb,
        classes=sorted(set(classes)),
        structures=sorted(set(structures)),
        enumerations=sorted(set(enumerations)),
    )


def resume_projet() -> str:
    try:
        projet = analyser(_projet_ou_echec())
    except Echec as exc:
        return str(exc)
    try:
        moteur = str(dossier_moteur(projet.chemin, projet.association))
    except Echec as exc:
        moteur = f"introuvable -- {exc}"
    lignes = [
        f"Projet   {projet.nom}",
        f"Fichier  {projet.chemin}",
        f"Moteur   Unreal Engine {projet.association or '(non precise)'}",
        f"         {moteur}",
        f"Modules  {', '.join(projet.modules) or 'aucun (projet Blueprint)'}",
        f"Cibles   {', '.join(projet.cibles) or 'aucune'}",
        f"Plugins actives  {', '.join(projet.plugins) or 'aucun'}",
        f"Code C++ {projet.fichiers_code} fichier(s) .h/.cpp : "
        f"{len(projet.classes)} classe(s), {len(projet.structures or [])} "
        f"structure(s), {len(projet.enumerations or [])} enumeration(s) Unreal",
    ]
    for titre, noms in (("Classes", projet.classes),
                        ("Structures", projet.structures or []),
                        ("Enums", projet.enumerations or [])):
        if noms:
            lignes.append(f"{titre:<9}" + ", ".join(noms[:60])
                          + (f" ... (+{len(noms) - 60})" if len(noms) > 60 else ""))
    lignes += ["", activite_recente(projet.chemin.parent)]
    return "\n".join(lignes)


def activite_recente(racine: Path, nombre: int = 12) -> str:
    """Ce qui a bouge en dernier : fichiers modifies et commits Git.

    C'est ce qui permet de repondre a "ou en est le projet" sans inventer.
    """
    suivis = []
    for dossier in ("Source", "Config", "Content", "Plugins"):
        base = racine / dossier
        if not base.is_dir():
            continue
        for f in base.rglob("*"):
            if (f.is_file() and f.suffix.lower() in (
                    ".h", ".cpp", ".cs", ".ini", ".uasset", ".umap")
                    and not any(p.lower() in ("binaries", "intermediate")
                                for p in f.parts)):
                try:
                    suivis.append((f.stat().st_mtime, f))
                except OSError:
                    continue
    suivis.sort(key=lambda x: -x[0])
    lignes = ["Activite recente (fichiers modifies) :"]
    lignes += [f"  {time.strftime('%d/%m/%Y %H:%M', time.localtime(t))}  "
               f"{f.relative_to(racine).as_posix()}" for t, f in suivis[:nombre]]
    if not suivis:
        lignes.append("  aucun fichier suivi")
    try:
        r = subprocess.run(["git", "log", "-8", "--date=format:%d/%m/%Y",
                            "--pretty=format:  %ad  %s"], cwd=str(racine),
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=20,
                           creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
        if r.returncode == 0 and r.stdout.strip():
            lignes += ["Derniers enregistrements Git :", r.stdout.rstrip()]
    except (OSError, subprocess.SubprocessError):
        pass
    return "\n".join(lignes)


# --- Compilation ---------------------------------------------------------------

# file(ligne[,colonne]): error|warning CODE: message   (MSVC et UHT)
_ERREUR = re.compile(
    r"^\s*(?P<fichier>[A-Za-z]:[\\/][^(]+?|[^(:]+?)\((?P<ligne>\d+)(?:,\d+)?\)"
    r"\s*:\s*(?P<genre>fatal error|error|Error|warning|Warning)"
    r"\s*(?P<code>[A-Z]+\d+)?\s*:?\s*(?P<message>.*)$")
# Erreurs d'edition de liens et de l'outil de construction, sans ligne.
_ERREUR_SANS_LIGNE = re.compile(
    r"^\s*(?P<ou>(?:[A-Za-z]:)?[^:]+?)\s*:\s*(?P<genre>fatal error|error)\s+"
    r"(?P<code>LNK\d+|C\d+)\s*:\s*(?P<message>.*)$")
_LIVE_CODING = re.compile(r"Live Coding is active", re.I)


@dataclass
class Diagnostic:
    genre: str          # "erreur" ou "avertissement"
    fichier: str
    ligne: int
    code: str
    message: str

    def __str__(self) -> str:
        ou = f"{self.fichier}({self.ligne})" if self.ligne else self.fichier
        code = f" {self.code}" if self.code else ""
        return f"{ou}:{code} {self.message}".strip()


def analyser_sortie(sortie: str) -> list[Diagnostic]:
    """Les erreurs et avertissements d'une compilation, sans doublon."""
    vus, resultat = set(), []
    for ligne in sortie.splitlines():
        m = _ERREUR.match(ligne)
        if m:
            genre = "avertissement" if m["genre"].lower() == "warning" else "erreur"
            d = Diagnostic(genre, m["fichier"].strip(), int(m["ligne"]),
                           m["code"] or "", m["message"].strip())
        else:
            m = _ERREUR_SANS_LIGNE.match(ligne)
            if not m:
                continue
            d = Diagnostic("erreur", m["ou"].strip(), 0, m["code"],
                           m["message"].strip())
        cle = (d.genre, d.fichier, d.ligne, d.code, d.message)
        if cle not in vus:
            vus.add(cle)
            resultat.append(d)
    return resultat


def commande_compilation(projet: Projet, moteur: Path,
                         configuration: str) -> list[str]:
    editeurs = [c for c in projet.cibles if c.endswith("Editor")]
    if not editeurs:
        raise Echec("Ce projet n'a pas de cible Editor en C++ (aucun "
                    "fichier *Editor.Target.cs dans Source/) : c'est un "
                    "projet Blueprint, il n'y a rien a compiler.")
    build = moteur / "Engine" / "Build" / "BatchFiles" / "Build.bat"
    if not build.is_file():
        raise Echec(f"Build.bat introuvable dans le moteur : {build}")
    return [str(build), editeurs[0], "Win64", configuration,
            f"-Project={projet.chemin}", "-WaitMutex", "-FromMsBuild"]


def compiler(configuration: str = "Development", ask=None) -> str:
    """Compile la cible Editor du projet et rend un compte-rendu lisible."""
    configuration = configuration if configuration in (
        "Development", "DebugGame", "Debug") else "Development"
    try:
        projet = analyser(_projet_ou_echec())
        moteur = dossier_moteur(projet.chemin, projet.association)
        commande = commande_compilation(projet, moteur, configuration)
    except Echec as exc:
        return str(exc)

    # Compiler n'ecrit que dans Binaries/ et Intermediate/ du projet, et se
    # relance a volonte : c'est un geste courant, journalise sans fenetre.
    action = safety.Action(
        kind="compilation",
        summary=f"Compiler {projet.nom} ({configuration})",
        targets=[str(projet.chemin)],
        reversible=True,
        routine=True,
    )
    try:
        if not safety.guard(action, ask=ask):
            return "Compilation annulee."
    except safety.Refused as exc:
        return str(exc)

    debut = time.time()
    try:
        resultat = subprocess.run(
            commande, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=DUREE_MAX_COMPILATION,
            cwd=str(projet.chemin.parent), creationflags=CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        return (f"Compilation arretee apres {DUREE_MAX_COMPILATION // 60} "
                "minutes : elle semble bloquee.")
    except OSError as exc:
        return f"Compilation impossible a lancer : {exc}"
    duree = time.time() - debut
    global derniere_compilation
    derniere_compilation = compte_rendu(
        projet.nom, resultat.returncode,
        resultat.stdout + "\n" + resultat.stderr, duree)
    return derniere_compilation


def compte_rendu(nom: str, code_retour: int, sortie: str, duree: float) -> str:
    if _LIVE_CODING.search(sortie):
        return ("Compilation refusee : l'editeur Unreal est ouvert avec Live "
                "Coding actif. Ferme l'editeur, ou compile depuis l'editeur "
                "avec Ctrl+Alt+F11.")
    diagnostics = analyser_sortie(sortie)
    erreurs = [d for d in diagnostics if d.genre == "erreur"]
    avertissements = [d for d in diagnostics if d.genre == "avertissement"]
    reussi = code_retour == 0 and not erreurs

    lignes = [f"Compilation de {nom} : {'REUSSIE' if reussi else 'ECHEC'} "
              f"en {duree:.0f} s -- {len(erreurs)} erreur(s), "
              f"{len(avertissements)} avertissement(s)."]
    for d in erreurs[:ERREURS_AFFICHEES]:
        lignes.append(f"  [erreur] {d}")
    if len(erreurs) > ERREURS_AFFICHEES:
        lignes.append(f"  ... et {len(erreurs) - ERREURS_AFFICHEES} autres")
    for d in avertissements[:10]:
        lignes.append(f"  [avert.] {d}")
    if not reussi and not erreurs:
        # Echec sans erreur reconnue : la fin de la sortie dit pourquoi.
        fin = [l for l in sortie.splitlines() if l.strip()][-15:]
        lignes.append("  Aucune erreur au format habituel. Fin de la sortie :")
        lignes += [f"    {l[:200]}" for l in fin]
    return "\n".join(lignes)


# --- Journaux et plantages -----------------------------------------------------

def journaux(lignes: int = 60, tout: bool = False) -> str:
    """Le journal de la derniere session de l'editeur ou du jeu.

    Par defaut, seulement les erreurs et avertissements : un journal Unreal
    fait des milliers de lignes dont l'essentiel est sans interet.
    """
    try:
        projet = _projet_ou_echec()
    except Echec as exc:
        return str(exc)
    dossier = projet.parent / "Saved" / "Logs"
    journal = dossier / f"{projet.stem}.log"
    if not journal.is_file():
        fichiers = sorted(dossier.glob("*.log"), key=lambda f: f.stat().st_mtime,
                          reverse=True) if dossier.is_dir() else []
        if not fichiers:
            return f"Aucun journal dans {dossier} : le projet n'a pas encore ete lance."
        journal = fichiers[0]
    texte = journal.read_text(encoding="utf-8", errors="replace").splitlines()
    return filtrer_journal(texte, journal, lignes, tout)


def filtrer_journal(texte: list[str], journal: Path, lignes: int,
                    tout: bool) -> str:
    lignes = max(10, min(int(lignes or 60), 400))
    if tout:
        retenues = texte[-lignes:]
    else:
        retenues = [l for l in texte
                    if re.search(r"\b(Error|Fatal|Warning)\b\s*:", l)][-lignes:]
    erreurs = sum(1 for l in texte if re.search(r"\b(Error|Fatal)\b\s*:", l))
    avert = sum(1 for l in texte if re.search(r"\bWarning\b\s*:", l))
    entete = (f"{journal.name} : {len(texte)} lignes, {erreurs} erreur(s), "
              f"{avert} avertissement(s).")
    if not retenues:
        return entete + " Rien a signaler."
    return entete + "\n" + "\n".join(l[:300] for l in retenues)


def lire_plantage(xml_texte: str) -> tuple[str, list[str]]:
    """(message, pile d'appels) depuis CrashContext.runtime-xml."""
    try:
        racine = ET.fromstring(xml_texte)
    except ET.ParseError as exc:
        raise Echec(f"rapport de plantage illisible : {exc}")
    message = (racine.findtext(".//ErrorMessage") or "").strip()
    pile = (racine.findtext(".//CallStack") or "").strip().splitlines()
    return message, [l.strip() for l in pile if l.strip()]


def dernier_plantage() -> str:
    try:
        projet = _projet_ou_echec()
    except Echec as exc:
        return str(exc)
    dossier = projet.parent / "Saved" / "Crashes"
    rapports = sorted((d for d in dossier.iterdir() if d.is_dir()),
                      key=lambda d: d.stat().st_mtime,
                      reverse=True) if dossier.is_dir() else []
    if not rapports:
        return f"Aucun plantage enregistre dans {dossier}."
    rapport = rapports[0]
    contexte = rapport / "CrashContext.runtime-xml"
    quand = time.strftime("%d/%m/%Y %H:%M",
                          time.localtime(rapport.stat().st_mtime))
    if not contexte.is_file():
        return f"Plantage du {quand} ({rapport.name}), sans rapport lisible."
    try:
        message, pile = lire_plantage(
            contexte.read_text(encoding="utf-8", errors="replace"))
    except Echec as exc:
        return str(exc)

    # Les lignes du projet sont celles qu'on peut corriger : on les signale.
    modules = {m.lower() for m in analyser(projet).modules} | {projet.stem.lower()}
    lignes = [f"Dernier plantage : {quand} ({len(rapports)} rapport(s) au total)",
              f"Message : {message or '(aucun)'}", "Pile d'appels :"]
    for appel in pile[:30]:
        marque = ">>" if any(m in appel.lower() for m in modules) else "  "
        lignes.append(f"  {marque} {appel[:240]}")
    if any(l.startswith("  >>") for l in lignes):
        lignes.append("(>> = code du projet : c'est la que la correction se fait)")
    return "\n".join(lignes)


# --- Etape 5 : construire une version jouable, reperer les assets lourds -------

DUREE_MAX_PAQUET = 4 * 3600


def commande_paquet(projet: Projet, moteur: Path, configuration: str,
                    sortie: Path) -> list[str]:
    uat = moteur / "Engine" / "Build" / "BatchFiles" / "RunUAT.bat"
    if not uat.is_file():
        raise Echec(f"RunUAT.bat introuvable dans le moteur : {uat}")
    commande = [str(uat), "BuildCookRun", f"-project={projet.chemin}", "-noP4",
                "-platform=Win64", f"-clientconfig={configuration}",
                "-cook", "-allmaps", "-stage", "-pak", "-archive",
                f"-archivedirectory={sortie}", "-utf8output"]
    # Un projet Blueprint n'a rien a compiler : -build le ferait echouer.
    if any(c.endswith("Editor") for c in projet.cibles):
        commande.insert(5, "-build")
    return commande


def empaqueter(configuration: str = "Development", ask=None) -> str:
    """Construit une version jouable du jeu (BuildCookRun) dans Packaged/."""
    configuration = configuration if configuration in (
        "Development", "Shipping", "DebugGame") else "Development"
    try:
        projet = analyser(_projet_ou_echec())
        moteur = dossier_moteur(projet.chemin, projet.association)
        sortie = projet.chemin.parent / "Packaged" / configuration
        commande = commande_paquet(projet, moteur, configuration, sortie)
    except Echec as exc:
        return str(exc)
    action = safety.Action(kind="compilation",
                           summary=f"Empaqueter {projet.nom} ({configuration})",
                           targets=[str(sortie)], reversible=True, routine=True)
    try:
        if not safety.guard(action, ask=ask):
            return "Empaquetage annule."
    except safety.Refused as exc:
        return str(exc)
    debut = time.time()
    try:
        r = subprocess.run(commande, capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           timeout=DUREE_MAX_PAQUET,
                           cwd=str(projet.chemin.parent),
                           creationflags=CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        return "Empaquetage arrete apres 4 heures : il semble bloque."
    except OSError as exc:
        return f"Empaquetage impossible a lancer : {exc}"
    rendu = compte_rendu(projet.nom, r.returncode, r.stdout + "\n" + r.stderr,
                         time.time() - debut).replace("Compilation de", "Empaquetage de", 1)
    if r.returncode == 0:
        rendu += f"\nVersion jouable dans : {sortie}"
    return rendu


TAILLES_ALERTE = {".uasset": 50 * 1024 * 1024, ".umap": 200 * 1024 * 1024}


def assets_lourds(nombre: int = 25) -> str:
    """Les plus gros assets du dossier Content, sur le disque."""
    try:
        projet = _projet_ou_echec()
    except Echec as exc:
        return str(exc)
    contenu = projet.parent / "Content"
    if not contenu.is_dir():
        return f"Pas de dossier Content dans {projet.parent}."
    fichiers = [(f.stat().st_size, f) for f in contenu.rglob("*")
                if f.is_file() and f.suffix.lower() in (".uasset", ".umap", ".ubulk")]
    if not fichiers:
        return "Aucun asset dans Content."
    fichiers.sort(key=lambda x: -x[0])
    total = sum(t for t, _ in fichiers)
    lignes = [f"{len(fichiers)} fichiers d'assets, {total / 1e9:.2f} Go au total. "
              f"Les {min(nombre, len(fichiers))} plus lourds :"]
    for taille, f in fichiers[:max(1, int(nombre))]:
        alerte = taille >= TAILLES_ALERTE.get(f.suffix.lower(), 1 << 62)
        chemin = "/Game/" + f.relative_to(contenu).with_suffix("").as_posix()
        lignes.append(f"  {taille / 1e6:8.1f} Mo  {chemin}" + ("  <- lourd" if alerte else ""))
    lignes.append("Textures : 4096 ou plus sans raison, pas de mip-maps ; maillages : "
                  "pas de niveaux de detail (LOD) ; sons : non compresses. A "
                  "verifier dans l'editeur ou avec python_editeur.")
    return "\n".join(lignes)


# --- Ouvrir Unreal, jouer, arreter ------------------------------------------------

def _editeur_exe(moteur: Path) -> Path:
    exe = moteur / "Engine" / "Binaries" / "Win64" / "UnrealEditor.exe"
    if not exe.is_file():
        raise Echec(f"UnrealEditor.exe introuvable dans le moteur : {exe}")
    return exe


def ouvrir_editeur() -> str:
    """Ouvre le projet dans l'editeur Unreal de sa version."""
    try:
        projet = analyser(_projet_ou_echec())
        exe = _editeur_exe(dossier_moteur(projet.chemin, projet.association))
    except Echec as exc:
        return str(exc)
    try:
        subprocess.Popen([str(exe), str(projet.chemin)], cwd=str(projet.chemin.parent),
                         creationflags=0x00000008 if os.name == "nt" else 0)
    except OSError as exc:
        return f"Ouverture impossible : {exc}"
    return (f"Unreal Engine {projet.association} s'ouvre sur {projet.nom}. "
            "Le chargement prend de quelques secondes a quelques minutes.")


def lancer_jeu(carte: str = "", fenetre: bool = True) -> str:
    """Lance le jeu tout seul, hors editeur (-game), pour un test rapide."""
    try:
        projet = analyser(_projet_ou_echec())
        exe = _editeur_exe(dossier_moteur(projet.chemin, projet.association))
    except Echec as exc:
        return str(exc)
    commande = [str(exe), str(projet.chemin)] + ([carte] if carte else []) + ["-game", "-log"]
    if fenetre:
        commande += ["-windowed", "-ResX=1600", "-ResY=900"]
    try:
        subprocess.Popen(commande, cwd=str(projet.chemin.parent),
                         creationflags=0x00000008 if os.name == "nt" else 0)
    except OSError as exc:
        return f"Lancement impossible : {exc}"
    return (f"{projet.nom} se lance en jeu{' sur ' + carte if carte else ''}. "
            "Le journal de la partie se lira avec journaux_unreal.")


def moteurs_installes() -> dict[str, Path]:
    """{"5.8": dossier} : tous les Unreal Engine installes sur ce PC."""
    trouves: dict[str, Path] = {}
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\EpicGames\Unreal Engine") as racine:
            i = 0
            while True:
                try:
                    version = winreg.EnumKey(racine, i)
                except OSError:
                    break
                i += 1
                dossier = _registre("HKLM", rf"SOFTWARE\EpicGames\Unreal Engine\{version}"
                                    ).get("InstalledDirectory")
                if dossier and Path(dossier).is_dir():
                    trouves[version] = Path(dossier)
    except (ImportError, OSError):
        pass
    for version, dossier in _launcher_installes().items():
        if dossier.is_dir():
            trouves.setdefault(version, dossier)
    return dict(sorted(trouves.items(), key=lambda kv: [int(x) for x in kv[0].split(".")
                                                         if x.isdigit()]))


# --- Tests automatises d'Unreal (Automation) -----------------------------------------

_RESULTAT_TEST = re.compile(
    r"Test Completed\. Result=\{(?P<etat>\w+)\}\s+Name=\{(?P<nom>[^}]*)\}\s+Path=\{(?P<chemin>[^}]*)\}")


def lire_rapport_tests(rapport: dict | None, journal: str) -> tuple[list[tuple[str, str, list[str]]], str]:
    """[(etat, chemin, erreurs)] depuis index.json, sinon depuis le journal."""
    resultats = []
    if rapport:
        for t in rapport.get("tests", []):
            erreurs = [str(e.get("event", {}).get("message", ""))
                       for e in t.get("entries", [])
                       if e.get("event", {}).get("type") in ("Error", "Fatal")]
            resultats.append((str(t.get("state", "?")),
                              str(t.get("fullTestPath") or t.get("testDisplayName")),
                              erreurs))
        if resultats:
            return resultats, "rapport"
    for m in _RESULTAT_TEST.finditer(journal):
        resultats.append((m["etat"], m["chemin"] or m["nom"], []))
    return resultats, "journal"


_TEST_DECLARE = re.compile(
    r"(?:IMPLEMENT_(?:SIMPLE|COMPLEX|CUSTOM_SIMPLE|CUSTOM_COMPLEX)_AUTOMATION_TEST"
    r"|BEGIN_DEFINE_SPEC|DEFINE_SPEC|IMPLEMENT_NETWORKED_AUTOMATION_TEST)"
    r"\s*\(\s*\w+\s*,\s*(?:\w+\s*,\s*)?\"([^\"]+)\"")


def familles_de_tests(racine: Path) -> list[str]:
    """Debuts de nom des tests ecrits dans le code du projet (Source/, Plugins/).

    "Project" n'est qu'une convention : les tests d'Iron Fall s'appellent
    autrement, et le filtre par defaut ne trouvait rien.
    """
    familles: list[str] = []
    for dossier in (racine / "Source", racine / "Plugins"):
        if not dossier.is_dir():
            continue
        for f in dossier.rglob("*.cpp"):
            try:
                texte = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for nom in _TEST_DECLARE.findall(texte):
                tete = nom.split(".")[0].strip()
                if tete and tete not in familles:
                    familles.append(tete)
    return familles


def lancer_tests(filtre: str = "") -> str:
    """Lance les tests automatises d'Unreal (Session Frontend) sans fenetre."""
    import json as _json
    import tempfile

    try:
        projet = analyser(_projet_ou_echec())
        moteur = dossier_moteur(projet.chemin, projet.association)
    except Echec as exc:
        return str(exc)
    exe = moteur / "Engine" / "Binaries" / "Win64" / "UnrealEditor-Cmd.exe"
    if not exe.is_file():
        return f"UnrealEditor-Cmd.exe introuvable : {exe}"
    filtre = re.sub(r"[^\w. +-]", "", filtre or "")
    if not filtre or filtre == "Project":
        familles = familles_de_tests(projet.chemin.parent)
        filtre = "+".join(familles) if familles else "Project"
    safety.guard(safety.Action(kind="compilation", summary=f"Tests Unreal : {filtre}",
                               targets=[str(projet.chemin)], routine=True))
    with tempfile.TemporaryDirectory() as dossier:
        commande = [str(exe), str(projet.chemin),
                    f"-ExecCmds=Automation RunTests {filtre};Quit",
                    "-unattended", "-nopause", "-nosplash", "-NullRHI", "-log",
                    "-stdout", "-FullStdOutLogOutput",
                    f"-ReportExportPath={dossier}",
                    "-testexit=Automation Test Queue Empty"]
        debut = time.time()
        try:
            r = subprocess.run(commande, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=DUREE_MAX_COMPILATION,
                               cwd=str(projet.chemin.parent),
                               creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
        except subprocess.TimeoutExpired:
            return "Tests arretes apres une heure : ils semblent bloques."
        except OSError as exc:
            return f"Tests impossibles a lancer : {exc}"
        rapport = None
        index = Path(dossier) / "index.json"
        if index.is_file():
            try:
                rapport = _json.loads(index.read_text(encoding="utf-8-sig"))
            except ValueError:
                rapport = None
    resultats, source = lire_rapport_tests(rapport, r.stdout + r.stderr)
    duree = time.time() - debut
    if not resultats:
        # Le plus souvent, l'editeur n'a meme pas demarre (projet pas
        # compile, module manquant) : on montre POURQUOI, pas juste « rien ».
        erreurs = [l.strip() for l in (r.stdout + r.stderr).splitlines()
                   if re.search(r"\b(Error|Fatal|missing|could not be found|"
                                r"failed to load|rebuild)\b", l, re.IGNORECASE)]
        message = (f"Aucun test n'a tourne pour « {filtre} » ({duree:.0f} s, code "
                   f"de sortie {r.returncode}).")
        if erreurs:
            message += " Erreurs d'Unreal :\n" + "\n".join(f"  {e[:240]}" for e in erreurs[-8:])
            if any(re.search(r"missing|rebuild|could not be found", e, re.IGNORECASE)
                   for e in erreurs):
                message += ("\nLe projet n'est probablement pas compile pour l'editeur : "
                            "demande « compile le projet », puis relance les tests.")
        else:
            message += (" Aucun test du projet ne porte ce nom. Tests trouves dans "
                        "le code : " + (", ".join(familles_de_tests(projet.chemin.parent))
                                        or "aucun") + ".")
        return message
    echecs = [x for x in resultats if x[0].lower() not in ("success", "succeeded")]
    lignes = [f"Tests Unreal « {filtre} » : {len(resultats) - len(echecs)} reussi(s), "
              f"{len(echecs)} en echec, en {duree:.0f} s (d'apres le {source})."]
    for etat, chemin, erreurs in echecs[:30]:
        lignes.append(f"  [ECHEC] {chemin}")
        lignes += [f"      {e[:240]}" for e in erreurs[:3]]
    return "\n".join(lignes)


# --- Le reste de la boite a outils Unreal ---------------------------------------------

def regenerer_fichiers_projet() -> str:
    """Regenere la solution Visual Studio (.sln) du projet."""
    try:
        projet = analyser(_projet_ou_echec())
        moteur = dossier_moteur(projet.chemin, projet.association)
    except Echec as exc:
        return str(exc)
    ubt = moteur / "Engine" / "Binaries" / "DotNET" / "UnrealBuildTool" / "UnrealBuildTool.exe"
    if not ubt.is_file():
        return f"UnrealBuildTool introuvable : {ubt}"
    try:
        r = subprocess.run([str(ubt), "-projectfiles", f"-project={projet.chemin}",
                            "-game", "-rocket", "-progress"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=900, cwd=str(projet.chemin.parent),
                           creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"Regeneration impossible : {exc}"
    if r.returncode == 0:
        return f"Fichiers du projet regeneres : {projet.chemin.with_suffix('.sln')}"
    fin = "\n".join((r.stdout + r.stderr).strip().splitlines()[-15:])
    return f"Echec de la regeneration (code {r.returncode}) :\n{fin}"


def nettoyer_build(ask=None) -> str:
    """Supprime Binaries et Intermediate (vers la Corbeille) : build propre."""
    try:
        projet = _projet_ou_echec()
    except Echec as exc:
        return str(exc)
    cibles = [projet.parent / d for d in ("Binaries", "Intermediate")
              if (projet.parent / d).is_dir()]
    if not cibles:
        return "Rien a nettoyer : ni Binaries ni Intermediate."
    action = safety.Action(kind="fichier", summary=f"Nettoyer le build de {projet.stem}",
                           targets=[str(c) for c in cibles], reversible=True,
                           details="Vers la Corbeille. Unreal les recree a la "
                                   "prochaine compilation.")
    try:
        if not safety.guard(action, ask=ask):
            return "Nettoyage annule."
    except safety.Refused as exc:
        return str(exc)
    from send2trash import send2trash

    for c in cibles:
        send2trash(str(c))
    return ("Binaries et Intermediate partis a la Corbeille. Recompile le projet "
            "(compiler_unreal), puis regenere les fichiers du projet si l'IDE se perd.")


def ouvrir_ide() -> str:
    """Ouvre la solution du projet dans Visual Studio ou Rider."""
    try:
        projet = _projet_ou_echec()
    except Echec as exc:
        return str(exc)
    sln = projet.with_suffix(".sln")
    if not sln.is_file():
        return (f"{sln.name} n'existe pas encore : genere-le avec "
                "regenerer_fichiers_projet.")
    try:
        os.startfile(str(sln))  # type: ignore[attr-defined]
    except (AttributeError, OSError) as exc:
        return f"Ouverture impossible : {exc}"
    return f"{sln.name} s'ouvre dans ton IDE."


def creer_classe(nom: str, parent: str = "AActor", dossier: str = "") -> tuple[str, str, str, str]:
    """(chemin .h, contenu .h, chemin .cpp, contenu .cpp) d'une classe Unreal."""
    projet = analyser(_projet_ou_echec())
    if not projet.modules:
        raise Echec("Projet sans module C++ : impossible d'y ajouter une classe.")
    module = projet.modules[0]
    prefixes = {"A": "AActor", "U": "UObject", "F": "", "S": ""}
    nom = re.sub(r"\W", "", nom)
    lettre = "A" if parent.startswith("A") else "U"
    if nom[:1] in prefixes and nom[1:2].isupper():
        nom = nom[1:]
    classe = lettre + nom
    sous = (dossier.strip("/\\") + "/") if dossier else ""
    h = f"Source/{module}/{sous}{nom}.h"
    cpp = f"Source/{module}/{sous}{nom}.cpp"
    api = f"{module.upper()}_API"
    composant = parent.endswith("Component")
    corps_h = f"""#pragma once

#include "CoreMinimal.h"
#include "{_entete_parent(parent)}"
#include "{nom}.generated.h"

UCLASS({'ClassGroup=(Custom), meta=(BlueprintSpawnableComponent)' if composant else 'Blueprintable'})
class {api} {classe} : public {parent}
{{
\tGENERATED_BODY()

public:
\t{classe}();

protected:
\tvirtual void BeginPlay() override;
}};
"""
    corps_cpp = f"""#include "{sous}{nom}.h"

{classe}::{classe}()
{{
\t{'PrimaryComponentTick' if composant else 'PrimaryActorTick'}.bCanEverTick = false;
}}

void {classe}::BeginPlay()
{{
\tSuper::BeginPlay();
}}
"""
    return h, corps_h, cpp, corps_cpp


def _entete_parent(parent: str) -> str:
    connus = {
        "AActor": "GameFramework/Actor.h", "APawn": "GameFramework/Pawn.h",
        "ACharacter": "GameFramework/Character.h",
        "APlayerController": "GameFramework/PlayerController.h",
        "AGameModeBase": "GameFramework/GameModeBase.h",
        "UActorComponent": "Components/ActorComponent.h",
        "USceneComponent": "Components/SceneComponent.h",
        "UObject": "UObject/Object.h", "UUserWidget": "Blueprint/UserWidget.h",
        "UAnimInstance": "Animation/AnimInstance.h",
    }
    return connus.get(parent, f"{parent[1:] if parent[:1] in 'AU' else parent}.h")
