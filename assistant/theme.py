"""Palette et reglages visuels, en un seul endroit.

Direction : affichage tete haute technique. Bahnschrift, la police derivee du
DIN que Windows fournit, en demi-gras. Cascadia Mono pour les mesures. Traits
fins, angles coupes, libelles en capitales espacees.

Deux corrections importantes par rapport a la premiere version :

  - Le cyan pur (#00E5FF) sur un noir quasi absolu fatiguait les yeux. Un
    bleu-vert tres sature sur fond tres sombre cree un halo autour des
    lettres : l'oeil n'arrive pas a faire la mise au point sur les deux
    couleurs a la fois. Le cyan a ete desature et le fond remonte.

  - Les textes etaient trop fins. Sur fond sombre, un trait fin clair
    "brule" et devient penible a lire. Tout est passe en demi-gras, d'un
    corps au-dessus.

Ce qui reste ecarte : l'aplat bleu sur l'element selectionne, signature de
Windows. Un liseret cyan a gauche marque la selection sans remplir la ligne.

Tkinter n'a pas de feuille de style : sans ce module, les couleurs se
retrouvent recopiees dans quarante appels de widgets et la moindre retouche
devient un travail de fourmi.
"""
from __future__ import annotations

# --- Couleurs ---------------------------------------------------------------
#
# Le fond n'est pas un noir absolu : un ecart de luminosite trop grand avec
# le texte est ce qui fatigue. On reste sombre, mais on respire.

BG          = "#0C1319"   # fond de la fenetre, ardoise bleutee
SURFACE     = "#131D25"   # panneaux, barre laterale
SURFACE_2   = "#1D2A34"   # survol, champs de saisie
BORDER      = "#2A414C"   # traits fins, visibles sans etre durs

# Abaisse le 24/08/2026, a la demande de l'utilisateur : "trop lumineux, ca
# fait mal aux yeux". C'est le defaut classique du mode sombre -- un blanc
# presque pur sur un fond presque noir "bave" sur ses bords (halation), et
# l'oeil corrige en permanence.
#
# Le remede est double, et l'un sans l'autre echoue : on baisse la luminosite,
# ce qui amincirait le trait, et on monte la graisse pour le compenser. On
# reste tres au-dessus du seuil AAA -- 8.60 sur le fond le plus clair, la ou
# 7 suffit.
TEXT        = "#B8C9D2"   # texte principal
TEXT_DIM    = "#9BB6C2"   # remonte : l'ancien gris etait trop efface
# Remonte le 24/08/2026, apres mesure. L'ancien #66838F donnait 4.23 sur
# SURFACE et 3.63 sur SURFACE_2, sous les 4.5 exiges par WCAG pour du texte
# normal. C'etait la SEULE couleur du theme a ne pas passer -- et c'est celle
# des explications sous les libelles, donc precisement le texte qu'on lit
# quand on ne sait pas quoi faire.
TEXT_FAINT  = "#7895A1"   # 5.89 / 5.38 / 4.61 sur BG / SURFACE / SURFACE_2

ACCENT      = "#4FD3E6"   # cyan desature : le meme registre, sans le halo
ACCENT_SOFT = "#12303A"   # fond du cyan
ACCENT_DEEP = "#2E93A6"   # cyan eteint, pour les traits secondaires

GOLD        = "#F5B845"   # secondaire chaud, a doser
GREEN       = "#4FE0A8"
AMBER       = "#F5B845"
RED         = "#FF6B78"

# --- Typographie ------------------------------------------------------------
#
# Bahnschrift est la police technique fournie avec Windows 10 et 11. Sa
# variante SemiBold donne l'epaisseur qui manquait, et sa construction
# geometrique porte le registre "instrument" mieux que Segoe UI.

_UI = "Bahnschrift SemiBold"
_UI_LEGER = "Bahnschrift"

# Cascadia Mono SemiBold, pas Cascadia Mono. Meme famille, meme chasse -- donc
# les colonnes des relevés restent alignees au pixel -- mais une graisse
# au-dessus. Sur fond sombre, le trait normal "brule" et se lit mal ; c'est la
# meme correction que celle deja faite sur les libelles de l'interface.
#
# La variante est verifiee presente avant usage (voir mono_disponible) : sur
# une machine ou elle manque, Tk se rabat silencieusement sur une police
# proportionnelle et tous les tableaux partent en accordeon.
_MONO = "Cascadia Mono SemiBold"
_MONO_REPLI = "Cascadia Mono"

FONT_UI        = (_UI, 11, "bold")
FONT_UI_SMALL  = (_UI, 10, "bold")
# Les libelles des cases de navigation. En Bahnschrift maigre ils s'effacaient
# a cote de leur icone ; en demi-gras, l'icone et le mot ont le meme poids.
FONT_UI_TINY   = (_UI, 9, "bold")
FONT_TITLE     = (_UI, 16)
FONT_LABEL     = (_UI, 11, "bold")
FONT_INPUT     = (_UI, 12, "bold")


def mono_disponible(nom: str) -> bool:
    """La police est-elle reellement installee ?

    Tk ne signale pas une famille absente : il en substitue une autre, souvent
    proportionnelle, et les colonnes des relevés se decalent sans que rien
    n'explique pourquoi. On verifie donc avant de choisir.
    """
    try:
        import tkinter.font as tkfont

        return nom in set(tkfont.families())
    except Exception:  # noqa: BLE001 - pas de racine Tk : on verra plus tard
        return True


def police_mono() -> str:
    return _MONO if mono_disponible(_MONO) else _MONO_REPLI


# Les sorties de mesure sont des colonnes alignees : elles exigent une largeur
# fixe, sinon les tailles et les chemins partent en accordeon.
#
# Resolues a la construction de la fenetre, pas a l'import : interroger la
# liste des polices demande une racine Tk, qui n'existe pas encore ici.
FONT_MONO      = (_MONO, 10)
FONT_MONO_BOLD = (_MONO, 10, "bold")
FONT_MONO_TITRE = (_MONO, 11, "bold")


def resoudre_polices() -> None:
    """Retombe sur la graisse normale si la demi-grasse manque.

    Appele une fois, apres la creation de la fenetre.
    """
    global FONT_MONO, FONT_MONO_BOLD, FONT_MONO_TITRE
    famille = police_mono()
    FONT_MONO = (famille, 10, "bold")
    FONT_MONO_BOLD = (famille, 10, "bold")
    FONT_MONO_TITRE = (famille, 11, "bold")


# Les titres de section : capitales espacees, comme une legende d'instrument.
FONT_HUD       = (_UI, 9)


def espacer(texte: str) -> str:
    """Ecarte les lettres d'un libelle.

    Tkinter ne gere pas l'interlettrage. Sur un titre court en capitales, un
    espace entre chaque caractere donne le meme effet et coute une ligne.
    """
    return " ".join(texte.upper())


# --- Espacements ------------------------------------------------------------

PAD = 8          # unite de base ; tout est un multiple
PAD_L = 16
PAD_XL = 24

RADIUS = 10      # rayon simule des cartes
CHAMFER = 7      # taille du coin coupe des boutons


def hover(widget, normal: str, over: str) -> None:
    """Effet de survol sur un widget Tk, qui n'en propose aucun nativement."""
    widget.bind("<Enter>", lambda _e: widget.configure(bg=over))
    widget.bind("<Leave>", lambda _e: widget.configure(bg=normal))
