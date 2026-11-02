# Assistant local

Assistant textuel qui connaît cette machine, et qui s'oriente vers le
développement de jeux vidéo. **Le modèle de langage tourne en local**, sur la
carte graphique.

**La règle : les données privées ne quittent jamais le PC.** Vos fichiers,
vos conversations et ce que l'assistant apprend de la machine restent ici.
L'application peut aller sur Internet pour ce qui la concerne elle-même, et
seulement quand vous le demandez : la **vérification des mises à jour**
(GitHub) et la **réparation de l'image de Windows** (DISM, qui récupère des
fichiers sains auprès de Windows Update).

### [⬇️ Télécharger l'installateur (Windows)](https://github.com/alexis73beloeil100-dev/assistant-local-/releases/latest)

Un seul fichier, rien d'autre à installer. La liste de fichiers ci-dessus est
le code source : elle ne sert qu'à qui veut le lire.

---

## Démarrer

**Double-clic sur « Assistant local » sur le Bureau.**

C'est un vrai exécutable Windows : `dist\AssistantLocal\AssistantLocal.exe`.
Il n'a besoin ni de Python ni de rien d'installé — tout est embarqué.

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
| Mise à jour | vérifier et installer la dernière version publiée |

**La conversation**, pour les questions libres, où le modèle est
indispensable. Pour dicter : la dictée de Windows, **Win+H** dans la zone de
texte. La voix de l'assistant (reconnaissance, mot-clé, lecture à voix
haute) a été retirée en 1.0.6 : avec un modèle local, elle ne comprenait
qu'une phrase sur six.

**La mini-fenêtre** : **Win+Maj+A**, n'importe où, fait apparaître un petit
orbe en haut de l'écran, la zone de texte prête. Échap le renvoie.

**L'atelier Unreal** (mode Dev) : projets récents ou **Choisir le projet**,
moteur UE5 retrouvé tout seul (registre, Launcher ou moteur compilé), compilation
avec les erreurs par fichier et ligne, journaux de l'éditeur, dernier rapport de
plantage. Voir `assistant/skills/unreal.py`.

**Le mode Dev / PC**, en bas à gauche. En **Dev**, le modèle ne voit que les
outils du développement (fichiers et code, captures, commandes, applications,
état du PC, atelier Unreal) : 27 outils au lieu de 81, il répond plus vite et se trompe moins
d'outil. En **PC**, il a tout.

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
cd "%USERPROFILE%\Documents\Assistant"
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

Tout est journalisé dans `%APPDATA%\AssistantLocal\logs\actions.jsonl` — accepté **comme** refusé.

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

## Distribuer l'application

`installateur\Installer_AssistantLocal.exe` (116 Mo) est un installateur
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

**Les mises à jour** passent par le panneau **Mise à jour** : *Vérifier*
interroge la dernière Release GitHub, *Installer* télécharge le paquet,
contrôle son empreinte SHA-256 et le lance. Le paquet ne contient que les
fichiers qui ont changé. Il est fabriqué par GitHub
(`.github/workflows/publier.yml`) : un commit dont le message contient
`[publier]` construit l'application sous Windows et publie la Release.

Pour le reconstruire à la main :

```bash
.venv\Scripts\python.exe reconstruire.py
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installateur.iss
```

---

## Autotest

```bash
dist\AssistantLocal\AssistantLocal.exe --autotest
```

Chaque partie est vérifiée : environnement, droits d'écriture, disques,
relevé matériel, moteur d'IA, modèle, lecture d'images, jeux, applications,
inventaire, démarrage de Windows. Chacune dit ce qu'elle teste, ce qu'elle trouve, et quoi faire si ça
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
- elle est journalisée dans `%APPDATA%\AssistantLocal\logs\actions.jsonl`, acceptée **comme**
  refusée.

Certains chemins sont refusés même si tu confirmes — voir `PROTECTED_PATHS`
dans `config.py`. `%USERPROFILE%\Documents\Unreal Projects` en fait partie.

---

## Architecture

```
assistant/
  config.py          réglages : racines scannées, exclusions, modèle, chemins protégés
  util.py            normalisation de chemins, formatage
  safety.py          garde-fou d'écriture + journal d'audit
  llm.py             Ollama + catalogue d'outils appelables par le modèle
  cli.py             entrée texte
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
  mini_fenetre.py    l'orbe de Win+Maj+A
  mise_a_jour.py     vérifier, télécharger, contrôler, installer
  sans_console.py    aucune fenêtre noire pour les programmes lancés
  startup.py         démarrage automatique avec Windows
```

**Les données ne vivent pas dans le dossier du programme.** Celui-ci est
effacé et recréé à chaque reconstruction, et supprimé à la désinstallation.
Elles sont dans ton profil, où rien ne les touche :

```
%APPDATA%\AssistantLocal\
  settings.json        réglages, dont la commande des programmes désactivés
  logs\actions.jsonl   journal des actions
  logs\assistant.log   sortie du lancement automatique
```

C'est `startup_backup` qui rend ce choix indispensable : il conserve la
commande exacte des programmes retirés du démarrage. Perdue, un programme
désactivé ne peut plus jamais être réactivé autrement qu'en le réinstallant.
Les données laissées à l'ancien emplacement sont rapatriées au premier
lancement.

Le modèle **ne touche jamais au disque lui-même**. Il choisit un outil dans le
catalogue de `llm.py`, l'assistant l'exécute et lui rend le résultat. C'est ce
qui rend le comportement prévisible et vérifiable.

---

## Composants

| Rôle | Choix | Où |
|---|---|---|
| Modèle de langage | `qwen3.5:4b` | GPU, ~6,1 Go VRAM |
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

## Publier une mise à jour

L'installateur complet pèse 1,15 Go, mais **74 % de ce poids sont les
bibliothèques CUDA**, qui n'ont pas bougé depuis le premier jour. Ce qui porte
le travail — l'exécutable — en fait 24. Obliger les gens à retélécharger 1,15 Go
pour un correctif de trois lignes, c'est s'assurer qu'ils ne le prendront
jamais.

D'où un second format de livraison, qui ne contient que la différence :

```
.venv\Scripts\python.exe outils\paquet_maj.py 1.0.1
```

L'argument est la version **déjà publiée**, celle dont on part ; la version
d'arrivée est lue dans `assistant/__init__.py`. Le script compare le dossier
livré au manifeste de la version publiée, et compile un installateur qui ne
transporte que les fichiers dont le contenu a changé.

### La séquence, dans l'ordre

1. Corriger le code, incrémenter `__version__` **et** `MaVersion` dans
   `installateur.iss` (un test refuse qu'ils divergent).
2. `python reconstruire.py` — reconstruit `dist/` et y recopie les licences.
3. `python outils\paquet_maj.py <version précédente>` — produit le paquet
   **et** le manifeste de la nouvelle version.
4. Committer le nouveau manifeste. **C'est l'étape qu'on oublie**, et elle ne
   se rattrape pas : sans le manifeste d'une version publiée, il devient
   impossible de calculer ce qui a changé depuis ce que les gens ont
   réellement installé.

### Ce que le paquet refuse de faire

- **S'installer sur une machine vierge.** Il contient quelques dizaines de
  fichiers, pas les 2,5 Go de bibliothèques : l'application ne démarrerait
  pas, et le message d'erreur ne dirait rien de la vraie cause. Il vérifie la
  base de registres et renvoie vers l'installateur complet.
- **Descendre une version.** Si la version installée est plus récente, il
  demande confirmation avant de continuer.
- **S'appliquer depuis une autre version que celle prévue.** Une mise à jour
  1.0.1 → 1.0.2 ne livre que ce qui diffère de la 1.0.1 ; posée sur une 1.0.0,
  elle laisserait des fichiers d'une version intermédiaire.

### Pourquoi rien ne se met à jour tout seul

Il n'y a **aucune vérification automatique** : le panneau Mise à jour ne
contacte GitHub que sur un clic. Une application qui se connecte d'elle-même,
sans que personne l'ait demandé, c'est ce qu'on refuse.

### Le détail qui fait tenir l'ensemble

Le paquet porte **le même `AppId`** que l'installateur complet. C'est ce qui
le fait reconnaître comme une mise à jour et non comme un second logiciel :
Inno ajoute alors ses fichiers au journal de désinstallation existant au lieu
de le remplacer. Avec un identifiant différent, Windows afficherait deux
« Assistant local », et désinstaller l'un laisserait 2,5 Go derrière l'autre.
Un test vérifie que les deux identifiants restent égaux.

---

## Licences

**Le programme distribué est sous [licence MIT](LICENSE).**

Il s'est transmis sous GPLv3 jusqu'au 23/08/2026, parce qu'il intégrait
`openrgb-python`. Cette bibliothèque a d'abord été remplacée par du code écrit
pour ce projet, puis le pilotage de l'éclairage a été retiré entièrement en
1.0.7. Plus aucun composant intégré n'impose sa licence à l'ensemble.

Les fichiers écrits pour ce projet restent sous [licence MIT](LICENSE) et
réutilisables comme tels. Le détail composant par composant est dans
[LICENCES-TIERS.md](LICENCES-TIERS.md).

Le tableau des licences se régénère depuis les métadonnées des paquets
installés, plutôt que d'être tenu à la main :

```
.venv\Scripts\python.exe outils\licences_tierces.py
```

