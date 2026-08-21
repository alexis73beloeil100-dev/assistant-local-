"""Icones dessinees au trait, sans le moindre fichier image.

Pourquoi les dessiner plutot que les charger. L'application est hors ligne et
packagee : chaque image embarquee est un fichier de plus a copier dans le
bundle, a declarer dans le .spec, et a retrouver via _MEIPASS. Un trace tient
en quelques lignes, se recolore d'un attribut, et suit n'importe quelle taille
sans crenelage.

Le trait est volontairement fin et anguleux : c'est la meme direction que le
reste de l'interface -- lecture d'instrument, pas de bouton d'application
grand public. Chaque icone est dessinee dans un carre de 0 a 1, puis mise a
l'echelle : ajouter une icone ne demande donc jamais de calculer des pixels.
"""
from __future__ import annotations

import tkinter as tk

# Epaisseur du trait, en fraction de la taille de l'icone. Sous 0,06 le trait
# disparait sur un ecran dense ; au-dela de 0,11 l'icone devient une tache.
#
# 0,09 pour tenir le meme poids que les libelles, passes en demi-gras : une
# icone au trait fin a cote d'un mot epais se lit comme un element desactive.
EPAISSEUR = 0.09


def _t(x: float, y: float, ox: float, oy: float, taille: float):
    """Passe des coordonnees normalisees (0 a 1) aux pixels du canvas."""
    return ox + x * taille, oy + y * taille


def _ligne(canvas, points, ox, oy, taille, couleur, largeur, **kw):
    plats = []
    for x, y in points:
        px, py = _t(x, y, ox, oy, taille)
        plats.extend((px, py))
    return canvas.create_line(*plats, fill=couleur, width=largeur,
                              capstyle="round", joinstyle="round", **kw)


def _rect(canvas, x1, y1, x2, y2, ox, oy, taille, couleur, largeur, **kw):
    ax, ay = _t(x1, y1, ox, oy, taille)
    bx, by = _t(x2, y2, ox, oy, taille)
    return canvas.create_rectangle(ax, ay, bx, by, outline=couleur,
                                   width=largeur, **kw)


def _ovale(canvas, x1, y1, x2, y2, ox, oy, taille, couleur, largeur, **kw):
    ax, ay = _t(x1, y1, ox, oy, taille)
    bx, by = _t(x2, y2, ox, oy, taille)
    return canvas.create_oval(ax, ay, bx, by, outline=couleur, width=largeur,
                              **kw)


# --- Les traces --------------------------------------------------------------
#
# Chaque fonction dessine dans le carre unite. Elles rendent la liste des
# identifiants crees, pour pouvoir tout recolorer au survol.

def _puce(c, ox, oy, s, col, w):
    """Processeur : un carre et ses broches."""
    ids = [_rect(c, .25, .25, .75, .75, ox, oy, s, col, w),
           _rect(c, .40, .40, .60, .60, ox, oy, s, col, w)]
    for f in (.36, .5, .64):
        ids += [_ligne(c, [(f, .10), (f, .25)], ox, oy, s, col, w),
                _ligne(c, [(f, .75), (f, .90)], ox, oy, s, col, w),
                _ligne(c, [(.10, f), (.25, f)], ox, oy, s, col, w),
                _ligne(c, [(.75, f), (.90, f)], ox, oy, s, col, w)]
    return ids


def _alerte(c, ox, oy, s, col, w):
    """Triangle d'avertissement."""
    return [_ligne(c, [(.5, .14), (.90, .82), (.10, .82), (.5, .14)],
                   ox, oy, s, col, w),
            _ligne(c, [(.5, .40), (.5, .60)], ox, oy, s, col, w),
            _ligne(c, [(.5, .70), (.5, .72)], ox, oy, s, col, w)]


def _pouls(c, ox, oy, s, col, w):
    """Battement : la ligne d'un moniteur cardiaque."""
    return [_ligne(c, [(.08, .5), (.28, .5), (.38, .24), (.52, .78),
                       (.62, .5), (.92, .5)], ox, oy, s, col, w)]


def _jauge(c, ox, oy, s, col, w):
    """Cadran et aiguille."""
    ax, ay = _t(.10, .18, ox, oy, s)
    bx, by = _t(.90, .98, ox, oy, s)
    return [c.create_arc(ax, ay, bx, by, start=20, extent=140, style="arc",
                         outline=col, width=w),
            _ligne(c, [(.5, .62), (.70, .36)], ox, oy, s, col, w)]


def _manette(c, ox, oy, s, col, w):
    """Manette de jeu."""
    return [_ligne(c, [(.30, .32), (.70, .32)], ox, oy, s, col, w),
            _ligne(c, [(.30, .32), (.12, .62), (.22, .72), (.36, .58),
                       (.64, .58), (.78, .72), (.88, .62), (.70, .32)],
                   ox, oy, s, col, w),
            _ligne(c, [(.26, .45), (.38, .45)], ox, oy, s, col, w),
            _ligne(c, [(.32, .39), (.32, .51)], ox, oy, s, col, w),
            _ovale(c, .62, .42, .70, .50, ox, oy, s, col, w)]


def _disque(c, ox, oy, s, col, w):
    """Plateau de disque, vu de dessus."""
    return [_ovale(c, .10, .10, .90, .90, ox, oy, s, col, w),
            _ovale(c, .43, .43, .57, .57, ox, oy, s, col, w),
            _ligne(c, [(.62, .38), (.80, .26)], ox, oy, s, col, w)]


def _dossier(c, ox, oy, s, col, w):
    return [_ligne(c, [(.10, .78), (.10, .26), (.42, .26), (.50, .38),
                       (.90, .38), (.90, .78), (.10, .78)],
                   ox, oy, s, col, w)]


def _alimentation(c, ox, oy, s, col, w):
    """Bouton marche/arret."""
    ax, ay = _t(.18, .18, ox, oy, s)
    bx, by = _t(.82, .82, ox, oy, s)
    return [c.create_arc(ax, ay, bx, by, start=65, extent=290, style="arc",
                         outline=col, width=w),
            _ligne(c, [(.5, .08), (.5, .44)], ox, oy, s, col, w)]


def _cle(c, ox, oy, s, col, w):
    """Cle a molette, en diagonale."""
    return [_ovale(c, .12, .12, .44, .44, ox, oy, s, col, w),
            _ligne(c, [(.36, .36), (.86, .86)], ox, oy, s, col, w),
            _ligne(c, [(.74, .86), (.86, .86), (.86, .74)],
                   ox, oy, s, col, w)]


def _curseurs(c, ox, oy, s, col, w):
    """Trois reglages, poignees a des hauteurs differentes."""
    ids = []
    for i, (y, poignee) in enumerate(((.28, .34), (.5, .64), (.72, .46))):
        ids.append(_ligne(c, [(.12, y), (.88, y)], ox, oy, s, col, w))
        ids.append(_ovale(c, poignee - .06, y - .06, poignee + .06, y + .06,
                          ox, oy, s, col, w, fill=col))
    return ids


def _grille(c, ox, oy, s, col, w):
    ids = []
    for x in (.14, .54):
        for y in (.14, .54):
            ids.append(_rect(c, x, y, x + .32, y + .32, ox, oy, s, col, w))
    return ids


def _fusee(c, ox, oy, s, col, w):
    return [_ligne(c, [(.5, .08), (.66, .34), (.66, .68), (.34, .68),
                       (.34, .34), (.5, .08)], ox, oy, s, col, w),
            _ligne(c, [(.34, .52), (.18, .70), (.34, .68)], ox, oy, s, col, w),
            _ligne(c, [(.66, .52), (.82, .70), (.66, .68)], ox, oy, s, col, w),
            _ligne(c, [(.44, .78), (.44, .90)], ox, oy, s, col, w),
            _ligne(c, [(.56, .78), (.56, .90)], ox, oy, s, col, w)]


def _cloche(c, ox, oy, s, col, w):
    return [_ligne(c, [(.22, .68), (.30, .56), (.30, .40), (.70, .40),
                       (.70, .56), (.78, .68), (.22, .68)],
                   ox, oy, s, col, w),
            _ligne(c, [(.42, .40), (.42, .30), (.58, .30), (.58, .40)],
                   ox, oy, s, col, w),
            _ligne(c, [(.43, .76), (.57, .76)], ox, oy, s, col, w)]


def _note(c, ox, oy, s, col, w):
    ids = [_rect(c, .20, .12, .80, .88, ox, oy, s, col, w)]
    for y in (.34, .50, .66):
        ids.append(_ligne(c, [(.32, y), (.68, y)], ox, oy, s, col, w))
    return ids


def _terminal(c, ox, oy, s, col, w):
    return [_rect(c, .10, .20, .90, .80, ox, oy, s, col, w),
            _ligne(c, [(.26, .40), (.40, .50), (.26, .60)], ox, oy, s, col, w),
            _ligne(c, [(.50, .62), (.72, .62)], ox, oy, s, col, w)]


def _registre(c, ox, oy, s, col, w):
    """Journal : des lignes, et une coche."""
    ids = [_rect(c, .14, .12, .86, .88, ox, oy, s, col, w)]
    for y in (.32, .48):
        ids.append(_ligne(c, [(.28, y), (.72, y)], ox, oy, s, col, w))
    ids.append(_ligne(c, [(.30, .66), (.42, .76), (.68, .58)],
                      ox, oy, s, col, w))
    return ids


def _bouclier(c, ox, oy, s, col, w):
    return [_ligne(c, [(.5, .10), (.84, .26), (.84, .54), (.5, .90),
                       (.16, .54), (.16, .26), (.5, .10)],
                   ox, oy, s, col, w),
            _ligne(c, [(.34, .48), (.46, .60), (.68, .38)],
                   ox, oy, s, col, w)]


def _boussole(c, ox, oy, s, col, w):
    return [_ovale(c, .10, .10, .90, .90, ox, oy, s, col, w),
            _ligne(c, [(.36, .64), (.64, .36), (.64, .36)],
                   ox, oy, s, col, w),
            _ligne(c, [(.64, .36), (.56, .56), (.36, .64)],
                   ox, oy, s, col, w)]


def _parole(c, ox, oy, s, col, w):
    """Conversation : une bulle et une onde."""
    return [_ligne(c, [(.14, .70), (.14, .22), (.86, .22), (.86, .62),
                       (.40, .62), (.24, .80), (.24, .62), (.14, .62)],
                   ox, oy, s, col, w),
            _ligne(c, [(.32, .42), (.32, .42)], ox, oy, s, col, w),
            _ligne(c, [(.42, .36), (.42, .48)], ox, oy, s, col, w),
            _ligne(c, [(.52, .32), (.52, .52)], ox, oy, s, col, w),
            _ligne(c, [(.62, .38), (.62, .46)], ox, oy, s, col, w)]


def _cerveau(c, ox, oy, s, col, w):
    """Ce que l'assistant sait : un reseau de noeuds relies."""
    noeuds = [(.24, .30), (.52, .18), (.78, .36),
              (.20, .62), (.50, .52), (.76, .70), (.44, .82)]
    ids = [_ligne(c, [noeuds[0], noeuds[1], noeuds[2]], ox, oy, s, col, w),
           _ligne(c, [noeuds[0], noeuds[4], noeuds[2]], ox, oy, s, col, w),
           _ligne(c, [noeuds[3], noeuds[4], noeuds[5]], ox, oy, s, col, w),
           _ligne(c, [noeuds[3], noeuds[6], noeuds[5]], ox, oy, s, col, w)]
    for x, y in noeuds:
        ids.append(_ovale(c, x - .055, y - .055, x + .055, y + .055,
                          ox, oy, s, col, w, fill=col))
    return ids


TRACES = {
    "cerveau": _cerveau,
    "puce": _puce,
    "alerte": _alerte,
    "pouls": _pouls,
    "jauge": _jauge,
    "manette": _manette,
    "disque": _disque,
    "dossier": _dossier,
    "alimentation": _alimentation,
    "cle": _cle,
    "curseurs": _curseurs,
    "grille": _grille,
    "fusee": _fusee,
    "cloche": _cloche,
    "note": _note,
    "terminal": _terminal,
    "registre": _registre,
    "bouclier": _bouclier,
    "boussole": _boussole,
    "parole": _parole,
}


def dessiner(canvas: tk.Canvas, nom: str, ox: float, oy: float,
             taille: float, couleur: str) -> list[int]:
    """Trace une icone et rend les identifiants crees.

    Un nom inconnu ne dessine rien plutot que de lever : une icone manquante
    ne doit jamais empecher la barre laterale de s'afficher.
    """
    trace = TRACES.get(nom)
    if trace is None:
        return []
    largeur = max(1, round(EPAISSEUR * taille))
    return trace(canvas, ox, oy, taille, couleur, largeur)
