#environment settable variables
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

$patch1 =
@'
From 7af1798ad07ded2e39b0ce60544c382c9919e35d Mon Sep 17 00:00:00 2001
From: Norbert Pocs <norbertp@openssl.org>
Date: Tue, 17 Feb 2026 02:34:12 -0800
Subject: [PATCH] win: Fix warning build issue

---
 test/build_wincrypt_test.c | 6 +++++-
 1 file changed, 5 insertions(+), 1 deletion(-)

diff --git a/test/build_wincrypt_test.c b/test/build_wincrypt_test.c
index 5bd75e6a..25fd9d93 100644
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
$patch2 =
@'
From d130c5f74873b3aad74f58bd7d0fdea0fb16397c Mon Sep 17 00:00:00 2001
From: Norbert Pocs <norbertp@openssl.org>
Date: Thu, 8 Jan 2026 16:11:10 +0100
Subject: [PATCH] windows-makefile: Don't prefix libdir when it is absolute
 path
MIME-Version: 1.0
Content-Type: text/plain; charset=UTF-8
Content-Transfer-Encoding: 8bit

When --libdir was passed to configuration as an absolute path then
the makefile MODULESDIR_dir became concat(prefix, libdir) creating
an invalid path.

Fixes: https://github.com/openssl/project/issues/1797

Signed-off-by: Norbert Pocs <norbertp@openssl.org>

Reviewed-by: Saša Nedvědický <sashan@openssl.org>
Reviewed-by: Richard Levitte <levitte@openssl.org>
(Merged from https://github.com/openssl/openssl/pull/29579)
---
 Configurations/windows-makefile.tmpl | 2 +-
 1 file changed, 1 insertion(+), 1 deletion(-)

diff --git a/Configurations/windows-makefile.tmpl b/Configurations/windows-makefile.tmpl
index 408b571d66..e9f985f855 100644
--- a/Configurations/windows-makefile.tmpl
+++ b/Configurations/windows-makefile.tmpl
@@ -208,7 +208,7 @@ OPENSSLDIR_dir={- canonpath($openssldir_dir) -}
 LIBDIR={- our $libdir = $config{libdir} || "lib";
           file_name_is_absolute($libdir) ? "" : $libdir -}
 MODULESDIR_dev={- use File::Spec::Functions qw(:DEFAULT splitpath catpath);
-                  our $modulesprefix = catdir($prefix,$libdir);
+                  our $modulesprefix = file_name_is_absolute($libdir) ? $libdir : catdir($prefix,$libdir);
                   our ($modulesprefix_dev, $modulesprefix_dir,
                        $modulesprefix_file) =
                       splitpath($modulesprefix, 1);
-- 
2.52.0
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
	pushd $dir
	# 3.1.2 does not build on windows without this patch
	# TODO patches do not apply
	if ($branch -eq "openssl-3.1.2") {
		$patch1 | git apply
		$patch2 | git apply
	}
	perl .\Configure enable-fips --libdir="C:\Program Files\OpenSSL Project\$branch" VC-WIN64A
	cmd /c '"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" && perl .\Configure enable-fips --libdir="C:\Program Files\OpenSSL Project\$branch\lib" VC-WIN64A'
	cmd /c '"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" && nmake'
	cmd /c '"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" && nmake build_docs'
	# fipsmodule.cnf has to be generated
	apps\openssl fipsinstall -module providers\fips.dll -out fipsmodule.cnf
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
	msiexec /i "$installerDir\OpenSSL-x64-$version" $params /qn
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
