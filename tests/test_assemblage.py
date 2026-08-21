"""Verifie que les pieces sont bien reliees entre elles.

Les tests de regression figent des defauts connus. Ceux-ci verifient les
contrats : chaque outil est appelable, chaque panneau se construit, chaque
garde-fou refuse ce qu'il doit refuser.

C'est cette serie qui aurait attrape le defaut le plus grave du projet : la
demande de confirmation lisait sur l'entree standard, absente d'une
application fenetree, et toutes les actions plantaient avant d'etre proposees.
"""
from __future__ import annotations

import pytest


# --- Le catalogue d'outils ---------------------------------------------------

def test_chaque_outil_a_un_schema_valide():
    from assistant import llm

    assert len(llm.TOOLS) > 40, "le catalogue s'est vide"
    noms = set()
    for outil in llm.TOOLS:
        schema = outil.schema()
        assert schema["type"] == "function"
        fonction = schema["function"]
        assert fonction["name"] == outil.name
        assert fonction["description"].strip(), f"{outil.name} sans description"
        assert fonction["parameters"]["type"] == "object"
        for requis in fonction["parameters"].get("required", []):
            assert requis in fonction["parameters"]["properties"], (
                f"{outil.name} exige {requis} sans le declarer")
        assert outil.name not in noms, f"{outil.name} en double"
        noms.add(outil.name)


def test_les_outils_qui_agissent_sont_marques():
    """Un outil non marque ne peut pas etre simule pendant les tests.

    C'est ce marquage qui evite qu'un test lance un jeu ou supprime un
    fichier chez l'utilisateur.
    """
    from assistant import llm

    doivent_agir = {
        "executer_commande", "lancer_jeu", "nettoyer", "arreter_processus",
        "desactiver_programme_demarrage", "reactiver_programme_demarrage",
        "redemarrer_service", "vider_cache", "ouvrir_application",
        "fermer_application", "regler_volume", "changer_volume",
        "couper_son", "changer_sortie_audio", "profil_alimentation",
        "verrouiller_session", "mettre_en_veille", "eteindre_ou_redemarrer",
        "mode_jeu", "quitter_mode_jeu", "copier", "enregistrer_capture",
        "ouvrir_dans_explorateur", "annuler_arret",
        "lecture_media", "taper_au_clavier", "ouvrir_reglage_windows",
        "desinstaller_jeu", "oublier",
    }
    marques = {o.name for o in llm.TOOLS if o.effect}
    manquants = doivent_agir - marques
    assert not manquants, f"outils agissants non marques : {manquants}"


def test_un_outil_qui_agit_est_neutralise_en_simulation():
    from assistant import llm

    resultat = llm.dispatch("lancer_jeu", {"nom": "assetto"}, dry_run=True)
    assert resultat.startswith("[simulation]")


def test_un_outil_inconnu_ne_leve_pas():
    from assistant import llm

    assert "inconnu" in llm.dispatch("outil_qui_n_existe_pas", {}).lower()


def test_des_arguments_invalides_ne_levent_pas():
    """Une erreur d'outil doit revenir au modele comme du texte."""
    from assistant import llm

    resultat = llm.dispatch("chercher_fichier", {"parametre_inexistant": 1})
    assert isinstance(resultat, str) and resultat


# --- Les garde-fous ----------------------------------------------------------

def test_un_chemin_protege_est_refuse_meme_avec_un_accord():
    from assistant import safety

    action = safety.Action(
        kind="fichier",
        summary="Supprimer un dossier systeme",
        targets=["C:\\Windows\\System32"],
    )
    with pytest.raises(safety.Refused):
        safety.guard(action, ask=lambda _texte: True)


def test_sans_moyen_de_demander_l_action_est_refusee():
    """Le defaut le plus grave du projet.

    La demande de confirmation lisait sur l'entree standard. Dans une
    application fenetree il n'y en a pas : l'appel levait "lost sys.stdin" et
    l'action plantait. Elle doit desormais etre refusee proprement.
    """
    from assistant import safety

    def impossible(_texte):
        raise RuntimeError("lost sys.stdin")

    action = safety.Action(kind="registre", summary="Action de test",
                           targets=["HKCU\\Test"])
    with pytest.raises(safety.Refused):
        safety.guard(action, ask=impossible)


def test_un_refus_de_l_utilisateur_arrete_l_action():
    from assistant import safety

    action = safety.Action(kind="registre", summary="Action de test",
                           targets=["HKCU\\Test"])
    with pytest.raises(safety.Refused):
        safety.guard(action, ask=lambda _texte: False)


def test_un_accord_laisse_passer():
    from assistant import safety

    action = safety.Action(kind="registre", summary="Action de test",
                           targets=["HKCU\\Test"])
    assert safety.guard(action, ask=lambda _texte: True) is True


def test_les_processus_systeme_ne_sont_jamais_arretes():
    from assistant.skills import fixes

    for nom in ("lsass.exe", "csrss.exe", "explorer.exe", "winlogon.exe"):
        resultat = fixes.arreter_processus(nom, ask=lambda _t: True)
        assert not resultat.ok, nom
        assert "systeme" in resultat.message.lower()


def test_les_services_critiques_ne_sont_jamais_redemarres():
    from assistant.skills import fixes

    for nom in ("RpcSs", "DcomLaunch", "EventLog"):
        resultat = fixes.redemarrer_service(nom, ask=lambda _t: True)
        assert not resultat.ok, nom


# --- Les panneaux ------------------------------------------------------------

def test_chaque_panneau_se_construit_sans_lever():
    """Un panneau qui leve laisse l'utilisateur devant un ecran vide."""
    from assistant import panels

    assert len(panels.PANELS) >= 15
    for panneau in panels.PANELS:
        contenu = panels.content(panneau.key)
        assert isinstance(contenu, str)
        assert contenu.strip(), f"{panneau.key} rend un contenu vide"
        assert "Erreur pendant la preparation" not in contenu, panneau.key


def test_les_cles_de_panneaux_sont_uniques():
    from assistant import panels

    cles = [p.key for p in panels.PANELS]
    assert len(cles) == len(set(cles))


def test_l_accueil_propose_des_exemples_cliquables():
    from assistant import panels

    contenu = panels.content("accueil")
    exemples = [l for l in contenu.splitlines() if l.startswith(panels.EXEMPLE)]
    assert len(exemples) >= 8, "l'accueil doit guider un nouvel utilisateur"


# --- Les competences ---------------------------------------------------------

def test_le_catalogue_d_applications_se_construit():
    from assistant.skills import apps

    catalogue = apps.catalogue()
    assert catalogue, "aucune application detectee"
    assert all(a.nom and a.cible for a in catalogue)


def test_la_detection_de_jeux_ne_leve_pas():
    from assistant.skills import games

    for jeu in games.all_games():
        assert jeu.name and jeu.launcher and jeu.game_id


def test_un_fichier_binaire_n_est_pas_lu_comme_du_texte():
    from assistant.skills import content

    assert content.kind("photo.png") == "binaire"
    assert content.kind("notes.txt") == "text"
    assert content.kind("rapport.pdf") == "rich"


def test_une_image_est_reconnue_comme_telle():
    from assistant.skills import vision

    assert vision.is_image("capture.png")
    assert vision.is_image("PHOTO.JPG")
    assert not vision.is_image("document.pdf")


# --- L'autotest --------------------------------------------------------------

def test_l_autotest_couvre_les_points_essentiels():
    from assistant import selftest

    noms = [nom for nom, _fonction, _essentiel in selftest.VERIFICATIONS]
    assert len(noms) >= 10
    essentiels = [nom for nom, _f, essentiel in selftest.VERIFICATIONS if essentiel]
    assert "Releve materiel" in essentiels
    assert "Disques" in essentiels


# --- Le panneau affiche, joint a la conversation -----------------------------
#
# Les panneaux et la conversation s'ignoraient : le modele n'avait aucune idee
# de ce qui etait affiche. Ces contrats verifient que la passerelle tient.

def test_un_panneau_consulte_devient_du_contexte():
    from assistant import panels

    panels._cache["problemes"] = "PROBLEMES DETECTES\n\n  [GRAVE] Disque plein"
    joint = panels.contexte("problemes")

    assert joint is not None
    libelle, contenu = joint
    assert libelle == panels.BY_KEY["problemes"].label
    assert "Disque plein" in contenu


def test_un_panneau_jamais_ouvert_ne_declenche_aucun_calcul():
    """contexte() ne doit lire que le cache.

    Sinon une question sans rapport declencherait un releve materiel de six
    secondes, simplement parce que l'utilisateur a effleure un menu.
    """
    from assistant import panels

    panels._cache.pop("autotest", None)
    assert panels.contexte("autotest") is None


def test_l_accueil_n_est_jamais_joint():
    """C'est un mode d'emploi, pas une donnee sur la machine.

    Ses lignes d'exemple pourraient en plus etre prises pour des consignes.
    """
    from assistant import panels

    panels._cache["accueil"] = "BIENVENUE\n>> Quelle est la configuration ?"
    assert panels.contexte("accueil") is None


def test_un_panneau_trop_long_est_coupe_par_le_bas():
    """Les panneaux mettent l'essentiel en tete : on garde la tete."""
    from assistant import panels

    panels._cache["espace"] = "DEBUT IMPORTANT\n" + ("x" * panels.CONTEXTE_MAX * 2)
    joint = panels.contexte("espace")

    assert joint is not None
    _libelle, contenu = joint
    assert contenu.startswith("DEBUT IMPORTANT")
    assert len(contenu) < panels.CONTEXTE_MAX + 200


def test_le_contexte_est_presente_comme_une_donnee():
    """Un panneau affiche du texte venu d'ailleurs -- noms de fichiers,
    messages du journal Windows. Il ne doit jamais etre lu comme une consigne.
    """
    from assistant import llm

    message = llm.message_de_contexte("Problemes detectes", "  [GRAVE] rien")

    assert message["role"] == "system"
    assert "DONNEE" in message["content"]
    assert message["content"].startswith(llm.CONTEXTE_MARQUEUR)


def test_le_contexte_est_remplace_et_jamais_empile():
    """Cinq questions devant le meme panneau ne doivent pas laisser cinq
    copies de son contenu dans l'historique."""
    from assistant import llm

    convo = [{"role": "system", "content": "regles"}]
    for _ in range(5):
        convo = llm.sans_contexte(convo)
        convo.append(llm.message_de_contexte("Mes jeux", "un jeu"))
        convo.append({"role": "user", "content": "et alors ?"})

    contextes = [m for m in convo
                 if str(m.get("content", "")).startswith(llm.CONTEXTE_MARQUEUR)]
    assert len(contextes) == 1
    assert convo[0]["content"] == "regles", "le message systeme doit survivre"


def test_le_modele_sait_qu_il_peut_se_servir_du_panneau():
    """Sans cette regle, il rappelle l'outil pour retrouver ce qu'il a deja."""
    from assistant import llm

    assert "panneau" in llm.SYSTEM_PROMPT
