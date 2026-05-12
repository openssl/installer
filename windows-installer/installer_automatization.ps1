#environment settable variables
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

$version = 0 # version is detected later
$targetDir = "C:\openssl"
$fipsTargetDir = "C:\openssl-fips"
$gitUrl = "https://github.com/openssl/openssl.git"
$installerDir = "C:\build-target\Installer64\DefaultBuild"


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
		[string]$extra_config_options
	)
	git clone --depth 1 -b $branch $gitUrl $dir
	pushd $dir
	# 3.1.2 does not build on windows without this patch
	# TODO patches do not apply probably because of win style new line
	if ($branch -eq "openssl-3.1.2") {
		git apply "$PSScriptRoot\0001-win-Fix-warning-build-issue.patch"
		git apply "$PSScriptRoot\0002-windows-makefile-libdir-absolute.patch"
	}
	cmd /c '"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" && perl .\Configure enable-fips $extra_config_options VC-WIN64A'
	cmd /c '"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" && nmake'
	if ($branch -ne $fipsVersionBranch) {
		cmd /c '"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" && nmake build_docs'
		$version = (Get-Item .\apps\openssl.exe).VersionInfo.FileVersion
	}
	popd
}

# The winctx used is in the format OpenSSL-4.0-OpenSSLProject
# This variable should be set without the first openssl: "4.0-OpenSSLProject"
# as the OpenSSL prefix is hardcoded in the library and is not changeable
# the version calculates automatically; the only thing we need to chose is the <ctx>
$winctx = ($version[0..2] - join '') + "-OpenSSLProject"
#TODO
#the openssl.aip file should be fetched from somewhere. For now it has to be present locally
function Build-Installer {
	if (-not (Test-Path "commands.aic")) {
		New-Item -Path "commands.aic" -ItemType File
	}
	@"
;aic
SetVersion $version
SetProperty VERSION_REGISTRY='$winctx'
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

Build-Openssl -branch $versionBranch -dir $targetDir -extra_config_options "-DOSSL_WINCTX=OpenSSLProject"
# the fips version doesn't need winctx to be set; only the fips provider files are used from there
Build-Openssl -branch $fipsVersionBranch -dir $fipsTargetDir

Build-Installer

Test-Openssl
