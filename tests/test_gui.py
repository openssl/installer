# GUI tests: walk the installer wizard via pywinauto (UIA backend).
#
# Hardened port of windows-installer/test_gui.py. The control names below
# (CheckBox1, RadioButton1, Static2, ...) are pywinauto auto-IDs from the
# Advanced Installer-generated wizard; they are stable as long as the .aip
# dialog layout doesn't change. If the wizard is restructured, expect these
# selectors to need updates.
from __future__ import annotations

import subprocess
import time
from contextlib import suppress
from typing import Any

import pytest
from conftest import InstallerInfo
from conftest import uninstall
from pywinauto import Application
from pywinauto.findwindows import find_windows


Wizard = tuple[Application, Any]


pytestmark = pytest.mark.gui

WIZARD_TIMEOUT = 30  # seconds to wait for any dialog transition


@pytest.fixture
def wizard(installer: InstallerInfo):
    """Launch the installer GUI; tear down by cancelling cleanly.

    Ensures no prior install exists first — otherwise the wizard opens
    the Modify/Repair/Remove dialog instead of the Welcome screen, and
    the connect() call would never find the expected window.

    Dispatches by installer type: `.exe` is the AI bootstrapper, launched
    directly. `.msi` falls back to `msiexec /i` for legacy artifacts (the
    inner MSI of the .exe-wrapped form is rejected by its LaunchCondition).

    Yields (app, dlg) — the pywinauto Application and current top window.
    """
    uninstall(installer)
    if installer.path.suffix.lower() == ".exe":
        proc = subprocess.Popen([str(installer.path)])
    else:
        proc = subprocess.Popen(["msiexec.exe", "/i", str(installer.path)])
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


def _wait_for_dialog(app: Any) -> Any:
    """Return the current top window once it is ready to be queried.

    UIA event subscribers can transiently fail (COMError 0x80040201) when a
    property is read right after a dialog transition, before the UIA tree has
    settled. `wait('visible ready')` retries internally and only returns once
    the window's visible/enabled state is stable.
    """
    dlg = app.top_window()
    dlg.wait("visible ready", timeout=WIZARD_TIMEOUT)
    return dlg


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
    return _wait_for_dialog(app)


def _current_static(dlg: Any) -> str:
    """Return the dialog's header label text (Static2 in AI's layout)."""
    return dlg.Static2.window_text()


def test_welcome_to_install_full_flow(wizard: Wizard, installer: InstallerInfo) -> None:
    """Walk the wizard from welcome through the additional-options dialog,
    asserting expected state at each step. The fixture cancels on teardown."""
    app, dlg = wizard

    # ---- 1. Welcome dialog ----
    dlg = _click_and_advance(dlg, app)

    # ---- 2. License agreement ----
    assert _current_static(dlg) == "End-User License Agreement", f"unexpected dialog title: {_current_static(dlg)!r}"
    assert not dlg.Next.is_enabled(), "Next should be disabled before accepting the license"
    dlg.RadioButton1.click()  # Accept
    assert dlg.Next.is_enabled(), "Next should be enabled after accepting the license"
    dlg = _click_and_advance(dlg, app)

    # ---- 3. Install path ----
    assert _current_static(dlg) == "Select Installation Folder", f"unexpected dialog title: {_current_static(dlg)!r}"
    expected_path = f"C:\\Program Files\\OpenSSL Library\\openssl-{installer.short}\\"
    actual_path = dlg.ComboBox.selected_text()
    assert actual_path == expected_path, f"install path: expected {expected_path!r}, got {actual_path!r}"
    dlg = _click_and_advance(dlg, app)

    # ---- 4. Components ----
    assert _current_static(dlg) == "Components to install"
    # App and SDK should default to on.
    assert dlg.CheckBox1.get_toggle_state() == 1, "Install application should default ON"
    assert dlg.CheckBox2.get_toggle_state() == 1, "Install SDK should default ON"

    # Turning both off should be blocked.
    dlg.CheckBox1.click()
    dlg.CheckBox2.click()
    dlg.Next.click()
    popup = _find_popup(app, "at least one option")
    popup.OK.click()
    # Re-enable both.
    dlg.CheckBox1.click()
    dlg.CheckBox2.click()
    dlg = _click_and_advance(dlg, app)

    # ---- 5. Additional options ----
    assert _current_static(dlg) == "Configuring additional Options"
    # FIPS off by default; its sub-options should not be enabled.
    assert dlg.CheckBox2.get_toggle_state() == 0, "FIPS should default OFF"


def test_fips_requires_app(wizard: Wizard) -> None:
    """On the additional-options page, enabling FIPS without the app must
    produce 'FIPS can't be installed without the openssl app.'."""
    app, dlg = wizard

    # Welcome → License (accept) → Path → Components
    dlg = _click_and_advance(dlg, app)
    dlg.RadioButton1.click()
    dlg = _click_and_advance(dlg, app)
    dlg = _click_and_advance(dlg, app)

    # Components: turn the app off.
    assert _current_static(dlg) == "Components to install"
    dlg.CheckBox1.click()
    dlg = _click_and_advance(dlg, app)

    # Additional options: enable FIPS — should error.
    assert _current_static(dlg) == "Configuring additional Options"
    dlg.CheckBox2.click()
    dlg.Next.click()
    popup = _find_popup(app, "openssl app")
    popup.OK.click()
