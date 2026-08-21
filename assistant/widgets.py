"""Briques d'interface que Tkinter ne fournit pas.

Tk s'arrete aux widgets rectangulaires gris. Coins arrondis, zone defilante
et cartes de message se construisent a la main, sur un Canvas.
"""
from __future__ import annotations

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


class LevelMeter(tk.Canvas):
    """Vu-metre : le niveau du micro, et le seuil de detection de parole.

    Sans ca, un micro trop faible echoue en silence et rien n'explique
    pourquoi l'assistant n'a "rien entendu".
    """

    def __init__(self, parent, width=160, height=8):
        super().__init__(parent, width=width, height=height, bg=parent["bg"],
                         highlightthickness=0, bd=0)
        # Surtout pas self._w : Tkinter y range le chemin Tcl du widget, et
        # l'ecraser rend le widget inutilisable ("invalid command name").
        self._width = width
        self._track = self.create_rectangle(0, 0, width, height,
                                            fill=t.SURFACE_2, outline="")
        self._bar = self.create_rectangle(0, 0, 0, height,
                                          fill=t.ACCENT, outline="")
        self._mark = self.create_line(0, 0, 0, height, fill=t.AMBER, width=1)

    def update_level(self, level: float, threshold: float) -> None:
        # Echelle racine : la parole vit dans le bas de la plage, une echelle
        # lineaire la rendrait invisible.
        full = max(threshold * 6, 0.05)
        pos = min((level / full) ** 0.5, 1.0) * self._width
        mark = min((threshold / full) ** 0.5, 1.0) * self._width
        self.coords(self._bar, 0, 0, pos, self.winfo_reqheight())
        self.coords(self._mark, mark, 0, mark, self.winfo_reqheight())
        self.itemconfigure(self._bar,
                           fill=t.GREEN if level > threshold else t.ACCENT)

    def reset(self) -> None:
        self.coords(self._bar, 0, 0, 0, self.winfo_reqheight())


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
        if isinstance(widget, tk.Text):
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

        self.body = tk.Label(
            card, text=text, bg=bubble_bg, fg=fg, font=font,
            justify="left", anchor="w", wraplength=width_hint,
        )
        self.body.pack(fill="x", padx=t.PAD_L,
                       pady=(2, t.PAD) if label else (4, 4))

    def set_wrap(self, width: int) -> None:
        self.body.configure(wraplength=max(width, 200))


def _looks_tabular(text: str) -> bool:
    """Detecte une sortie en colonnes, qui doit rester en chasse fixe."""
    lines = text.splitlines()
    if len(lines) < 3:
        return False
    indented = sum(1 for line in lines if line.startswith("  "))
    return indented >= len(lines) // 2
