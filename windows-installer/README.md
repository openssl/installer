Windows installer script
========================

Overview
--------

The windows installer script found in this directory builds a windows installer
executable capable of installing both 32 and 64 bit openssl binaries, along
with their corresponding development headers

Requirements
------------

* [NSIS](https://nsis.sourceforge.io/Main_Page) version 3.0.8 or later
* Windows 2022 or later
* The Windows SDK
  - The `makecert.exe` utility (to demonstrate installer signing)
  - The `Pvk2Pfx.exe` utility (to demonstrate installer signing)
  - The `SignTool.exe` utility (to demonstrate installer signing)

Notes on Signing
----------------

Installer signing is demonstrated here using self signed certificates. Do not
use this signed code in a deployment as the self signed certificate should not
be trusted.  However, if you wish to observe this signed installer in
operation, the self signed certificate may be imported to the local trust store
following the instructions
[here](https://learn.microsoft.com/en-us/windows/win32/appxpkg/how-to-create-a-package-signing-certificate).
Note: Importing this example certificate to the trust store is done at your own
risk

Installer Build Prerequisites
-----------------------------
```
1) Build Openssl from the parent of this directory:
    a) clone the openssl repository
    b) cd path\to\openssl\
    c) mkdir \_build64
    d) cd \_build64
    e) perl ..\Configure [options] VC-WIN64A
    f) nmake
    g) nmake DESTDIR=..\install64
    h) repeat steps b-g substituting 32 for 64 to build VC-WIN32
```

Building the installer
----------------------

From the windows-installer directory, the included makefile can build 2 targets
1) openssl-installer
2) signed-openssl-installer

If target 1 is selected, the openssl-testversion-installer.exe file will be
generated, pulling needed binaries from the ../\_build32 and ../\_build64
directories.

If target 2 is selected, A self signed certificate will be generated and used to
create the same installer, and digitally sign it.  Note that the Signtool
utility requires a password for the generated private key be passed on the
command line, while the MakeCert utility requires that it be entered via a gui
popup window.  As such the Makefile is hard coded to use the password
'testpass', which must be entered when prompted during certificate generation,
or the signing process will fail.

Installer build options
-----------------------

* `/DBUILD64`
  - Optional
  - Path to the fully qualified 64 bit install directory (ex `c:\path\to\openssl_install64`)

* `/DBUILD32`
  - Optional
  - Path to the fully qualified 32 bit build direcotry (ex `c:\path\to\openssl_install32`)

* `/DLICENSE_FILE`
  - Required
  - Path to the openssl LICENSE.TXT file

* `/DVERSION`
  - Required
  - Version number to insert in the openssl installer file name and meta data
  - Should match the version of openssl being built

* `/DSIGN`
  - Optional
  - Path to the fully qualified location of the code signing certificate pfx file

* `/DSIGNPASS`
  - Required if /DSIGN is provided
  - Password string to decrypt the pfx file

