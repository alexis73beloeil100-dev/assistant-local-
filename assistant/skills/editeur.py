"""Atelier Unreal, etape 3 : piloter l'editeur et les Blueprints.

L'editeur ne s'ouvre pas de l'exterieur : il faut un plugin a l'interieur.
UnrealMCP (ressources_unreal/UnrealMCP, licence MIT, voir NOTICE.txt) ecoute
sur 127.0.0.1:55557 -- la machine elle-meme, jamais le reseau -- et execute
des commandes JSON : acteurs du niveau, Blueprints, composants, noeuds,
liaisons, widgets, capture d'ecran.

Protocole : une connexion par commande ; on envoie {"type": ..., "params":
{...}} en UTF-8, l'editeur repond un objet JSON et ferme.

Les commandes qui modifient le projet passent par le garde-fou comme gestes
courants (journalises sans fenetre) : un Blueprint se construit en dizaines
de noeuds, une fenetre a chacun rendrait l'outil inutilisable, et chaque
geste se defait dans l'editeur par Ctrl+Z.
"""
from __future__ import annotations

import json
import shutil
import socket
import sys
from pathlib import Path

from assistant import safety

HOTE = "127.0.0.1"
PORT = 55557
DELAI = 20
NOM_PLUGIN = "UnrealMCP"

# Commandes qui ne font que lire : elles ne passent pas par le journal.
LECTURES = {"ping", "get_actors_in_level", "find_actors_by_name",
            "get_actor_properties", "find_blueprint_nodes"}


class Injoignable(Exception):
    """L'editeur ne repond pas sur le port du plugin."""


# --- Le plugin ---------------------------------------------------------------

def source_plugin() -> Path:
    """Le plugin livre avec l'application, en source comme dans l'exe."""
    candidats = [Path(__file__).resolve().parents[2] / "ressources_unreal" / NOM_PLUGIN]
    base = getattr(sys, "_MEIPASS", None)
    if base:
        candidats.append(Path(base) / "ressources_unreal" / NOM_PLUGIN)
    for c in candidats:
        if (c / f"{NOM_PLUGIN}.uplugin").is_file():
            return c
    raise FileNotFoundError("plugin UnrealMCP absent de l'application")


def installer_plugin(ask=None) -> str:
    """Copie le plugin dans Plugins/ du projet et l'active dans le .uproject."""
    from assistant.skills import unreal

    projet = unreal.projet_actuel()
    if projet is None:
        return "Aucun projet Unreal choisi."
    try:
        source = source_plugin()
    except FileNotFoundError as exc:
        return str(exc)
    cible = projet.parent / "Plugins" / NOM_PLUGIN
    deja = cible.exists()
    action = safety.Action(
        kind="projet",
        summary=(f"{'Mettre a jour' if deja else 'Installer'} le plugin "
                 f"d'editeur {NOM_PLUGIN} dans {projet.stem}"),
        targets=[str(cible), str(projet)],
        reversible=True,
        details="Il ecoute seulement sur cette machine (127.0.0.1:55557). "
                "Le projet devra etre recompile, editeur ferme.")
    try:
        if not safety.guard(action, ask=ask):
            return "Installation annulee."
    except safety.Refused as exc:
        return str(exc)
    if deja:
        shutil.rmtree(cible)
    shutil.copytree(source, cible)
    activer_dans_uproject(projet)
    return (f"Plugin {NOM_PLUGIN} installe dans {cible}. Ferme l'editeur, "
            "compile le projet (compiler_unreal), puis rouvre-le : le plugin "
            "demarre avec l'editeur.")


def activer_dans_uproject(projet: Path) -> None:
    donnees = json.loads(projet.read_text(encoding="utf-8-sig"))
    plugins = donnees.setdefault("Plugins", [])
    for nom in (NOM_PLUGIN, "EditorScriptingUtilities"):
        entree = next((p for p in plugins if p.get("Name") == nom), None)
        if entree is None:
            plugins.append({"Name": nom, "Enabled": True})
        else:
            entree["Enabled"] = True
    projet.write_text(json.dumps(donnees, indent="\t", ensure_ascii=False) + "\n",
                      encoding="utf-8")


# --- Parler a l'editeur ----------------------------------------------------------

def envoyer(commande: str, params: dict | None = None,
            delai: float = DELAI) -> dict:
    """Une commande, une reponse. Leve Injoignable si l'editeur est absent."""
    message = json.dumps({"type": commande, "params": params or {}}).encode("utf-8")
    try:
        with socket.create_connection((HOTE, PORT), timeout=delai) as s:
            s.sendall(message)
            recu = b""
            while True:
                morceau = s.recv(65536)
                if not morceau:
                    break
                recu += morceau
                try:
                    return json.loads(recu.decode("utf-8"))
                except ValueError:
                    continue
    except OSError as exc:
        raise Injoignable(
            "L'editeur Unreal ne repond pas : ouvre ton projet dans "
            "l'editeur. Si c'est deja fait, le plugin UnrealMCP n'est pas "
            "installe ou pas compile (outil installer_plugin_editeur).") from exc
    if not recu:
        raise Injoignable("L'editeur a ferme la connexion sans repondre.")
    return json.loads(recu.decode("utf-8", errors="replace"))


def commande(nom: str, params: dict | None = None) -> str:
    """Execute une commande et rend un texte pour le modele."""
    params = {k: v for k, v in (params or {}).items() if v not in (None, "", [])}
    if nom not in LECTURES:
        cible = params.get("blueprint_name") or params.get("name") or ""
        safety.guard(safety.Action(kind="editeur", summary=f"{nom} {cible}".strip(),
                                   targets=[json.dumps(params, ensure_ascii=False)[:300]],
                                   routine=True))
    try:
        reponse = envoyer(nom, params)
    except Injoignable as exc:
        return str(exc)
    return formater(reponse)


def formater(reponse: dict) -> str:
    if reponse.get("status") == "error" or reponse.get("success") is False:
        return "Refuse par l'editeur : " + str(
            reponse.get("error") or reponse.get("message") or reponse)
    corps = reponse.get("result", reponse)
    texte = json.dumps(corps, ensure_ascii=False, indent=1)
    return texte if len(texte) < 12000 else texte[:12000] + "\n... (coupe)"


def etat() -> str:
    try:
        envoyer("ping", delai=3)
    except Injoignable as exc:
        return str(exc)
    return "L'editeur Unreal repond : le pilotage est disponible."
