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
    if len(recents) == 1:
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

_CLASSE = re.compile(r"^\s*class\s+\w+_API\s+(\w+)", re.M)


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


def analyser(chemin: Path) -> Projet:
    donnees = lire_uproject(chemin)
    racine = chemin.parent
    source = racine / "Source"
    classes: list[str] = []
    nb = 0
    if source.is_dir():
        for f in source.rglob("*"):
            if f.suffix.lower() in (".h", ".cpp"):
                nb += 1
                if f.suffix.lower() == ".h":
                    try:
                        classes += _CLASSE.findall(
                            f.read_text(encoding="utf-8", errors="replace"))
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
        f"Code C++ {projet.fichiers_code} fichier(s) .h/.cpp, "
        f"{len(projet.classes)} classe(s) exportee(s)",
    ]
    if projet.classes:
        lignes.append("         " + ", ".join(projet.classes[:40])
                      + (" ..." if len(projet.classes) > 40 else ""))
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
