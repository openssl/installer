from pathlib import Path
import unittest
from subprocess import Popen
from time import sleep
import argparse

from pywinauto import Application

debug = 1
def debug_msg(msg):
    if debug:
        print(msg)

version = '4.0.0'

# load arguments
parser = argparse.ArgumentParser()
parser.add_argument('--path', help='path to the installer .msi')
args = parser.parse_args()

if args.path:
    installer_path = args.path
else:
    installer_path = f"C:\\Users\\build-target\\Installer64\\DefaultBuild\\OpenSSL-x64-{version}.msi"
installer = str(next(Path(installer_path).glob("*.msi"), None))
if installer == 'None':
    print("Installer was not found")
    exit(1)
version = str(installer).split('-')[-1].replace('.msi', '')
major_v = version.split('.')[0]
minor_v = version.split('.')[1]
config_v = f'{major_v}.{minor_v}'
print(config_v)
registry_version = version.rsplit(".", 1)[0]
debug_msg(f"found installer file at: {installer}")
debug_msg(f"found installer version: {version}")

class InstallerTest(unittest.TestCase):
    @classmethod
    def setUpClass(self):
        Popen(["msiexec.exe", "/i", installer])
        sleep(1)
        self.app = Application(backend='uia').connect(title_re='OpenSSL Project Setup')
        self.dlg = self.app.top_window()

    @classmethod
    def tearDownClass(self):
        self.dlg = self.app.top_window()
        self.dlg.close()
        sleep(1)

        self.dlg.Yes.click()

        dlg = self.app.top_window()
        dlg.Finish.click()

    def click_next(self):
        self.dlg.Next.click()
        self.dlg = self.app.top_window()

    def click_back(self):
        self.dlg.Back.click()
        self.dlg = self.app.top_window()

    def test_gui(self):
        # welcome dialog
        self.click_next()

        # license dialog
        if (self.dlg.Static2.window_text() != 'End-User License Agreement'):
            self.fail("Wrong dialog")
        if (self.dlg.Next.is_enabled == True):
            self.fail("Next should be disabled without agreeing to license")
        #debug
        #self.dlg.RadioButton1.window_text()
        self.dlg.RadioButton1.click()
        self.click_next()

        # install path dialog
        if (self.dlg.Static2.window_text() != 'Select Installation Folder'):
            self.fail("Wrong dialog")
        install_path = f'C:\\Program Files\\OpenSSL Project\\openssl-{version}\\'
        t = self.dlg.ComboBox.selected_text()
        if (t != install_path):
            self.fail(f"Awaited install path: {install_path}, got {t}")
        self.click_next()

        # components to install dialog
        if (self.dlg.Static2.window_text() != 'Components to install'):
            self.fail("Wrong dialog")
        if (self.dlg.CheckBox1.get_toggle_state() == 0 or self.dlg.CheckBox2.get_toggle_state() == 0):
            self.fail("Install application and sdk is the default.")
        #turn them off and a popup should appear
        self.dlg.CheckBox1.click()
        self.dlg.CheckBox2.click()
        self.dlg.Next.click()
        #wait to appear
        sleep(1)
        if (self.dlg.static.window_text() != 'Please choose at least one option.'):
            self.fail("Not installing 0 options is not enabled")
        self.dlg.OK.click()
        #turn back on
        self.dlg.CheckBox1.click()
        self.dlg.CheckBox2.click()
        self.click_next()

        # additional options dialog
        if (self.dlg.Static2.window_text() != 'Configuring additional Options'):
            self.fail("Wrong dialog")
        if (self.dlg.CheckBox2.get_toggle_state() != 0
            and self.dlg.RadioButton1.is_enabled != False
            and self.dlg.RadioButton2.is_enabled != False):
            self.fail("FIPS shouldn't be installed by default")
        # check that FIPS is not installable when apps is disabled
        self.click_back()
        self.dlg.CheckBox1.click()
        self.click_next()
        self.dlg.CheckBox2.click()
        self.dlg.Next.click()
        sleep(1)
        if (self.dlg.static.window_text() != "FIPS can't be installed without the openssl app."):
            self.fail("Can't install FIPS without the app")
        self.dlg.OK.click()
        sleep(1)

if __name__ == '__main__':
    suite = unittest.TestLoader().loadTestsFromTestCase(InstallerTest)
    unittest.TextTestRunner(verbosity=2).run(suite)
