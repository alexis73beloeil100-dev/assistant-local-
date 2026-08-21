# Assistant local

Assistant vocal et textuel qui connaît cette machine. **Rien ne sort du PC** :
le modèle de langage, la reconnaissance vocale et la synthèse tournent tous
en local.

---

## Démarrer

**Double-clic sur « Assistant local » sur le Bureau.**

C'est un vrai exécutable Windows : `dist\AssistantLocal\AssistantLocal.exe`.
Il n'a besoin ni de Python ni de rien d'installé — tout est embarqué (2,3 Go,
dont l'essentiel en bibliothèques CUDA).

L'application **démarre elle-même son moteur** (le serveur Ollama). Tu n'as
rien à lancer avant elle. C'est important : Ollama ne s'inscrit pas au
démarrage de Windows, donc après chaque redémarrage il ne tourne plus — et
l'assistant se retrouvait sans cerveau, avec pour seul symptôme un
« Ollama ne répond pas » incompréhensible.

Si l'application refuse de démarrer, la raison est écrite dans
`dist\AssistantLocal\erreurs.log` et affichée dans une boîte de dialogue.

### La fenêtre

Deux modes dans la même fenêtre.

**Les panneaux**, pour ce que l'application sait déjà. Un clic, affichage
immédiat (mesuré : 0,02 à 0,05 s) — la donnée est relevée au démarrage et
affichée telle quelle. La faire reformuler par le modèle serait lent, et un
modèle qui recopie des chiffres finit toujours par en déformer un.

| Panneau | Contenu |
|---|---|
| Ma configuration | carte mère, BIOS, CPU, RAM barrette par barrette, GPU, disques |
| Problèmes détectés | ce qui ne va vraiment pas, avec le remède |
| État en direct | charge CPU par cœur, RAM, GPU |
| Pourquoi ça rame | ce qui sature la machine maintenant |
| Mes jeux | groupés par launcher, avec les tailles |
| Espace disque | index + ce qui peut être récupéré |
| Mes fichiers | index et surveillance |
| Démarrage de Windows | ce qui se lance avec la session |
| Ce que je peux réparer | correctifs disponibles |
| Autotest | vérifier que tout fonctionne |

**La conversation**, pour les questions libres, où le modèle est
indispensable. Bouton **Parler** pour dicter, case « Répondre à voix haute »
décochée par défaut.

La pastille en haut à droite : verte = prêt, ambre = en travail, rouge =
problème.

### Reconstruire l'exécutable

```bash
.venv\Scripts\python.exe -m PyInstaller --noconfirm AssistantLocal.spec
.venv\Scripts\python.exe creer_raccourci.py
```

`--collect-submodules assistant` est indispensable : les imports du projet sont
écrits à l'intérieur des fonctions, et l'analyse statique de PyInstaller ne les
voit pas. Sans ça l'exe se construit sans erreur, puis meurt au lancement.

### En ligne de commande

```bash
cd "C:\Users\Asuna\Documents\Assistant"
.venv\Scripts\python.exe -m assistant.cli
```

---

## Ce qu'il sait faire

### Fichiers

Il connaît les disques C: et H: — **1,14 million d'entrées**.

**Rien n'est stocké sur ton disque.** Cette connaissance vit en mémoire vive
et disparaît quand tu fermes l'application. Elle se reconstruit toute seule au
démarrage, en 40 secondes, en tâche de fond : le reste de l'assistant (jeux,
diagnostic, état machine) répond immédiatement pendant ce temps.

Et dans tous les cas, **aucun contenu de fichier n'est jamais lu** — seulement
les noms, les tailles et les dates, comme l'index d'un livre sans le texte.

Pour repasser sur un index conservé d'un démarrage à l'autre (démarrage
instantané, mais un fichier de ~750 Mo sur le disque), mets
`PERSIST_INDEX = True` dans `assistant/config.py`.

```bash
.venv\Scripts\python.exe -m assistant.cli cherche moza ffb
.venv\Scripts\python.exe -m assistant.cli gros "C:\Program Files"
.venv\Scripts\python.exe -m assistant.cli caches
.venv\Scripts\python.exe -m assistant.cli doublons
.venv\Scripts\python.exe -m assistant.cli scan      # reconstruit l'index
```

### Contenu des fichiers

Au-delà des noms, l'assistant **ouvre et lit vraiment tes fichiers** quand la
question l'exige — et ne conserve rien. La lecture se fait au moment de la
question, le texte vit en mémoire le temps de la réponse, puis disparaît.

| Format | Lu via |
|---|---|
| texte, code, config, logs, `.ini`, `.json`, `.csv` | détection d'encodage (UTF-8 / cp1252) |
| PDF | pypdf |
| Word `.docx` | python-docx |
| Excel `.xlsx` | openpyxl |
| PowerPoint `.pptx` | extraction XML directe |

Trois outils nouveaux : `lire_fichier`, `chercher_dans_fichiers`,
`apercu_dossier`. Exemples de questions qui marchent maintenant :

- « Quels réglages MOZA sont configurés dans Assetto Corsa ? »
- « Résume-moi ce PDF »
- « Dans quel fichier j'ai écrit ma clé d'API ? »
- « Qu'est-ce qu'il y a sur mon Bureau ? »

**Comment il choisit quoi ouvrir.** L'index des noms sert à sélectionner les
candidats ; on en ouvre quelques centaines, ciblées, jamais les 935 000. Les
dépendances installées (`site-packages`, `.venv`, `node_modules`, `.nuget`)
sont exclues — sans ça, 400 fichiers de bibliothèque passaient avant tes
propres fichiers et la recherche ne trouvait rien.

**Le contenu d'un fichier est traité comme une donnée, jamais comme une
consigne.** Si un fichier contient un texte qui demande d'agir, l'assistant te
le signale au lieu d'obéir.


### Machine

```bash
.venv\Scripts\python.exe -m assistant.cli etat      # CPU par cœur, RAM, GPU, disques
.venv\Scripts\python.exe -m assistant.cli diag      # cherche ce qui ralentit
.venv\Scripts\python.exe -m assistant.cli demarrage # programmes au démarrage
```

`diag` regarde **le détail par cœur, jamais la moyenne**. Un processus qui
sature un cœur d'un Ryzen 8 cœurs n'apparaît qu'à 12 % de CPU global tout en
rendant la machine désagréable — c'est exactement le cas d'`audiodg.exe` ici.

### Matériel et santé du PC

Dès l'ouverture, l'application **relève la configuration de la machine sur
laquelle elle tourne** — quelle qu'elle soit. Rien n'est codé en dur : disques,
chemins protégés et matériel sont découverts au démarrage.

`configuration_machine` donne la fiche technique : carte mère, BIOS, processeur,
barrettes de RAM une par une (capacité, fréquence réelle, référence), carte
graphique et âge du pilote, disques physiques, volumes, version de Windows.

`detecter_problemes` cherche activement ce qui ne va pas :

| Contrôle | Ce qu'il attrape |
|---|---|
| Santé SMART des disques | un disque qui va lâcher, avant qu'il lâche |
| Usure et température SSD | cellules en fin de vie, NVMe qui se bride |
| Espace libre par volume | seuils à 10 % et 5 % |
| Fréquence RAM réelle vs nominale | **profil XMP/EXPO non activé** — perf payée mais pas utilisée |
| Barrettes dépareillées | double canal dégradé |
| Fréquence CPU actuelle vs max | bridage thermique ou mode économie |
| Périphériques en erreur | pilote absent ou en conflit |
| Journal Windows sur 7 jours | erreurs disque, NTFS, WHEA, écrans bleus, TPM |
| Redémarrage en attente | explique quantité de comportements erratiques |
| État de l'antivirus | protection coupée, signatures périmées |

Chaque point sort avec sa **gravité** (GRAVE / À SURVEILLER) et son remède en
clair, pas juste un code d'erreur. Les optimisations possibles (XMP non activé,
barrettes dépareillées, redémarrage en attente) sont listées **à part** : ce ne
sont pas des pannes.

**Le journal Windows est filtré par liste blanche.** Seules les sources
réellement actionnables sont rapportées — erreurs disque, NTFS, WHEA, écrans
bleus, contrôleur de stockage — et seulement au-delà d'un seuil d'occurrences.
Tout le reste est ignoré en silence : une machine en parfait état produit en
permanence des erreurs DCOM, Hyper-V, TPM ou DeviceAssociation sans la moindre
conséquence. Les afficher revient à inventer des problèmes, et l'utilisateur
cesse alors de faire confiance au diagnostic.

Le relevé complet coûte ~6 s, dominé par la lecture du journal d'événements.
Il est fait une fois au démarrage, en tâche de fond.


### Réparer, pas seulement constater

Six correctifs, **tous réversibles**, tous soumis à confirmation :

| Correctif | Retour arrière |
|---|---|
| Désactiver un programme au démarrage | la commande est sauvegardée avant suppression |
| Réactiver un programme au démarrage | depuis cette sauvegarde |
| Arrêter un processus | relançable normalement |
| Redémarrer un service | — |
| Vider un cache | part à la corbeille |
| Nettoyer les résidus disque | part à la corbeille |

**Ce que l'assistant refuse de faire, même si on insiste :** arrêter un
processus système (`lsass`, `csrss`, `explorer`…) ou redémarrer un service
critique (`RpcSs`, `DcomLaunch`…). Ces actions font tomber la session Windows.

Tout est journalisé dans `data/logs/actions.jsonl` — accepté **comme** refusé.

### Images et captures d'écran

`lire_image` lit une image, `lire_ecran` photographie l'écran et le lit. Sert à
demander de l'aide sur un menu de réglages affiché à l'écran. **L'image est
supprimée juste après lecture.**

| Sans modèle de vision | Avec (3,2 Go, optionnel) |
|---|---|
| lit le **texte** de l'image (OCR local) | comprend la **disposition** : curseurs, cases cochées |

### Index toujours à jour

Une surveillance suit Téléchargements, Documents, Bureau, Images, Vidéos et
Musique. Un fichier créé apparaît dans la recherche en ~4 secondes ; supprimé,
il disparaît.

La mise à jour est **incrémentale**. Reconstruire l'index plein texte à chaque
changement reindexerait 935 000 lignes toutes les 2 secondes — ça finit par
corrompre la table FTS5.


### Jeux

```bash
.venv\Scripts\python.exe -m assistant.cli jeux
.venv\Scripts\python.exe -m assistant.cli jouer euro truck
```

Détecte Steam, Epic, Ubisoft, EA et Riot. Le lancement passe par les URI des
launchers, donc DRM, overlay et synchro des sauvegardes fonctionnent
normalement.

---

## Voix

```bash
.venv\Scripts\python.exe -m assistant.main
```

### Dicter une phrase

Le bouton **Parler** est un interrupteur : un clic démarre, un second clic
transcrit et envoie.

Ce n'est pas un détail d'ergonomie. La détection automatique de fin de phrase
ne peut pas être fiable : elle repose sur un seuil de volume, et un simple pic
de bruit ambiant suffit à la déclencher. Mesuré sur cette machine —
« parole détectée » à 2,3 s puis arrêt à 6,2 s **alors que personne n'avait
parlé**. L'utilisateur voyait le vu-mètre bouger et n'obtenait jamais sa
phrase. Quand quelqu'un peut cliquer, il n'y a aucune raison de deviner.

### Écoute permanente

Case **« Écoute permanente (alexa) »** dans la barre latérale, décochée
par défaut.

| Déclencheur | Quand l'utiliser |
|---|---|
| Dire **« alexa »** | à la souris, hors jeu |
| **Ctrl + Alt + Espace** | en jeu ou en vocal — aucun faux déclenchement |

**Pourquoi « alexa » et pas « hey jarvis ».** openWakeWord ne fournit que six
modèles pré-entraînés, tous entraînés sur de l'anglais. Les deux détecteurs ont
été mis à tourner en parallèle sur le même flux, même micro, même voix :

| Modèle | Score maximal | Blocs au-dessus du seuil |
|---|---|---|
| `hey_jarvis` | 0,097 | **0** — n'a jamais déclenché |
| `alexa` | **0,692** | 4 |

Sept fois plus haut. Ce n'était ni le micro, ni le seuil : le modèle
`hey_jarvis` ne reconnaît pas cette prononciation. Un mot-clé au choix — « Tom »,
par exemple — demanderait d'entraîner un réseau de neurones : torch, tensorflow,
plusieurs giga-octets et des heures de calcul. Et une syllabe est de toute façon
trop courte pour un déclenchement fiable.

Le mot-clé se change à un seul endroit, `WAKE_MODEL` dans `voice/wake.py`.

Là, personne ne peut cliquer pour dire « j'ai fini » : la fin de phrase doit
être détectée. Trois règles évitent le défaut ci-dessus — il faut **320 ms de
son continu** pour croire à de la parole (un claquement de clavier ne dure
qu'un bloc), l'enregistrement ne s'arrête **jamais avant 2,5 s** (une
hésitation en début de phrase ne doit pas le couper), et le silence exigé est
porté à **1,5 s**.

Décochée par défaut, parce que le micro écoute alors en continu : ça se
déclenche sur ce que disent les autres en vocal, et ça consomme du processeur
pendant une partie. C'est un choix, pas un réglage imposé.

Options utiles :

```bash
--no-wake      # raccourci seul, zéro CPU au repos
--muet         # répond à l'écrit sans parler
--micros       # liste les micros
--mic 11       # force un micro
--seuil 0.7    # mot-clé plus strict s'il part tout seul
```

---

## Si le micro ne répond pas

L'assistant **calibre le seuil de parole sur ton micro** au début de chaque
enregistrement : il mesure le bruit de fond pendant 0,4 s et place le seuil
au-dessus. Un seuil fixe ne peut pas marcher — le niveau dépend entièrement du
gain de la carte son.

En bas de la barre latérale :

1. Choisis le micro dans la liste déroulante.
2. Clique **Tester le micro** → il affiche le bruit de fond et le seuil calculé.
   - « muet » en rouge = ce périphérique ne capte rien, prends-en un autre.
3. Clique **Parler** : la barre du vu-mètre monte quand tu parles, le trait
   ambre est le seuil, la barre passe au vert quand tu le franchis.

Sur cette machine, le micro *Mic in at rear panel* sort un bruit de fond de
`0.0033`, ce qui donne un seuil de `0.0073`.

---

## Distribuer l'application

`installateur\Installer_AssistantLocal.exe` (1,13 Go) est un installateur
Windows classique, produit par Inno Setup depuis `installateur.iss`.

- s'installe dans `%LOCALAPPDATA%\AssistantLocal`, **sans droits
  administrateur** ;
- propose le raccourci Bureau et le démarrage avec Windows en cases à cocher ;
- ouvre l'écran des composants à la fin, pour choisir le modèle adapté à la
  machine ;
- **désinstallation propre** depuis Applications installées, qui ferme d'abord
  l'application et le moteur de calcul (sinon leurs fichiers restent
  verrouillés et le dossier reste à moitié vide).

Le moteur d'IA et les modèles ne sont **pas** dans l'installateur : ils pèsent
plusieurs Go et dépendent du matériel de la machine cible.

Pour le reconstruire :

```bash
.venv\Scripts\python.exe reconstruire.py
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installateur.iss
```

---

## Autotest

```bash
dist\AssistantLocal\AssistantLocal.exe --autotest
```

Onze vérifications : environnement, droits d'écriture, disques, relevé
matériel, moteur d'IA, modèle, transcription, micro, lecture d'images, voix,
jeux. Chacune dit ce qu'elle teste, ce qu'elle trouve, et quoi faire si ça
échoue.

C'est ce qui a permis de trouver deux bugs invisibles autrement : les modèles
OCR non embarqués dans l'exécutable, et les réglages écrits dans `_internal`,
le dossier privé de PyInstaller — donc effacés à chaque mise à jour.

---

## Sécurité

**Lecture libre, écriture confirmée.** L'assistant lit, mesure et propose ce
qu'il veut. Toute modification passe par `assistant/safety.py` :

- elle est décrite en clair avant d'être faite ;
- elle attend un accord explicite ;
- elle est journalisée dans `data/logs/actions.jsonl`, acceptée **comme**
  refusée.

Certains chemins sont refusés même si tu confirmes — voir `PROTECTED_PATHS`
dans `config.py`. `C:\Users\Asuna\Documents\Unreal Projects` en fait partie.

---

## Architecture

```
assistant/
  config.py          réglages : racines scannées, exclusions, modèle, chemins protégés
  util.py            normalisation de chemins, formatage
  safety.py          garde-fou d'écriture + journal d'audit
  llm.py             Ollama + catalogue d'outils appelables par le modèle
  cli.py             entrée texte
  main.py            entrée vocale
  index/
    db.py            schéma SQLite + requêtes (FTS5)
    scanner.py       parcours des disques
  skills/
    files.py         recherche, poids, doublons, caches
    system.py        CPU/RAM/GPU/disques, diagnostic de lenteur
    games.py         détection et lancement des jeux
  gui.py             la fenêtre
  theme.py           couleurs, polices, espacements
  widgets.py         coins arrondis, zone défilante, cartes de message
  voice/
    stt.py           Whisper (GPU, repli CPU automatique)
    tts.py           voix Windows Hortense
    wake.py          mot-clé + raccourci global
  startup.py         démarrage automatique avec Windows
data/
  logs/actions.jsonl journal des actions
  logs/assistant.log sortie du lancement automatique
```

Le modèle **ne touche jamais au disque lui-même**. Il choisit un outil dans le
catalogue de `llm.py`, l'assistant l'exécute et lui rend le résultat. C'est ce
qui rend le comportement prévisible et vérifiable.

---

## Composants

| Rôle | Choix | Où |
|---|---|---|
| Modèle de langage | `qwen3.5:4b` | GPU, ~6,1 Go VRAM |
| Reconnaissance vocale | `faster-whisper medium` | GPU, ~1,5 Go VRAM |
| Mot-clé | openWakeWord `alexa` | CPU, négligeable |
| Synthèse vocale | SAPI Hortense | CPU |
| Index fichiers | SQLite + FTS5 | **mémoire vive uniquement** |

Les deux modèles GPU tiennent ensemble dans les 16 Go de la RTX 5060 Ti, en
laissant ~8 Go libres pour un jeu qui tourne en même temps.

Le moteur de langage se change en une ligne : `LLM_MODEL` dans `config.py`,
puis `ollama pull <nom>`. Un modèle plus gros répond mieux mais choisit ses
outils plus lentement et mange la VRAM du jeu.

---

## Démarrer avec Windows

```bash
.venv\Scripts\python.exe -m assistant.cli demarrage-auto on
```

L'assistant se lance alors avec ta session, **sans fenêtre**, et reconstruit sa
connaissance des fichiers en mémoire. Pour l'enlever : `demarrage-auto off`.
Ça écrit une seule valeur dans `HKCU\...\Run`, aucun droit administrateur.

---

## Entretien

La connaissance des fichiers est une photographie prise au démarrage. Après
une grosse installation ou désinstallation, relance `assistant.cli scan`
(40 secondes) — ou redémarre simplement l'assistant.

