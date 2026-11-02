"""Sauvegarde chiffree, restauration apres reinitialisation, bibliotheque locale."""
from __future__ import annotations

import io
import json
import zipfile

import pytest

from assistant import licence, sauvegarde
from assistant.skills import bibliotheque


def test_chacha20_rend_exactement_le_vecteur_de_la_norme():
    """RFC 8439, section 2.4.2."""
    texte = (b"Ladies and Gentlemen of the class of '99: If I could offer you "
             b"only one tip for the future, sunscreen would be it.")
    chiffre = sauvegarde.chacha20(bytes(range(32)),
                                  bytes.fromhex("000000000000004a00000000"), texte, 1)
    assert chiffre.hex().startswith("6e2e359a2568f98041ba0728dd0d6981")
    assert chiffre.hex().endswith("5af90bbf74a35be6b40b8eedf2785e42874d")


def test_mauvais_mot_de_passe_ou_archive_modifiee_refuses():
    paquet = sauvegarde.chiffrer(b"secret", "bon-mot-de-passe")
    assert sauvegarde.dechiffrer(paquet, "bon-mot-de-passe") == b"secret"
    with pytest.raises(sauvegarde.MotDePasseFaux):
        sauvegarde.dechiffrer(paquet, "mauvais-mot-de-passe")
    abime = paquet[:-40] + bytes([paquet[-40] ^ 1]) + paquet[-39:]
    with pytest.raises(sauvegarde.MotDePasseFaux):
        sauvegarde.dechiffrer(abime, "bon-mot-de-passe")


@pytest.fixture
def pc(tmp_path, monkeypatch):
    """Un faux PC : dossier de donnees, Documents, reglages, identifiant."""
    donnees = tmp_path / "AppData" / "AssistantLocal"
    documents = tmp_path / "Documents" / "Assistant local - cle maitre"
    monkeypatch.setattr(sauvegarde.config, "DATA_DIR", donnees)
    monkeypatch.setattr(licence, "dossier_maitre", lambda: documents)
    monkeypatch.setattr(licence, "fichier_maitre",
                        lambda: documents / "cle_maitre_SECRETE.txt")
    memoire = {}
    import assistant.settings as reglages

    monkeypatch.setattr(reglages, "get", lambda k, d=None: memoire.get(k, d))
    monkeypatch.setattr(reglages, "set", lambda k, v: memoire.__setitem__(k, v))
    return donnees, documents, memoire


def test_reinitialiser_le_pc_ne_fait_rien_perdre(tmp_path, pc, monkeypatch):
    donnees, documents, memoire = pc
    (donnees / "logs").mkdir(parents=True)
    (donnees / "settings.json").write_text('{"mode_outils": "dev"}', encoding="utf-8")
    (donnees / "logs" / "actions.jsonl").write_text('{"x": 1}\n', encoding="utf-8")
    (donnees / "bibliotheque").mkdir()
    (donnees / "bibliotheque" / "bibliotheque.db").write_bytes(b"0" * 1000)

    # Ce PC : une cle maitre, et la cle publique de l'application est la sienne.
    graine = bytes(range(32))
    monkeypatch.setattr(licence, "CLE_PUBLIQUE", licence.publique_depuis_graine(graine).hex())
    documents.mkdir(parents=True)
    licence.fichier_maitre().write_text(f"{licence.ENTETE_SECRET}\n{graine.hex()}\n",
                                        encoding="utf-8")
    monkeypatch.setattr(licence, "identifiant_pc", lambda: "ancien-pc")
    memoire[licence.CLE_REGLAGE] = licence.fabriquer_cle(graine, "Alex", "ancien-pc")

    message = sauvegarde.sauvegarder(str(tmp_path / "USB"), "mot-de-passe-solide")
    archive = next((tmp_path / "USB").glob("*.alsauv"))
    assert "avec la cle maitre" in message
    assert licence.ENTETE_SECRET.encode() not in archive.read_bytes(), "la cle maitre est chiffree"
    contenu = zipfile.ZipFile(io.BytesIO(sauvegarde.dechiffrer(
        archive.read_bytes(), "mot-de-passe-solide"))).namelist()
    assert "donnees/settings.json" in contenu and sauvegarde.NOM_MAITRE in contenu
    assert not any("bibliotheque" in n for n in contenu), "ce qui se retelecharge n'y est pas"

    # Reinitialisation : tout disparait, l'identifiant du PC change.
    import shutil

    shutil.rmtree(donnees)
    shutil.rmtree(documents)
    memoire.clear()
    monkeypatch.setattr(licence, "identifiant_pc", lambda: "nouveau-pc")

    assert "refusee" in sauvegarde.restaurer(str(archive), "mauvais-mot-de-passe")
    assert not donnees.exists(), "un mauvais mot de passe ne touche a rien"

    message = sauvegarde.restaurer(str(archive), "mot-de-passe-solide")
    assert json.loads((donnees / "settings.json").read_text())["mode_outils"] == "dev"
    assert (donnees / "logs" / "actions.jsonl").is_file()
    assert licence.graine_maitre() == graine
    assert "Nouvelle cle d'acces Dev fabriquee" in message
    assert licence.examiner(memoire[licence.CLE_REGLAGE], pc="nouveau-pc")[0]


def test_un_mot_de_passe_trop_court_est_refuse(tmp_path, pc):
    assert "trop court" in sauvegarde.sauvegarder(str(tmp_path), "court")


# --- Bibliotheque locale ------------------------------------------------------------

@pytest.fixture
def bibli(tmp_path, monkeypatch):
    monkeypatch.setattr(bibliotheque, "DOSSIER", tmp_path / "bibli")
    monkeypatch.setattr(bibliotheque, "BASE", tmp_path / "bibli" / "b.db")


def _zip(fichiers: dict) -> bytes:
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w") as z:
        for nom, texte in fichiers.items():
            z.writestr(nom, texte)
    return tampon.getvalue()


def test_la_bibliotheque_indexe_et_retrouve_hors_ligne(bibli):
    archive = _zip({
        "reference/en/cpp/memory/unique_ptr.html":
            "<html><head><title>std::unique_ptr - cppreference</title></head><body>"
            "<p>std::unique_ptr is a smart pointer that owns another object.</p>"
            "<pre>auto p = std::make_unique&lt;int&gt;(5);</pre></body></html>",
        "docs/whatsnew/changelog.txt": "unique_ptr bpo-1234 bruit",
    })
    assert bibliotheque.indexer_archive("cppreference", archive) == 1
    texte = bibliotheque.chercher("unique_ptr smart pointer")
    assert "std::unique_ptr - cppreference" in texte and "changelog" not in texte
    assert "std::make_unique<int>(5);" in bibliotheque.lire(
        "reference/en/cpp/memory/unique_ptr.html")
    assert "cppreference" in bibliotheque.etat() and "1 morceaux" in bibliotheque.etat()


def test_bibliotheque_vide_dit_comment_la_remplir(bibli):
    assert "installer_bibliotheque" in bibliotheque.chercher("x")


def test_un_long_texte_est_decoupe_entre_les_paragraphes():
    texte = "\n\n".join(f"Paragraphe {i} " + "mot " * 100 for i in range(10))
    morceaux = bibliotheque.decouper(texte, 1000)
    assert len(morceaux) > 3 and all(len(m) <= 2000 for m in morceaux)
    assert all(m.startswith("Paragraphe") for m in morceaux)
