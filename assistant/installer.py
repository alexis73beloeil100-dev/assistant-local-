"""Installateur : detecte la machine, propose les composants, les telecharge.

Le principe est le meme que celui de l'assistant lui-meme : regarder d'abord
ce que la machine a dans le ventre, puis proposer ce qui lui convient. Sur une
carte a 4 Go de VRAM, on ne propose pas le modele de 9 Go -- il tournerait sur
le processeur, dix fois plus lentement, sans que l'utilisateur comprenne
pourquoi.

Chaque composant est une case a cocher. Ceux deja presents sont detectes et
grises : reinstaller 3 Go pour rien n'a aucun interet.
"""
from __future__ import annotations

import queue
import threading
import tkinter as tk

from assistant import components as comp
from assistant import theme as t
from assistant.widgets import RoundButton, ScrollArea

TITLE = "Assistant local - Installation"


class Installer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(TITLE)
        self.geometry("820x680")
        self.minsize(700, 560)
        self.configure(bg=t.BG)

        self.events: queue.Queue = queue.Queue()
        self.components: list[comp.Component] = []
        self.vars: dict[str, tk.BooleanVar] = {}
        self.rows: dict[str, tk.Frame] = {}
        self.options: list[dict] = []
        self.running = False

        self._build()
        self.after(50, self._drain)
        self._detect()

    # --- interface --------------------------------------------------------

    def _build(self) -> None:
        header = tk.Frame(self, bg=t.SURFACE)
        header.pack(fill="x")
        tk.Label(header, text="Installation de l'assistant local", bg=t.SURFACE,
                 fg=t.TEXT, font=("Segoe UI Semibold", 15)).pack(
            anchor="w", padx=t.PAD_XL, pady=(t.PAD_L, 2))
        tk.Label(header,
                 text="Tout fonctionne hors ligne une fois installe. "
                      "Rien n'est envoye sur Internet ensuite.",
                 bg=t.SURFACE, fg=t.TEXT_DIM, font=t.FONT_UI_SMALL).pack(
            anchor="w", padx=t.PAD_XL, pady=(0, t.PAD_L))

        self.machine = tk.Label(
            self, text="Analyse de la machine ...", bg=t.BG, fg=t.TEXT_DIM,
            font=t.FONT_MONO, justify="left", anchor="w",
        )
        self.machine.pack(fill="x", padx=t.PAD_XL, pady=(t.PAD_L, t.PAD))

        tk.Label(self, text="MODELE DE LANGAGE", bg=t.BG, fg=t.TEXT_FAINT,
                 font=t.FONT_UI_TINY, anchor="w").pack(
            fill="x", padx=t.PAD_XL, pady=(t.PAD, 4))

        self.modeles = tk.Frame(self, bg=t.BG)
        self.modeles.pack(fill="x", padx=t.PAD_XL)
        self.model_choice = tk.StringVar()

        tk.Label(self, text="COMPOSANTS", bg=t.BG, fg=t.TEXT_FAINT,
                 font=t.FONT_UI_TINY, anchor="w").pack(
            fill="x", padx=t.PAD_XL, pady=(t.PAD, 4))

        self.liste = ScrollArea(self, bg=t.BG)
        self.liste.pack(fill="both", expand=True, padx=t.PAD_L)

        bas = tk.Frame(self, bg=t.SURFACE)
        bas.pack(fill="x")

        self.total = tk.Label(bas, text="", bg=t.SURFACE, fg=t.TEXT,
                              font=t.FONT_UI, anchor="w")
        self.total.pack(side="left", padx=t.PAD_XL, pady=t.PAD_L)

        self.bouton = RoundButton(bas, "Installer", self.start, width=130,
                                  bg=t.ACCENT, fg="#0b1220", hover_bg="#79b4ff")
        self.bouton.pack(side="right", padx=t.PAD_XL, pady=t.PAD_L)

        self.etat = tk.Label(self, text="", bg=t.BG, fg=t.TEXT_DIM,
                             font=t.FONT_UI_SMALL, anchor="w")
        self.etat.pack(fill="x", padx=t.PAD_XL, pady=(0, t.PAD_L))

    def _add_row(self, component: comp.Component, present: bool) -> None:
        cadre = tk.Frame(self.liste.inner, bg=t.SURFACE)
        cadre.pack(fill="x", padx=t.PAD, pady=4)

        var = tk.BooleanVar(value=(component.default and not present))
        self.vars[component.key] = var

        haut = tk.Frame(cadre, bg=t.SURFACE)
        haut.pack(fill="x", padx=t.PAD_L, pady=(t.PAD_L, 2))

        case = tk.Checkbutton(
            haut, variable=var, bg=t.SURFACE, activebackground=t.SURFACE,
            selectcolor=t.SURFACE_2, highlightthickness=0, bd=0,
            cursor="hand2", command=self._refresh_total,
        )
        case.pack(side="left")
        if present:
            case.configure(state="disabled")

        titre = component.label + ("   [deja installe]" if present else "")
        tk.Label(haut, text=titre, bg=t.SURFACE,
                 fg=t.TEXT_FAINT if present else t.TEXT,
                 font=t.FONT_LABEL, anchor="w").pack(side="left", padx=(4, 0))

        if component.size_gb > 0 and not present:
            tk.Label(haut, text=f"{component.size_gb:.1f} Go", bg=t.SURFACE,
                     fg=t.ACCENT, font=t.FONT_UI_SMALL).pack(side="right")

        tk.Label(cadre, text=component.description, bg=t.SURFACE,
                 fg=t.TEXT_DIM, font=t.FONT_UI_SMALL, justify="left",
                 anchor="w", wraplength=680).pack(
            fill="x", padx=(t.PAD_L + 22, t.PAD_L), pady=(0, t.PAD_L))

        etat = tk.Label(cadre, text="", bg=t.SURFACE, fg=t.TEXT_FAINT,
                        font=t.FONT_UI_TINY, anchor="w")
        etat.pack(fill="x", padx=(t.PAD_L + 22, t.PAD_L), pady=(0, t.PAD))
        self.rows[component.key] = etat

    def _refresh_total(self) -> None:
        total = sum(c.size_gb for c in self.components
                    if self.vars[c.key].get())
        if total <= 0:
            self.total.configure(text="Rien a telecharger.")
        else:
            self.total.configure(text=f"A telecharger : {total:.1f} Go")


    def _build_models(self, options: list[dict]) -> None:
        """Un choix par modele, avec son cout reel sur cette machine.

        Aucun modele n'est masque : celui qui depasse la carte reste
        selectionnable, mais on annonce qu'il tournera sur le processeur.
        """
        for widget in self.modeles.winfo_children():
            widget.destroy()

        for option in options:
            if option["recommended"]:
                self.model_choice.set(option["id"])

            ligne = tk.Frame(self.modeles, bg=t.SURFACE)
            ligne.pack(fill="x", pady=2)

            haut = tk.Frame(ligne, bg=t.SURFACE)
            haut.pack(fill="x", padx=t.PAD_L, pady=(t.PAD, 0))

            tk.Radiobutton(
                haut, variable=self.model_choice, value=option["id"],
                bg=t.SURFACE, activebackground=t.SURFACE,
                selectcolor=t.SURFACE_2, highlightthickness=0, bd=0,
                cursor="hand2", command=self._on_model_change,
            ).pack(side="left")

            titre = option["label"]
            tk.Label(haut, text=titre, bg=t.SURFACE, fg=t.TEXT,
                     font=t.FONT_LABEL).pack(side="left", padx=(4, 8))

            if option["recommended"]:
                tk.Label(haut, text="CONSEILLE POUR TA CONFIGURATION",
                         bg=t.SURFACE, fg=t.GREEN,
                         font=t.FONT_UI_TINY).pack(side="left")

            tk.Label(haut, text=f"{option['download_gb']:.1f} Go",
                     bg=t.SURFACE, fg=t.ACCENT,
                     font=t.FONT_UI_SMALL).pack(side="right")

            couleur = t.TEXT_DIM if option["fits"] else t.AMBER
            tk.Label(ligne, text=f"{option['impact']} - {option['speed']}",
                     bg=t.SURFACE, fg=couleur, font=t.FONT_UI_TINY,
                     anchor="w").pack(fill="x", padx=(t.PAD_L + 22, t.PAD_L),
                                      pady=(0, t.PAD))

        self.options = options

    def _on_model_change(self) -> None:
        """Repercute le choix sur le composant a telecharger."""
        choisi = self.model_choice.get()
        option = next((o for o in self.options if o["id"] == choisi), None)
        if option is None:
            return
        for component in self.components:
            if component.key == "modele":
                component.label = f"Modele de langage ({choisi})"
                component.size_gb = option["download_gb"]
                component.install = comp.install_model(choisi)
                component.detect = lambda m=choisi: comp.model_installed(m)
                if component.key in self.rows:
                    deja = component.detect()
                    self.rows[component.key].configure(
                        text="deja installe" if deja else "",
                        fg=t.TEXT_FAINT)
                    self.vars[component.key].set(not deja)
        self._refresh_total()

    # --- evenements -------------------------------------------------------

    def post(self, kind: str, payload) -> None:
        self.events.put((kind, payload))

    def _drain(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "machine":
                    self.machine.configure(text=payload)
                elif kind == "modeles":
                    self._build_models(payload)
                elif kind == "rows":
                    for component, present in payload:
                        self.components.append(component)
                        self._add_row(component, present)
                    self._refresh_total()
                elif kind == "etat":
                    self.etat.configure(text=payload)
                elif kind == "ligne":
                    key, texte, couleur = payload
                    if key in self.rows:
                        self.rows[key].configure(text=texte, fg=couleur)
                elif kind == "fini":
                    self.running = False
                    self.bouton.set_enabled(True)
                    self.bouton.set_text("Terminer" if payload else "Reessayer")
                    if payload:
                        self.bouton.command = self.destroy
        except queue.Empty:
            pass
        self.after(50, self._drain)

    # --- detection --------------------------------------------------------

    def _detect(self) -> None:
        def work():
            vram = comp.vram_gb()
            resume = [
                f"  Processeur   {comp.cpu_threads()} threads",
                f"  Memoire      {comp.ram_gb():.0f} Go",
                f"  Carte video  {vram:.0f} Go de VRAM" if vram
                else "  Carte video  aucune carte dediee detectee",
            ]
            _modele, raison = comp.recommend_llm()
            resume.append("")
            resume.append(f"  {raison}")
            self.post("machine", "\n".join(resume))
            self.post("modeles", comp.model_options())

            catalogue = comp.catalogue()
            lignes = []
            for component in catalogue:
                try:
                    present = component.detect()
                except Exception:  # noqa: BLE001
                    present = False
                lignes.append((component, present))
            self.post("rows", lignes)
            self.post("etat", "Coche ce que tu veux installer, puis clique "
                              "sur Installer.")

        threading.Thread(target=work, daemon=True).start()

    # --- installation -----------------------------------------------------

    def start(self) -> None:
        if self.running:
            return
        choisis = [c for c in self.components if self.vars[c.key].get()]
        if not choisis:
            self.post("etat", "Aucun composant selectionne.")
            return

        self.running = True
        self.bouton.set_enabled(False)
        self.bouton.set_text("Installation")

        def work():
            echecs = 0
            for component in choisis:
                self.post("ligne", (component.key, "en cours ...", t.AMBER))
                self.post("etat", f"{component.label} ...")

                def progress(message, key=component.key):
                    self.post("ligne", (key, message, t.AMBER))

                try:
                    ok, message = component.install(progress)
                except Exception as exc:  # noqa: BLE001
                    ok, message = False, f"{type(exc).__name__}: {exc}"

                if ok:
                    self.post("ligne", (component.key, message, t.GREEN))
                else:
                    echecs += 1
                    self.post("ligne", (component.key, message, t.RED))

            if echecs:
                self.post("etat", f"{echecs} composant(s) en echec. "
                                  "Le detail est indique ci-dessus.")
            else:
                self.post("etat", "Installation terminee. Tu peux lancer "
                                  "l'assistant depuis le Bureau.")
            self.post("fini", echecs == 0)

        threading.Thread(target=work, daemon=True).start()


def main() -> int:
    Installer().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
