; ---------------------------------------------------------------------------
;  installer\mediadesk.iss
;  Script do Inno Setup para gerar o instalador do YT-DLP Media Desk.
;
;  Instalacao POR UTILIZADOR (PrivilegesRequired=lowest) em
;  %LOCALAPPDATA%\Programs\YT-DLP Media Desk — a pasta fica gravavel, o que
;  resolve a restricao de escrita dos "modulos" quando instalado.
;
;  Compilar (depois de gerar dist\MediaDesk-Portable):
;     "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\mediadesk.iss
;
;  Resultado: dist\MediaDesk-Setup.exe
; ---------------------------------------------------------------------------

#define AppName "YT-DLP Media Desk"
#define AppVersion "3.7.2"
#define AppPublisher "ALDACO"
#define AppCopyright "Design e interacao por ALDACO. Motor de downloads por YT-DLP. Software livre: GPL-3.0."
#define AppExeName "YT-DLP-Media-Desk.exe"
#define SourceDir "..\dist\MediaDesk-Portable"

[Setup]
AppId={{B7F3E2A1-9C4D-4E7B-8A2F-5D1C6E9B0A34}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppCopyright={#AppCopyright}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} - Instalador
VersionInfoCopyright={#AppCopyright}
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}
VersionInfoTextVersion={#AppVersion}
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=MediaDesk-Setup
SetupIconFile=..\app.ico
UninstallDisplayIcon={app}\{#AppExeName}
LicenseFile=..\licenses\THIRD-PARTY-NOTICES.txt
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
MinVersion=10.0

[Languages]
Name: "portuguese"; MessagesFile: "compiler:Languages\Portuguese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[CustomMessages]
portuguese.CreateDesktopIcon=Criar um atalho no ambiente de trabalho
english.CreateDesktopIcon=Create a desktop shortcut
spanish.CreateDesktopIcon=Crear un acceso directo en el escritorio
french.CreateDesktopIcon=Créer un raccourci sur le Bureau
german.CreateDesktopIcon=Eine Verknüpfung auf dem Desktop erstellen

portuguese.Shortcuts=Atalhos:
english.Shortcuts=Shortcuts:
spanish.Shortcuts=Accesos directos:
french.Shortcuts=Raccourcis :
german.Shortcuts=Verknüpfungen:

portuguese.UninstallApp=Desinstalar {#AppName}
english.UninstallApp=Uninstall {#AppName}
spanish.UninstallApp=Desinstalar {#AppName}
french.UninstallApp=Désinstaller {#AppName}
german.UninstallApp={#AppName} deinstallieren

portuguese.RunApp=Executar {#AppName}
english.RunApp=Run {#AppName}
spanish.RunApp=Ejecutar {#AppName}
french.RunApp=Exécuter {#AppName}
german.RunApp={#AppName} ausführen

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:Shortcuts}"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\{cm:UninstallApp}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:RunApp}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Apenas artefactos gerados em execucao. Nunca remover "downloads" (dados do utilizador).
Type: files; Name: "{app}\.payload-version"
Type: files; Name: "{app}\launcher.log"
