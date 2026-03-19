from pathlib import Path
from subprocess import run, DEVNULL
import winreg
import shutil
import argparse
from time import sleep

class Error(Exception):
    pass

debug = 1
def debug_msg(msg):
    if debug:
        print(msg)

# load arguments
parser = argparse.ArgumentParser()
# should be something like: "C:\OpenSSL-x64-4.0.0.msi"
parser.add_argument('--installer', help='filepath to the installer .msi')
args = parser.parse_args()

debug_msg(args.installer)

if args.installer:
    installer = args.installer
    if not Path(installer).exists():
        print(f"Installer '{installer}' was not found")
        exit(1)
else:
    installer_path = fr"C:\Users\build-target\Installer64\DefaultBuild"
    installer = str(next(Path(installer_path).glob("*.msi"), None))
    if installer == 'None':
        print(f"No installer was found at {installer_path}")
        exit(1)
version = str(installer).split('-')[-1].replace('.msi', '')
major_v = version.split('.')[0]
minor_v = version.split('.')[1]
config_v = f'{major_v}.{minor_v}'
print(config_v)
registry_version = version.rsplit(".", 1)[0]
debug_msg(f"found installer file at: {installer}")
debug_msg(f"found installer version: {version}")

# needs to be changed manually
fips_version_validated = '3.1.2'

program_files = f'C:\\Program Files\\OpenSSL Library\\openssl-{version}\\'
common_files = f'C:\\Program Files\\Common Files\\SSL\\openssl-{config_v}\\'
installed_files = {program_files:[{'name':'LICENSE.txt', 'flags':'all'},
                                  {'name':'version.dat', 'flags':'all'}],
                   f'{program_files}bin\\':[{'name':'openssl.exe', 'flags':'app'},
                                            {'name':f'libcrypto-{major_v}-x64.dll', 'flags':'app'},
                                            {'name':f'libssl-{major_v}-x64.dll', 'flags':'app'}],
                   f'{program_files}lib\\':[{'name':f'libcrypto-{major_v}-x64.dll', 'flags':'sdk'},
                                            {'name':f'libssl-{major_v}-x64.dll', 'flags':'sdk'},
                                            {'name':f'libcrypto-{major_v}-x64.pdb', 'flags':'sdk'},
                                            {'name':f'libssl-{major_v}-x64.pdb', 'flags':'sdk'},
                                            {'name':f'libcrypto.lib', 'flags':'sdk'},
                                            {'name':f'libssl.lib', 'flags':'sdk'}],
                   f'{program_files}lib\\ossl-modules\\':[{'name':'fips.dll', 'flags':'fips'},
                                                          {'name':'fips.lib', 'flags':'fips_sdk'},
                                                          {'name':'fips.pdb', 'flags':'fips_sdk'},
                                                          {'name':'legacy.dll', 'flags':'all'},
                                                          {'name':'legacy.lib', 'flags':'sdk'},
                                                          {'name':'legacy.pdb', 'flags':'sdk'}],
                   f'{program_files}html\\man1\\':[{'name':'openssl.html', 'flags':'sdk'}],
                   f'{program_files}html\\man3\\':[{'name':'EVP_PKEY_new.html', 'flags':'sdk'}],
                   f'{program_files}html\\man5\\':[{'name':'config.html', 'flags':'sdk'}],
                   f'{program_files}html\\man7\\':[{'name':'EVP_RAND.html', 'flags':'sdk'}],
                   f'{program_files}include\\openssl\\':[{'name':'evp.h', 'flags':'sdk'}],
                   common_files:[{'name':'ct_log_list.cnf', 'flags':'all'},
                                 {'name':'ct_log_list.cnf.dist', 'flags':'all'},
                                 {'name':'openssl.cnf', 'flags':'all'},
                                 {'name':'openssl.cnf.dist', 'flags':'all'},
                                 {'name':'fipsmodule.cnf', 'flags':'fips'}]}
should_stay_files = {f'{common_files}':[{'name':'ct_log_list.cnf', 'flags':'all'},
                                        {'name':'openssl.cnf', 'flags':'all'}]}


# helper functions
def install_openssl(options=[]):
    run(["msiexec", "/i", installer, "/qn", *options], check=True)
def uninstall_openssl():
    run(["msiexec", "/x", installer, "/qn"], check=False)

def check_installed_files(flags):
    flags += ('all',)
    for path, v in installed_files.items():
        for file in v:
            if file['flags'] in flags:
                if not Path(f'{path}{file["name"]}').exists():
                    raise Error('file {}{} was not found'.format(path, file["name"]))
            else:
                if Path(path+file['name']).exists():
                    raise Error('file {}{} file should not be installed'.format(path, file["name"]))
def check_should_stay_files():
    for path, v in should_stay_files.items():
        for file in v:
            if not Path(path+file['name']).exists():
                raise Error('file {} was not found, but should have been'.format(file["name"]))

def check_openssl_version():
    # as the opened terminal has non-updated $Env:Path, we need to pass the
    # full path to the program
    res = run([f'{program_files}bin\\openssl.exe', 'version'], check=True, capture_output=True, text=True)
    # also eliminate -dev at the end of the version e.g. 4.0.0-dev
    version_res = res.stdout.split(' ')[1].split('-')[0]
    if version_res != version:
        raise Error('Version does not match: {} -> {}'.format(version, version_res))

def check_fips_loadability(fips_type):
    cnf = f"{common_files}openssl.cnf"
    cnf_old = f"{common_files}openssl_old.cnf"
    config = Path(cnf)
    shutil.copy2(config, cnf_old)

    fipsmodule_path = rf'.include C:\\Program Files\\Common Files\\SSL\\openssl-{config_v}\\fipsmodule.cnf'
    content = config.read_text(encoding="utf-8")
    content = content.replace("# .include fipsmodule.cnf", fipsmodule_path)
    content = content.replace("# fips = fips_sect", "fips = fips_sect")
    content = content.replace("# activate = 1", "activate = 1")
    config.write_text(content, encoding="utf-8")

    res = run([f'{program_files}bin\\openssl.exe', 'list', '-providers', '-provider=fips'], capture_output=True, text=True)
    #cleanup
    shutil.move(cnf_old, cnf)
    if (res.returncode != 0):
       raise Error()

    #check the version number
    version_res = res.stdout.split('fips')[-1].split('version: ')[1].split('\n')[0]
    v = version if fips_type == 'current' else fips_version_validated
    if version_res != v:
        raise Error('Version does not match: {} -> {}'.format(v, version_res))
def check_legacy_loadability():
    run([f'{program_files}bin\\openssl.exe', 'list', '-providers', '-provider=legacy'], check=True, stdout=DEVNULL, stderr=DEVNULL)

def check_registry_entries():
    paths = [f"SOFTWARE\\OpenSSL Corporation\\OpenSSL-{registry_version}-OpenSSLProject",
             f"SOFTWARE\\Wow6432Node\\OpenSSL-{registry_version}-OpenSSLProject"]

    for path in paths:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
            value, _ = winreg.QueryValueEx(key, "MODULESDIR")
            if value != f"C:\\Program Files\\OpenSSL Library\\openssl-{version}\\lib\\ossl-modules":
                raise Error('incorrect MODULESDIR: {}'.format(value))
            value, _ = winreg.QueryValueEx(key, "OPENSSLDIR")
            if value != f"C:\\Program Files\\Common Files\\SSL\\openssl-{config_v}":
                raise Error('incorrect OPENSSLDIR: {}'.format(value))
            value, _ = winreg.QueryValueEx(key, "EnvPath")
            if value != f"C:\\Program Files\\OpenSSL Library\\openssl-{version}\\bin\\":
                raise Error('incorrect EnvPath: {}'.format(value))


# test cases
def test_default():
    install_openssl()
    check_installed_files(('app', 'sdk'))
    # as this is the first test case, let's wait until Visual Studio redistributable
    # is installed
    sleep(5)
    check_openssl_version()
    check_registry_entries()
    check_legacy_loadability()

def test_app():
    install_openssl(['INSTALL_APP=1', 'INSTALL_SDK=0'])
    check_installed_files(('app',))

def test_sdk():
    install_openssl(['INSTALL_SDK=1', 'INSTALL_APP=0'])
    check_installed_files(('sdk',))

def test_app_sdk():
    install_openssl(['INSTALL_APP=1', 'INSTALL_SDK=1'])
    check_installed_files(('app', 'sdk'))

def test_fips_validated():
    install_openssl(['INSTALL_FIPS=1', 'INSTALL_FIPS_TYPE=validated', 'INSTALL_SDK=1'])
    check_installed_files(('fips', 'fips_sdk', 'app', 'sdk'))
    check_fips_loadability('validated')

def test_fips_current():
    install_openssl(['INSTALL_FIPS=1', 'INSTALL_FIPS_TYPE=current'])
    check_fips_loadability('current')

def test_fips_without_app():
    try:
        install_openssl(['INSTALL_FIPS=1', 'INSTALL_FIPS_TYPE=validated', 'INSTALL_SDK=1', 'INSTALL_APP=0'])
        raise Error('Fips was installed without openssl.exe')
    except:
        # this should fail
        # as openssl.exe is needed to generate fipsmodule.cnf
        pass

tests = [test_default,
         test_app,
         test_sdk, 
         test_app_sdk,
         test_fips_validated,
         test_fips_current,
         test_fips_without_app]


# run tests
failed = 0
print(f"Running {len(tests)} tests:")
#try to uninstall if there is something left on the system
uninstall_openssl()
for i, t in enumerate(tests):
    print(f'{i+1}. {t.__name__:.<33}', end='', flush=True)
    try:
        t()
        print('\033[32mOK\033[0m')
    except Exception as e:
        print('\033[31mFAIL\033[0m')
        print(e)
        failed += 1
    uninstall_openssl()
    check_should_stay_files()

if failed == 0:
    print("All tests were successful!")
else:
    print("Failed tests:\t", failed, '/', len(tests))
