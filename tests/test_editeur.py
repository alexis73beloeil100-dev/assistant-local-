"""Atelier Unreal, etape 3 : le plugin et le dialogue avec l'editeur.

Un faux editeur ecoute pour de vrai sur 127.0.0.1, avec le meme protocole
que le plugin : un objet JSON recu, un objet JSON rendu, connexion fermee.
"""
from __future__ import annotations

import json
import socket
import threading

import pytest

from assistant import llm
from assistant.skills import editeur


@pytest.fixture
def faux_editeur(monkeypatch):
    serveur = socket.socket()
    serveur.bind(("127.0.0.1", 0))
    serveur.listen(5)
    recus, reponses = [], []

    def boucle():
        while True:
            try:
                client, _ = serveur.accept()
            except OSError:
                return
            with client:
                donnees = b""
                while True:
                    donnees += client.recv(65536)
                    try:
                        message = json.loads(donnees)
                        break
                    except ValueError:
                        continue
                recus.append(message)
                reponse = reponses.pop(0) if reponses else {
                    "status": "success", "result": {"ok": True}}
                client.sendall(json.dumps(reponse).encode())

    threading.Thread(target=boucle, daemon=True).start()
    monkeypatch.setattr(editeur, "PORT", serveur.getsockname()[1])
    monkeypatch.setattr(editeur.safety, "guard", lambda action, ask=None: True)
    monkeypatch.setattr(llm, "mode_actuel", lambda: "dev")
    yield recus, reponses
    serveur.close()


def test_une_commande_part_au_format_du_plugin(faux_editeur):
    recus, reponses = faux_editeur
    reponses.append({"status": "success", "result": {"node_id": "A1B2"}})
    texte = llm.dispatch("blueprint_noeud", {
        "blueprint": "BP_Arme", "genre": "evenement", "nom": "ReceiveBeginPlay",
        "position": [0, 0]})
    assert recus[-1] == {"type": "add_blueprint_event_node", "params": {
        "blueprint_name": "BP_Arme", "event_name": "ReceiveBeginPlay",
        "node_position": [0, 0]}}
    assert '"node_id": "A1B2"' in texte


def test_relier_deux_noeuds(faux_editeur):
    recus, _ = faux_editeur
    llm.dispatch("blueprint_relier", {"blueprint": "BP_Arme", "source": "A1",
                                      "broche_source": "then", "cible": "B2",
                                      "broche_cible": "execute"})
    assert recus[-1]["type"] == "connect_blueprint_nodes"
    assert recus[-1]["params"] == {"blueprint_name": "BP_Arme",
                                   "source_node_id": "A1", "source_pin": "then",
                                   "target_node_id": "B2", "target_pin": "execute"}


def test_les_valeurs_vides_ne_partent_pas(faux_editeur):
    recus, _ = faux_editeur
    llm.dispatch("acteur_creer", {"type": "PointLight", "nom": "Lampe"})
    assert recus[-1]["params"] == {"type": "PointLight", "name": "Lampe"}


def test_un_refus_de_l_editeur_se_lit(faux_editeur):
    _, reponses = faux_editeur
    reponses.append({"status": "error", "error": "Blueprint not found: BP_X"})
    assert llm.dispatch("blueprint_compiler", {"blueprint": "BP_X"}) == (
        "Refuse par l'editeur : Blueprint not found: BP_X")


def test_editeur_ferme_le_dit_et_propose_le_plugin(monkeypatch):
    libre = socket.socket()
    libre.bind(("127.0.0.1", 0))
    port = libre.getsockname()[1]
    libre.close()
    monkeypatch.setattr(editeur, "PORT", port)
    texte = editeur.etat()
    assert "ne repond pas" in texte and "installer_plugin_editeur" in texte


def test_installer_le_plugin_copie_et_active(tmp_path, monkeypatch):
    from assistant.skills import unreal

    projet = tmp_path / "Tireur" / "Tireur.uproject"
    projet.parent.mkdir()
    projet.write_text(json.dumps({"EngineAssociation": "5.5", "Plugins": [
        {"Name": "EditorScriptingUtilities", "Enabled": False}]}), encoding="utf-8")
    monkeypatch.setattr(unreal, "projet_actuel", lambda: projet)
    monkeypatch.setattr(editeur.safety, "guard", lambda action, ask=None: True)

    texte = editeur.installer_plugin()
    assert "installe" in texte
    plugin = projet.parent / "Plugins" / "UnrealMCP"
    assert (plugin / "UnrealMCP.uplugin").is_file()
    assert (plugin / "NOTICE.txt").is_file(), "la licence part avec le plugin"
    assert (plugin / "Source" / "UnrealMCP" / "Private" / "UnrealMCPBridge.cpp").is_file()
    actives = {p["Name"]: p["Enabled"] for p in json.loads(projet.read_text())["Plugins"]}
    assert actives == {"EditorScriptingUtilities": True, "UnrealMCP": True}


def test_le_plugin_n_ecoute_que_sur_la_machine():
    source = (editeur.source_plugin() / "Source" / "UnrealMCP" / "Private"
              / "UnrealMCPBridge.cpp").read_text(encoding="utf-8")
    assert '#define MCP_SERVER_HOST "127.0.0.1"' in source
    assert editeur.HOTE == "127.0.0.1"


def test_les_outils_de_l_editeur_sont_en_mode_dev_seulement():
    assert llm.OUTILS_EDITEUR <= llm.OUTILS_DEV
    assert llm.OUTILS_EDITEUR <= llm.OUTILS_DEV_SEULEMENT
