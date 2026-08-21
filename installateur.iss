; Installateur de l'Assistant local.
;
; Produit un Setup.exe unique, distribuable, avec desinstallation propre.
; Compile par outils/creer_setup.py, qui verifie d'abord que dist/ est a jour.
;
; L'installation se fait dans le profil de l'utilisateur (pas Program Files) :
; l'application ecrit son journal et ses reglages a cote d'elle, ce que les
; droits de Program Files interdiraient sans elevation. Aucun droit
; administrateur n'est donc necessaire.

#define MonNom "Assistant local"
#define MonExe "AssistantLocal.exe"
#define MonEditeur "Assistant local"
#define MaVersion "1.0.0"

[Setup]
AppId={{8F3C1A62-4E7D-4B21-9C0E-2A5D6B7E9F14}
AppName={#MonNom}
AppVersion={#MaVersion}
AppPublisher={#MonEditeur}
DefaultDirName={localappdata}\AssistantLocal
DefaultGroupName={#MonNom}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=installateur
OutputBaseFilename=Installer_AssistantLocal
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; 2,4 Go de contenu : sans cette marge, l'installation echoue en fin de course.
ExtraDiskSpaceRequired=0
UninstallDisplayName={#MonNom}
UninstallDisplayIcon={app}\{#MonExe}
; Page d'explication avant l'installation : sans elle, la personne qui
; installe ne sait pas ce que fait le logiciel, ni pourquoi un second ecran
; s'ouvre a la fin pour telecharger des modeles.
InfoBeforeFile=installateur_infos.txt

[Languages]
Name: "francais"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "raccourcibureau"; Description: "Creer un raccourci sur le Bureau"; \
    GroupDescription: "Raccourcis :"
Name: "demarrage"; Description: "Lancer l'assistant au demarrage de Windows"; \
    GroupDescription: "Demarrage :"; Flags: unchecked

[Files]
Source: "dist\AssistantLocal\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MonNom}"; Filename: "{app}\{#MonExe}"
Name: "{group}\Composants et installation"; Filename: "{app}\{#MonExe}"; \
    Parameters: "--installer"
Name: "{group}\Desinstaller {#MonNom}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MonNom}"; Filename: "{app}\{#MonExe}"; \
    Tasks: raccourcibureau

[Registry]
; Demarrage avec la session, uniquement si la case est cochee. Sous HKCU,
; donc sans droits administrateur, et retire a la desinstallation.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "AssistantLocal"; \
    ValueData: """{app}\{#MonExe}"""; Flags: uninsdeletevalue; \
    Tasks: demarrage

[Run]
; A la fin de l'installation, on propose l'ecran des composants : le moteur
; d'IA et les modeles ne sont pas embarques (ils pesent plusieurs Go et
; dependent du materiel de la machine).
Filename: "{app}\{#MonExe}"; Parameters: "--installer"; \
    Description: "Choisir et telecharger les composants (moteur IA, voix)"; \
    Flags: postinstall skipifsilent
Filename: "{app}\{#MonExe}"; \
    Description: "Ouvrir l'assistant apres l'installation"; \
    Flags: postinstall nowait skipifsilent unchecked

[UninstallDelete]
; Reglages et journaux crees par l'application apres l'installation :
; sans cela, le dossier resterait avec quelques fichiers orphelins.
Type: filesandordirs; Name: "{app}\data"
Type: files; Name: "{app}\erreurs.log"

[Code]
procedure FermerApplication();
var
  CodeRetour: Integer;
begin
  { L'application peut tourner : ses fichiers seraient verrouilles et
    l'operation laisserait un dossier a moitie ecrit. On la ferme d'abord,
    ainsi que le moteur de calcul d'Ollama qui charge ses DLL. }
  Exec('taskkill.exe', '/IM AssistantLocal.exe /F', '', SW_HIDE,
       ewWaitUntilTerminated, CodeRetour);
  Exec('taskkill.exe', '/IM llama-server.exe /F', '', SW_HIDE,
       ewWaitUntilTerminated, CodeRetour);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  FermerApplication();
  Result := '';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    FermerApplication();
end;
