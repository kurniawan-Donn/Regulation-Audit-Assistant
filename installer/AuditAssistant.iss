; Installer Windows Audit Assistant (Inno Setup 6).
;
; Dibangun oleh scripts/build_installer.py - jangan dikompilasi langsung tanpa
; folder bundel. Parameter dari skrip build:
;   /DAppVersion=1.2.3  /DBundleDir=<folder bundel>  /DOutputDir=<folder dist>
;
; Dipasang per pengguna (tanpa hak admin) di %LOCALAPPDATA%\Programs\Audit Assistant.
; Data pengguna (Database Regulasi, temuan, riwayat, API key) ada di
; %LOCALAPPDATA%\Audit Assistant dan TIDAK disentuh saat update maupun uninstall.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef BundleDir
  #define BundleDir "..\build\bundle"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

#define AppName "Audit Assistant"
#define AppPublisher "Audit Assistant"
#define AppUrl "https://github.com/kurniawan-Donn/regulation-audit-assistant"

[Setup]
; AppId tetap sama di semua versi agar Setup baru memperbarui instalasi lama.
AppId={{8F3C2B71-5E4A-4C1D-9B7E-2A6D4F8C1E35}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename=AuditAssistant-{#AppVersion}-Setup
SetupIconFile=audit-assistant.ico
UninstallDisplayIcon={app}\audit-assistant.ico
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Tutup aplikasi yang sedang berjalan sebelum file ditimpa saat update.
CloseApplications=yes
RestartApplications=no

[Languages]
; Indonesian.isl: terjemahan komunitas dari repositori Inno Setup
; (issrc/Files/Languages/Unofficial), butuh Inno Setup 6.5+.
Name: "indonesian"; MessagesFile: "Indonesian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; Bersihkan kode versi lama agar file yang dihapus di versi baru tidak tertinggal.
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\static"
Type: filesandordirs; Name: "{app}\templates"
Type: filesandordirs; Name: "{app}\scripts"
Type: filesandordirs; Name: "{app}\python"

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Excludes: "Audit Assistant.bat,userdata"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "audit-assistant.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\python\python.exe"; Parameters: "-m scripts.launch --installed"; WorkingDir: "{app}"; IconFilename: "{app}\audit-assistant.ico"; Comment: "Jalankan Audit Assistant"; Flags: runminimized
Name: "{group}\Folder Data {#AppName}"; Filename: "{localappdata}\{#AppName}"; Comment: "Database Regulasi, temuan, riwayat, dan log"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\python\python.exe"; Parameters: "-m scripts.launch --installed"; WorkingDir: "{app}"; IconFilename: "{app}\audit-assistant.ico"; Comment: "Jalankan Audit Assistant"; Flags: runminimized; Tasks: desktopicon

[Dirs]
Name: "{localappdata}\{#AppName}"; Flags: uninsneveruninstall

[Run]
Filename: "{app}\python\python.exe"; Parameters: "-m scripts.launch --installed"; WorkingDir: "{app}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent runminimized

[UninstallDelete]
; File cache Python yang dibuat saat aplikasi berjalan.
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\scripts"
Type: filesandordirs; Name: "{app}\python"
