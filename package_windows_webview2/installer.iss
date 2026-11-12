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
#ifdef TestScope
  #ifndef TestMenuRoot
    #define TestMenuRoot "{app}\synthetic-menu"
  #endif
  #ifndef TestDataRoot
    #define TestDataRoot "{app}\synthetic-data"
  #endif
#endif

[Setup]
AppId={{C7FCBD76-02F4-49C4-B187-9A143237A1F9}
#ifdef PublicPreview
AppName=DLMS Desktop Windows Preview
AppVerName=DLMS Desktop Windows Preview {#Release} (unsigned)
AppPublisher=DLMS project
AppVersion={#BackendVersion}
VersionInfoVersion={#BackendNumericVersion}
#else
AppName=DLMS Desktop WebView2 Candidate
AppVerName=DLMS Desktop WebView2 Candidate {#Release}
AppPublisher=DLMS Desktop private project
AppVersion=0.1.0
#endif
DefaultDirName={localappdata}\Programs\DLMS Desktop WebView2 Candidate
DefaultGroupName=DLMS Desktop WebView2 Candidate
DisableProgramGroupPage=yes
; Show the ordinary checked Start menu choice on every setup run.
UsePreviousTasks=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0.22000
CloseApplications=no
RestartApplications=no
AppMutex=Local\DLMSDesktop.WebView2Candidate.Running
SetupIconFile=..\desktop_assets\icons\windows\DLMSDesktop.ico
UninstallDisplayIcon={app}\versions\{#Release}\DLMS-Desktop-WebView2.exe
UninstallFilesDir={app}\uninstall
OutputDir={#OutputRoot}
OutputBaseFilename=DLMS-Desktop-WebView2-Windows-x86_64-{#Release}-Setup
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

[Tasks]
Name: "startmenu"; Description: "Create a Start menu shortcut"; GroupDescription: "Shortcuts:"
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Icons]
; This launcher lives under the guarded application root, not the shell tree.
Name: "{app}\Launch DLMS Desktop"; Filename: "{app}\versions\{#Release}\DLMS-Desktop-WebView2.exe"; Parameters: "{code:MenuProfileParameters}"; WorkingDir: "{app}\versions\{#Release}"; AppUserModelID: "io.github.drakahari.DLMSDesktop.WebView2Candidate"
#ifdef TestScope
; Real shortcut behavior, restricted to the disposable installation tree.
Name: "{#TestMenuRoot}\DLMS Desktop"; Filename: "{app}\versions\{#Release}\DLMS-Desktop-WebView2.exe"; Parameters: "{code:MenuProfileParameters}"; WorkingDir: "{app}\versions\{#Release}"; AppUserModelID: "io.github.drakahari.DLMSDesktop.WebView2Candidate"; Tasks: startmenu
Name: "{#TestMenuRoot}\Uninstall DLMS Desktop"; Filename: "{uninstallexe}"; Tasks: startmenu
Name: "{app}\synthetic-desktop\DLMS Desktop"; Filename: "{app}\versions\{#Release}\DLMS-Desktop-WebView2.exe"; Parameters: "{code:DesktopProfileParameters}"; WorkingDir: "{app}\versions\{#Release}"; AppUserModelID: "io.github.drakahari.DLMSDesktop.WebView2Candidate"; Tasks: desktopicon
#else
Name: "{group}\DLMS Desktop"; Filename: "{app}\versions\{#Release}\DLMS-Desktop-WebView2.exe"; Parameters: "{code:MenuProfileParameters}"; WorkingDir: "{app}\versions\{#Release}"; AppUserModelID: "io.github.drakahari.DLMSDesktop.WebView2Candidate"; Tasks: startmenu
Name: "{group}\Uninstall DLMS Desktop"; Filename: "{uninstallexe}"; Tasks: startmenu
Name: "{userdesktop}\DLMS Desktop WebView2 Candidate"; Filename: "{app}\versions\{#Release}\DLMS-Desktop-WebView2.exe"; Parameters: "{code:DesktopProfileParameters}"; WorkingDir: "{app}\versions\{#Release}"; AppUserModelID: "io.github.drakahari.DLMSDesktop.WebView2Candidate"; Tasks: desktopicon

[Run]
Filename: "{app}\versions\{#Release}\DLMS-Desktop-WebView2.exe"; Parameters: "{code:MenuProfileParameters}"; Description: "Open DLMS Desktop"; Flags: nowait postinstall skipifsilent; Check: LaunchConfigurationReady
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
  TDirectoryMapping = record
    ReadAccess, WriteAccess, ExecuteAccess, AllAccess: LongWord;
  end;
  TPrivilegeBuffer = record
    Data: array[0..1023] of Byte;
  end;
var
  Pins: array of THandle;
  PinnedPaths: TStringList;
  AppDirectories: TStringList;
  CurrentSid: String;
  SavedMenuParameters, SavedDesktopParameters: String;
  ShortcutProblem: String;
  ShortcutParentUnsafe: Boolean;
  ProfilePage: TInputOptionWizardPage;
  ProfileChoices: TStringList;
  SelectedProfile, ProfileProblem, PriorRecord, ResolutionEvidence: String;
  ProfileResolved, RecordExisted, ProfileRecordSaved: Boolean;

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
function DuplicateAccessToken(Token: THandle; Level: Integer; var Duplicate: THandle): Boolean;
  external 'DuplicateToken@advapi32.dll stdcall';
function NativeAccessCheck(Descriptor: NativeUInt; Token: THandle; Desired: LongWord;
  var Mapping: TDirectoryMapping; var Privileges: TPrivilegeBuffer;
  var PrivilegeSize, Granted, AccessStatus: LongWord): Boolean;
  external 'AccessCheck@advapi32.dll stdcall';
function CreatePrivateDirectory(Name: String; Security: NativeUInt): Boolean;
  external 'CreateDirectoryW@kernel32.dll stdcall';
function NativeValidSid(Sid: NativeUInt): Boolean;
  external 'IsValidSid@advapi32.dll stdcall';
function NativeReadFile(Handle: THandle; Buffer: AnsiString; Count: LongWord;
  var Read: LongWord; Overlapped: NativeUInt): Boolean;
  external 'ReadFile@kernel32.dll stdcall';
function NativeWriteFile(Handle: THandle; Buffer: AnsiString; Count: LongWord;
  var Written: LongWord; Overlapped: NativeUInt): Boolean;
  external 'WriteFile@kernel32.dll stdcall';
function NativeSeek(Handle: THandle; Distance: Longint; High: NativeUInt; Method: LongWord): LongWord;
  external 'SetFilePointer@kernel32.dll stdcall';
function NativeTruncate(Handle: THandle): Boolean;
  external 'SetEndOfFile@kernel32.dll stdcall';
function NativeFlush(Handle: THandle): Boolean;
  external 'FlushFileBuffers@kernel32.dll stdcall';
function NativeMoveFile(Source, Destination: String; Flags: LongWord): Boolean;
  external 'MoveFileExW@kernel32.dll stdcall';
function TokenElevation(Token: THandle; Kind: Integer; var Elevated: LongWord;
  Size: LongWord; var Needed: LongWord): Boolean;
  external 'GetTokenInformation@advapi32.dll stdcall';

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

function EffectiveCreateAccess(Descriptor: NativeUInt): Boolean;
var Token, Duplicate: THandle; Mapping: TDirectoryMapping;
    Privileges: TPrivilegeBuffer; Size, Granted, AccessStatus: LongWord;
begin
  Result := False;
  { Duplicate for AccessCheck only; never impersonate or elevate this process. }
  if not OpenToken(CurrentProcess, 10, Token) then Exit;
  try
    if not DuplicateAccessToken(Token, 2, Duplicate) then Exit;
    try
      Mapping.ReadAccess := $120089; Mapping.WriteAccess := $120116;
      Mapping.ExecuteAccess := $1200A0; Mapping.AllAccess := $1F01FF;
      Size := SizeOf(Privileges); Granted := 0; AccessStatus := 0;
      { FILE_ADD_SUBDIRECTORY must actually be granted to the current token. }
      if not NativeAccessCheck(Descriptor, Duplicate, 4, Mapping, Privileges,
          Size, Granted, AccessStatus) then Exit;
      Result := (AccessStatus <> 0) and ((Granted and 4) = 4);
    finally CloseNative(Duplicate); end;
  finally CloseNative(Token); end;
end;

function CapabilityPrincipal(Sid: NativeUInt): Boolean;
var Text: String;
begin
  { IsValidSid checks the SID structure/revision. ConvertSidToStringSid emits
    canonical decimal authority/RIDs: authority 15, first RID 3, >=2 RIDs.
    This is a Windows principal class, not a grant to a particular unknown SID.
    Capabilities constrain a token's user access; ordinary grants are still
    checked independently. Package SIDs (15-2) are NOT capabilities. }
  Result := False;
  if not NativeValidSid(Sid) then Exit;
  Text := SidString(Sid);
  Result := (Copy(Text, 1, 9) = 'S-1-15-3-') and (Length(Text) > 9);
end;

function DirectorySecurityAllowedCore(Owner, Dacl, Descriptor: NativeUInt;
  CreationParent, ShellObject: Boolean): Boolean;
var Ace: NativeUInt; Info: TAclSizeInfo; Prefix: TAcePrefix;
    I: Integer; Sid, OwnerSid: String;
begin
    Result := False;
    OwnerSid := SidString(Owner);
    if OwnerSid <> CurrentSid then begin
      if not CreationParent or (OwnerSid <> 'S-1-5-32-544') then Exit;
    end;
    if Dacl = 0 then Exit;
    if not AclInformation(Dacl, Info, SizeOf(Info), 2) then Exit;
    for I := 0 to Integer(Info.Count) - 1 do begin
      if not AceInformation(Dacl, I, Ace) then Exit;
      CopyAce(Prefix, Ace, SizeOf(Prefix));
      { Inherit-only grants also matter to a creation parent: they can grant
        untrusted writers access to the new child or its eventual files. }
      if (CreationParent or ((Prefix.Flags and 8) = 0)) and (Prefix.Kind <> 1) then begin
        if Prefix.Kind <> 0 then Exit;
        Sid := SidString(Ace + 8);
        if Sid = '' then Exit;
        if (Sid <> CurrentSid) and (Sid <> 'S-1-5-18') and
           (Sid <> 'S-1-5-32-544') and (Sid <> 'S-1-3-4') and
           ((Prefix.Mask and $500D0156) <> 0) and
           not (ShellObject and CapabilityPrincipal(Ace + 8)) then Exit;
      end;
    end;
    Result := (not CreationParent) or EffectiveCreateAccess(Descriptor);
end;

function DirectorySecurityAllowed(Owner, Dacl, Descriptor: NativeUInt;
  CreationParent: Boolean): Boolean;
begin
  Result := DirectorySecurityAllowedCore(Owner, Dacl, Descriptor, CreationParent, False);
end;

function DirectorySecurityCore(Handle: THandle; CreationParent, ShellObject: Boolean): Boolean;
var Owner, Group, Dacl, Sacl, Descriptor: NativeUInt;
begin
  Result := False;
  { AccessCheck requires both owner and group in the returned descriptor. }
  if SecurityInformation(Handle, 1, 7, Owner, Group, Dacl, Sacl, Descriptor) <> 0 then Exit;
  try
    Result := DirectorySecurityAllowedCore(Owner, Dacl, Descriptor, CreationParent, ShellObject);
  finally FreeNative(Descriptor); end;
end;

function DirectorySecurity(Handle: THandle; CreationParent: Boolean): Boolean;
begin Result := DirectorySecurityCore(Handle, CreationParent, False); end;

function OwnedDirectory(Handle: THandle): Boolean;
begin Result := DirectorySecurity(Handle, False); end;

function ReservedDosStem(Component: String): Boolean;
var Stem: String; Dot: Integer;
begin
  Dot := Pos('.', Component);
  if Dot = 0 then Stem := Component else Stem := Copy(Component, 1, Dot - 1);
  Stem := Uppercase(Trim(Stem));
  Result := (Stem = 'CON') or (Stem = 'PRN') or (Stem = 'AUX') or (Stem = 'NUL');
  if Result then Exit;
  if (Length(Stem) = 4) and ((Copy(Stem, 1, 3) = 'COM') or (Copy(Stem, 1, 3) = 'LPT')) then
    Result := ((Stem[4] >= '1') and (Stem[4] <= '9')) or
              (Stem[4] = #185) or (Stem[4] = #178) or (Stem[4] = #179);
end;

function NativeLocalPath(Path: String): String;
var Remaining, Part: String; Separator: Integer;
begin
  Result := '';
  { Keep display/bookkeeping paths canonical and local. Extended syntax must
    never turn UNC, devices, ADS, traversal or trailing-dot/space aliases into
    accepted paths. Only the checked absolute drive path reaches native APIs. }
  if (Length(Path) < 3) or (Copy(Path, 2, 2) <> ':\') or
     not (((Path[1] >= 'A') and (Path[1] <= 'Z')) or ((Path[1] >= 'a') and (Path[1] <= 'z'))) or
     (Pos(':', Copy(Path, 3, Length(Path))) <> 0) or (Pos('/', Path) <> 0) or
     (Pos(#0, Path) <> 0) or (CompareText(Path, ExpandFileName(Path)) <> 0) then Exit;
  Remaining := Copy(Path, 4, Length(Path));
  while Remaining <> '' do begin
    Separator := Pos('\', Remaining);
    if Separator = 0 then begin Part := Remaining; Remaining := ''; end
    else begin Part := Copy(Remaining, 1, Separator - 1); Delete(Remaining, 1, Separator); end;
    if (Part = '') or (Part = '.') or (Part = '..') then Exit;
    if (Part[Length(Part)] = '.') or (Part[Length(Part)] = ' ') then Exit;
    if ReservedDosStem(Part) then Exit;
  end;
  Result := '\\?\' + Path;
end;

function PinDirectory(Path: String; RequireOwner: Boolean): Boolean;
var Handle: THandle; Info: TNativeFileInfo; N: Integer; NativePath: String;
begin
  Result := False;
  Path := RemoveBackslashUnlessRoot(Path);
  NativePath := NativeLocalPath(Path);
  if NativePath = '' then Exit;
  N := PinnedPaths.IndexOf(Lowercase(Path));
  if N >= 0 then begin
    Result := (not RequireOwner) or OwnedDirectory(Pins[N]); Exit;
  end;
  { READ_CONTROL | FILE_READ_ATTRIBUTES | FILE_LIST_DIRECTORY; no DELETE sharing. }
  Handle := OpenDirectory(NativePath, $20081, 3, 0, 3, $2200000, 0);
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
  Parent, NativePath: String;
begin
  Result := False;
  Path := RemoveBackslashUnlessRoot(ExpandFileName(Path));
  NativePath := NativeLocalPath(Path);
  if NativePath = '' then Exit;
  Parent := RemoveBackslashUnlessRoot(ExtractFileDir(Path));
  { Pin root-to-leaf: never open a descendant through an unpinned ancestor. }
  if (Parent <> Path) and not SafeDirectoryChain(Parent) then Exit;
  Attributes := NativeAttributes(NativePath);
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
  if FindFirst(AddBackslash(NativeLocalPath(Path)) + '*', Found) then begin
    try
      repeat
        if (Found.Name <> '.') and (Found.Name <> '..') then begin
          Child := AddBackslash(Path) + Found.Name;
          if (Found.Attributes and $400) <> 0 then Exit;
          if ((Found.Attributes and $10) <> 0) and not SafeTree(Child) then Exit;
        end;
      until not FindNext(Found);
      { A partial enumeration must never qualify a tree as safe. }
      if NativeLastError <> 18 then Exit;
    finally FindClose(Found); end;
  end else if (NativeLastError <> 2) and (NativeLastError <> 18) then Exit;
  Result := True;
end;

function SafeCreationParent(Path: String): Boolean;
var N: Integer;
begin
  Result := False;
  if not SafeDirectoryChain(Path) or not PinDirectory(Path, False) then Exit;
  Path := RemoveBackslashUnlessRoot(ExpandFileName(Path));
  N := PinnedPaths.IndexOf(Lowercase(Path));
  if N < 0 then Exit;
  Result := DirectorySecurity(Pins[N], True);
end;

function SafeShortcutDirectory(Path: String; CreationParent, ShellObject: Boolean): Boolean;
var N: Integer;
begin
  Result := False;
  if not SafeDirectoryChain(Path) or not PinDirectory(Path, False) then Exit;
  N := PinnedPaths.IndexOf(Lowercase(RemoveBackslashUnlessRoot(ExpandFileName(Path))));
  if N < 0 then Exit;
  Result := DirectorySecurityCore(Pins[N], CreationParent, ShellObject);
end;

function EnsurePrivateDirectory(Path: String): Boolean;
var Parent, NativePath: String;
begin
  Result := False;
  Path := RemoveBackslashUnlessRoot(ExpandFileName(Path));
  NativePath := NativeLocalPath(Path);
  if NativePath = '' then Exit;
  if not SafeDirectoryChain(Path) then Exit;
  { Existing application components remain strictly current-user-owned. }
  if DirExists(Path) then begin Result := PinDirectory(Path, True); Exit; end;
  Parent := RemoveBackslashUnlessRoot(ExtractFileDir(Path));
  if Parent = Path then Exit;
  if not DirExists(Parent) and not EnsurePrivateDirectory(Parent) then Exit;
  if not SafeCreationParent(Parent) then Exit;
  { Do not adopt a directory planted between the absence check and creation.
    Pin and verify this child before creating any descendant or payload file.
    The parent is pinned and has no untrusted mutating/inheritable grants. }
  if not CreatePrivateDirectory(NativePath, 0) then Exit;
  Result := PinDirectory(Path, True);
end;

function GuardApplication(CreatePaths: Boolean): Boolean;
var Path: String;
begin
  Result := False;
  ReleasePins;
  if not InitializeGuard then Exit;
  AppDirectories.Clear;
  Path := ExpandConstant('{app}');
  if not SafeDirectoryChain(Path) then Exit;
  if DirExists(Path) and not SafeTree(Path) then Exit;
  if CreatePaths then begin
    if not EnsurePrivateDirectory(Path) or
       not EnsurePrivateDirectory(ExpandConstant('{app}\versions\{#Release}')) or
       not EnsurePrivateDirectory(ExpandConstant('{app}\uninstall')) then Exit;
  end;
  Result := SafeTree(Path);
end;

function SupportedWebView2Version(Version: String): Boolean;
var I, J, Dot, Value, Minimum, Compared: Integer;
    Part: String;
begin
  Result := False;
  Compared := 0;
  for I := 0 to 3 do begin
    Dot := Pos('.', Version);
    if I < 3 then begin
      if Dot = 0 then Exit;
      Part := Copy(Version, 1, Dot - 1);
      Delete(Version, 1, Dot);
    end else begin
      if Dot <> 0 then Exit;
      Part := Version;
    end;
    if (Part = '') or (Length(Part) > 5) then Exit;
    for J := 1 to Length(Part) do
      if (Part[J] < '0') or (Part[J] > '9') then Exit;
    Value := StrToIntDef(Part, -1);
    if (Value < 0) or (Value > 65535) then Exit;
    case I of
      0: Minimum := 155;
      1: Minimum := 0;
      2: Minimum := 4283;
      3: Minimum := 45;
    end;
    if Compared = 0 then begin
      if Value < Minimum then Compared := -1;
      if Value > Minimum then Compared := 1;
    end;
  end;
  Result := Compared >= 0;
end;

function HasWebView2Runtime: Boolean;
var Version, FileVersion, Key, Image: String;
begin
  Result := False;
  Key := 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  { This candidate trusts only the protected machine Runtime. The host performs
    the authoritative path, ownership, ACL and Microsoft signature validation
    of the actual selected browser process; registration alone is insufficient. }
  if not RegQueryStringValue(HKLM32, Key, 'pv', Version) or
     not SupportedWebView2Version(Version) then Exit;
  Image := ExpandConstant('{pf32}') + '\Microsoft\EdgeWebView\Application\' + Version + '\msedgewebview2.exe';
  Result := FileExists(Image) and GetVersionNumbersString(Image, FileVersion) and (FileVersion = Version);
end;

function MenuProfileParameters(Unused: String): String;
begin Result := SavedMenuParameters; end;

function DesktopProfileParameters(Unused: String): String;
begin Result := SavedDesktopParameters; end;

function ProfileArgumentsAllowed(Arguments: String): Boolean;
var Profile: String; I: Integer;
begin
  Result := Arguments = '';
  if Result then Exit;
  if Copy(Arguments, 1, 10) <> '--profile ' then Exit;
  Profile := Copy(Arguments, 11, Length(Arguments));
  if (Length(Profile) < 1) or (Length(Profile) > 32) then Exit;
  if (Profile[1] < 'a') or (Profile[1] > 'z') then Exit;
  for I := 2 to Length(Profile) do
    if not (((Profile[I] >= 'a') and (Profile[I] <= 'z')) or
            ((Profile[I] >= '0') and (Profile[I] <= '9')) or
            (Profile[I] = '_') or (Profile[I] = '-')) then Exit;
  Result := True;
end;

function VersionComponentAllowed(Version: String): Boolean;
var I: Integer;
begin
  Result := False;
  if Version = '' then Exit;
  for I := 1 to Length(Version) do
    if not (((Version[I] >= 'A') and (Version[I] <= 'Z')) or
            ((Version[I] >= 'a') and (Version[I] <= 'z')) or
            ((Version[I] >= '0') and (Version[I] <= '9')) or
            (Version[I] = '-')) then Exit;
  Result := True;
end;

function CaptureShortcutProfile(Path: String; var Parameters: String; ShellObject: Boolean): Boolean;
var Attributes, ErrorCode: LongWord; Handle, TargetHandle: THandle;
    Info: TNativeFileInfo; Shell, Link: Variant;
    Target, Directory, Versions, Version, Parent: String;
begin
  Result := False; Parameters := '';
  ShortcutParentUnsafe := True;
  ShortcutProblem := 'The shortcut directory is inaccessible, has unsafe ownership/permissions, or contains a reparse point: ' + ExtractFileDir(Path);
  Parent := ExtractFileDir(Path);
  if not SafeDirectoryChain(Parent) then Exit;
  { Even an absent shortcut must not authorize writing through an unsafe parent.
    Pin the existing ancestor before Inno creates any missing menu directory. }
  while not DirExists(Parent) do begin
    if ExtractFileDir(Parent) = Parent then Exit;
    Parent := ExtractFileDir(Parent);
  end;
  ShortcutProblem := 'The shortcut creation parent has unsafe ownership/permissions or is inaccessible: ' + Parent;
  if not SafeShortcutDirectory(Parent, True, ShellObject) then Exit;
  if DirExists(ExtractFileDir(Path)) and
     not SafeShortcutDirectory(ExtractFileDir(Path), False, ShellObject) then Exit;
  ShortcutParentUnsafe := False;
  ShortcutProblem := 'The existing shortcut must be a trusted regular file pointing to an existing version in this installation, with a matching working directory and only an optional --profile argument: ' + Path;
  Attributes := NativeAttributes(NativeLocalPath(Path));
  if Attributes = $FFFFFFFF then begin
    ErrorCode := NativeLastError;
    Result := (ErrorCode = 2) or (ErrorCode = 3); Exit;
  end;
  { Pin a regular trusted shortcut against writes/replacement while COM reads it.
    The leaf is released before Inno replaces it; no target is executed/resolved. }
  Handle := OpenDirectory(NativeLocalPath(Path), $20081, 1, 0, 3, $200000, 0);
  if Handle = THandle(-1) then Exit;
  try
    if not FileInformation(Handle, Info) or ((Info.Attributes and $410) <> 0) or
       (Info.Links <> 1) or not DirectorySecurityCore(Handle, False, ShellObject) then Exit;
    try
      Shell := CreateOleObject('WScript.Shell');
      Link := Shell.CreateShortcut(Path);
      Target := Link.TargetPath;
      Directory := Link.WorkingDirectory;
      Parameters := Link.Arguments;
      Link := Unassigned; Shell := Unassigned;
    except Exit; end;
    if (NativeLocalPath(Target) = '') or (NativeLocalPath(Directory) = '') or
       (CompareText(ExtractFileName(Target), 'DLMS-Desktop-WebView2.exe') <> 0) or
       (CompareText(ExtractFileDir(Target), Directory) <> 0) then Exit;
    Versions := ExpandConstant('{app}\versions');
    if CompareText(ExtractFileDir(Directory), Versions) <> 0 then Exit;
    Version := ExtractFileName(Directory);
    if not VersionComponentAllowed(Version) or not ProfileArgumentsAllowed(Parameters) or
       not PinDirectory(Directory, True) then Exit;
    TargetHandle := OpenDirectory(NativeLocalPath(Target), $20081, 1, 0, 3, $200000, 0);
    if TargetHandle = THandle(-1) then Exit;
    try
      Result := FileInformation(TargetHandle, Info) and ((Info.Attributes and $410) = 0)
        and (Info.Links = 1) and OwnedDirectory(TargetHandle);
    finally CloseNative(TargetHandle); end;
  finally CloseNative(Handle); end;
end;

function StartMenuLaunchPath: String;
begin
#ifdef TestScope
  Result := ExpandConstant('{#TestMenuRoot}\DLMS Desktop.lnk');
#else
  Result := ExpandConstant('{group}\DLMS Desktop.lnk');
#endif
end;

function AppLaunchPath: String;
begin Result := ExpandConstant('{app}\Launch DLMS Desktop.lnk'); end;

function ProfileNameAllowed(Profile: String): Boolean;
begin Result := (Profile <> '') and ProfileArgumentsAllowed('--profile ' + Profile); end;

function DataRoot: String;
begin
#ifdef TestScope
  Result := ExpandConstant('{#TestDataRoot}');
#else
  Result := ExpandConstant('{localappdata}\DLMSDesktop\WebView2Candidate');
#endif
end;

function ProfileRecordPath: String;
begin Result := ExpandConstant('{app}\launch-profile.txt'); end;

function ReadRecordHandle(Handle: THandle; var Text: String): Boolean;
var Info: TNativeFileInfo; Buffer: AnsiString; Read: LongWord;
begin
  Result := False; Text := '';
  if not FileInformation(Handle, Info) or ((Info.Attributes and $410) <> 0) or
     (Info.Links <> 1) or (Info.SizeHigh <> 0) or (Info.SizeLow > 128) or
     not OwnedDirectory(Handle) then Exit;
  SetLength(Buffer, Info.SizeLow);
  if NativeSeek(Handle, 0, 0, 0) = $FFFFFFFF then Exit;
  if not NativeReadFile(Handle, Buffer, Info.SizeLow, Read, 0) or (Read <> Info.SizeLow) then Exit;
  Text := Buffer; Result := True;
end;

function ReadProfileRecord: Boolean;
var Handle: THandle; Attributes, ErrorCode: LongWord; Name: String;
begin
  Result := False; PriorRecord := ''; RecordExisted := False;
  Attributes := NativeAttributes(NativeLocalPath(ProfileRecordPath));
  if Attributes = $FFFFFFFF then begin
    ErrorCode := NativeLastError;
    Result := (ErrorCode = 2) or (ErrorCode = 3); Exit;
  end;
  RecordExisted := True;
  if not SafeDirectoryChain(ExtractFileDir(ProfileRecordPath)) or
     not PinDirectory(ExtractFileDir(ProfileRecordPath), True) then Exit;
  Handle := OpenDirectory(NativeLocalPath(ProfileRecordPath), $80020000, 1, 0, 3, $200000, 0);
  if Handle = THandle(-1) then Exit;
  try
    if not ReadRecordHandle(Handle, PriorRecord) then Exit;
    if Copy(PriorRecord, 1, 23) <> 'DLMS-LAUNCH-PROFILE-1'#13#10 then Exit;
    Name := Copy(PriorRecord, 24, Length(PriorRecord));
    if not ProfileNameAllowed(Name) then Exit;
    if ProfileChoices.IndexOf(Name) < 0 then ProfileChoices.Add(Name);
    Result := True;
  finally CloseNative(Handle); end;
end;

procedure AddProfile(Name: String);
begin
  if ProfileChoices.IndexOf(Name) < 0 then ProfileChoices.Add(Name);
end;

function DiscoverProfiles(Area: String): Boolean;
var Found: TFindRec; Path: String; ErrorCode: LongWord;
begin
  Result := False;
  if not SafeDirectoryChain(Area) then Exit;
  if not DirExists(Area) then begin
    if NativeAttributes(NativeLocalPath(Area)) <> $FFFFFFFF then Exit;
    ErrorCode := NativeLastError;
    Result := (ErrorCode = 2) or (ErrorCode = 3); Exit;
  end;
  if not PinDirectory(Area, True) then Exit;
  if FindFirst(AddBackslash(NativeLocalPath(Area)) + '*', Found) then begin
    try
      repeat
        if (Found.Name <> '.') and (Found.Name <> '..') then begin
          Path := AddBackslash(Area) + Found.Name;
          if ((Found.Attributes and $400) <> 0) or ((Found.Attributes and $10) = 0) or
             not ProfileNameAllowed(Found.Name) or not PinDirectory(Path, True) then Exit;
          AddProfile(Found.Name);
        end;
      until not FindNext(Found);
      if NativeLastError <> 18 then Exit;
    finally FindClose(Found); end;
  end else if (NativeLastError <> 2) and (NativeLastError <> 18) then Exit;
  Result := True;
end;

function CaptureProfileChoice(Path: String; ShellObject: Boolean): Boolean;
var Parameters: String;
begin
  Result := CaptureShortcutProfile(Path, Parameters, ShellObject);
  ResolutionEvidence := ResolutionEvidence + Path + '=';
  if FileExists(Path) then ResolutionEvidence := ResolutionEvidence + 'present';
  ResolutionEvidence := ResolutionEvidence + ':' + Parameters + #10;
  if Result and FileExists(Path) then begin
    if Parameters = '' then AddProfile('default')
    else AddProfile(Copy(Parameters, 11, Length(Parameters)));
  end;
end;

procedure ResolveProfile;
var I: Integer; Requested: String; Token: THandle; Elevated, Needed: LongWord;
    Authority, Existing: TStringList;
begin
  ProfileResolved := True; SelectedProfile := ''; ProfileProblem := '';
  ResolutionEvidence := '';
  ProfileChoices.Clear;
  if not InitializeGuard then begin ProfileProblem := 'Cannot identify the current Windows account.'; Exit; end;
  { A manually elevated setup must not discover or initialize administrator data. }
  if not OpenToken(CurrentProcess, 8, Token) then begin ProfileProblem := 'Cannot verify setup account.'; Exit; end;
  try
    if not TokenElevation(Token, 20, Elevated, SizeOf(Elevated), Needed) or (Elevated <> 0) then begin
      ProfileProblem := 'Close Setup and run the downloaded installer normally, without Run as administrator. DLMS is installed for the current signed-in user.'; Exit;
    end;
  finally CloseNative(Token); end;
  try
    if not CaptureProfileChoice(AppLaunchPath, False) then begin ProfileProblem := ShortcutProblem; Exit; end;
    if WizardIsTaskSelected('startmenu') and not CaptureProfileChoice(StartMenuLaunchPath, True) then begin
      ProfileProblem := ShortcutProblem; Exit;
    end;
    if not ReadProfileRecord then begin ProfileProblem := 'The saved DLMS launch selection is invalid or inaccessible. It was not replaced. ' + ProfileRecordPath; Exit; end;
    ResolutionEvidence := ResolutionEvidence + 'record=' + PriorRecord + #10;
    if not SafeDirectoryChain(DataRoot) or (DirExists(DataRoot) and not PinDirectory(DataRoot, True)) then begin
      ProfileProblem := 'Existing DLMS data has unsafe or inaccessible storage. Setup will not select an empty replacement.'; Exit;
    end;
    if not SafeDirectoryChain(DataRoot + '\removed') or
       (DirExists(DataRoot + '\removed') and not PinDirectory(DataRoot + '\removed', True)) then begin
      ProfileProblem := 'The DLMS removal history is unsafe or inaccessible. Setup will not create replacement data.'; Exit;
    end;
    Authority := TStringList.Create;
    Existing := TStringList.Create;
    try
      Authority.Assign(ProfileChoices);
      ProfileChoices.Clear;
      if not DiscoverProfiles(DataRoot + '\profiles') or not DiscoverProfiles(DataRoot + '\shell') then begin
        ProfileProblem := 'Existing DLMS profiles could not be safely listed. Setup will not select an empty replacement.'; Exit;
      end;
      Existing.Assign(ProfileChoices);
      Existing.Sort;
      ResolutionEvidence := ResolutionEvidence + 'existing=' + Existing.Text;
      if Authority.Count > 0 then begin
        for I := 0 to Authority.Count - 1 do
          if (Existing.Count > 0) and (Existing.IndexOf(Authority[I]) < 0) then begin
            ProfileProblem := 'The saved launch profile "' + Authority[I] +
              '" is missing, but other DLMS profiles exist. Setup stopped rather than create an empty replacement. Resolve this specific recovery case before installing.';
            Exit;
          end;
        ProfileChoices.Assign(Authority);
      end else if ProfileChoices.Count = 0 then AddProfile('default');
    finally Authority.Free; Existing.Free; end;
    for I := 0 to ProfileChoices.Count - 1 do begin
      if NativeAttributes(NativeLocalPath(DataRoot + '\removed\' + ProfileChoices[I] + '.json')) <> $FFFFFFFF then begin
        ProfileProblem := 'A saved DLMS launch selection has an intentional-removal record. Setup will not recreate it.'; Exit;
      end;
      if (NativeLastError <> 2) and (NativeLastError <> 3) then begin
        ProfileProblem := 'The DLMS removal history is inaccessible. Setup will not create replacement data.'; Exit;
      end;
    end;
    Requested := ExpandConstant('{param:DLMSPROFILE|}');
    if Requested <> '' then begin
      if not ProfileNameAllowed(Requested) or (ProfileChoices.IndexOf(Requested) < 0) then begin
        ProfileProblem := 'The requested profile does not match a discovered launch selection. Existing data was not changed.'; Exit;
      end;
      SelectedProfile := Requested;
    end else if ProfileChoices.Count = 1 then SelectedProfile := ProfileChoices[0];
    ProfilePage.CheckListBox.Items.Clear;
    for I := 0 to ProfileChoices.Count - 1 do ProfilePage.Add(ProfileChoices[I]);
  finally ReleasePins; end;
end;

procedure InitializeWizard;
begin
  ProfileChoices := TStringList.Create;
  ProfilePage := CreateInputOptionPage(wpSelectTasks, 'Choose existing DLMS data',
    'More than one existing launch selection was found.',
    'Choose the existing profile to reopen. Setup will preserve all profiles and will not create an empty replacement.', True, False);
  ProfileResolved := False;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if PageID <> ProfilePage.ID then Exit;
  ResolveProfile;
  Result := (ProfileProblem <> '') or (SelectedProfile <> '') or WizardSilent;
end;

function ProfileSelectionError: String;
begin
  if not ProfileResolved then ResolveProfile;
  Result := ProfileProblem;
  if Result <> '' then Exit;
  if SelectedProfile = '' then begin
    if not WizardSilent and (ProfilePage.SelectedValueIndex >= 0) then
      SelectedProfile := ProfileChoices[ProfilePage.SelectedValueIndex]
    else begin Result := 'Several existing DLMS profiles were found. Select which existing profile to reopen; no data was changed.'; Exit; end;
  end;
  if FileExists(DataRoot + '\removed\' + SelectedProfile + '.json') then begin
    Result := 'The selected DLMS profile has an intentional-removal record. Setup will not recreate it.'; Exit;
  end;
  SavedMenuParameters := '--profile ' + SelectedProfile;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var Problem: String;
begin
  Result := True;
  if WizardSilent then Exit;
  if CurPageID = wpSelectTasks then ProfileResolved := False;
  if CurPageID <> ProfilePage.ID then Exit;
  Problem := ProfileSelectionError;
  Result := Problem = '';
  if not Result then MsgBox(Problem, mbError, MB_OK);
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo,
  MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
begin
  Result := MemoDirInfo + NewLine + NewLine + MemoTasksInfo + NewLine + NewLine;
  if ProfileProblem <> '' then Result := Result + ProfileProblem
  else Result := Result +
    'Your existing DLMS data and settings will be kept. On a new installation, DLMS sets up its data automatically when first opened.';
end;

procedure SaveProfileRecord;
var Handle, Previous: THandle; Text, Temporary: String; Buffer: AnsiString;
    Written, Flags: LongWord; RecordPublished: Boolean;
begin
  Buffer := 'DLMS-LAUNCH-PROFILE-1'#13#10 + SelectedProfile;
  Previous := THandle(-1);
  if RecordExisted then begin
    { Hold the original read-only identity through publication; DELETE sharing
      permits atomic replacement of this leaf, never writes into a linked target. }
    Previous := OpenDirectory(NativeLocalPath(ProfileRecordPath), $80020000, 5, 0, 3, $200000, 0);
    if Previous = THandle(-1) then RaiseException('The DLMS launch selection could not be revalidated.');
    if not ReadRecordHandle(Previous, Text) or (Text <> PriorRecord) then begin
      CloseNative(Previous);
      RaiseException('The saved DLMS launch selection changed during setup. It was not overwritten.');
    end;
    if Text = Buffer then begin CloseNative(Previous); Exit; end;
  end;
  Temporary := ProfileRecordPath + '.' + GetDateTimeString('yyyymmddhhnnsszzz', '-', '-') + '.tmp';
  Handle := OpenDirectory(NativeLocalPath(Temporary), $C0020000, 0, 0, 1, $200000, 0);
  if Handle = THandle(-1) then begin
    if Previous <> THandle(-1) then CloseNative(Previous);
    RaiseException('Could not stage the DLMS launch selection. Existing selection was preserved.');
  end;
  RecordPublished := False;
  try
    if not ReadRecordHandle(Handle, Text) or (Text <> '') then
      RaiseException('The staged launch selection is unsafe. Existing selection was preserved.');
    if (NativeSeek(Handle, 0, 0, 0) = $FFFFFFFF) or
       not NativeWriteFile(Handle, Buffer, Length(Buffer), Written, 0) or (Written <> Length(Buffer)) or
       not NativeTruncate(Handle) or not NativeFlush(Handle) then
      RaiseException('Could not stage the DLMS launch selection. Existing selection was preserved.');
    CloseNative(Handle); Handle := THandle(-1);
    Flags := 8; { MOVEFILE_WRITE_THROUGH; no replace when originally absent. }
    if RecordExisted then Flags := Flags or 1;
    if not NativeMoveFile(NativeLocalPath(Temporary), NativeLocalPath(ProfileRecordPath), Flags) then
      RaiseException('Could not publish the DLMS launch selection. Existing selection was preserved.');
    RecordPublished := True;
  finally
    if Handle <> THandle(-1) then CloseNative(Handle);
    if Previous <> THandle(-1) then CloseNative(Previous);
    { Retain a failed staging file as evidence; never delete an ambiguous path. }
    if not RecordPublished then Log('Unpublished launch selection retained: ' + Temporary);
  end;
end;

procedure CurStepChanged(Step: TSetupStep);
begin
  { Unmanaged configuration intentionally survives uninstall/reinstall. }
  if Step = ssPostInstall then begin
    SaveProfileRecord;
    ProfileRecordSaved := True;
  end;
end;

function LaunchConfigurationReady: Boolean;
begin Result := ProfileRecordSaved; end;

function GetCustomSetupExitCode: Integer;
begin
  Result := 0;
  if not ProfileRecordSaved then Result := 1;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpFinished) and not ProfileRecordSaved then
    WizardForm.FinishedLabel.Caption := 'DLMS launch configuration could not be saved. Installation is incomplete. Review the error above before launching or retrying. Existing application data was not changed.';
end;

function CaptureLaunchProfiles: Boolean;
var MenuPath, DesktopPath, PreviousParameters: String;
begin
  Result := False;
  if not CaptureShortcutProfile(AppLaunchPath, PreviousParameters, False) then Exit;
  MenuPath := StartMenuLaunchPath;
#ifdef TestScope
  DesktopPath := ExpandConstant('{app}\synthetic-desktop\DLMS Desktop.lnk');
#else
  DesktopPath := ExpandConstant('{userdesktop}\DLMS Desktop WebView2 Candidate.lnk');
#endif
  if WizardIsTaskSelected('startmenu') and
     not CaptureShortcutProfile(MenuPath, PreviousParameters, True) then begin
    if ShortcutParentUnsafe then
      ShortcutProblem := 'Start menu integration cannot safely use this destination. ' + ShortcutProblem +
        ' No Windows permissions were changed.'
    else ShortcutProblem := 'Existing DLMS Start menu launch shortcut is invalid or unsafe. ' + ShortcutProblem;
    Exit;
  end;
  SavedDesktopParameters := SavedMenuParameters;
  if WizardIsTaskSelected('desktopicon') then begin
    if not CaptureShortcutProfile(DesktopPath, PreviousParameters, True) then Exit;
    if FileExists(DesktopPath) then SavedDesktopParameters := PreviousParameters;
  end;
  Result := True;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var Expected, Choice: String;
begin
  Result := '';
  Result := ProfileSelectionError;
  if Result <> '' then Exit;
  Expected := ResolutionEvidence; Choice := SelectedProfile;
  ResolveProfile;
  if (ProfileProblem <> '') or (ResolutionEvidence <> Expected) or
     (ProfileChoices.IndexOf(Choice) < 0) then begin
    Result := 'DLMS launch configuration changed while Setup was open. Go Back and review it again. ' + ProfileProblem;
    Exit;
  end;
  SelectedProfile := Choice;
  SavedMenuParameters := '--profile ' + Choice;
  if not HasWebView2Runtime then begin
    Result := 'Protected machine-wide Microsoft Edge WebView2 Evergreen Runtime 155.0.4283.45 or newer is required under Program Files (x86). Per-user/AppData Runtime installations are unsupported by this candidate. Ask the owner before installing or updating prerequisites. This installer does not download or install them.';
    Exit;
  end;
  if not GuardApplication(True) then begin
    ReleasePins;
    Result := 'The installation directory is unsafe or inaccessible. Choose a local directory owned by your account without public write access, junctions or links.';
    Exit;
  end;
  if not CaptureLaunchProfiles then begin
    ReleasePins;
    Result := ShortcutProblem + ' No profile data was changed.';
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
    for I := AppDirectories.Count - 1 downto 0 do RemoveDir(NativeLocalPath(AppDirectories[I]));
  end;
end;

procedure DeinitializeUninstall;
begin ReleasePins; end;
