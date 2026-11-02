"""La cle d'acces au mode Dev : signature, PC, expiration, et le secret."""
from __future__ import annotations

import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest

from assistant import licence

RACINE = Path(__file__).resolve().parent.parent

GRAINE = bytes(range(32))
PUBLIQUE = licence.publique_depuis_graine(GRAINE).hex()


@pytest.mark.parametrize("graine,publique,message,signature", [
    # RFC 8032, section 7.1, tests 1 et 2.
    ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
     "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
     "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
     "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
    ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
     "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
     "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
     "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
])
def test_ed25519_rend_exactement_les_vecteurs_de_la_norme(graine, publique,
                                                          message, signature):
    g, m = bytes.fromhex(graine), bytes.fromhex(message)
    assert licence.publique_depuis_graine(g).hex() == publique
    assert licence.signer(g, m).hex() == signature
    assert licence.verifier_signature(bytes.fromhex(publique), m,
                                      bytes.fromhex(signature))


def test_une_cle_valide_ouvre_le_mode_dev():
    cle = licence.fabriquer_cle(GRAINE, "Alex", pc="abc123")
    valide, raison = licence.examiner(cle, PUBLIQUE, pc="abc123")
    assert valide and "Alex" in raison and "sans fin" in raison


def test_chaque_caractere_modifie_fait_refuser_la_cle():
    """Changer le nom, l'identifiant ou la date casse la signature."""
    cle = licence.fabriquer_cle(GRAINE, "Alex", pc="abc123")
    refus = 0
    for i in range(len(licence.PREFIXE), len(cle)):
        if cle[i] == ".":
            continue
        autre = "A" if cle[i] != "A" else "B"
        if not licence.examiner(cle[:i] + autre + cle[i + 1:], PUBLIQUE,
                                pc="abc123")[0]:
            refus += 1
    modifiables = len(cle) - len(licence.PREFIXE) - 1
    # Le dernier caractere base64 porte des bits ignores : une seule
    # retouche par moitie de cle peut tomber dessus sans rien changer.
    assert refus >= modifiables - 2


def test_une_cle_fabriquee_sans_la_cle_maitre_est_refusee():
    fausse = licence.fabriquer_cle(bytes(32), "Pirate")
    valide, raison = licence.examiner(fausse, PUBLIQUE, pc="")
    assert not valide and "signature invalide" in raison


def test_une_cle_ne_marche_pas_sur_un_autre_pc():
    cle = licence.fabriquer_cle(GRAINE, "Alex", pc="abc123")
    valide, raison = licence.examiner(cle, PUBLIQUE, pc="autre")
    assert not valide and "autre PC" in raison


def test_une_cle_expiree_le_dit_avec_sa_date():
    cle = licence.fabriquer_cle(GRAINE, "Abonne", fin="2026-12-31")
    assert licence.examiner(cle, PUBLIQUE, pc="", aujourd_hui=date(2026, 12, 31))[0]
    valide, raison = licence.examiner(cle, PUBLIQUE, pc="",
                                      aujourd_hui=date(2027, 1, 1))
    assert not valide and "31/12/2026" in raison


def test_sans_cle_publique_installee_tout_reste_ferme():
    cle = licence.fabriquer_cle(GRAINE, "Alex")
    valide, raison = licence.examiner(cle, "", pc="")
    assert not valide and "clé maître" in raison


def test_le_mode_dev_reste_ferme_sans_cle(monkeypatch):
    from assistant import llm

    memoire = {"mode_outils": "dev"}
    monkeypatch.setattr(llm, "mode_actuel", llm.mode_actuel)
    import assistant.settings as reglages

    monkeypatch.setattr(reglages, "get", lambda k, d=None: memoire.get(k, d))
    monkeypatch.setattr(reglages, "set", lambda k, v: memoire.__setitem__(k, v))
    monkeypatch.setattr(licence, "dev_autorise", lambda: False)

    assert llm.mode_actuel() == "pc", "un reglage edite a la main n'ouvre rien"
    with pytest.raises(llm.ModeVerrouille):
        llm.changer_mode("dev")

    monkeypatch.setattr(licence, "dev_autorise", lambda: True)
    llm.changer_mode("dev")
    assert llm.mode_actuel() == "dev"


def test_aucune_cle_secrete_n_est_dans_le_depot():
    """La cle maitre ne doit JAMAIS partir sur GitHub."""
    suivis = subprocess.run(["git", "ls-files"], cwd=RACINE,
                            capture_output=True, text=True).stdout.split("\n")
    fautifs = []
    for nom in filter(None, suivis):
        chemin = RACINE / nom
        if nom.endswith("test_licence_dev.py") or nom.endswith("licence.py"):
            continue
        try:
            if licence.ENTETE_SECRET in chemin.read_text(encoding="utf-8",
                                                         errors="ignore"):
                fautifs.append(nom)
        except OSError:
            continue
    assert not fautifs, f"cle maitre dans le depot : {fautifs}"
    assert "cle_maitre" in (RACINE / ".gitignore").read_text(encoding="utf-8")


def test_la_cle_maitre_ne_s_ecrase_jamais(tmp_path, monkeypatch):
    monkeypatch.setattr(licence, "dossier_maitre", lambda: tmp_path)
    monkeypatch.setattr(licence, "fichier_maitre",
                        lambda: tmp_path / "cle_maitre_SECRETE.txt")
    publique = licence.creer_cle_maitre()
    graine = licence.graine_maitre()
    assert graine and licence.publique_depuis_graine(graine).hex() == publique
    with pytest.raises(FileExistsError):
        licence.creer_cle_maitre()
    assert licence.graine_maitre() == graine


# --- Essai gratuit -------------------------------------------------------------

@pytest.fixture
def traces(monkeypatch, tmp_path):
    """Les trois endroits de l'essai, dans un dossier jetable."""
    registre = {"e": ""}
    monkeypatch.setattr(licence, "_lire_registre", lambda: registre["e"])
    monkeypatch.setattr(licence, "_ecrire_registre",
                        lambda v: registre.__setitem__("e", v))
    fichiers = [tmp_path / "appdata" / "essai.dat", tmp_path / "commun" / "essai.dat"]
    monkeypatch.setattr(licence, "_fichiers_essai", lambda: fichiers)
    monkeypatch.setattr(licence, "identifiant_pc", lambda: "pc-test")
    return registre, fichiers


def test_l_essai_dure_trente_jours_puis_se_ferme(traces):
    debut = date(2026, 11, 2)
    assert licence.etat_essai(debut) == ("jamais", 30)
    assert licence.commencer_essai(debut)[0]
    assert licence.etat_essai(debut + timedelta(days=29)) == ("actif", 1)
    assert licence.etat_essai(debut + timedelta(days=30)) == ("fini", 0)
    ok, raison = licence.commencer_essai(debut + timedelta(days=31))
    assert not ok and "termine" in raison


def test_reinstaller_ou_effacer_deux_traces_sur_trois_ne_remet_pas_a_zero(traces):
    registre, fichiers = traces
    debut = date(2026, 11, 2)
    licence.commencer_essai(debut)
    # Desinstaller-reinstaller ne touche a aucune trace ; on en efface deux.
    registre["e"] = ""
    fichiers[0].unlink()
    assert licence.etat_essai(debut + timedelta(days=40)) == ("fini", 0)
    # Et la trace effacee est reecrite a la verification suivante.
    licence.etat_essai(debut + timedelta(days=41))
    assert registre["e"] and fichiers[0].is_file()


def test_modifier_la_date_a_la_main_ferme_l_essai(traces):
    registre, fichiers = traces
    licence.commencer_essai(date(2026, 11, 2))
    for f in fichiers:
        f.write_text(f.read_text().replace("2026-11-02", "2027-11-02", 1))
    registre["e"] = registre["e"].replace("2026-11-02", "2027-11-02", 1)
    assert licence.etat_essai(date(2026, 11, 10)) == ("fini", 0)


def test_reculer_l_horloge_ne_rend_pas_de_jours(traces):
    debut = date(2026, 11, 2)
    licence.commencer_essai(debut)
    licence.etat_essai(debut + timedelta(days=20))
    assert licence.etat_essai(debut + timedelta(days=2)) == ("fini", 0)


def test_les_traces_d_un_autre_pc_ne_comptent_pas(traces, monkeypatch):
    debut = date(2026, 11, 2)
    licence.commencer_essai(debut)
    monkeypatch.setattr(licence, "identifiant_pc", lambda: "autre-pc")
    assert licence.etat_essai(debut + timedelta(days=60))[0] == "jamais"


def test_l_essai_actif_ouvre_le_mode_dev_sans_cle(traces, monkeypatch):
    monkeypatch.setattr(licence, "cle_enregistree", lambda: "")
    assert not licence.dev_autorise()
    licence.commencer_essai()
    assert licence.dev_autorise()


def test_la_cle_publique_du_proprietaire_est_inscrite_et_valide():
    cle = bytes.fromhex(licence.CLE_PUBLIQUE)
    assert len(cle) == 32
    licence._decoder(cle)  # leve si ce n'est pas un point de la courbe
    # Une cle fabriquee par n'importe quelle autre cle maitre est refusee.
    autre = licence.fabriquer_cle(GRAINE, "Pirate")
    assert not licence.examiner(autre, pc="")[0]
