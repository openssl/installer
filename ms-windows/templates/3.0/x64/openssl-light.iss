; Copyright 2016-2019 The OpenSSL Project Authors. All Rights Reserved.
;
; Licensed under the OpenSSL license (the "License").  You may not use
; this file except in compliance with the License.  You can obtain a copy
; in the file LICENSE in the source distribution or at
; https://www.openssl.org/source/license.html

[Setup]
AppName=OpenSSL Light (64-bit)
AppVersion=[[DOTTED_VERSION]]
AppVerName=OpenSSL [[DOTTED_VERSION]] Light (64-bit)
AppPublisher=OpenSSL Foundation
AppPublisherURL=https://www.openssl.org
AppSupportURL=https://github.com/openssl/installer
AppUpdatesURL=https://www.openssl.org
VersionInfoVersion=[[WINDOWS_DOTTED_VERSION]]
DefaultDirName={pf}\OpenSSL
DisableDirPage=no
DefaultGroupName=OpenSSL
SourceDir=[[INSTALLER_SOURCE_DIR]]
OutputBaseFilename=OpenSSL-[[DOTTED_VERSION]]-x64-light
LicenseFile=license.txt
; SetupIconFile=compiler:SetupClassicIcon.ico
PrivilegesRequired=admin
Compression=bzip
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
; Minimum version supported is Windows XP.
MinVersion=5.1
CreateUninstallRegKey=not IsMSI

[Code]
// Determine whether or not the installer is being called from the WiX wrapper.
function IsMSI(): Boolean;
var
  x: Integer;
begin
  Result := False;

  for x := 1 to ParamCount do
  begin
    if CompareText(Copy(ParamStr(x), 1, 5), '/MSI=') = 0 then
    begin
      Result := True;
    end;
  end;
end;

// Sets a static registry key as per the input.  Lets the MSI wrapper do its thing later.
procedure PrepareMSIUninstall();
var
  x: Integer;
  subkey: String;
begin
  for x := 1 to ParamCount do
  begin
    if CompareText(Copy(ParamStr(x), 1, 5), '/MSI=') = 0 then
    begin
      subkey := 'SOFTWARE\Inno Setup MSIs\' + Copy(ParamStr(x), 6, Length(ParamStr(x)) - 5);
      RegDeleteKeyIncludingSubkeys(HKLM, subkey);
      RegWriteStringValue(HKLM, subkey, '', ExpandConstant('{uninstallexe}'));
    end;
  end;
end;

function InitializeSetup() : Boolean;
var
  MsgResult : Integer;
  ErrCode: integer;
begin
  // Deal with the VC++ 2019 Redistributable issue.
  if ((NOT FileExists(ExpandConstant('{sys}') + '\vcruntime140.dll'))) then begin
    MsgResult := SuppressibleMsgBox('The OpenSSL installation setup has detected that the following critical component is missing:'#10'Microsoft Visual C++ 2019 Redistributables (64-bit)'#10#10'OpenSSL will not function properly without this component.'#10'Download the required redistributables now?', mbError, MB_YESNOCANCEL, IDNO);
    if (MsgResult = IDCANCEL) then exit;

    if (MsgResult = IDYES) then begin
      ShellExecAsOriginalUser('open', 'https://aka.ms/vs/16/release/vc_redist.x64.exe', '', '', SW_SHOW, ewNoWait, ErrCode);
    end;
  end;

  Result := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  IsCopied : Boolean;
  MsgResult : Integer;
begin
  if (CurStep = ssPostInstall) then begin
    // Copy files to the system directory if the task was selected.
    if (IsTaskSelected('copytosystem')) then begin
      MsgResult := IDCANCEL;
      repeat
        IsCopied := FileCopy(ExpandConstant('{app}') + '\libcrypto-3-x64.dll', ExpandConstant('{sys}') + '\libcrypto-3-x64.dll', False);
        if (NOT IsCopied) then  MsgResult := SuppressibleMsgBox('Unable to copy libcrypto-3-x64.dll to ' + ExpandConstant('{sys}') + '.'#10'Please close any applications that may be using this OpenSSL component and click Retry to try again.'#10'Clicking Cancel will register the file to be moved during the next reboot.'#10#10'If you click Cancel, OpenSSL may not function properly until the computer is rebooted.', mbError, MB_RETRYCANCEL, IDCANCEL);
      until ((IsCopied) OR (MsgResult = IDCANCEL));
      if (NOT IsCopied) then begin
        FileCopy(ExpandConstant('{app}') + '\libcrypto-3-x64.dll', ExpandConstant('{app}') + '\tmpeay32.dll', False);
        RestartReplace(ExpandConstant('{app}') + '\tmpeay32.dll', ExpandConstant('{sys}') + '\libcrypto-3-x64.dll');
      end;

      MsgResult := IDCANCEL;
      repeat
        IsCopied := FileCopy(ExpandConstant('{app}') + '\libssl-3-x64.dll', ExpandConstant('{sys}') + '\libssl-3-x64.dll', False);
        if (NOT IsCopied) then  MsgResult := SuppressibleMsgBox('Unable to copy libssl-3-x64.dll to ' + ExpandConstant('{sys}') + '.'#10'Please close any applications that may be using this OpenSSL component and click Retry to try again.'#10'Clicking Cancel will register the file to be moved during the next reboot.'#10#10'If you click Cancel, OpenSSL may not function properly until the computer is rebooted.', mbError, MB_RETRYCANCEL, IDCANCEL);
      until ((IsCopied) OR (MsgResult = IDCANCEL));
      if (NOT IsCopied) then begin
        FileCopy(ExpandConstant('{app}') + '\libssl-3-x64.dll', ExpandConstant('{app}') + '\tmpssl32.dll', False);
        RestartReplace(ExpandConstant('{app}') + '\tmpssl32.dll', ExpandConstant('{sys}') + '\libssl-3-x64.dll');
      end;
    end
    else begin
      FileCopy(ExpandConstant('{app}') + '\libcrypto-3-x64.dll', ExpandConstant('{app}') + '\bin\libcrypto-3-x64.dll', False);
      FileCopy(ExpandConstant('{app}') + '\libssl-3-x64.dll', ExpandConstant('{app}') + '\bin\libssl-3-x64.dll', False);
    end;
  end;
end;

[Tasks]
Name: copytosystem; Description: "The Windows &system directory"; GroupDescription: "Copy OpenSSL DLLs to:"; Flags: exclusive
Name: copytobin; Description: "The OpenSSL &binaries (/bin) directory"; GroupDescription: "Copy OpenSSL DLLs to:"; Flags: exclusive unchecked

[Files]
Source: "conf\*"; DestDir: "{cf}\SSL"; Flags: recursesubdirs
Source: "bin\PEM\*"; DestDir: "{app}\bin\PEM"; Flags: recursesubdirs
Source: "bin\*.pl"; DestDir: "{app}\bin"
Source: "bin\openssl.exe"; DestDir: "{app}\bin"
Source: "bin\*.dll"; DestDir: "{app}\bin"
Source: "text\*"; DestDir: "{app}"; Flags: recursesubdirs
Source: "tools\*"; DestDir: "{app}"; Flags: recursesubdirs
Source: "libcrypto-3-x64.dll"; DestDir: "{app}"
Source: "libssl-3-x64.dll"; DestDir: "{app}"
Source: "start.bat"; DestDir: "{app}"

[Icons]
Name: "{group}\OpenSSL Command Prompt (x64)"; Filename: "{app}\start.bat"; WorkingDir: "{app}"
Name: "{group}\OpenSSL Website"; Filename: "https://www.openssl.org/"; WorkingDir: "{app}"
Name: "{group}\OpenSSL Documentation"; Filename: "https://www.openssl.org/docs/"; WorkingDir: "{app}"
Name: "{group}\Uninstall OpenSSL"; Filename: "{uninstallexe}"; Check: not IsMSI

[Registry]
Root: HKLM; Subkey: "SOFTWARE\Inno Setup MSIs"; Check: IsMSI; AfterInstall: PrepareMSIUninstall

[Run]
Filename: "https://github.com/sponsors/openssl"; Description: "Become a sponsor of the OpenSSL project"; WorkingDir: "{app}"; Flags: shellexec postinstall nowait skipifsilent unchecked

[UninstallDelete]
Type: files; Name: "{app}\bin\libcrypto-3-x64.dll"
Type: files; Name: "{app}\bin\libssl-3-x64.dll"
