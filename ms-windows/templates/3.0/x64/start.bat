@echo off
@set PATH=%PATH%;%~dp0bin

title OpenSSL Command Prompt (Intel/AMD x64)
echo OpenSSL Command Prompt (Intel/AMD x64)
echo.
openssl version -a
echo.

%SystemDrive%
cd %UserProfile%

cmd.exe /K
