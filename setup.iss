[code]
#define VerFile FileOpen("version")
#define AppVer FileRead(VerFile)
#expr FileClose(VerFile)
#undef VerFile

[Setup]
AppName=NADO
AppVersion={#AppVer}
DefaultDirName={pf}\NADO
DefaultGroupName=NADO
UninstallDisplayIcon={app}\nado.exe
Compression=lzma2
SolidCompression=yes
OutputBaseFilename=NADO_setup
SetupIconFile=graphics\icon.ico
DisableDirPage=no

WizardImageFile=graphics\left.bmp
WizardSmallImageFile=graphics\mini.bmp

[Files]
Source: "nado.dist\*" ; DestDir: "{app}"; Flags: recursesubdirs;

[Icons]
Name: "{group}\NADO"; Filename: "{app}\nado.exe"
Name: "{group}\Uninstall NADO"; Filename: "{uninstallexe}"

Name: "{commondesktop}\NADO"; Filename: "{app}\nado.exe"

[Registry]
; keys for 32-bit systems
Root: HKCU32; Subkey: "SOFTWARE\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers"; ValueType: String; ValueName: "{app}\nado.exe"; ValueData: "RUNASADMIN"; Flags: uninsdeletekeyifempty uninsdeletevalue; Check: not IsWin64
Root: HKLM32; Subkey: "SOFTWARE\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers"; ValueType: String; ValueName: "{app}\nado.exe"; ValueData: "RUNASADMIN"; Flags: uninsdeletekeyifempty uninsdeletevalue; Check: not IsWin64

; keys for 64-bit systems
Root: HKCU64; Subkey: "SOFTWARE\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers"; ValueType: String; ValueName: "{app}\nado.exe"; ValueData: "RUNASADMIN"; Flags: uninsdeletekeyifempty uninsdeletevalue; Check: IsWin64
Root: HKLM64; Subkey: "SOFTWARE\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers"; ValueType: String; ValueName: "{app}\nado.exe"; ValueData: "RUNASADMIN"; Flags: uninsdeletekeyifempty uninsdeletevalue; Check: IsWin64


[Run]
Filename: "{app}\NADO.exe"; Description: "Run NADO"; Flags: shellexec postinstall skipifsilent unchecked
