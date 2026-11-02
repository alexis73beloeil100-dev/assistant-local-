"""Briques d'interface que Tkinter ne fournit pas.

Tk s'arrete aux widgets rectangulaires gris. Coins arrondis, zone defilante
et cartes de message se construisent a la main, sur un Canvas.
"""
from __future__ import annotations

import re
import tkinter as tk

from assistant import theme as t


def rounded_rect(canvas: tk.Canvas, x1, y1, x2, y2, r, **kwargs):
    """Rectangle a coins arrondis : Tk ne connait que les angles droits."""
    points = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


def chamfered(canvas: tk.Canvas, x1, y1, x2, y2, coupe, **kwargs):
    """Rectangle a coins coupes, en diagonale.

    L'angle coupe est la signature des affichages techniques : il donne une
    lecture d'instrument la ou un coin arrondi donne une lecture de bouton
    d'application grand public.
    """
    points = [
        x1 + coupe, y1,
        x2 - coupe, y1,
        x2, y1 + coupe,
        x2, y2 - coupe,
        x2 - coupe, y2,
        x1 + coupe, y2,
        x1, y2 - coupe,
        x1, y1 + coupe,
    ]
    return canvas.create_polygon(points, smooth=False, **kwargs)


class RoundButton(tk.Canvas):
    """Bouton a coins coupes, cercle d'un liseret, avec survol.

    Le nom est reste celui d'origine pour ne pas casser les appels existants,
    mais la forme a change : coins coupes et contour fin plutot que pave
    arrondi plein.
    """

    def __init__(self, parent, text, command=None, *, width=110, height=34,
                 bg=t.SURFACE_2, fg=t.TEXT, hover_bg=None, font=t.FONT_LABEL,
                 radius=8):
        super().__init__(parent, width=width, height=height, bg=parent["bg"],
                         highlightthickness=0, bd=0)
        self.command = command
        self._bg = bg
        self._hover_bg = hover_bg or t.SURFACE_2
        self._fg = fg
        self._enabled = True

        contour = t.ACCENT if bg == t.ACCENT else t.BORDER
        self._shape = chamfered(self, 1, 1, width - 1, height - 1, t.CHAMFER,
                                fill=bg, outline=contour, width=1)
        self._label = self.create_text(width / 2, height / 2, text=text,
                                       fill=fg, font=font)

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)
        self.configure(cursor="hand2")

    def _on_enter(self, _e=None):
        if self._enabled:
            self.itemconfigure(self._shape, fill=self._hover_bg)

    def _on_leave(self, _e=None):
        if self._enabled:
            self.itemconfigure(self._shape, fill=self._bg)

    def _on_click(self, _e=None):
        if self._enabled and self.command:
            self.command()

    def set_text(self, text: str) -> None:
        self.itemconfigure(self._label, text=text)

    def set_couleurs(self, bg, fg, hover_bg=None) -> None:
        """Change l'apparence, pour un bouton qui marque un etat actif."""
        self._bg, self._fg = bg, fg
        self._hover_bg = hover_bg or t.SURFACE_2
        self.itemconfigure(self._shape, fill=bg,
                           outline=t.ACCENT if bg == t.ACCENT else t.BORDER)
        self.itemconfigure(self._label, fill=fg)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self.itemconfigure(self._shape, fill=self._bg if enabled else t.SURFACE)
        self.itemconfigure(self._label, fill=self._fg if enabled else t.TEXT_FAINT)
        self.configure(cursor="hand2" if enabled else "arrow")


class StatusDot(tk.Canvas):
    """Pastille de couleur : etat lisible d'un coup d'oeil."""

    def __init__(self, parent, size=9):
        super().__init__(parent, width=size, height=size, bg=parent["bg"],
                         highlightthickness=0, bd=0)
        self._dot = self.create_oval(1, 1, size - 1, size - 1,
                                     fill=t.TEXT_FAINT, outline="")

    def set_color(self, color: str) -> None:
        self.itemconfigure(self._dot, fill=color)


class NavCell(tk.Frame):
    """Une case de la grille de navigation : une icone, un mot.

    Remplace les lignes titre + sous-titre, qui prenaient deux lignes chacune :
    dix-huit destinations occupaient plus de haut que la fenetre, et il fallait
    faire defiler un menu pour trouver une page. En grille, tout tient d'un
    seul coup d'oeil.

    Le sous-titre n'est pas perdu : il devient l'infobulle du survol, et le
    titre complet s'affiche en tete du panneau ouvert.
    """

    def __init__(self, parent, *, icone: str, texte: str, command,
                 largeur: int = 62, hauteur: int = 56, taille_icone: int = 24):
        super().__init__(parent, bg=t.SURFACE, cursor="hand2",
                         width=largeur, height=hauteur)
        self.pack_propagate(False)

        from assistant import icons

        self._icone = icone
        self._command = command
        self._actif = False

        self._toile = tk.Canvas(self, width=largeur, height=taille_icone + 8,
                                bg=t.SURFACE, highlightthickness=0, bd=0)
        self._toile.pack(pady=(7, 0))
        self._decalage = ((largeur - taille_icone) / 2, 4)
        self._taille_icone = taille_icone
        self._ids = icons.dessiner(self._toile, icone, *self._decalage,
                                   taille_icone, t.TEXT_FAINT)

        self._texte = tk.Label(self, text=texte, bg=t.SURFACE, fg=t.TEXT_FAINT,
                               font=t.FONT_UI_TINY)
        self._texte.pack()

        for widget in (self, self._toile, self._texte):
            widget.bind("<Button-1>", lambda _e: self._command())
            widget.bind("<Enter>", lambda _e: self._survol(True))
            widget.bind("<Leave>", lambda _e: self._survol(False))

    def _peindre(self, couleur: str, fond: str) -> None:
        self.configure(bg=fond)
        self._toile.configure(bg=fond)
        self._texte.configure(bg=fond, fg=couleur)
        for identifiant in self._ids:
            # Sur un Canvas Tk, la couleur du TRAIT n'a pas le meme nom selon
            # l'element : c'est `fill` pour une ligne, `outline` pour une
            # forme fermee. Se tromper ne leve pas -- ca peint l'interieur et
            # laisse le contour gris, ou l'inverse.
            genre = self._toile.type(identifiant)
            if genre == "line":
                self._toile.itemconfigure(identifiant, fill=couleur)
                continue
            self._toile.itemconfigure(identifiant, outline=couleur)
            # Les seules formes remplies sont les poignees de curseurs : on ne
            # repeint l'interieur que s'il y en avait deja un.
            if self._toile.itemcget(identifiant, "fill"):
                self._toile.itemconfigure(identifiant, fill=couleur)

    def _survol(self, dedans: bool) -> None:
        if self._actif:
            return
        self._peindre(t.TEXT if dedans else t.TEXT_FAINT,
                      t.SURFACE_2 if dedans else t.SURFACE)

    def set_actif(self, actif: bool) -> None:
        self._actif = actif
        self._peindre(t.ACCENT if actif else t.TEXT_FAINT,
                      t.ACCENT_SOFT if actif else t.SURFACE)


# L'aiguilleur de molette est installe une seule fois pour toute la fenetre.
_wheel_bound = False


def _dispatch_wheel(event):
    """Fait defiler la zone qui contient le widget survole.

    On remonte la chaine des parents depuis le widget sous le curseur : la
    premiere ScrollArea rencontree est celle que l'utilisateur regarde. Un
    widget Text (les panneaux) gere deja la molette lui-meme, on le laisse
    faire.
    """
    widget = event.widget
    while widget is not None:
        if isinstance(widget, ScrollArea):
            widget.canvas.yview_scroll(int(-event.delta / 120), "units")
            return "break"
        if isinstance(widget, tk.Text) and not isinstance(widget,
                                                          TexteMarkdown):
            widget.yview_scroll(int(-event.delta / 120), "units")
            return "break"
        widget = getattr(widget, "master", None)
    return None


class ScrollArea(tk.Frame):
    """Zone defilante verticale contenant des widgets quelconques.

    Le Canvas gere le defilement, le Frame interieur recoit le contenu. Les
    deux doivent etre resynchronises a chaque changement de taille, sinon la
    barre de defilement ment sur la hauteur reelle.
    """

    def __init__(self, parent, bg=t.BG):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.inner = tk.Frame(self.canvas, bg=bg)

        self.scrollbar = tk.Scrollbar(self, orient="vertical",
                                      command=self.canvas.yview,
                                      bg=t.SURFACE, troughcolor=bg,
                                      activebackground=t.SURFACE_2,
                                      highlightthickness=0, bd=0, width=10)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self._window = self.canvas.create_window((0, 0), window=self.inner,
                                                 anchor="nw")

        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self._bind_wheel(self)

    def _on_inner_configure(self, _e=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        # Le contenu doit suivre la largeur du canvas pour que le retour a la
        # ligne des messages se recalcule quand la fenetre est redimensionnee.
        self.canvas.itemconfigure(self._window, width=event.width)

    def _bind_wheel(self, _widget=None):
        """Active la molette sur toute la fenetre, une seule fois.

        Deux approches naives echouent ici. bind_all sur chaque zone : la
        derniere creee capture la molette et les autres cessent de repondre.
        Un bind par widget : chaque Label ou case a cocher pose dans la zone
        intercepte le survol, et la molette s'arrete des que le curseur passe
        dessus -- il faudrait viser la barre de defilement, ce qui est
        precisement ce qu'on veut eviter.

        On lie donc l'evenement une seule fois au niveau de la fenetre, et on
        remonte la hierarchie depuis le widget survole jusqu'a trouver la
        zone defilante qui le contient. Peu importe ce qu'il y a dessous, la
        molette fait defiler ce que l'utilisateur regarde.
        """
        global _wheel_bound
        if _wheel_bound:
            return
        _wheel_bound = True
        self.winfo_toplevel().bind_all("<MouseWheel>", _dispatch_wheel, add="+")

    def bind_wheel_recursive(self, widget=None) -> None:
        """Conservee pour compatibilite : l'aiguilleur rend ce travail inutile."""
        return

    def scroll_to_bottom(self):
        self.canvas.update_idletasks()
        self.canvas.yview_moveto(1.0)


class Message(tk.Frame):
    """Une carte de message dans la conversation."""

    def __init__(self, parent, text: str, role: str = "assistant",
                 width_hint: int = 640):
        super().__init__(parent, bg=t.BG)

        if role == "user":
            bubble_bg, fg, font, label = t.ACCENT_SOFT, t.TEXT, t.FONT_UI, "Toi"
            label_fg = t.ACCENT
        elif role == "tool":
            bubble_bg, fg, font, label = t.BG, t.TEXT_FAINT, t.FONT_UI_TINY, ""
            label_fg = t.TEXT_FAINT
        elif role == "error":
            bubble_bg, fg, font, label = t.SURFACE, t.RED, t.FONT_UI, "Erreur"
            label_fg = t.RED
        elif role == "info":
            bubble_bg, fg, font, label = t.BG, t.TEXT_DIM, t.FONT_UI_SMALL, ""
            label_fg = t.TEXT_DIM
        else:
            bubble_bg, fg, font, label = t.SURFACE, t.TEXT, t.FONT_UI, "Assistant"
            label_fg = t.GREEN

        # Une sortie d'outil est un tableau aligne : elle exige du mono.
        if role == "assistant" and _looks_tabular(text):
            font = t.FONT_MONO

        pad_y = (2, 2) if role in ("tool", "info") else (t.PAD // 2, t.PAD // 2)
        card = tk.Frame(self, bg=bubble_bg)
        card.pack(fill="x", padx=t.PAD_L, pady=pad_y)

        if label:
            tk.Label(card, text=label, bg=bubble_bg, fg=label_fg,
                     font=t.FONT_LABEL, anchor="w").pack(
                fill="x", padx=t.PAD_L, pady=(t.PAD, 0))

        pady = (2, t.PAD) if label else (4, 4)
        if role == "assistant" and font != t.FONT_MONO:
            # Le modele ecrit en Markdown : **gras**, listes, `code`. Affiche
            # brut dans un Label, ca donnait des asterisques partout.
            self.body = TexteMarkdown(card, text, bg=bubble_bg, fg=fg,
                                      font=font)
        else:
            self.body = tk.Label(
                card, text=text, bg=bubble_bg, fg=fg, font=font,
                justify="left", anchor="w", wraplength=width_hint,
            )
        self.body.pack(fill="x", padx=t.PAD_L, pady=pady)

    def set_wrap(self, width: int) -> None:
        if isinstance(self.body, tk.Label):
            self.body.configure(wraplength=max(width, 200))


# --- Markdown -------------------------------------------------------------

_GRAS_OU_CODE = re.compile(r"(\*\*.+?\*\*|__.+?__|`[^`]+`)")
_PUCE = re.compile(r"^(\s*)[-*+]\s+")
_TITRE = re.compile(r"^\s*#{1,6}\s+")


def segments_markdown(texte: str) -> list[tuple[str, str]]:
    """Decoupe un texte Markdown en (morceau, style).

    Styles : "" (normal), "gras", "code", "titre", "bloc" (bloc de code).
    Seul le sous-ensemble qu'ecrivent les modeles est traite : gras, code,
    titres, listes, blocs de code. Le reste passe tel quel.
    """
    sortie: list[tuple[str, str]] = []
    dans_bloc = False
    lignes = texte.split("\n")
    for i, ligne in enumerate(lignes):
        fin = "\n" if i < len(lignes) - 1 else ""
        if ligne.strip().startswith("```"):
            dans_bloc = not dans_bloc
            continue
        if dans_bloc:
            sortie.append((ligne + fin, "bloc"))
            continue
        if _TITRE.match(ligne):
            titre = _TITRE.sub("", ligne).replace("**", "")
            sortie.append((titre + fin, "titre"))
            continue
        ligne = _PUCE.sub(lambda m: m.group(1) + "• ", ligne)
        for morceau in _GRAS_OU_CODE.split(ligne):
            if not morceau:
                continue
            if morceau.startswith(("**", "__")) and len(morceau) > 4:
                sortie.append((morceau[2:-2], "gras"))
            elif morceau.startswith("`") and len(morceau) > 2:
                sortie.append((morceau[1:-1], "code"))
            else:
                sortie.append((morceau, ""))
        if fin:
            sortie.append((fin, ""))
    return sortie


class TexteMarkdown(tk.Text):
    """Texte en lecture seule qui rend le gras, les titres et le code.

    Un Text plutot qu'un Label : c'est le seul widget Tk qui melange des
    styles dans un meme paragraphe. Sa hauteur suit le nombre de lignes
    affichees, recalculee a chaque changement de largeur. Le texte reste
    selectionnable : on peut copier un extrait de code.
    """

    def __init__(self, parent, texte: str, *, bg, fg, font):
        super().__init__(parent, bg=bg, fg=fg, font=font, wrap="word",
                         relief="flat", bd=0, highlightthickness=0,
                         height=1, padx=0, pady=0, cursor="arrow",
                         selectbackground=t.ACCENT_SOFT,
                         insertwidth=0)
        famille, taille = font[0], font[1]
        self.tag_configure("gras", foreground="#EEF6F9")
        self.tag_configure("titre", foreground="#EEF6F9",
                           font=(famille, taille + 1, "bold"))
        self.tag_configure("code", foreground=t.ACCENT, font=t.FONT_MONO)
        self.tag_configure("bloc", foreground=t.ACCENT, font=t.FONT_MONO)
        for morceau, style in segments_markdown(texte):
            self.insert("end", morceau, style or ())
        self.configure(state="disabled")
        self.bind("<Configure>", lambda _e: self._ajuster())
        # Un message ne defile pas : la molette fait defiler la conversation.
        # Sans ce renvoi, la liaison de classe de Text l'avalait.
        self.bind("<MouseWheel>", lambda e: _dispatch_wheel(e) or "break")

    def _ajuster(self) -> None:
        try:
            lignes = self.count("1.0", "end", "displaylines")
        except tk.TclError:
            return
        hauteur = max(1, int(lignes[0] if isinstance(lignes, tuple)
                             else lignes or 1))
        if int(self.cget("height")) != hauteur:
            self.configure(height=hauteur)


def _looks_tabular(text: str) -> bool:
    """Detecte une sortie en colonnes, qui doit rester en chasse fixe."""
    lines = text.splitlines()
    if len(lines) < 3:
        return False
    indented = sum(1 for line in lines if line.startswith("  "))
    return indented >= len(lines) // 2


class Bandeau(tk.Frame):
    """Un avertissement structure, la ou il n'y avait qu'un texte colore.

    Un message important ecrit en jaune au milieu du reste se lit comme du
    decor : rien ne le separe de ce qui l'entoure, et l'oeil finit par le
    sauter.

    Le bandeau lui donne un cadre : un liseré de couleur a gauche, un fond
    legerement detache, un titre court et une explication. Le fond reste
    SOMBRE et le texte clair -- l'inverse, un pave orange vif dans une
    interface sombre, eblouit et se lit moins bien qu'un texte simple.

    Trois tons seulement. Au-dela, la couleur cesse de signifier quelque chose.
    """

    TONS = {
        "info": (t.ACCENT, "Information"),
        "alerte": (t.AMBER, "Attention"),
        "erreur": (t.RED, "Probleme"),
    }

    def __init__(self, parent, texte: str, ton: str = "alerte",
                 titre: str = "", action=None, libelle_action: str = ""):
        couleur, defaut = self.TONS.get(ton, self.TONS["alerte"])
        super().__init__(parent, bg=t.SURFACE, highlightthickness=1,
                         highlightbackground=t.BORDER)

        # Le liseré porte la couleur, pas le fond. Trois pixels suffisent a
        # distinguer un avertissement d'une erreur du coin de l'oeil.
        tk.Frame(self, bg=couleur, width=3).pack(side="left", fill="y")

        corps = tk.Frame(self, bg=t.SURFACE)
        corps.pack(side="left", fill="both", expand=True,
                   padx=t.PAD_L, pady=t.PAD)

        tk.Label(corps, text=t.espacer(titre or defaut), bg=t.SURFACE,
                 fg=couleur, font=t.FONT_HUD, anchor="w").pack(fill="x")
        self._texte = tk.Label(corps, text=texte, bg=t.SURFACE, fg=t.TEXT,
                               font=t.FONT_UI_SMALL, anchor="w",
                               justify="left", wraplength=560)
        self._texte.pack(fill="x", pady=(2, 0))

        if action is not None:
            RoundButton(corps, libelle_action or "Corriger", action,
                        width=132, bg=t.SURFACE_2,
                        hover_bg=t.BORDER).pack(anchor="w", pady=(t.PAD, 0))

    def set_wrap(self, width: int) -> None:
        """Meme interface que Message : la fenetre les redimensionne ensemble.

        Sans cette methode, poser un bandeau dans la liste des messages ferait
        echouer le reajustement a chaque redimensionnement -- et seulement
        quand un avertissement est affiche, donc rarement au moment ou l'on
        essaie.
        """
        self._texte.configure(wraplength=max(width - 2 * t.PAD_L, 200))
