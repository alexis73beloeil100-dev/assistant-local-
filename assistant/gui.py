"""Fenetre de l'assistant.

Deux modes dans la meme fenetre :

  - les PANNEAUX, pour ce que l'application sait deja. Configuration,
    problemes, jeux, espace disque : ces donnees sont relevees au demarrage.
    Les faire reformuler par le modele de langage serait lent et hasardeux --
    un modele qui recopie des chiffres finit toujours par en deformer un.
    Alors on les affiche directement. Un clic, rien a attendre.

  - la CONVERSATION, pour les questions libres, ou le modele est
    indispensable.

Tout ce qui est lent part dans un thread. La regle en Tk est stricte : seul
le thread principal touche aux widgets, donc les threads de travail postent
leurs resultats dans une file que la fenetre vide vingt fois par seconde.
"""
from __future__ import annotations

import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path

from assistant import llm, panels, theme as t
from assistant.index import db, scanner, watcher
from assistant.skills import games, hardware
from assistant.voice import stt, tts, wake
from assistant.widgets import (LevelMeter, Message, RoundButton, ScrollArea,
                               StatusDot)

TITLE = "Assistant local"
SUBTITLE = "tout reste sur cette machine"
CHAT_KEY = "conversation"


class AssistantWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(TITLE)
        self.geometry("1120x740")
        self.minsize(860, 560)
        self.configure(bg=t.BG)

        self.events: queue.Queue = queue.Queue()
        self.convo = llm.new_conversation()
        self.busy = False
        self.speak = tk.BooleanVar(value=False)
        self.mic_device: int | None = None
        self.current = CHAT_KEY
        self._messages: list[Message] = []
        self._nav: dict[str, tk.Frame] = {}
        self.recorder: stt.Recorder | None = None
        self.ecoute = tk.BooleanVar(value=False)
        self.boucle_vocale: wake.VoiceLoop | None = None

        self._build()
        self.after(50, self._drain)
        self._brancher_confirmation()
        self._boot()

    # =====================================================================
    # Construction
    # =====================================================================

    def _build(self) -> None:
        self._build_header()

        body = tk.Frame(self, bg=t.BG)
        body.pack(fill="both", expand=True)

        self._build_sidebar(body)

        self.stage = tk.Frame(body, bg=t.BG)
        self.stage.pack(side="left", fill="both", expand=True)

        self._build_panel_view()
        self._build_chat_view()

        # Au tout premier lancement, on ouvre l'accueil plutot que la
        # conversation : quelqu'un qui decouvre l'application ne sait pas
        # quoi taper dans un champ vide.
        from assistant import settings

        premiere_fois = not settings.get("deja_lance", False)
        if premiere_fois:
            settings.set("deja_lance", True)
            self.show("accueil")
        else:
            self.show(CHAT_KEY)

    def _build_header(self) -> None:
        header = tk.Frame(self, bg=t.SURFACE, height=58)
        header.pack(fill="x")
        header.pack_propagate(False)

        left = tk.Frame(header, bg=t.SURFACE)
        left.pack(side="left", padx=t.PAD_L)
        tk.Label(left, text=TITLE, bg=t.SURFACE, fg=t.TEXT,
                 font=t.FONT_TITLE).pack(side="left", pady=t.PAD_L)
        from assistant import __version__
        tk.Label(left, text=f"  {SUBTITLE}   v{__version__}",
                 bg=t.SURFACE, fg=t.TEXT_FAINT,
                 font=t.FONT_UI_SMALL).pack(side="left", pady=t.PAD_L)

        right = tk.Frame(header, bg=t.SURFACE)
        right.pack(side="right", padx=t.PAD_L)
        self.status_text = tk.StringVar(value="Demarrage")
        tk.Label(right, textvariable=self.status_text, bg=t.SURFACE,
                 fg=t.TEXT_DIM, font=t.FONT_UI_SMALL).pack(
            side="right", padx=(t.PAD, 0))
        self.dot = StatusDot(right)
        self.dot.pack(side="right", pady=t.PAD_XL)

        # Filet cyan sous l'en-tete : marque la separation sans cadre.
        tk.Frame(self, bg=t.ACCENT_DEEP, height=1).pack(fill="x")

    def _build_sidebar(self, parent) -> None:
        side = tk.Frame(parent, bg=t.SURFACE, width=240)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)

        self._build_sidebar_bottom(side)

        liste = ScrollArea(side, bg=t.SURFACE)
        liste.pack(fill="both", expand=True)
        interieur = liste.inner

        self._nav_entry(interieur, CHAT_KEY, "Conversation",
                        "poser une question libre", entete="PARLER")

        tk.Label(interieur, text=t.espacer("consulter"), bg=t.SURFACE,
                 fg=t.ACCENT_DEEP, font=t.FONT_HUD, anchor="w").pack(
            fill="x", padx=t.PAD_L, pady=(t.PAD_L, 4))

        for panel in panels.PANELS:
            self._nav_entry(interieur, panel.key, panel.label, panel.subtitle)

    def _nav_entry(self, parent, key: str, label: str, subtitle: str,
                   entete: str | None = None) -> None:
        if entete:
            tk.Label(parent, text=t.espacer(entete), bg=t.SURFACE,
                     fg=t.ACCENT_DEEP, font=t.FONT_HUD, anchor="w").pack(
                fill="x", padx=t.PAD_L, pady=(t.PAD_L, 4))

        ligne = tk.Frame(parent, bg=t.SURFACE, cursor="hand2")
        ligne.pack(fill="x")

        # Liseret vertical a gauche : marque la selection sans remplir la
        # ligne d'un aplat, qui donnerait l'aspect d'un menu Windows.
        liseret = tk.Frame(ligne, bg=t.SURFACE, width=3)
        liseret.pack(side="left", fill="y")

        corps = tk.Frame(ligne, bg=t.SURFACE)
        corps.pack(side="left", fill="x", expand=True)

        titre = tk.Label(corps, text=label, bg=t.SURFACE, fg=t.TEXT_DIM,
                         font=t.FONT_LABEL, anchor="w")
        titre.pack(fill="x", padx=(t.PAD_L - 3, t.PAD_L), pady=(6, 0))
        sous = tk.Label(corps, text=subtitle, bg=t.SURFACE, fg=t.TEXT_FAINT,
                        font=t.FONT_UI_TINY, anchor="w")
        sous.pack(fill="x", padx=(t.PAD_L - 3, t.PAD_L), pady=(0, 6))

        ligne.titre = titre        # type: ignore[attr-defined]
        ligne.sous = sous          # type: ignore[attr-defined]
        ligne.corps = corps        # type: ignore[attr-defined]
        ligne.liseret = liseret    # type: ignore[attr-defined]
        ligne.actif = False        # type: ignore[attr-defined]

        for widget in (ligne, corps, titre, sous):
            widget.bind("<Button-1>", lambda _e, k=key: self.show(k))
            widget.bind("<Enter>", lambda _e, l=ligne: self._hover(l, True))
            widget.bind("<Leave>", lambda _e, l=ligne: self._hover(l, False))

        self._nav[key] = ligne

    def _hover(self, ligne, dedans: bool) -> None:
        if ligne.actif:            # type: ignore[attr-defined]
            return
        couleur = t.SURFACE_2 if dedans else t.SURFACE
        ligne.configure(bg=couleur)
        ligne.corps.configure(bg=couleur)    # type: ignore[attr-defined]
        ligne.titre.configure(bg=couleur)    # type: ignore[attr-defined]
        ligne.sous.configure(bg=couleur)     # type: ignore[attr-defined]
        ligne.liseret.configure(             # type: ignore[attr-defined]
            bg=t.ACCENT_DEEP if dedans else couleur)

    def _build_sidebar_bottom(self, side) -> None:
        bottom = tk.Frame(side, bg=t.SURFACE)
        bottom.pack(side="bottom", fill="x", pady=t.PAD_L)

        tk.Label(bottom, text=t.espacer("micro"), bg=t.SURFACE,
                 fg=t.ACCENT_DEEP, font=t.FONT_HUD, anchor="w").pack(
            fill="x", padx=t.PAD_L, pady=(0, 4))

        self.mics = stt.microphones()
        noms = [nom[:28] for _i, nom in self.mics] or ["aucun micro"]
        self.mic_choice = tk.StringVar(value=noms[0])
        picker = tk.OptionMenu(bottom, self.mic_choice, *noms,
                               command=self._on_mic_change)
        picker.configure(bg=t.SURFACE_2, fg=t.TEXT, font=t.FONT_UI_TINY,
                         activebackground=t.BORDER, activeforeground=t.TEXT,
                         highlightthickness=0, bd=0, anchor="w",
                         relief="flat", cursor="hand2")
        picker["menu"].configure(bg=t.SURFACE_2, fg=t.TEXT,
                                 font=t.FONT_UI_TINY,
                                 activebackground=t.ACCENT_SOFT)
        picker.pack(fill="x", padx=t.PAD_L)

        self.meter = LevelMeter(bottom, width=180)
        self.meter.pack(padx=t.PAD_L, pady=(6, 2), anchor="w")

        self.mic_hint = tk.Label(bottom, text="", bg=t.SURFACE,
                                 fg=t.TEXT_FAINT, font=t.FONT_UI_TINY,
                                 anchor="w")
        self.mic_hint.pack(fill="x", padx=t.PAD_L, pady=(0, t.PAD))

        for texte, action in (("Tester le micro", self.test_micro),
                              ("Composants et installation",
                               self.open_installer)):
            lien = tk.Label(bottom, text=texte, bg=t.SURFACE, fg=t.ACCENT,
                            font=t.FONT_UI_TINY, anchor="w", cursor="hand2")
            lien.pack(fill="x", padx=t.PAD_L, pady=(0, 6))
            lien.bind("<Button-1>", lambda _e, a=action: a())

        tk.Checkbutton(
            bottom, text=" Ecoute permanente (hey jarvis)",
            variable=self.ecoute, command=self._basculer_ecoute,
            bg=t.SURFACE, fg=t.TEXT_DIM, font=t.FONT_UI_SMALL,
            selectcolor=t.SURFACE_2, activebackground=t.SURFACE,
            activeforeground=t.TEXT, highlightthickness=0, bd=0,
            anchor="w", cursor="hand2",
        ).pack(fill="x", padx=t.PAD_L)

        self.ecoute_etat = tk.Label(bottom, text="", bg=t.SURFACE,
                                    fg=t.TEXT_FAINT, font=t.FONT_UI_TINY,
                                    anchor="w")
        self.ecoute_etat.pack(fill="x", padx=t.PAD_L, pady=(0, t.PAD))

        tk.Checkbutton(
            bottom, text=" Repondre a voix haute", variable=self.speak,
            bg=t.SURFACE, fg=t.TEXT_DIM, font=t.FONT_UI_SMALL,
            selectcolor=t.SURFACE_2, activebackground=t.SURFACE,
            activeforeground=t.TEXT, highlightthickness=0, bd=0,
            anchor="w", cursor="hand2",
        ).pack(fill="x", padx=t.PAD_L)

    # --- vue panneau ------------------------------------------------------

    def _build_panel_view(self) -> None:
        self.panel_view = tk.Frame(self.stage, bg=t.BG)

        entete = tk.Frame(self.panel_view, bg=t.BG)
        entete.pack(fill="x", padx=t.PAD_XL, pady=(t.PAD_L, t.PAD))

        self.panel_title = tk.Label(entete, text="", bg=t.BG, fg=t.TEXT,
                                    font=("Segoe UI Semibold", 14), anchor="w")
        self.panel_title.pack(side="left")

        self.panel_refresh = RoundButton(entete, "Actualiser",
                                         self._refresh_panel, width=104,
                                         bg=t.SURFACE_2, hover_bg=t.BORDER)
        self.panel_refresh.pack(side="right")

        cadre = tk.Frame(self.panel_view, bg=t.SURFACE)
        self.panel_frame = cadre
        cadre.pack(fill="both", expand=True, padx=t.PAD_XL,
                   pady=(0, t.PAD_XL))

        barre = tk.Scrollbar(cadre, bg=t.SURFACE, troughcolor=t.SURFACE,
                             activebackground=t.SURFACE_2,
                             highlightthickness=0, bd=0, width=10)
        barre.pack(side="right", fill="y")

        self.panel_text = tk.Text(
            cadre, bg=t.SURFACE, fg=t.TEXT, font=t.FONT_MONO, wrap="word",
            spacing1=1, spacing3=1,
            relief="flat", padx=t.PAD_L, pady=t.PAD_L, state="disabled",
            insertbackground=t.TEXT, yscrollcommand=barre.set,
        )
        self.panel_text.pack(fill="both", expand=True)
        barre.configure(command=self.panel_text.yview)

        self.panel_text.tag_configure("grave", foreground=t.RED)
        self.panel_text.tag_configure("attention", foreground=t.AMBER)
        self.panel_text.tag_configure("titre", foreground=t.ACCENT)
        self.panel_text.tag_configure("remede", foreground=t.TEXT_DIM)

        # Accueil des panneaux interactifs : ils remplacent la zone de texte
        # quand le panneau affiche de vrais widgets.
        self.panel_widget_host = tk.Frame(self.panel_view, bg=t.BG)
        self.panel_widgets: dict[str, tk.Frame] = {}
        # Les exemples de l'accueil : cliquables, et ils doivent en avoir l'air.
        self.panel_text.tag_configure("exemple", foreground=t.ACCENT,
                                      font=t.FONT_MONO_BOLD)
        self.panel_text.tag_bind("exemple", "<Enter>",
                                 lambda _e: self.panel_text.configure(cursor="hand2"))
        self.panel_text.tag_bind("exemple", "<Leave>",
                                 lambda _e: self.panel_text.configure(cursor=""))
        self.panel_text.tag_bind("exemple", "<Button-1>", self._cliquer_exemple)

    def _render_panel(self, texte: str) -> None:
        self.panel_text.configure(state="normal")
        self.panel_text.delete("1.0", "end")
        for ligne in texte.splitlines():
            depouille = ligne.strip()
            tag = ""
            if ligne.startswith(panels.EXEMPLE):
                # On retire le marqueur a l'affichage : l'utilisateur voit
                # la phrase telle qu'il la dirait, pas un code interne.
                self.panel_text.insert(
                    "end", "  " + ligne[len(panels.EXEMPLE):] + "\n", "exemple")
                continue
            if "[GRAVE]" in ligne:
                tag = "grave"
            elif "[A SURVEILLER]" in ligne or "/!\\" in ligne:
                tag = "attention"
            elif depouille.startswith("->"):
                tag = "remede"
            elif (depouille and len(depouille) > 8
                  and depouille == depouille.upper()):
                tag = "titre"
            self.panel_text.insert("end", ligne + "\n", tag)
        self.panel_text.configure(state="disabled")
        self.panel_text.yview_moveto(0)

    def _cliquer_exemple(self, event) -> None:
        """Envoie la phrase d'exemple sur laquelle on vient de cliquer."""
        index = self.panel_text.index(f"@{event.x},{event.y}")
        debut = self.panel_text.index(f"{index} linestart")
        fin = self.panel_text.index(f"{index} lineend")
        phrase = self.panel_text.get(debut, fin).strip()
        if phrase:
            self.ask(phrase)

    def _montrer_interactif(self, panel) -> None:
        """Affiche un panneau fait de widgets plutot que de texte."""
        self.panel_frame.pack_forget()
        self.panel_widget_host.pack(fill="both", expand=True,
                                    padx=t.PAD_XL, pady=(0, t.PAD_XL))

        for enfant in self.panel_widget_host.winfo_children():
            enfant.pack_forget()

        widget = self.panel_widgets.get(panel.key)
        if widget is None:
            if panel.interactif == "startup":
                from assistant.optimiser import StartupOptimizer

                widget = StartupOptimizer(self.panel_widget_host, self)
            else:
                return
            self.panel_widgets[panel.key] = widget
        else:
            widget.recharger()

        widget.pack(fill="both", expand=True)

    def _refresh_panel(self) -> None:
        if self.current == CHAT_KEY:
            return
        cle = self.current
        panel = panels.BY_KEY.get(cle)
        if panel is not None and panel.interactif:
            widget = self.panel_widgets.get(cle)
            if widget is not None:
                widget.recharger()
            return
        self._render_panel("Actualisation ...")

        def work():
            self.post("panneau", (cle, panels.content(cle, force=True)))

        threading.Thread(target=work, daemon=True).start()

    # --- vue conversation -------------------------------------------------

    def _build_chat_view(self) -> None:
        self.chat_view = tk.Frame(self.stage, bg=t.BG)

        self.chat = ScrollArea(self.chat_view, bg=t.BG)
        self.chat.pack(fill="both", expand=True)
        self.chat.canvas.bind("<Configure>", self._on_resize, add="+")

        bar = tk.Frame(self.chat_view, bg=t.BG)
        bar.pack(fill="x", padx=t.PAD_L, pady=t.PAD_L)

        field = tk.Frame(bar, bg=t.SURFACE_2, highlightthickness=1,
                         highlightbackground=t.BORDER)
        field.pack(side="left", fill="x", expand=True)
        self.entry = tk.Entry(field, bg=t.SURFACE_2, fg=t.TEXT,
                              insertbackground=t.ACCENT, relief="flat",
                              font=t.FONT_INPUT)
        self.entry.pack(fill="x", padx=t.PAD_L, pady=10)
        self.entry.bind("<Return>", lambda _e: self.send())

        self.mic_btn = RoundButton(bar, "Parler", self.listen_once, width=96,
                                   bg=t.SURFACE_2, hover_bg=t.BORDER)
        self.mic_btn.pack(side="left", padx=(t.PAD, 0))
        self.send_btn = RoundButton(bar, "Envoyer", self.send, width=96,
                                    bg=t.ACCENT, fg="#0b1220",
                                    hover_bg="#79b4ff")
        self.send_btn.pack(side="left", padx=(t.PAD, 0))

    # =====================================================================
    # Navigation
    # =====================================================================

    def show(self, key: str) -> None:
        self.current = key
        for cle, ligne in self._nav.items():
            actif = cle == key
            ligne.actif = actif        # type: ignore[attr-defined]
            fond = t.ACCENT_SOFT if actif else t.SURFACE
            ligne.configure(bg=fond)
            ligne.corps.configure(bg=fond)   # type: ignore[attr-defined]
            ligne.titre.configure(     # type: ignore[attr-defined]
                bg=fond, fg=t.ACCENT if actif else t.TEXT_DIM)
            ligne.sous.configure(bg=fond)    # type: ignore[attr-defined]
            ligne.liseret.configure(         # type: ignore[attr-defined]
                bg=t.ACCENT if actif else fond)

        self.panel_view.pack_forget()
        self.chat_view.pack_forget()

        if key == CHAT_KEY:
            self.chat_view.pack(fill="both", expand=True)
            self.entry.focus_set()
            return

        panel = panels.BY_KEY.get(key)
        self.panel_title.configure(text=panel.label if panel else key)
        self.panel_view.pack(fill="both", expand=True)

        if panel is not None and panel.interactif:
            self._montrer_interactif(panel)
            return

        self.panel_widget_host.pack_forget()
        self.panel_frame.pack(fill="both", expand=True, padx=t.PAD_XL,
                              pady=(0, t.PAD_XL))

        if panel is not None and not panel.live and panels.is_ready(key):
            self._render_panel(panels.content(key))
            return

        self._render_panel("Preparation ...")

        def work():
            self.post("panneau", (key, panels.content(key)))

        threading.Thread(target=work, daemon=True).start()

    # =====================================================================
    # Evenements
    # =====================================================================

    def post(self, kind: str, payload) -> None:
        self.events.put((kind, payload))

    def _drain(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "status":
                    texte, couleur = payload
                    self.status_text.set(texte)
                    self.dot.set_color(couleur)
                elif kind == "busy":
                    self._set_busy(payload)
                elif kind == "appel":
                    # Un thread demande a executer quelque chose sur le fil
                    # principal. C'est la seule facon sure de toucher aux
                    # widgets depuis un travail de fond : after() appele
                    # depuis un thread echoue des que la boucle Tk n'est pas
                    # celle du thread appelant.
                    try:
                        payload()
                    except Exception:  # noqa: BLE001
                        pass
                elif kind == "panneau":
                    cle, texte = payload
                    if self.current == cle:
                        self._render_panel(texte)
                elif kind == "level":
                    niveau, seuil = payload
                    self.meter.update_level(niveau, seuil)
                elif kind == "ecouteinfo":
                    texte, couleur = payload
                    self.ecoute_etat.configure(text=texte, fg=couleur)
                elif kind == "micinfo":
                    texte, couleur = payload
                    self.mic_hint.configure(text=texte, fg=couleur)
                elif kind == "alerte":
                    self.add(payload, "user")
                    self.chat_view.pack_forget()
                    self.show(CHAT_KEY)
                    try:
                        self.deiconify()
                        self.lift()
                        self.focus_force()
                    except tk.TclError:
                        pass
                    threading.Thread(target=tts.say, args=(payload,),
                                     daemon=True).start()
                elif kind == "speak":
                    if self.speak.get():
                        threading.Thread(target=tts.say, args=(payload,),
                                         daemon=True).start()
                else:
                    self.add(payload, kind)
        except queue.Empty:
            pass
        self.after(50, self._drain)

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.send_btn.set_enabled(not busy)
        self.mic_btn.set_enabled(not busy)

    # =====================================================================
    # Demarrage
    # =====================================================================

    def _boot(self) -> None:
        self.add("Pose ta question ici, ou clique \"Par ou commencer\" a "
                 "gauche pour voir des exemples.", "info")

        def work():
            self.post("status", ("Demarrage du moteur", t.AMBER))
            ok, message = llm.available(
                on_progress=lambda m: self.post("status", (m[:28], t.AMBER))
            )
            if not ok:
                self.post("error", message)

            self.post("status", ("Analyse de la machine", t.AMBER))
            hardware.collect()
            games.all_games()
            panels.prime(["configuration", "problemes", "jeux", "demarrage",
                          "correctifs"])
            self.post("info", hardware.summary())

            if not db.is_ready():
                self.post("status", ("Scan des fichiers", t.AMBER))
                stats = scanner.rebuild(verbose=False)
                nombre = f"{stats.get('files', 0):,}".replace(",", " ")
                self.post("info",
                          f"{nombre} fichiers connus, en memoire uniquement.")
                if watcher.start() is not None:
                    self.post("info", watcher.status())
                panels.prime(["espace", "fichiers"])

            self.post("status", ("Pret", t.GREEN))

        threading.Thread(target=work, daemon=True).start()
        self._brancher_alertes()

    def _brancher_alertes(self) -> None:
        """Affiche et annonce les minuteurs et surveillances qui se declenchent.

        Sans cela, une alerte se declenche dans un thread et personne n'en
        sait rien : l'utilisateur regle un minuteur qui ne le previent jamais.
        """
        from assistant.skills import reminders

        def prevenir(alerte) -> None:
            detail = f"  ({alerte.detail})" if alerte.detail else ""
            self.post("alerte", f"{alerte.message}{detail}")

        reminders.set_notifier(prevenir)

    # =====================================================================
    # Conversation
    # =====================================================================

    def _wrap_width(self) -> int:
        return max(self.chat.canvas.winfo_width() - 2 * t.PAD_XL - 24, 240)

    def _on_resize(self, _e=None) -> None:
        largeur = self._wrap_width()
        for message in self._messages:
            message.set_wrap(largeur)

    def add(self, texte: str, role: str = "assistant") -> None:
        message = Message(self.chat.inner, texte, role, self._wrap_width())
        message.pack(fill="x")
        self._messages.append(message)
        self.chat.scroll_to_bottom()

    def send(self) -> None:
        texte = self.entry.get().strip()
        if texte:
            self.entry.delete(0, "end")
            self.ask(texte)

    def ask(self, question: str) -> None:
        if self.busy:
            return
        self.show(CHAT_KEY)
        self.add(question, "user")
        self._set_busy(True)
        self.post("status", ("Reflexion", t.AMBER))

        def work():
            self.convo.append({"role": "user", "content": question})
            try:
                reponse, self.convo = llm.chat(
                    self.convo,
                    on_tool=lambda n, _a: self.post("tool", f"    {n}"),
                )
                self.post("assistant", reponse)
                self.post("speak", reponse)
            except Exception as exc:  # noqa: BLE001
                self.post("error", str(exc))
            # Elagage sur la taille reelle, plus sur un nombre de messages
            # fige : voir llm.trim_conversation.
            self.convo = llm.trim_conversation(self.convo)
            self.post("status", ("Pret", t.GREEN))
            self.post("busy", False)

        threading.Thread(target=work, daemon=True).start()

    # =====================================================================
    # Micro
    # =====================================================================

    def _on_mic_change(self, choix: str) -> None:
        for index, nom in self.mics:
            if nom[:28] == choix:
                self.mic_device = index
                break
        self.mic_hint.configure(text="")
        self.meter.reset()

    def test_micro(self) -> None:
        if self.busy:
            return
        self.mic_hint.configure(text="mesure ...", fg=t.TEXT_FAINT)

        def work():
            resultat = stt.probe(self.mic_device)
            if not resultat["ok"]:
                self.post("micinfo", (resultat["erreur"][:34], t.RED))
            elif resultat["crete"] < 1e-5:
                self.post("micinfo", ("muet - choisis un autre micro", t.RED))
            else:
                self.post("micinfo", (
                    f"bruit {resultat['bruit_de_fond']:.4f}  "
                    f"seuil {resultat['seuil_calcule']:.4f}", t.GREEN))

        threading.Thread(target=work, daemon=True).start()

    def listen_once(self) -> None:
        """Demarre ou arrete la dictee.

        Deux clics, pas de devinette : la detection automatique de fin de
        phrase se declenchait sur un simple pic de bruit ambiant et coupait
        l'enregistrement avant que l'utilisateur ait fini de parler.
        """
        if self.recorder is not None and self.recorder.running:
            self._finish_dictation()
            return
        if self.busy:
            return

        self.show(CHAT_KEY)
        self.recorder = stt.Recorder(device=self.mic_device)
        demarre = self.recorder.start(
            on_level=lambda niveau, seuil: self.post("level", (niveau, seuil))
        )
        if not demarre:
            self.post("error", "Le micro est deja en cours d'utilisation.")
            return

        self.mic_btn.set_text("Terminer")
        self.send_btn.set_enabled(False)
        self.post("status", ("Parle, puis clique Terminer", t.ACCENT))

    def _finish_dictation(self) -> None:
        enregistreur = self.recorder
        self.recorder = None
        if enregistreur is None:
            return

        self.mic_btn.set_text("Parler")
        self.mic_btn.set_enabled(False)
        self.post("status", ("Transcription", t.AMBER))

        def work():
            audio = enregistreur.stop()
            self.meter.reset()

            if enregistreur.error:
                self.post("error", f"Micro : {enregistreur.error}")
            elif audio.size == 0:
                self.post("info",
                          "Le micro n'a rien capte du tout. Choisis-en un "
                          "autre dans la liste a gauche.")
            else:
                import numpy as _np

                duree = audio.size / stt.SAMPLE_RATE
                crete = float(_np.max(_np.abs(audio)))
                try:
                    texte = stt.transcribe(audio)
                except Exception as exc:  # noqa: BLE001
                    texte = ""
                    self.post("error", f"Transcription impossible : {exc}")

                if texte:
                    self.after(0, lambda: self.ask(texte))
                else:
                    self.post("info",
                              f"Rien compris dans {duree:.1f} s d'audio "
                              f"(niveau maximal {crete:.3f}). "
                              "Parle plus fort ou plus pres du micro ; sous "
                              "0.01, monte le volume d'entree dans les "
                              "parametres son de Windows.")

            self.post("busy", False)
            self.after(0, lambda: self.mic_btn.set_enabled(True))
            self.post("status", ("Pret", t.GREEN))

        threading.Thread(target=work, daemon=True).start()

    # =====================================================================
    # Ecoute permanente
    # =====================================================================

    def _basculer_ecoute(self) -> None:
        """Active ou coupe le mot-cle et le raccourci global.

        Decoche par defaut : le mot-cle ecoute le micro en continu, ce qui se
        declenche sur ce que disent les autres en vocal et coute du CPU
        pendant une partie. C'est un choix, pas un reglage impose.
        """
        if not self.ecoute.get():
            if self.boucle_vocale is not None:
                self.boucle_vocale.stop()
                self.boucle_vocale = None
            self.ecoute_etat.configure(text="", fg=t.TEXT_FAINT)
            self.post("status", ("Pret", t.GREEN))
            return

        self.ecoute_etat.configure(text="chargement du mot-cle ...",
                                   fg=t.TEXT_FAINT)

        def demarrer():
            boucle = wake.VoiceLoop(device=self.mic_device)
            try:
                boucle.start_hotkey()
            except Exception as exc:  # noqa: BLE001
                self.post("ecouteinfo", (f"raccourci indisponible : "
                                         f"{type(exc).__name__}", t.AMBER))

            def sur_commande(texte: str) -> None:
                self.after(0, lambda: self.ask(texte))

            def sur_declenchement(trigger) -> None:
                detail = f" ({trigger.score})" if trigger.score else ""
                self.post("status", (f"{trigger.source}{detail} : parle",
                                     t.ACCENT))

            def sur_etat(message: str) -> None:
                self.post("ecouteinfo", (message[:34], t.TEXT_FAINT))

            try:
                self.post("ecouteinfo", ('"hey jarvis" ou Ctrl+Alt+Espace',
                                         t.GREEN))
                boucle.run(sur_commande, on_trigger=sur_declenchement,
                           on_status=sur_etat)
            except Exception as exc:  # noqa: BLE001
                self.post("ecouteinfo", (f"arret : {type(exc).__name__}",
                                         t.RED))
                self.after(0, lambda: self.ecoute.set(False))

            self.boucle_vocale = None

        self.boucle_vocale = None
        threading.Thread(target=demarrer, name="ecoute", daemon=True).start()

    # =====================================================================
    # Confirmation des actions
    # =====================================================================

    def _brancher_confirmation(self) -> None:
        """Fait passer les demandes d'accord par une fenetre, pas par le
        terminal.

        Sans cela, l'application packagee en mode fenetre n'a pas d'entree
        standard : la demande echouait sur "lost sys.stdin" et toute action
        du modele plantait avant d'etre proposee.
        """
        from assistant import safety

        safety.set_asker(self._demander_accord)

    def _demander_accord(self, texte: str) -> bool:
        """Appele depuis un thread de travail : marshale vers le fil principal.

        Le thread se met en attente pendant que la fenetre s'affiche, et
        repart avec la reponse.
        """
        reponse: dict = {}
        fini = threading.Event()

        def montrer():
            try:
                reponse["ok"] = self._fenetre_accord(texte)
            except Exception:  # noqa: BLE001
                reponse["ok"] = False
            fini.set()

        self.post("appel", montrer)
        # Cinq minutes : au-dela, l'utilisateur est parti, on refuse.
        if not fini.wait(timeout=300):
            return False
        return bool(reponse.get("ok", False))

    def _fenetre_accord(self, texte: str) -> bool:
        """Fenetre modale decrivant l'action, en attente d'un accord."""
        dialogue = tk.Toplevel(self)
        dialogue.title("Confirmation")
        dialogue.configure(bg=t.BG)
        dialogue.transient(self)
        dialogue.resizable(False, False)

        cadre = tk.Frame(dialogue, bg=t.BG)
        cadre.pack(fill="both", expand=True, padx=t.PAD_XL, pady=t.PAD_L)

        tk.Label(cadre, text=t.espacer("action a confirmer"), bg=t.BG,
                 fg=t.ACCENT_DEEP, font=t.FONT_HUD, anchor="w").pack(
            fill="x", pady=(0, t.PAD))

        corps = tk.Frame(cadre, bg=t.SURFACE)
        corps.pack(fill="both", expand=True)
        tk.Label(corps, text=texte, bg=t.SURFACE, fg=t.TEXT,
                 font=t.FONT_MONO, justify="left", anchor="w",
                 wraplength=560).pack(fill="both", expand=True,
                                      padx=t.PAD_L, pady=t.PAD_L)

        tk.Label(cadre, text="Rien ne sera fait sans ton accord. "
                             "Cette decision est journalisee.",
                 bg=t.BG, fg=t.TEXT_FAINT, font=t.FONT_UI_TINY,
                 anchor="w").pack(fill="x", pady=(t.PAD, 0))

        choix = {"ok": False}

        def repondre(accepte: bool) -> None:
            choix["ok"] = accepte
            dialogue.destroy()

        boutons = tk.Frame(cadre, bg=t.BG)
        boutons.pack(fill="x", pady=(t.PAD_L, 0))

        RoundButton(boutons, "Confirmer", lambda: repondre(True), width=118,
                    bg=t.ACCENT, fg="#06222A",
                    hover_bg="#7BE3F2").pack(side="right")
        RoundButton(boutons, "Annuler", lambda: repondre(False), width=104,
                    bg=t.SURFACE_2, hover_bg=t.BORDER).pack(
            side="right", padx=(0, t.PAD))

        # Annuler par defaut : la touche Echap et la croix refusent.
        dialogue.protocol("WM_DELETE_WINDOW", lambda: repondre(False))
        dialogue.bind("<Escape>", lambda _e: repondre(False))

        dialogue.update_idletasks()
        largeur = dialogue.winfo_width()
        hauteur = dialogue.winfo_height()
        x = self.winfo_rootx() + (self.winfo_width() - largeur) // 2
        y = self.winfo_rooty() + (self.winfo_height() - hauteur) // 3
        dialogue.geometry(f"+{max(x, 0)}+{max(y, 0)}")

        dialogue.grab_set()
        dialogue.focus_force()
        self.wait_window(dialogue)
        return choix["ok"]

    # =====================================================================
    # Installateur
    # =====================================================================

    def open_installer(self) -> None:
        """Ouvre l'installateur dans un processus separe.

        Il telecharge des modeles de plusieurs giga-octets : le faire dans
        cette fenetre figerait la conversation en cours.
        """
        if getattr(sys, "frozen", False):
            commande = [sys.executable, "--installer"]
        else:
            racine = Path(__file__).resolve().parent.parent
            commande = [sys.executable, str(racine / "AssistantLocal.py"),
                        "--installer"]
        try:
            subprocess.Popen(commande)
        except OSError as exc:
            self.post("error", f"Impossible d'ouvrir l'installateur : {exc}")


def main() -> int:
    AssistantWindow().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
