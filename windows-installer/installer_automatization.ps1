#envarionment settable variables
if (-not $opensslInstallVersion) {
	$version = "4.0.0"
} else {
	$version = $opensslInstallVersion
}

if (-not $opensslInstallRegistryVersion) {
	$registryVersion = "4.0-0"
} else {
	$registryVersion = $opensslInstallRegistryVersion
}
if (-not $opensslInstallVersionBranch) {
	$versionBranch = "master"
} else {
	$versionBranch = $opensslInstallVersionBranch
}
if (-not $opensslInstallFipsVersionBranch) {
	$fipsVersionBranch = "openssl-3.1.2"
} else {
	$fipsVersionBranch = $opensslInstallFipsVersionBranch
}

$winctx = $version -split "."
$winctx = $winctx[2]
$fipsWinctx = $fipsVersionBranch -split "."
$fipsWinctx = $winctx[2]
$targetDir = "C:\openssl"
$fipsTargetDir = "C:\openssl-fips"
$gitUrl = "https://github.com/openssl/openssl.git"
$installerDir = "C:\build-target\Installer64\DefaultBuild"
$patch =
@'
From bbeca7f85e9b54f73c36ca47edf57b68ab4bfb21 Mon Sep 17 00:00:00 2001
From: Norbert Pocs <norbertp@openssl.org>
Date: Wed, 11 Feb 2026 06:47:29 -0800
Subject: [PATCH] Fix build on windows

---
 test/build_wincrypt_test.c | 6 +++++-
 1 file changed, 5 insertions(+), 1 deletion(-)

diff --git a/test/build_wincrypt_test.c b/test/build_wincrypt_test.c
index 5bd75e6a43..25fd9d9346 100644
--- a/test/build_wincrypt_test.c
+++ b/test/build_wincrypt_test.c
@@ -22,7 +22,11 @@
 # include <wincrypt.h>
 # ifndef X509_NAME
 #  ifndef PEDANTIC
-#   warning "wincrypt.h no longer defining X509_NAME before OpenSSL headers"
+#    ifdef _MSC_VER
+#       pragma message("wincrypt.h no longer defining X509_NAME before OpenSSL headers")
+#    else
+#       warning "wincrypt.h no longer defining X509_NAME before OpenSSL headers"
+#    endif
 #  endif
 # endif
 #endif
-- 
2.53.0.windows.1
'@

function Install-Prerequisites {
	$prereq = @("Strawberry Perl", "Visual Studio BuildTools 2022", "NASM.NASM", "Git.Git")

	foreach ($r in $prereq) {
		winget install $r --silent --accept-package-agreements --accept-source-agreements --disable-interactivity
	}
}

function Build-Openssl {
	param (
		[string]$branch,
		[string]$dir,
		[string]$winctx
	)
	git clone --depth 1 -b $branch $gitUrl $dir
	# 3.1.2 does not build on windows without this patch
	if ($branch -eq "openssl-3.1.2") {
		if (-not (Test-Path "fix.patch")) {
			New-Item -Path "fix.patch" -ItemType File
		}
		Set-Content -Path "fix.patch" -Value $patch
	}
	pushd $dir
	perl .\Configure --banner="Configured" enable-fips -DOSSL_WINCTX=$winctx VC-WIN64A
	cmd /c '"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" && nmake'
	popd
}

#TODO
#the openssl.aip file should be fetched from somewhere. For now it has to be present locally
function Build-Installer {
	if (-not (Test-Path "commands.aic")) {
		New-Item -Path "commands.aic" -ItemType File
	}
	@"
;aic
SetVersion $version
SetProperty VERSION_REGISTRY='$registryVersion'
Save
Build -buildslist DefaultBuild
"@ | Set-Content "commands.aic"
	& 'C:\Program Files (x86)\Caphyon\Advanced Installer 23.3\bin\x86\AdvancedInstaller.com' /execute openssl.aip commands.aic
}

function Install-Openssl {
	param (
		[string]$params
	)
	echo "Installing openssl"
	msiexec /i "$installerDir\OpenSSL-x64-$version" /qn $params
}

function Uninstall-Openssl {
	echo "Uninstalling openssl"
	msiexec /x "$installerDir\OpenSSL-x64-$version" /qn
}

function Test-Case1 {
	Install-Openssl
	Uninstall-Openssl
}

function Test-Openssl {
	Test-Case1
	echo "Success"
}

Install-Prerequisites

Build-Openssl -branch $versionBranch -dir $targetDir -winctx $winctx
Build-Openssl -branch $fipsVersionBranch -dir $fipsTargetDir -winctx $fipsWinctx

Build-Installer

Test-Openssl
