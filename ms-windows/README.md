OpenSSL Installer Build Tools For Windows
=========================================

This packager prepares binary builds of OpenSSL for the Microsoft Windows operating system and encapsulates the generated files within EXE and MSI installers suitable for distribution.

Basic Setup
-----------

To perform builds efficiently, a relatively recent desktop class Intel/AMD CPU with at least 8 performance cores is strongly recommended to build all supported versions and architectures simultaneously.  At least 15GB of free disk storage should be available as well.

On a Windows computer (or virtual machine), install Visual C++ components from both Microsoft Visual Studio 2017 and Microsoft Visual Studio 2019.  During the installation process, be sure to select "MSVC ... ARM64" from the optional items under "Desktop development with C++" to be able to build for arm64.  Also be sure to install at least one Windows SDK.

The scripts here are written in the PHP scripting language.  Obtain a "Thread Safe" build of PHP for Windows from [windows.php.net](https://windows.php.net/download/).  The 'zlib', 'zip', and 'openssl' extensions need to be enabled.

Obtain a copy of this repository.  Avoid putting the repository into a directory structure with paths that have spaces in them.  Some tools have difficulties with spaces.  The various paths also get quite long, so the closer to the root of a drive that this repository sits on the machine, the less likely that limitations in Windows itself will be encountered.

Running Build Tools
-------------------

The main 'build-tools.php' script performs all of the work to download required dependencies (Perl, NASM, Inno Setup, Wix toolset) from HTTPS enabled websites (hence why the 'openssl' extension in PHP is required to build OpenSSL), validate environments, download, validate and extract OpenSSL release tarballs, run `perl Configure` and `nmake`, and run Inno Setup and Wix toolset.

Avoid moving or renaming parent directories after running the build tools script.  It is easier to just start from a completely fresh copy of this repository if you need to move or rename parent folders.  A number of paths get mapped to the current directory structure during the initialization/preparation and build process and will probably result in errors if the parent directories are moved or renamed.

From a Command Prompt, run:

```
php build-tools.php -?
```

To get basic help output from the tool.

Running:

```
php build-tools.php
```

Provides an interactive guided interface.  All build tools operations aim to be idempotent and repeatable across multiple machines.

Within the 'templates' subdirectory of this repository are the currently supported base versions.  To setup a base version, it must first be initialized.  For example, initializing OpenSSL 3.1.x begins with:

```
php build-tools.php init 3.1
```

This will create several directories and download, validate, and extract/setup the dependencies that are defined in 'templates/3.1/info.json'.  During "installation" of Inno Setup 5, an Administrator UAC elevation prompt will appear despite being told to not do that in the options passed to it and it doesn't actually get formally installed on the system (i.e. no registry entries for Add/Remove Programs).  All the other dependencies do not require Administrator elevation.

The next step is to create base version environment profiles for your system.  Start a Visual Studio Command Prompt for x86, x64, and ARM64.  Run 'cl.exe' to confirm that the correct Visual C++ compiler is running.  The "Cross Tools" flavors follow the nomenclature of "local_target" (e.g. x64_ARM64 = local machine architecture => target).

Each base version has a preferred version of the Visual C++ compiler but the only actual requirement is that the target architecture matches.

Within each Visual Studio Command Prompt, run the relevant line that matches:

```
php build-tools.php save-profile 3.1 x86
php build-tools.php save-profile 3.1 x64
php build-tools.php save-profile 3.1 arm64
```

The "save-profile" will run all validations against the environment.  If they all pass, the environment is saved to the 'versions/3.1/profiles' directory.

Close the Visual Studio Command Prompts.  You won't need them again for that base version.

The above steps only need to be performed one time per base version on a system.

Building OpenSSL
----------------

Now it is time to build OpenSSL and prepare packaged installers.  Preparing to build and package OpenSSL v3.1.0, for example, is accomplished via:

```
php build-tools.php prepare 3.1.0
```

Of course, replace the specific version according to what needs to be built.  That will download the source tarball, verify and extract it, and also prepare Inno Setup and Wix toolset installer scripts from 'templates/3.1' for each architecture and place them into the 'versions/3.1/3.1.0/installers' subdirectory.

Now comes the fun part...building 6 flavors of OpenSSL (/MD, /MDd, /MT, /MTd + two static variants) and producing 4 different installers (two EXEs and two MSIs) per architecture:

```
php build-tools.php build-all 3.1.0
```

That will run builds for all configured architectures simultaneously using the saved environment profiles for the base version.  This is where approximately one core of a CPU per architecture is required.  To concurrently build and package multiple versions for all configured architectures:

```
php build-tools.php build-all 1.1.1t 3.0.8 3.1.0
```

Concurrently building all supported base versions for all architectures currently requires approximately 8 CPU cores, 15GB of disk storage, and over 40 minutes of patient waiting.

When a build finishes, the generated installers will be located in the final Output subdirectory for the specific version and architecture installer (e.g. 'versions/3.1/3.1.0/installers/x86/final/Output').

The 'build-all' command also builds two portable flavors that combines all architectures.  One ZIP file only contains essentials like executables and DLLs (about 12MB compressed) while the other includes all compiled libraries designed for Visual C++ developers (about 140MB compressed).

Debugging/Troubleshooting
-------------------------

The build tools script is designed to capture and log errors and output.  Logged output can appear in both 'temp/logs' and 'versions' build output broken down by specific version and architecture (e.g. 'versions/3.1/3.1.0/out_x86/logs').

In general, two log files are generated when the build tool runs an external program like 'nmake':  One file for stdout and the other for stderr.  This keeps noise on the command line to a minimum but makes it slightly more difficult to diagnose problems.  Usually the last few lines of the error log will have the error message details while the other log file will show the relevant last bits of information from the command that were output before the error occurred.

If nothing shows up in the log files, then it is probably environment related and most likely something on the system Path environment variable in the saved environment profile.  Windows applications frequently modify the system Path.  Look at the JSON files in the 'profiles' subdirectory in the base version (e.g. 'versions/3.1/profiles/x86.json') to see if the Path can be cleaned up by removing extraneous application references.  Manually adjusting the Path in those JSON files won't impact the system but could implicitly get rid of conflicting software (e.g. DLLs) that Windows might be picking up during the build process but were not detected during the various validation phases.

The base version 'init' will probably break if dependencies vanish from their source URLs.  The locations in the base version JSON files will need to be updated to point at new URLs.

Directory Structure
-------------------

This directory structure layout should help with understanding the output of each major step (init, save-profile, prepare, build/build-all):

* /templates - Main base version JSON and templated Inno Setup and Wix toolset scripts.  The base version JSON files drive the entire process to produce consistent results.
* /versions/3.1/deps - Verified binary dependencies.  Required to build and package OpenSSL.  Output of 'init'.
* /versions/3.1/profiles - Stores and preserves environment variables in architecture and system-dependent JSON files.  Output of 'save-profile'.
* /versions/3.1/3.1.0/source - Extracted source code tree.  Output of 'prepare'.
* /versions/3.1/3.1.0/temp_ARCH - A temporary copy of the extracted source code tree to enable concurrent building of multiple architectures for a single version (e.g. temp_x86, temp_x64, temp_arm64).  Used during 'build'.
* /versions/3.1/3.1.0/out_ARCH - Build output for an architecture (e.g. out_x86, out_x64, out_arm64).  Output of 'build'.
* /versions/3.1/3.1.0/installers - Installer structure preparation location and final output.  Output of 'build' and 'build-all'.

Creating New Templates
----------------------

When a new base version is released (e.g. 3.2), the simplest approach to creating a new template is to copy the previous version's template and then make some adjustments to 'info.json' and various installer scripts.  For official releases, the various dependencies should be updated to best reflect supported end-user OSes and architectures.  The build tools script can be used to evaluate/validate all potential dependencies via 'init-test':

```
php build-tools.php init-test 3.2
```

That downloads and validates all dependencies for a base version, which checks all hashes against the hashes in the 'info.json' file.  Obviously, changing dependencies can result in breakages, so thorough testing is necessary.

Updating the version of Visual Studio may come with the additional requirement to modify the installer script templates to point at updated VC++ runtimes.  The installer scripts are just plain text files with specially formatted codes embedded into them (e.g. `[[DOTTED_VERSION]]`) that get replaced during the 'prepare' pre-build phase.  Changes to installer script templates propagate to specific versions when the 'prepare' pre-build phase is run.

When new major versions are produced (e.g. `libssl-3.dll` to `libssl-4.dll`), then the Wix toolset scripts need new GUIDs to allow multiple versions of the OpenSSL DLLs to be installed on the same system.
