"""La mini-fenetre : un orbe qui apparait au-dessus de tout sur Win+Maj+A.

Poser une question ne devrait pas obliger a quitter ce qu'on fait pour aller
chercher la grande fenetre. Le raccourci fait apparaitre un petit orbe en
haut de l'ecran, une zone de texte deja prete sous lui ; la reponse s'affiche
dans une bulle, et Echap le renvoie.

Il ne pense pas seul : il parle a travers la grande fenetre, qui reste
l'unique proprietaire de la conversation. Une question posee ici apparait
aussi la-bas, et se poursuit la-bas d'un clic.

L'oeil de l'orbe dit ce qu'il fait :
    cyan    pret
    ambre   il reflechit
"""
from __future__ import annotations

import tkinter as tk

from assistant import theme as t

RACCOURCI = "<cmd>+<shift>+a"
RACCOURCI_LISIBLE = "Win+Maj+A"

LARGEUR = 380
HAUT_ECRAN = 36          # distance au bord haut de l'ecran, en pixels
ORBE = 104               # diametre de l'orbe
BARRE_L, BARRE_H = 52, 38

# Couleur rendue transparente par Windows : tout ce qui la porte disparait,
# et la fenetre prend la forme de ce qu'on y dessine. Elle ne doit servir a
# rien d'autre dans la fenetre.
TRANSPARENT = "#010203"

CORPS = "#1E3A47"
CORPS_BORD = "#2A5566"
ECRAN = "#08161C"
BARRE = "#0A0F14"
BARRE_BORD = "#24323C"

YEUX = {"pret": t.ACCENT, "reflexion": t.AMBER}


class MiniFenetre(tk.Toplevel):
    """L'orbe, sa barre a deux boutons, la zone de texte et la bulle."""

    def __init__(self, fenetre):
        super().__init__(fenetre)
        self.fenetre = fenetre
        self.etat = "pret"
        self.attend_reponse = False

        self.withdraw()
        self.overrideredirect(True)
        self.configure(bg=TRANSPARENT)
        try:
            self.attributes("-topmost", True)
        except tk.TclError:
            pass
        self._fond = TRANSPARENT
        try:
            self.attributes("-transparentcolor", TRANSPARENT)
        except tk.TclError:
            # Hors Windows : un fond plein, le reste fonctionne pareil.
            self._fond = t.BG
            self.configure(bg=t.BG)

        haut = ORBE + 22 + BARRE_H + 8
        self.toile = tk.Canvas(self, width=LARGEUR, height=haut,
                               bg=self._fond, highlightthickness=0, bd=0)
        self.toile.pack()
        self._dessiner()

        self.saisie_cadre = tk.Frame(self, bg=t.SURFACE,
                                     highlightbackground=BARRE_BORD,
                                     highlightthickness=1)
        self.saisie = tk.Entry(self.saisie_cadre, bg=t.SURFACE, fg=t.TEXT,
                               insertbackground=t.ACCENT, relief="flat",
                               font=t.FONT_UI, bd=0)
        self.saisie.pack(fill="x", padx=12, pady=9)
        self.saisie_cadre.pack(fill="x", padx=8, pady=(4, 0))

        self.bulle = tk.Frame(self, bg=t.SURFACE,
                              highlightbackground=BARRE_BORD,
                              highlightthickness=1)
        self.bulle_texte = tk.Label(self.bulle, text="", bg=t.SURFACE,
                                    fg=t.TEXT, font=t.FONT_UI, justify="left",
                                    anchor="w", wraplength=LARGEUR - 40)
        self.bulle_texte.pack(fill="x", padx=12, pady=(10, 4))
        self.lien = tk.Label(self.bulle, text="Continuer dans la grande fenêtre",
                             bg=t.SURFACE, fg=t.ACCENT_DEEP,
                             font=t.FONT_UI_TINY, cursor="hand2", anchor="w")
        self.lien.pack(fill="x", padx=12, pady=(0, 10))
        self.lien.bind("<Button-1>", lambda _e: self.ouvrir_grande_fenetre())

        self.saisie.bind("<Return>", lambda _e: self.envoyer())
        self.bind("<Escape>", lambda _e: self.cacher())
        self.toile.tag_bind("crayon", "<Button-1>",
                            lambda _e: self.montrer_saisie())
        self.toile.tag_bind("orbe", "<ButtonPress-1>", self._prendre)
        self.toile.tag_bind("orbe", "<B1-Motion>", self._glisser)

        fenetre.abonnes_reponse.append(self._sur_message)

    # --- Dessin ------------------------------------------------------------

    def _dessiner(self) -> None:
        c = self.toile
        c.delete("all")
        cx = LARGEUR // 2
        r = ORBE // 2
        y0 = 4
        cy = y0 + r

        # Ombre au sol : il flotte.
        c.create_oval(cx - 30, y0 + ORBE + 8, cx + 30, y0 + ORBE + 14,
                      fill="#0A1A20", outline="", tags="orbe")
        # Les deux petites oreilles, puis le corps.
        for s in (-1, 1):
            c.create_oval(cx + s * (r + 8) - 9, cy - 8, cx + s * (r + 8) + 9,
                          cy + 10, fill=CORPS_BORD, outline="", tags="orbe")
        c.create_oval(cx - r, y0, cx + r, y0 + ORBE, fill=CORPS,
                      outline=CORPS_BORD, width=2, tags="orbe")
        c.create_polygon(_arrondi(cx - 36, cy - 16, cx + 36, cy + 16, 16),
                         smooth=True, fill=ECRAN, outline="", tags="orbe")
        c.create_polygon(_arrondi(cx - 22, cy - 5, cx + 22, cy + 5, 5),
                         smooth=True, fill=YEUX[self.etat], outline="",
                         tags=("orbe", "oeil"))

        # La barre : le crayon, qui rend la main a la zone de texte.
        by = y0 + ORBE + 22
        c.create_polygon(_arrondi(cx - BARRE_L // 2, by, cx + BARRE_L // 2,
                                  by + BARRE_H, BARRE_H // 2),
                         smooth=True, fill=BARRE, outline=BARRE_BORD,
                         tags="crayon")
        c.create_line(cx - 7, by + 26, cx + 6, by + 12, fill=t.TEXT,
                      width=3, capstyle="round", tags="crayon")
        c.create_line(cx - 9, by + 28, cx - 6, by + 25, fill=t.TEXT,
                      width=2, capstyle="round", tags="crayon")

    def _changer_etat(self, etat: str) -> None:
        self.etat = etat
        self.toile.itemconfigure("oeil", fill=YEUX[etat])

    # --- Afficher, cacher --------------------------------------------------

    def basculer(self) -> None:
        if self.winfo_viewable():
            self.cacher()
        else:
            self.montrer()

    def montrer(self) -> None:
        self.update_idletasks()
        x = (self.winfo_screenwidth() - LARGEUR) // 2
        self.geometry(f"+{x}+{HAUT_ECRAN}")
        self.deiconify()
        self.lift()
        self.montrer_saisie()

    def cacher(self) -> None:
        self.withdraw()

    def montrer_saisie(self) -> None:
        # Sans focus_force, la fenetre s'affiche mais le clavier reste au jeu
        # ou a l'application qui l'avait : on taperait dans le vide.
        self.focus_force()
        self.saisie.focus_set()

    def ouvrir_grande_fenetre(self) -> None:
        self.cacher()
        try:
            self.fenetre.deiconify()
            self.fenetre.lift()
            self.fenetre.focus_force()
        except tk.TclError:
            pass

    # --- Demander ----------------------------------------------------------

    def envoyer(self) -> None:
        question = self.saisie.get().strip()
        if not question or self.fenetre.busy:
            return
        self.saisie.delete(0, "end")
        self._poser(question)
        self.fenetre.ask(question)

    def _poser(self, question: str) -> None:
        self.attend_reponse = True
        self._changer_etat("reflexion")
        self._bulle(f"« {question} »\n\nJe réfléchis…", t.TEXT_DIM)

    def _sur_message(self, genre: str, texte: str) -> None:
        """Appele par la grande fenetre pour chaque message affiche."""
        if not self.attend_reponse:
            return
        if genre == "user":
            self._changer_etat("reflexion")
            self._bulle(f"« {texte} »\n\nJe réfléchis…", t.TEXT_DIM)
            return
        if genre not in ("assistant", "error", "info"):
            return
        self.attend_reponse = False
        self._changer_etat("pret")
        self._bulle(texte, t.RED if genre == "error" else t.TEXT)

    def _bulle(self, texte: str, couleur) -> None:
        self.bulle_texte.configure(text=texte, fg=couleur)
        if not self.bulle.winfo_ismapped():
            self.bulle.pack(fill="x", padx=8, pady=(6, 8))

    # --- Deplacer ----------------------------------------------------------

    def _prendre(self, event) -> None:
        self._origine = (event.x_root - self.winfo_x(),
                         event.y_root - self.winfo_y())

    def _glisser(self, event) -> None:
        ox, oy = self._origine
        self.geometry(f"+{event.x_root - ox}+{event.y_root - oy}")


def _arrondi(x1, y1, x2, y2, r):
    """Points d'un rectangle arrondi, a tracer avec smooth=True."""
    return [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
            x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]


def demarrer_raccourci(fenetre, mini: MiniFenetre):
    """Ecoute globale de Win+Maj+A, meme quand un jeu a le focus.

    Le rappel arrive sur le fil de pynput : il passe par la file de la grande
    fenetre, seul chemin sur pour toucher aux widgets.
    """
    from pynput import keyboard

    ecouteur = keyboard.GlobalHotKeys(
        {RACCOURCI: lambda: fenetre.post("appel", mini.basculer)})
    ecouteur.daemon = True
    ecouteur.start()
    return ecouteur
