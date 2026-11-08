; Inno Setup script - build with:  ISCC /DAppVersion=0.1.0 installer\DocuCraft.iss
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{6F0B0C54-3D1B-4B8E-9D55-DC0C0A7F1A01}
AppName=DocuCraft
AppVersion={#AppVersion}
AppPublisher=Hassan Malik (Shadow Creative Studio)
DefaultDirName={autopf}\DocuCraft
DefaultGroupName=DocuCraft
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=DocuCraft-Setup-{#AppVersion}
SetupIconFile=..\assets\icons\docucraft.ico
UninstallDisplayIcon={app}\DocuCraft.exe
LicenseFile=..\LICENSE
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; Flags: unchecked
Name: "pdfassoc"; Description: "Open &PDF files with DocuCraft (you can change this later in Windows Settings)"; Flags: unchecked

[Files]
Source: "..\dist\DocuCraft\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\DocuCraft"; Filename: "{app}\DocuCraft.exe"
Name: "{autodesktop}\DocuCraft"; Filename: "{app}\DocuCraft.exe"; Tasks: desktopicon

[Registry]
Root: HKA; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "DocuCraft.pdf"; ValueData: ""; Flags: uninsdeletevalue; Tasks: pdfassoc
Root: HKA; Subkey: "Software\Classes\DocuCraft.pdf"; ValueType: string; ValueData: "PDF document"; Flags: uninsdeletekey; Tasks: pdfassoc
Root: HKA; Subkey: "Software\Classes\DocuCraft.pdf\shell\open\command"; ValueType: string; ValueData: """{app}\DocuCraft.exe"" ""%1"""; Tasks: pdfassoc

[Run]
Filename: "{app}\DocuCraft.exe"; Description: "Launch DocuCraft"; Flags: nowait postinstall skipifsilent

; User data (history, settings, logs) lives in %APPDATA%\DocuCraft and is intentionally NOT removed on uninstall.
