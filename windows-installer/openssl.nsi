
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

# The name of the output file we create when building this
# NOTE version is passed with the /D option on the command line
OutFile "openssl-${VERSION}-installer.exe"

# The name that will appear in the installer title bar
NAME "${PRODUCT_NAME} ${VERSION}"

ShowInstDetails show

Var DataDir
Var ModDir

Function .onInit
	StrCpy $INSTDIR "C:\Program Files\openssl-${VERSION}"
FunctionEnd

# This section is run if installation of 32 bit binaries are selected

!ifdef BUILD64
# This section is run if installation of the 64 bit binaries are selectd
SectionGroup "64 Bit Installation"
	Section "64 Bit Binaries"
		SetOutPath $INSTDIR\x64\lib
		File /r "${BUILD64}\Program Files\OpenSSL\lib\"
		SetOutPath $INSTDIR\x64\bin
		File /r "${BUILD64}\Program Files\OpenSSL\bin\"
		SetOutPath "$INSTDIR\x64\Common Files"
		File /r "${BUILD64}\Program Files\Common Files\"
	SectionEnd
	Section "x64 Development Headers"
		SetOutPath $INSTDIR\x64\include
		File /r "${BUILD64}\Program Files\OpenSSL\include\"
	SectionEnd
SectionGroupEnd
!endif

!ifdef BUILD32
# This section is run if installation of the 64 bit binaries are selectd
SectionGroup "32 Bit Installation"
	Section "32 Bit Binaries"
		SetOutPath $INSTDIR\x32\lib
		File /r "${BUILD32}\Program Files (x86)\OpenSSL\lib\"
		SetOutPath $INSTDIR\x32\bin
		File /r "${BUILD32}\Program Files(x86)\OpenSSL\bin\"
		SetOutPath "$INSTDIR\x64\Common Files"
		File /r "${BUILD32}\Program Files (x86)\Common Files\"
	SectionEnd
	Section "x32 Development Headers"
		SetOutPath $INSTDIR\x32\include
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
!define openssl_hklm 'HKLM "SOFTWARE\OpenSSL"'

# This is run on uninstall
Section "Uninstall"
	RMDIR /r $INSTDIR
	DeleteRegValue ${env_hklm} OPENSSL_CONF
	DeleteRegValue ${env_hklm} SSL_CERT_FILE
	DeleteRegValue ${env_hklm} CTLOG_FILE
	DeleteRegValue ${env_hklm} OPENSSL_MODULES
	DeleteRegValue ${env_hklm} OPENSSL_ENGINES
        DeleteRegValue ${openssl_hklm} OPENSSLDIR
	SendMessage ${HWND_BROADCAST} ${WM_WININICHANGE} 0 "STR:Environment" /TIMEOUT=5000
SectionEnd

!insertmacro MUI_PAGE_WELCOME

!insertmacro MUI_PAGE_LICENSE ${LICENSE_FILE}

Function CheckRunUninstaller
!ifdef BUILD64
	StrCpy $DataDir "$INSTDIR\x64\Common Files\SSL"
        StrCpy $ModDir  "$INSTDIR\x64\lib\ossl-modules"
!else
	StrCpy $DataDir "$INSTDIR\x32\Common Files\SSL"
        StrCpy $ModDir  "$INSTDIR\x32\lib\ossl-modules"
!endif
        ifFileExists $INSTDIR\uninstall.exe 0 +2
        ExecWait "$INSTDIR\uninstall.exe /S _?=$INSTDIR"

	WriteRegExpandStr ${env_hklm} OPENSSL_CONF "$DataDir\openssl.cnf"
	WriteRegExpandStr ${env_hklm} SSL_CERT_FILE "$DataDir\cert.pem"
	WriteRegExpandStr ${env_hklm} CTLOG_FILE "$DataDir\ct_log_list.cnf"
	WriteRegExpandStr ${env_hklm} OPENSSL_MODULES "$ModDir"
	WriteRegExpandStr ${env_hklm} OPENSSL_ENGINES "$ModDir"
        WriteRegExpandStr ${openssl_hklm} OPENSSLDIR "$DataDir"
	SendMessage ${HWND_BROADCAST} ${WM_WININICHANGE} 0 "STR:Environment" /TIMEOUT=5000
FunctionEnd
!insertmacro MUI_PAGE_COMPONENTS

!define MUI_PAGE_CUSTOMFUNCTION_LEAVE CheckRunUninstaller
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
