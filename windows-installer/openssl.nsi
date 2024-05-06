
######################################################
# NSIS windows installer script file
# Requirements: NSIS 3.0 must be installed with the MUI plugin
# Usage notes:
# This script expects to be executed from the directory it is
# currently stored in.  It expects a 32 bit and 64 bit windows openssl
# build to be present in the ..\${BUILD32} and ..\${BUILD64} directories
# respectively
# ####################################################

!include "MUI.nsh"

!define PRODUCT_NAME "OpenSSL"

# The name of the output file we create when building this
# NOTE version is passed with the /D option on the command line
OutFile "openssl-${VERSION}-installer.exe"

# The name that will appear in the installer title bar
NAME "${PRODUCT_NAME} ${VERSION}"

ShowInstDetails show

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
		SetOutPath $INSTDIR\x64\lib
		File /r "${BUILD32}\Program Files\OpenSSL\lib\"
		SetOutPath $INSTDIR\x64\bin
		File /r "${BUILD32}\Program Files\OpenSSL\bin\"
		SetOutPath "$INSTDIR\x64\Common Files"
		File /r "${BUILD32}\Program Files\Common Files\"
	SectionEnd
	Section "x32 Development Headers"
		SetOutPath $INSTDIR\x64\include
		File /r "${BUILD32}\Program Files\OpenSSL\include\"
	SectionEnd
SectionGroupEnd
!endif

!ifdef BUILD64
Section "Documentation"
	SetOutPath $INSTDIR\html
	File /r "${BUILD64}\Program Files\OpenSSL\html\"
SectionEnd
!endif

# Always install the uninstaller
Section 
	WriteUninstaller $INSTDIR\uninstall.exe
SectionEnd

# This is run on uninstall
Section "Uninstall"
	RMDIR /r $INSTDIR
SectionEnd

!insertmacro MUI_PAGE_WELCOME

!insertmacro MUI_PAGE_LICENSE ${LICENSE_FILE}

Function CheckRunUninstaller
        ifFileExists $INSTDIR\uninstall.exe 0 +2
        ExecWait "$INSTDIR\uninstall.exe /S _?=$INSTDIR"
FunctionEnd
!insertmacro MUI_PAGE_COMPONENTS

!define MUI_PAGE_CUSTOMFUNCTION_LEAVE CheckRunUninstaller
!define MUI_DIRECTORYPAGE_TEXT_DESTINATION "Installation Directory"
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
