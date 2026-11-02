"""Atelier Unreal, etape 2 : lire, chercher, ecrire, annuler, plan, memoire,
Git, documentation, et la boucle de travail du modele."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from assistant.skills import code, web


@pytest.fixture
def projet(tmp_path, monkeypatch):
    racine = tmp_path / "Tireur"
    source = racine / "Source" / "Tireur"
    source.mkdir(parents=True)
    (racine / "Tireur.uproject").write_text("{}", encoding="utf-8")
    (source / "Arme.h").write_bytes(
        b"#pragma once\r\nUCLASS()\r\nclass TIREUR_API UArme : public UActorComponent\r\n"
        b"{\r\n\tUPROPERTY(EditAnywhere)\r\n\tint32 Munitions = 30;\r\n};\r\n")
    (source / "Arme.cpp").write_text(
        '#include "Arme.h"\nvoid UArme::Tirer() { Munitions--; }\n'
        "void UArme::Recharger() { Munitions = 30; }\n", encoding="utf-8")
    (racine / "Binaries").mkdir()
    (racine / "Binaries" / "Tireur.h").write_text("Munitions", encoding="utf-8")
    monkeypatch.setattr(code, "racine", lambda: racine.resolve())
    monkeypatch.setattr(code, "SAUVEGARDES", tmp_path / "sauvegardes")
    monkeypatch.setattr(code, "HISTORIQUE", tmp_path / "sauvegardes" / "h.json")
    monkeypatch.setattr(code.safety, "guard", lambda action, ask=None: True)
    monkeypatch.setattr(code.safety, "noter_annulation", lambda *a: None)
    return racine


# --- Le projet est une frontiere ------------------------------------------------

@pytest.mark.parametrize("chemin", ["../ailleurs.txt", "ABSOLU_HORS_PROJET",
                                    "Source/../../x.h"])
def test_rien_ne_sort_du_projet(projet, chemin):
    if chemin == "ABSOLU_HORS_PROJET":
        chemin = str(projet.parent / "Autre" / "x.h")
    with pytest.raises(code.HorsProjet):
        code.resoudre(chemin)
    assert "hors du projet" in code.creer_fichier(chemin, "x")


# --- Lire et chercher --------------------------------------------------------------

def test_lire_donne_les_numeros_de_ligne(projet):
    texte = code.lire_code("Source/Tireur/Arme.h", 5, 6)
    assert "    5  \tUPROPERTY(EditAnywhere)" in texte
    assert "    6  \tint32 Munitions = 30;" in texte
    assert "1 ligne(s) de plus" in texte


def test_chercher_ignore_ce_qu_unreal_regenere(projet):
    texte = code.chercher_code("Munitions")
    assert "Source/Tireur/Arme.h:6:" in texte
    assert "Source/Tireur/Arme.cpp:2:" in texte
    assert "Binaries" not in texte
    assert texte.startswith("3 occurrence(s) dans 2 fichier(s)")


def test_l_arborescence_cache_les_dossiers_generes(projet):
    texte = code.arborescence()
    assert "Arme.cpp" in texte and "Binaries" not in texte


# --- Ecrire ------------------------------------------------------------------------

def test_modifier_garde_les_fins_de_ligne_windows(projet):
    reponse = code.modifier_fichier("Source/Tireur/Arme.h",
                                    "int32 Munitions = 30;", "int32 Munitions = 45;")
    assert "Modifie" in reponse and "+\tint32 Munitions = 45;" in reponse
    brut = (projet / "Source" / "Tireur" / "Arme.h").read_bytes()
    assert b"int32 Munitions = 45;\r\n" in brut and b"\n" not in brut.replace(b"\r\n", b"")


def test_un_passage_absent_ou_ambigu_n_ecrit_rien(projet):
    fichier = projet / "Source" / "Tireur" / "Arme.cpp"
    avant = fichier.read_bytes()
    assert "introuvable" in code.modifier_fichier("Source/Tireur/Arme.cpp", "Viser()", "x")
    assert "2 fois" in code.modifier_fichier("Source/Tireur/Arme.cpp", "Munitions", "Balles")
    assert fichier.read_bytes() == avant
    code.modifier_fichier("Source/Tireur/Arme.cpp", "Munitions", "Balles", tout=True)
    assert fichier.read_text().count("Balles") == 2


def test_une_modification_refusee_n_ecrit_rien(projet, monkeypatch):
    fichier = projet / "Source" / "Tireur" / "Arme.h"
    avant = fichier.read_bytes()
    monkeypatch.setattr(code.safety, "guard", lambda action, ask=None: False)
    assert "refusee" in code.modifier_fichier("Source/Tireur/Arme.h", "30", "99")
    assert fichier.read_bytes() == avant


def test_annuler_rend_le_fichier_a_l_octet_pres(projet):
    fichier = projet / "Source" / "Tireur" / "Arme.h"
    avant = fichier.read_bytes()
    code.modifier_fichier("Source/Tireur/Arme.h", "= 30;", "= 12;")
    code.modifier_fichier("Source/Tireur/Arme.h", "EditAnywhere", "VisibleAnywhere")
    assert fichier.read_bytes() != avant
    code.annuler(0)  # la derniere
    code.annuler(1)
    assert fichier.read_bytes() == avant
    assert "[annulee]" in code.historique()


def test_creer_puis_annuler_la_creation(projet, monkeypatch):
    jetes = []
    import send2trash

    monkeypatch.setattr(send2trash, "send2trash", lambda p: (jetes.append(p), Path(p).unlink()))
    reponse = code.creer_fichier("Source/Tireur/Munitions.h", "#pragma once\n")
    assert "Cree" in reponse
    assert "existe deja" in code.creer_fichier("Source/Tireur/Munitions.h", "x")
    code.annuler(0)
    assert jetes and not (projet / "Source" / "Tireur" / "Munitions.h").exists()


# --- Plan et memoire ----------------------------------------------------------------

def test_le_plan_s_ecrit_et_se_coche(projet):
    code.plan(["Creer le composant", "L'ajouter a l'arme", "Compiler"])
    texte = code.plan(faites=[1, 3])
    assert texte.startswith("Plan (2/3)")
    assert "[x] 1. Creer le composant" in texte and "[ ] 2." in texte


def test_la_memoire_du_projet_est_relue(projet):
    assert code.memoire_pour_le_modele() == ""
    code.memoire_projet("Les composants sont prefixes par UAL_.")
    assert "UAL_" in code.memoire_pour_le_modele()
    assert (projet / "ASSISTANT.md").is_file()


# --- Git ----------------------------------------------------------------------------

def test_git_etat_et_enregistrement(projet):
    subprocess.run(["git", "init", "-q"], cwd=projet, check=True)
    subprocess.run(["git", "-c", "user.email=a@b", "-c", "user.name=a", "add", "-A"],
                   cwd=projet, check=True)
    subprocess.run(["git", "-c", "user.email=a@b", "-c", "user.name=a",
                    "commit", "-qm", "depart"], cwd=projet, check=True)
    code.modifier_fichier("Source/Tireur/Arme.h", "= 30;", "= 40;")
    assert "Arme.h" in code.git_etat()
    assert "+\tint32 Munitions = 40;" in code.git_difference()


# --- Documentation ------------------------------------------------------------------

def test_les_resultats_du_forum_et_de_stack_overflow_sont_lus():
    forum = {"topics": [{"id": 7, "slug": "tick-ne-part-pas", "title": "Tick ne part pas"}],
             "posts": [{"topic_id": 7, "blurb": "<b>bCanEverTick</b> = true"}]}
    assert web.resultats_forum(forum) == [
        ("Tick ne part pas", f"{web.FORUM}/t/tick-ne-part-pas/7", "bCanEverTick = true")]
    stack = {"items": [{"title": "Why &amp; how", "link": "https://so/q/1",
                        "score": 3, "is_answered": True}]}
    assert web.resultats_stack(stack) == [("Why & how", "https://so/q/1",
                                           "3 vote(s), resolue")]


def test_une_page_web_perd_son_decor_mais_garde_le_code():
    page = ("<html><head><link rel='x'><title>T</title></head><body><nav>menu</nav>"
            "<p>Active le tick :</p><pre>PrimaryComponentTick.bCanEverTick = true;</pre>"
            "<script>pub()</script></body></html>")
    texte = web.texte_de_page(page)
    assert "menu" not in texte and "pub()" not in texte and "rel=" not in texte
    assert "PrimaryComponentTick.bCanEverTick = true;" in texte


# --- La boucle du modele --------------------------------------------------------

def test_en_mode_dev_le_modele_a_trente_tours_et_ne_tourne_pas_en_rond(monkeypatch):
    from assistant import llm

    monkeypatch.setattr(llm, "mode_actuel", lambda: "dev")
    monkeypatch.setattr(llm, "avec_carte_machine", lambda m: list(m))
    monkeypatch.setattr(llm, "avec_consigne_de_mode", lambda m: list(m))
    lances = []
    monkeypatch.setattr(llm, "dispatch",
                        lambda n, a, dry_run=False: lances.append(n) or "rien")
    tours = {"n": 0}

    def appel(convo, with_tools=True, think=None):
        tours["n"] += 1
        if not with_tools:
            return {"content": "fini"}
        return {"content": "", "tool_calls": [
            {"function": {"name": "lire_code", "arguments": {"chemin": "a.h"}}}]}

    monkeypatch.setattr(llm, "_call", appel)
    reponse, convo = llm.chat([{"role": "user", "content": "x"}])
    assert lances == ["lire_code", "lire_code"], "le 3e appel identique ne part pas"
    assert any("tournes en rond" in str(m.get("content")) for m in convo)
    assert tours["n"] == llm.TOURS_DEV + 1


# --- N'importe quel projet ------------------------------------------------------

@pytest.fixture
def reglages(monkeypatch):
    memoire: dict = {}
    import assistant.settings as s

    monkeypatch.setattr(s, "get", lambda k, d=None: memoire.get(k, d))
    monkeypatch.setattr(s, "set", lambda k, v: memoire.__setitem__(k, v))
    return memoire


def test_un_projet_python_quelconque_devient_le_projet_de_travail(tmp_path, reglages,
                                                                  monkeypatch):
    app = tmp_path / "MonAppli"
    (app / "src").mkdir(parents=True)
    (app / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (app / "src" / "calcul.py").write_text("def double(x):\n    return x * 2\n",
                                           encoding="utf-8")
    message = code.choisir_projet(str(app))
    assert "MonAppli" in message and "pyproject.toml" in message
    assert code.racine() == app.resolve()
    assert "src/calcul.py:2:" in code.chercher_code("return x")
    monkeypatch.setattr(code.safety, "guard", lambda action, ask=None: True)
    assert "Modifie" in code.modifier_fichier("src/calcul.py", "x * 2", "x + x")


def test_un_dossier_avec_uproject_branche_aussi_unreal(tmp_path, reglages):
    from assistant.skills import unreal

    jeu = tmp_path / "Tireur"
    jeu.mkdir()
    (jeu / "Tireur.uproject").write_text("{}", encoding="utf-8")
    assert "projet Unreal" in code.choisir_projet(str(jeu))
    assert unreal.projet_actuel() == jeu / "Tireur.uproject"


def test_executer_lance_dans_le_projet_et_rend_la_sortie(tmp_path, reglages, monkeypatch):
    code.choisir_projet(str(tmp_path))
    monkeypatch.setattr(code.safety, "guard", lambda action, ask=None: True)
    commande = "pwd" if code.os.name != "nt" else "Get-Location"
    texte = code.executer(commande)
    assert texte.startswith("Code de sortie 0")
    assert str(tmp_path.resolve()) in texte


def test_construire_et_tester_passent_sans_fenetre_le_reste_demande(tmp_path, reglages,
                                                                    monkeypatch):
    code.choisir_projet(str(tmp_path))
    vues = []
    monkeypatch.setattr(code.safety, "guard",
                        lambda action, ask=None: vues.append(action) or False)
    code.executer("python -m pytest -q")
    code.executer("npm run build")
    code.executer("del important.txt")
    assert [a.routine for a in vues] == [True, True, False]


def test_une_commande_dangereuse_est_refusee_d_office(tmp_path, reglages):
    code.choisir_projet(str(tmp_path))
    assert code.executer("format c:").startswith("Je refuse")
