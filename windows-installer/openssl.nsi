
######################################################
# NSIS windows installer script file
#
# Requirements: NSIS 3.0 must be installed with the MUI plugin
# Usage notes:
# This script expects to be executed from the directory it is
# currently stored in.  It expects a 32 bit and 64 bit windows openssl
# build to be present in the ..\${BUILD32} and ..\${BUILD64} directories
# respectively
# ####################################################

!include "MUI.nsh"
!include "winmessages.nsh"

!define PRODUCT_NAME "OpenSSL"
!define VERSION "${MAJOR}.${MINOR}.${PATCH}"

# The name of the output file we create when building this
# NOTE major/minor/patch values are passed with the /D option
# on the command line
OutFile "openssl-${VERSION}-installer.exe"

# The name that will appear in the installer title bar
NAME "${PRODUCT_NAME} ${VERSION}"

ShowInstDetails show


Var DataDir
Var ModDir

Function .onInit
    StrCpy $INSTDIR "C:\Program Files\openssl-${MAJOR}.${MINOR}"
FunctionEnd

!ifdef BUILD64
# This section is run if installation of the 64 bit binaries are selectd
SectionGroup "64 Bit Installation"
    Section "64 Bit Binaries"
        SetOutPath $INSTDIR\x86_64\lib
        File /r "${BUILD64}\Program Files\OpenSSL\lib\"
        SetOutPath $INSTDIR\x86_64\bin
        File /r "${BUILD64}\Program Files\OpenSSL\bin\"
        SetOutPath "$INSTDIR\x86_64\Common Files"
        File /r "${BUILD64}\Program Files\Common Files\"
    SectionEnd
    Section "x86_64 Development Headers"
        SetOutPath $INSTDIR\x86_64\include
        File /r "${BUILD64}\Program Files\OpenSSL\include\"
    SectionEnd
SectionGroupEnd
!endif

!ifdef BUILD32
# This section is run if installation of the 32 bit binaries are selectd
SectionGroup "32 Bit Installation"
    Section "32 Bit Binaries"
        SetOutPath $INSTDIR\x86\lib
        File /r "${BUILD32}\Program Files (x86)\OpenSSL\lib\"
        SetOutPath $INSTDIR\x86\bin
        File /r "${BUILD32}\Program Files (x86)\OpenSSL\bin\"
        SetOutPath "$INSTDIR\x86\Common Files"
        File /r "${BUILD32}\Program Files (x86)\Common Files\"
    SectionEnd
    Section "x86 Development Headers"
        SetOutPath $INSTDIR\x86\include
        File /r "${BUILD32}\Program Files (x86)\OpenSSL\include\"
    SectionEnd
SectionGroupEnd
!endif

!ifdef BUILD64
Section "Documentation"
    SetOutPath $INSTDIR\html
    File /r "${BUILD64}\Program Files\OpenSSL\html\"
SectionEnd
!endif

# Always install the uninstaller and set a registry key
Section
    WriteUninstaller $INSTDIR\uninstall.exe
SectionEnd

!define env_hklm 'HKLM "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"'
!define openssl_hklm 'HKLM "SOFTWARE\OpenSSL-${MAJOR}.${MINOR}-${CTX}"'

# This is run on uninstall
Section "Uninstall"
    RMDIR /r $INSTDIR
    DeleteRegValue ${openssl_hklm} OPENSSLDIR
    DeleteRegValue ${openssl_hklm} MODULESDIR
    DeleteRegValue ${openssl_hklm} ENGINESDIR
    SendMessage ${HWND_BROADCAST} ${WM_WININICHANGE} 0 "STR:Environment" /TIMEOUT=5000
SectionEnd

!insertmacro MUI_PAGE_WELCOME

!insertmacro MUI_PAGE_LICENSE ${LICENSE_FILE}

Function CheckRunUninstaller
    ifFileExists $INSTDIR\uninstall.exe 0 +2
        ExecWait "$INSTDIR\uninstall.exe /S _?=$INSTDIR"
FunctionEnd

Function WriteRegistryKeys
!ifdef BUILD64
    StrCpy $DataDir "$INSTDIR\x86_64\Common Files\SSL"
    StrCpy $ModDir  "$INSTDIR\x86_64\lib\ossl-modules"
!else
    StrCpy $DataDir "$INSTDIR\x86\Common Files\SSL"
    StrCpy $ModDir  "$INSTDIR\x86\lib\ossl-modules"
!endif
    WriteRegExpandStr ${openssl_hklm} OPENSSLDIR "$DataDir"
    WriteRegExpandStr ${openssl_hklm} ENGINESDIR "$ModDir"
    WriteRegExpandStr ${openssl_hklm} MODULESDIR "$ModDir"
    SendMessage ${HWND_BROADCAST} ${WM_WININICHANGE} 0 "STR:Environment" /TIMEOUT=5000
FunctionEnd

Function DoDirectoryWork
    Call CheckRunUninstaller
    call WriteRegistryKeys
FunctionEnd

!insertmacro MUI_PAGE_COMPONENTS

!define MUI_PAGE_CUSTOMFUNCTION_LEAVE DoDirectoryWork
!define MUI_DIRECTORYPAGE_TEXT_DESTINATION "Installation Directory"
!insertmacro MUI_PAGE_DIRECTORY

!define MUI_DIRECTORYPAGE_VARIABLE $DataDir
!define MUI_DIRECTORYPAGE_TEXT_TOP "Select Configuration/Data Directory"
!define MUI_DIRECTORYPAGE_TEXT_DESTINATION "Configuration/Data Directory"
!insertmacro MUI_PAGE_DIRECTORY

!insertmacro MUI_PAGE_INSTFILES

!insertmacro MUI_UNPAGE_WELCOME
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH

!insertmacro MUI_LANGUAGE "English"

!ifdef SIGN
!define OutFileSignSHA1 "SignTool.exe sign /f ${SIGN} /p ${SIGNPASS} /fd sha1 /t http://timestamp.comodoca.com /v"
!define OutFileSignSHA256 "SignTool.exe sign /f ${SIGN} /p ${SIGNPASS} /fd sha256 /tr http://timestamp.comodoca.com?td=sha256 /td sha256 /v"

!finalize "${OutFileSignSHA1} .\openssl-${VERSION}-installer.exe"
!finalize "${OutFileSignSHA256} .\openssl-${VERSION}-installer.exe"
!endif
