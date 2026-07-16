# GUI tests: walk the installer wizard via pywinauto (UIA backend).
#
# The control names below (CheckBox1, RadioButton1, Static2, ...) are
# pywinauto auto-IDs from the Advanced Installer-generated wizard; they
# are stable as long as the .aip dialog layout doesn't change. If the
# wizard is restructured, expect these selectors to need updates.
from __future__ import annotations

import os
import subprocess
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

import pytest
from conftest import check_files
from conftest import check_fips_provider
from conftest import check_openssl_version
from conftest import check_registry
from conftest import InstallerInfo
from conftest import openssl_product_installed
from conftest import uninstall
from pywinauto import Application
from pywinauto.findwindows import find_windows


Wizard = tuple[Application, Any]


pytestmark = pytest.mark.gui

WIZARD_TIMEOUT = 30  # seconds to wait for any dialog transition
INSTALL_TIMEOUT = 300  # seconds; a full UI install (files + docs + registry) can be slow

# The AI styled wizard is a single top-level window (class MsiDialogCloseClass)
# whose content swaps between "dialogs"; its validation popups are separate
# standard (#32770) windows. We resolve the wizard by this class instead of
# app.top_window() — top_window() binds the handle of whatever is topmost at
# that instant (a tooltip / IME / transient #32770), which then dies and makes
# every later read raise COMError against a stale handle.
MAIN_WINDOW_CLASS = "MsiDialogCloseClass"


@pytest.fixture(autouse=True)
def _quiet_uia_faulthandler():
    """Silence faulthandler for the duration of each GUI test.

    pywinauto's UIA tree-walk raises handled, first-chance SEH exceptions
    (commonly 0x80040155 REGDB_E_IIDNOTREG) while enumerating dialog elements;
    pytest's faulthandler dumps the full C-stack on every one, and because
    control resolution retries until it times out, a single failure buries the
    real result under pages of identical traces. Disabling faulthandler here
    doesn't change pass/fail — it only stops the SEH spam — and is scoped to
    GUI tests, so hard-crash diagnostics stay on for the rest of the suite."""
    import faulthandler

    was_enabled = faulthandler.is_enabled()
    faulthandler.disable()
    try:
        yield
    finally:
        if was_enabled:
            faulthandler.enable()


@pytest.fixture
def wizard(installer: InstallerInfo):
    """Launch the installer GUI; tear down by cancelling cleanly.

    Ensures no prior install exists first — otherwise the wizard opens
    the Modify/Repair/Remove dialog instead of the Welcome screen, and
    the connect() call would never find the expected window.

    Dispatches by installer type: `.exe` is the AI bootstrapper, launched
    directly. `.msi` falls back to `msiexec /i` for legacy artifacts (the
    inner MSI of the .exe-wrapped form is rejected by its LaunchCondition).

    Yields (app, dlg) — the pywinauto Application and the main wizard window
    (resolved by class; see _wait_for_dialog).
    """
    uninstall(installer)
    if installer.path.suffix.lower() == ".exe":
        proc = subprocess.Popen([str(installer.path)])
        # wait for startup
        time.sleep(2)
    else:
        proc = subprocess.Popen(["msiexec.exe", "/i", str(installer.path)])
        # wait for startup
        time.sleep(2)
    try:
        app = Application(backend="uia").connect(
            title_re=f"OpenSSL Library {installer.version} Setup",
            timeout=WIZARD_TIMEOUT,
        )
        dlg = _wait_for_dialog(app)
        yield app, dlg
    finally:
        _safe_cancel(proc)


def _safe_cancel(proc: subprocess.Popen) -> None:
    """Try to close the wizard cleanly, then tear down its whole process tree.

    msiexec spawns child processes for the wizard UI; killing only the launcher
    leaves them running, which causes the next test's connect() to latch onto a
    dying leftover window and raise AppNotConnected mid-test. taskkill /T /F
    reaps the whole tree."""
    with suppress(Exception):
        app = Application(backend="uia").connect(process=proc.pid, timeout=5)
        top = app.top_window()
        top.close()
        # AI shows a "Cancel installation?" confirmation; accept it.
        with suppress(Exception):
            top = app.top_window()
            top["Yes"].click()
        # Final "Setup was interrupted" / Finish dialog.
        with suppress(Exception):
            top = app.top_window()
            top["Finish"].click()
    subprocess.run(
        ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
        check=False,
        capture_output=True,
    )
    with suppress(Exception):
        proc.wait(timeout=10)


def _retry_on_comerror(func: Any, *, what: str, tries: int = 4, delay: float = 1.0) -> Any:
    """Call `func`, retrying on COMError.

    pywinauto's UIA element resolution can raise COMError (0x80040201
    EVENT_E_ALL_SUBSCRIBERS_FAILED / 0x80040155 REGDB_E_IIDNOTREG) right after a
    dialog transition, before the UIA provider for the new dialog has settled —
    and pywinauto's own retry loop does NOT catch COMError, so it propagates
    immediately. Retrying with a short delay recovers the transient case; a
    persistent failure still raises (and the conftest hook then dumps the
    dialog's Win32 window state)."""
    from _ctypes import COMError

    last: BaseException | None = None
    for attempt in range(1, tries + 1):
        try:
            return func()
        except COMError as e:
            last = e
            print(f"[gui-diag] COMError on {what} (attempt {attempt}/{tries}): {e.args}", flush=True)
            time.sleep(delay)
    assert last is not None
    raise last


def _wait_for_dialog(app: Any) -> Any:
    """Return the wizard's main window once it is ready to be queried.

    Resolves by class (MsiDialogCloseClass), NOT app.top_window(): the latter
    binds the handle of whatever is topmost right after a transition — often a
    transient tooltip/IME/#32770 window — which then dies, so subsequent reads
    raise COMError against a stale handle and never recover (retrying the same
    bound spec can't help). A class_name spec re-resolves to the live window on
    every access. We force resolution here (window_text) so any transient
    COMError is caught and retried in this helper rather than in the caller."""

    def _fetch() -> Any:
        dlg = app.window(class_name=MAIN_WINDOW_CLASS)
        dlg.wait("visible ready", timeout=WIZARD_TIMEOUT)
        dlg.window_text()  # force UIA resolution now, where COMError is retried
        return dlg

    return _retry_on_comerror(_fetch, what="main wizard window")


def _find_popup(app: Any, text_fragment: str, timeout: float = 10.0) -> Any:
    """Find a top-level wizard window whose static text contains `text_fragment`.

    AI's validation popups are separate top-level windows with the SAME title
    as the main wizard ("OpenSSL Library X.Y.Z Setup"). `app.top_window()`
    can't disambiguate them, so we enumerate all top-level windows owned by
    the wizard process and match by their displayed static text instead.
    """
    deadline = time.monotonic() + timeout
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            hwnds = find_windows(process=app.process, top_level_only=True, visible_only=True)
        except Exception as e:
            last_err = e
            time.sleep(0.3)
            continue
        for hwnd in hwnds:
            try:
                w = app.window(handle=hwnd)
                if text_fragment.lower() in w.static.window_text().lower():
                    return w
            except Exception as e:
                last_err = e
                continue
        time.sleep(0.3)
    raise AssertionError(f"popup containing {text_fragment!r} not found within {timeout}s (last: {last_err})")


def _click_and_advance(dlg: Any, app: Any, button: str = "Next") -> Any:
    """Click `button` on `dlg`, return the next dialog once it has settled."""
    # best-match lookup tolerates &Next / "Next >" / trailing whitespace etc.
    dlg[button].click()
    # Let the styled window swap its content before we re-resolve controls;
    # the window handle is stable (class-resolved) but its children are not
    # mid-transition.
    time.sleep(1.0)
    return _wait_for_dialog(app)


def _current_static(dlg: Any) -> str:
    """Return the dialog's header label text (Static in AI's layout)."""
    return _retry_on_comerror(lambda: dlg.Static.window_text(), what="dlg.Static.window_text()")


def _wait_until(predicate: Any, *, timeout: float, what: str, poll: float = 2.0) -> None:
    """Poll `predicate` until it returns truthy, or raise on timeout.

    Used to detect UI-install completion from on-disk / registry state, which is
    UIA-independent — so it doesn't rely on the finish-dialog control names."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(poll)
    raise AssertionError(f"timed out after {timeout:.0f}s waiting for {what}")

@pytest.mark.skipif(os.getenv("CI") == "true", reason="GUI tests require interactive session")
def test_wizard_dialog_walk(wizard: Wizard, installer: InstallerInfo) -> None:
    """Walk the wizard from license through the additional-options dialog,
    asserting expected state (defaults, path, the 'at least one option'
    validation popup) at each step.

    This deliberately does NOT install — the fixture cancels on teardown. Real
    installation is verified by test_full_ui_install (via the UI) and, headless
    and deterministic, by the silent-install / lifecycle suites."""
    app, dlg = wizard

    # ---- 1. License agreement ----
    assert _current_static(dlg) == "OpenSSL Library License Agreement", f"unexpected dialog title: {_current_static(dlg)!r}"
    dlg = _click_and_advance(dlg, app, button="IAgree")  # accept license → next dialog

    # ---- 2. Install path ----
    assert _current_static(dlg) == "Choose install location", f"unexpected dialog title: {_current_static(dlg)!r}"
    expected_path = f"C:\\Program Files\\OpenSSL Library\\openssl-{installer.short}\\"
    actual_path = dlg.Edit.get_value()
    assert actual_path == expected_path, f"install path: expected {expected_path!r}, got {actual_path!r}"
    dlg = _click_and_advance(dlg, app)

    # ---- 3. Components ----
    assert _current_static(dlg) == "Options to install"
    # App and SDK should default to on.
    assert dlg.CheckBox1.get_toggle_state() == 1, "Install application should default ON"
    assert dlg.CheckBox2.get_toggle_state() == 1, "Install SDK should default ON"
    assert dlg.CheckBox3.get_toggle_state() == 1, "Adjust path should default ON"

    # Turning both off should be blocked.
    dlg.CheckBox1.click()
    dlg.CheckBox2.click()
    dlg.Next.click()
    popup = _find_popup(app, "at least one option")
    popup.OK.click()
    # wait for window to disappear
    time.sleep(1)
    # Re-enable both.
    dlg.CheckBox1.click()
    dlg.CheckBox2.click()
    dlg = _click_and_advance(dlg, app)

    # ---- 4. Additional options ----
    assert _current_static(dlg) == "Options to install"
    # FIPS off by default. On the OptionsDlg there is a single checkbox, whose
    # pywinauto identifier is "CheckBox" (not "CheckBox2" — that alias only
    # exists on the components page, which has three).
    assert dlg.CheckBox.get_toggle_state() == 0, "FIPS should default OFF"


@pytest.mark.skipif(os.getenv("CI") == "true", reason="GUI tests require interactive session")
def test_fips_requires_app(wizard: Wizard) -> None:
    """On the additional-options page, enabling FIPS without the app must
    produce 'FIPS can't be installed without the openssl app.'."""
    app, dlg = wizard

    # License (accept) → Path → Components
    dlg = _click_and_advance(dlg, app, button="IAgree")  # accept license → path
    dlg = _click_and_advance(dlg, app)  # path → components

    # Components: turn the app off.
    assert _current_static(dlg) == "Options to install"
    dlg.CheckBox1.click()
    dlg = _click_and_advance(dlg, app)

    # Additional options: enable FIPS — should error.
    assert _current_static(dlg) == "Options to install"
    dlg.CheckBox.click()
    dlg.Install.click()
    popup = _find_popup(app, "it is required to generate the FIPS configuration file")
    popup.OK.click()


@pytest.mark.skipif(os.getenv("CI") == "true", reason="GUI tests require interactive session")
def test_fips_module_type_selector_matches_flavor(wizard: Wizard, installer: InstallerInfo) -> None:
    """The FIPS module-type selector (validated 3.1.2 vs current) is offered
    only by the VS installers. Hybrid installers hide it and silently force the
    'current' module (commit 63b0a77): the validated module is VC-WIN64A and
    would drag the VC++ runtime into an otherwise-HybridCRT install.

    The radio group is hidden on the build name alone, independent of the FIPS
    checkbox state, so it's checked here without toggling FIPS."""
    app, dlg = wizard

    # License (accept) → Path → Components → Additional options.
    dlg = _click_and_advance(dlg, app, button="IAgree")  # accept license → path
    dlg = _click_and_advance(dlg, app)  # path → components
    assert _current_static(dlg) == "Options to install"
    dlg = _click_and_advance(dlg, app)  # components → additional options
    assert _current_static(dlg) == "Options to install"

    # The "Validated module (3.1.2)" radio button; present+visible only on VS.
    validated = dlg.child_window(title_re="(?i).*validated.*")
    shown = validated.exists(timeout=5) and validated.is_visible()
    if installer.flavor == "hybrid":
        assert not shown, "hybrid installer must not show the validated FIPS module option (commit 63b0a77)"
    else:
        assert shown, "VS installer must show the validated FIPS module option"


@pytest.mark.skipif(os.getenv("CI") == "true", reason="GUI tests require interactive session")
def test_full_ui_install(wizard: Wizard, installer: InstallerInfo, install_dir: Path, config: dict) -> None:
    """Drive the wizard all the way through a real install — app + SDK + the
    FIPS provider — then verify the installed tree and the FIPS provider
    version. This is the true end-to-end UI path the other GUI tests stop short
    of.

    The FIPS module type follows what each flavor offers in the UI: the hybrid
    installer has only the checkbox (module forced to the current version — the
    validated 3.1.2 option is hidden, commit 63b0a77), while the VS installer
    also shows the validated/current radio, where we pick the validated 3.1.2
    module.

    Completion is detected by polling the registry (openssl_product_installed),
    not the finish dialog, so the test doesn't depend on that dialog's control
    identifiers; the finish click is best-effort and the fixture reaps the
    process on teardown regardless. Assumes no interactive UAC prompt (the
    process runs elevated, same as the silent-install tests). If a prompt does
    appear, this test times out and the conftest hook dumps the wizard's
    window state."""
    app, dlg = wizard
    try:
        dlg = _click_and_advance(dlg, app, button="IAgree")  # license → path
        dlg = _click_and_advance(dlg, app)  # path → components
        assert _current_static(dlg) == "Options to install"
        dlg = _click_and_advance(dlg, app)  # components → additional options
        assert _current_static(dlg) == "Options to install"

        # Enable the FIPS provider (defaults off). Single checkbox on this page.
        if dlg.CheckBox.get_toggle_state() != 1:
            dlg.CheckBox.click()
        assert dlg.CheckBox.get_toggle_state() == 1, "FIPS checkbox did not turn on"

        if installer.flavor == "vs":
            # VS shows the module-type radio (enabled once FIPS is checked);
            # select the validated 3.1.2 module.
            time.sleep(0.5)  # let the radio group enable after checking FIPS
            dlg.child_window(title_re="(?i).*validated.*").click()
            expected_fips = config["fips"]["validated_versions"]
        else:
            # Hybrid: no radio; the module is forced to the current version.
            expected_fips = installer.version

        # On the options page the forward button is labelled "Install".
        dlg.Install.click()
        _wait_until(openssl_product_installed, timeout=INSTALL_TIMEOUT, what="the UI install to finish")

        # Dismiss the completion dialog if we can; teardown reaps the process
        # either way, so a wrong/absent identifier here must not fail the test.
        with suppress(Exception):
            _wait_for_dialog(app)["Finish"].click()

        # Verify what actually landed — the same checks the silent suite runs.
        check_openssl_version(install_dir, installer.version)
        check_files(config, installer, ("app", "sdk", "fips", "fips_sdk"))
        check_registry(config, installer, install_dir)
        check_fips_provider(install_dir, expected_fips)
    finally:
        uninstall(installer)
