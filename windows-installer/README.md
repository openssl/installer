# OpenSSL Library Windows Installer

The installer provides a binary distribution of the OpenSSL library for the Microsoft Windows operating system.

It can install the OpenSSL library DLLs, the `openssl` command-line application, and the development kit.

The installer, the application, and all installed DLL files are digitally signed with the OpenSSL Corporation key.

## Installer variants

The installer comes in two variants: EXE and MSI.

### Naming

* `OpenSSL-x64-VS-<version>` — includes the Microsoft Visual Studio redistributable required for `openssl.exe` to function.
  The redistributable package is installed only if it is not already present on the machine.

* `OpenSSL-x64-hybridCRT-<version>` — contains OpenSSL built using the Hybrid CRT method, so it does not depend on the Visual Studio redistributable.
  For more information, see [Hybrid CRT documentation](https://github.com/microsoft/WindowsAppSDK/blob/77761e244289fda6b3d5f14c7bded189fed4fb89/docs/Coding-Guidelines/HybridCRT.md).

## Supported Windows versions and platforms

The installer supports x64 platform builds only and can be run on Windows 7 / Windows Server 2008 R2 or more recent versions.
The Visual Studio redistributable is installed in its x64 version only.
For HybridCRT flavour to work on older versions than Windows 10, the Universal CRT has to be updated, [see](https://support.microsoft.com/en-us/servicing/os/windows/2020/06/update-for-universal-c-runtime-in-windows).

## Installation options

* **Installation folder**
  * Sets the path where the OpenSSL library is installed.
* **Development kit**
  * Files needed for development: `.dll`, `.pdb`, `.lib`, header files, and documentation.
* **Application**
  * Installs the `openssl.exe` application (and the required DLLs if not installed otherwise).
* **Adjust PATH**
  * Prepends the installation directory to the system `PATH` environment variable.
* **FIPS provider**
  * Optionally installs the FIPS provider.
    You can choose either the FIPS-validated OpenSSL FIPS provider version or the provider that comes with the current library version.
    The FIPS provider cannot be installed without the application (`openssl.exe`), as the application is required to generate the `fipsmodule.cnf` file.

    For the Hybrid CRT variant, only the FIPS provider of the current OpenSSL library version is available (there is no FIPS-validated version).

## Command-line installation

The installer can be run from the Windows Command Prompt. The command-line arguments for the options above are:

* `INSTALL_APPS` (1)
* `INSTALL_SDK` (1)
* `INSTALL_FIPS` (0)
* `INSTALL_FIPS_TYPE` — `validated` or `current`
* `ADJUSTSYSTEMPATHENV` (1)

Where 1 means enabled and 0 means disabled. The values in parentheses are the defaults.

Example of a command-line installation:

```
msiexec /i OpenSSL-<version>.msi /qn INSTALL_FIPS=1 INSTALL_FIPS_TYPE=current
```

## Registry entries

The installer creates entries in the HKEY_LOCAL_MACHINE (HKLM) and HKEY_CURRENT_USER (HKCU) registry hives.
These entries have paths to:

- `OPENSSLDIR` — directory with the configuration files
- `MODULESDIR` — provider DLL directory
- `EnvPath` — directory containing `openssl.exe`
