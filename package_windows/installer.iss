; Independent Desktop per-user installer. No original DLMS builder is used.
#ifndef Payload
  #error Payload is required
#endif
#ifndef Release
  #error Release is required
#endif
#ifndef OutputRoot
  #error OutputRoot is required
#endif

[Setup]
AppId={{D8777379-04C8-40E8-A15F-0F05F5919AF6}
AppName=DLMS Desktop Windows Candidate
AppVersion=0.1.0
AppVerName=DLMS Desktop Windows Candidate {#Release}
AppPublisher=DLMS Desktop private project
DefaultDirName={localappdata}\Programs\DLMS Desktop Candidate
DefaultGroupName=DLMS Desktop Candidate
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0.22000
CloseApplications=no
RestartApplications=no
AppMutex=Local\DLMSDesktop.WindowsCandidate.Running
SetupIconFile=..\desktop_assets\icons\windows\DLMSDesktop.ico
UninstallDisplayIcon={app}\versions\{#Release}\DLMS-Desktop.exe
UninstallFilesDir={app}\uninstall
OutputDir={#OutputRoot}
OutputBaseFilename=DLMS-Desktop-Windows-x86_64-{#Release}-Setup
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
SignedUninstaller=no
#ifdef TestScope
; Compile-time isolated qualification variant. Identical payload/version/update
; and uninstall behavior, with real-user integration explicitly omitted.
CreateUninstallRegKey=no
#else
CreateUninstallRegKey=yes
#endif

[Files]
Source: "{#Payload}\*"; DestDir: "{app}\versions\{#Release}"; Flags: ignoreversion recursesubdirs createallsubdirs

#ifndef TestScope
[Icons]
Name: "{group}\DLMS Desktop"; Filename: "{app}\versions\{#Release}\DLMS-Desktop.exe"; WorkingDir: "{app}\versions\{#Release}"
Name: "{group}\Uninstall DLMS Desktop"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\versions\{#Release}\DLMS-Desktop.exe"; Description: "Open DLMS Desktop"; Flags: nowait postinstall skipifsilent unchecked
#endif

; No data, profile, cache, downloads, backup or external directory is installed
; or deleted. Previous version payloads remain until explicit uninstall.

[Code]
type
  TNativeFileInfo = record
    Attributes: LongWord;
    Created, Accessed, Written: TFileTime;
    Volume, SizeHigh, SizeLow, Links, IndexHigh, IndexLow: LongWord;
  end;
  TTokenUserBuffer = record
    Sid: NativeUInt;
    Attributes: LongWord;
    Padding: array[0..255] of Byte;
  end;
  TAclSizeInfo = record
    Count, Used, FreeBytes: LongWord;
  end;
  TAcePrefix = record
    Kind, Flags: Byte;
    Size: Word;
    Mask: LongWord;
  end;
var
  Pins: array of THandle;
  PinnedPaths: TStringList;
  AppDirectories: TStringList;
  CurrentSid: String;

function NativeAttributes(Name: String): LongWord;
  external 'GetFileAttributesW@kernel32.dll stdcall';
function NativeLastError: LongWord;
  external 'GetLastError@kernel32.dll stdcall';
function OpenDirectory(Name: String; Access, Sharing: LongWord; Security: NativeUInt;
  Creation, Flags: LongWord; Template: THandle): THandle;
  external 'CreateFileW@kernel32.dll stdcall';
function FileInformation(Handle: THandle; var Info: TNativeFileInfo): Boolean;
  external 'GetFileInformationByHandle@kernel32.dll stdcall';
function CloseNative(Handle: THandle): Boolean;
  external 'CloseHandle@kernel32.dll stdcall';
function CurrentProcess: THandle;
  external 'GetCurrentProcess@kernel32.dll stdcall';
function OpenToken(Process: THandle; Access: LongWord; var Token: THandle): Boolean;
  external 'OpenProcessToken@advapi32.dll stdcall';
function TokenInformation(Token: THandle; Kind: Integer; var Info: TTokenUserBuffer;
  Size: LongWord; var Needed: LongWord): Boolean;
  external 'GetTokenInformation@advapi32.dll stdcall';
function SidToText(Sid: NativeUInt; var Text: NativeUInt): Boolean;
  external 'ConvertSidToStringSidW@advapi32.dll stdcall';
function NativeStringLength(Text: NativeUInt): Integer;
  external 'lstrlenW@kernel32.dll stdcall';
function CopyNativeString(Dest: String; Source: NativeUInt; Count: Integer): NativeUInt;
  external 'lstrcpynW@kernel32.dll stdcall';
function FreeNative(Value: NativeUInt): NativeUInt;
  external 'LocalFree@kernel32.dll stdcall';
function SecurityInformation(Handle: THandle; Kind, Requested: LongWord;
  var Owner, Group, Dacl, Sacl, Descriptor: NativeUInt): LongWord;
  external 'GetSecurityInfo@advapi32.dll stdcall';
function AclInformation(Acl: NativeUInt; var Info: TAclSizeInfo; Size, Kind: LongWord): Boolean;
  external 'GetAclInformation@advapi32.dll stdcall';
function AceInformation(Acl: NativeUInt; Index: LongWord; var Ace: NativeUInt): Boolean;
  external 'GetAce@advapi32.dll stdcall';
procedure CopyAce(var Dest: TAcePrefix; Source: NativeUInt; Size: NativeUInt);
  external 'RtlMoveMemory@kernel32.dll stdcall';

function SidString(Sid: NativeUInt): String;
var Text: NativeUInt;
begin
  Result := '';
  if not SidToText(Sid, Text) then Exit;
  try
    SetLength(Result, NativeStringLength(Text) + 1);
    CopyNativeString(Result, Text, Length(Result));
    SetLength(Result, Length(Result) - 1);
  finally
    FreeNative(Text);
  end;
end;

function InitializeGuard: Boolean;
var Token: THandle; User: TTokenUserBuffer; Needed: LongWord;
begin
  Result := False;
  if PinnedPaths = nil then begin
    PinnedPaths := TStringList.Create;
    AppDirectories := TStringList.Create;
  end;
  if CurrentSid <> '' then begin Result := True; Exit; end;
  if not OpenToken(CurrentProcess, 8, Token) then Exit;
  try
    if not TokenInformation(Token, 1, User, SizeOf(User), Needed) then Exit;
    CurrentSid := SidString(User.Sid);
    Result := CurrentSid <> '';
  finally CloseNative(Token); end;
end;

function OwnedDirectory(Handle: THandle): Boolean;
var Owner, Group, Dacl, Sacl, Descriptor, Ace: NativeUInt;
    Info: TAclSizeInfo; Prefix: TAcePrefix; I: Integer; Sid: String;
begin
  Result := False;
  if SecurityInformation(Handle, 1, 5, Owner, Group, Dacl, Sacl, Descriptor) <> 0 then Exit;
  try
    if (SidString(Owner) <> CurrentSid) or (Dacl = 0) then Exit;
    if not AclInformation(Dacl, Info, SizeOf(Info), 2) then Exit;
    for I := 0 to Integer(Info.Count) - 1 do begin
      if not AceInformation(Dacl, I, Ace) then Exit;
      CopyAce(Prefix, Ace, SizeOf(Prefix));
      if ((Prefix.Flags and 8) = 0) and (Prefix.Kind <> 1) then begin
        if Prefix.Kind <> 0 then Exit;
        Sid := SidString(Ace + 8);
        if Sid = '' then Exit;
        if (Sid <> CurrentSid) and (Sid <> 'S-1-5-18') and
           (Sid <> 'S-1-5-32-544') and (Sid <> 'S-1-3-4') and
           ((Prefix.Mask and $500D0156) <> 0) then Exit;
      end;
    end;
    Result := True;
  finally FreeNative(Descriptor); end;
end;

function PinDirectory(Path: String; RequireOwner: Boolean): Boolean;
var Handle: THandle; Info: TNativeFileInfo; N: Integer;
begin
  Result := False;
  Path := RemoveBackslashUnlessRoot(Path);
  N := PinnedPaths.IndexOf(Lowercase(Path));
  if N >= 0 then begin
    Result := (not RequireOwner) or OwnedDirectory(Pins[N]); Exit;
  end;
  { READ_CONTROL | FILE_READ_ATTRIBUTES | FILE_LIST_DIRECTORY; no DELETE sharing. }
  Handle := OpenDirectory(Path, $20081, 3, 0, 3, $2200000, 0);
  if Handle = THandle(-1) then Exit;
  if not FileInformation(Handle, Info) or ((Info.Attributes and $400) <> 0) or
     ((Info.Attributes and $10) = 0) or (RequireOwner and not OwnedDirectory(Handle)) then begin
    CloseNative(Handle); Exit;
  end;
  N := GetArrayLength(Pins); SetArrayLength(Pins, N + 1); Pins[N] := Handle;
  PinnedPaths.Add(Lowercase(Path));
  Result := True;
end;

procedure ReleasePins;
var I: Integer;
begin
  for I := GetArrayLength(Pins) - 1 downto 0 do CloseNative(Pins[I]);
  SetArrayLength(Pins, 0);
  if PinnedPaths <> nil then PinnedPaths.Clear;
end;

function SafeDirectoryChain(Path: String): Boolean;
var
  Attributes, ErrorCode: LongWord;
  Parent: String;
begin
  Result := False;
  Path := RemoveBackslashUnlessRoot(ExpandFileName(Path));
  if (Length(Path) < 3) or (Copy(Path, 2, 2) <> ':\') then Exit;
  Parent := RemoveBackslashUnlessRoot(ExtractFileDir(Path));
  { Pin root-to-leaf: never open a descendant through an unpinned ancestor. }
  if (Parent <> Path) and not SafeDirectoryChain(Parent) then Exit;
  Attributes := NativeAttributes(Path);
  if Attributes = $FFFFFFFF then begin
    ErrorCode := NativeLastError;
    if (ErrorCode <> 2) and (ErrorCode <> 3) then Exit;
  end else begin
    if not PinDirectory(Path, False) then Exit;
  end;
  Result := True;
end;

function SafeTree(Path: String): Boolean;
var Found: TFindRec; Child: String;
begin
  Result := False;
  if not PinDirectory(Path, True) then Exit;
  AppDirectories.Add(Path);
  if FindFirst(AddBackslash(Path) + '*', Found) then begin
    try
      repeat
        if (Found.Name <> '.') and (Found.Name <> '..') then begin
          Child := AddBackslash(Path) + Found.Name;
          if (Found.Attributes and $400) <> 0 then Exit;
          if ((Found.Attributes and $10) <> 0) and not SafeTree(Child) then Exit;
        end;
      until not FindNext(Found);
    finally FindClose(Found); end;
  end else if (NativeLastError <> 2) and (NativeLastError <> 18) then Exit;
  Result := True;
end;

function GuardApplication(CreatePaths: Boolean): Boolean;
var Path, Parent: String;
begin
  Result := False;
  ReleasePins;
  if not InitializeGuard then Exit;
  AppDirectories.Clear;
  Path := ExpandConstant('{app}');
  if not SafeDirectoryChain(Path) then Exit;
  Parent := Path;
  while not DirExists(Parent) do Parent := ExtractFileDir(Parent);
  { Require a current-user-owned, non-publicly-writable creation namespace. }
  if not PinDirectory(Parent, True) or not SafeDirectoryChain(Path) then Exit;
  if DirExists(Path) and not SafeTree(Path) then Exit;
  if CreatePaths then begin
    if not ForceDirectories(ExpandConstant('{app}\versions\{#Release}')) or
       not ForceDirectories(ExpandConstant('{app}\uninstall')) then Exit;
  end;
  Result := SafeTree(Path);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if not GuardApplication(True) then begin
    ReleasePins;
    Result := 'The installation directory is unsafe or inaccessible. Choose a local directory owned by your account without public write access, junctions or links.';
  end;
end;

procedure DeinitializeSetup;
begin ReleasePins; end;

function InitializeUninstall: Boolean;
begin
  Result := GuardApplication(False);
  if not Result then begin
    ReleasePins;
    Log('Uninstall refused: unsafe installation path, ownership, permissions or reparse point.');
    if not UninstallSilent then MsgBox('Uninstall refused because an installation path or its permissions changed. Restore the original directories and retry. Your data is unchanged.', mbError, MB_OK);
  end;
end;

procedure CurUninstallStepChanged(Step: TUninstallStep);
var I: Integer;
begin
  if Step = usPostUninstall then begin
    ReleasePins;
    { Logged file deletion ran with directory identities pinned. Remove only
      empty directories afterwards; RemoveDir never recursively follows links. }
    for I := AppDirectories.Count - 1 downto 0 do RemoveDir(AppDirectories[I]);
  end;
end;

procedure DeinitializeUninstall;
begin ReleasePins; end;
