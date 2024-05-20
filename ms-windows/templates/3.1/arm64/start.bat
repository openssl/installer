@echo off

rem * Copyright 2016-2019 The OpenSSL Project Authors. All Rights Reserved.
rem *
rem * Licensed under the OpenSSL license (the "License").  You may not use
rem * this file except in compliance with the License.  You can obtain a copy
rem * in the file LICENSE in the source distribution or at
rem * https://www.openssl.org/source/license.html

@set PATH=%PATH%;%~dp0bin

title OpenSSL Command Prompt (ARM64)
echo OpenSSL Command Prompt (ARM64)
echo.
openssl version -a
echo.

%SystemDrive%
cd %UserProfile%

cmd.exe /K
