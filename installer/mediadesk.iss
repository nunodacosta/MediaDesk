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
#define AppVersion "3.6.0"
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

[Tasks]
Name: "desktopicon"; Description: "Criar um atalho no ambiente de trabalho"; GroupDescription: "Atalhos:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Desinstalar {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Executar {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Apenas artefactos gerados em execucao. Nunca remover "downloads" (dados do utilizador).
Type: files; Name: "{app}\.payload-version"
Type: files; Name: "{app}\launcher.log"
