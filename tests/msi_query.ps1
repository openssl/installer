# Dump the FIPS-related UI facts from an installer's MSI database as JSON.
# Consumed by tests/test_silent_install.py::test_fips_validated_option_disabled_in_hybrid.
#
# Pass -MsiPath for a bare .msi, or -ProductCode for an installed product whose
# inner MSI Windows Installer has cached (the .exe-bootstrapper case).
#
# The WindowsInstaller.Installer COM object is driven through reflection
# (InvokeMember) rather than direct member access: that's the reliable way to
# reach MSI's parameterized StringData property from an automation client
# (win32com's dynamic dispatch invokes it as a method and fails).
[CmdletBinding()]
param(
    [string]$MsiPath = "",
    [string]$ProductCode = ""
)
$ErrorActionPreference = "Stop"

$installer = New-Object -ComObject WindowsInstaller.Installer

if ($ProductCode -ne "") {
    $MsiPath = $installer.GetType().InvokeMember(
        "ProductInfo", "GetProperty", $null, $installer, @($ProductCode, "LocalPackage"))
}
if ($MsiPath -eq "") { throw "either -MsiPath or -ProductCode is required" }

# OpenDatabase(path, 0): 0 = msiOpenDatabaseModeReadOnly
$database = $installer.GetType().InvokeMember(
    "OpenDatabase", "InvokeMethod", $null, $installer, @($MsiPath, 0))

function Get-One {
    # First column of the first row of a single-column query, or $null.
    param($db, [string]$sql)
    $view = $db.GetType().InvokeMember("OpenView", "InvokeMethod", $null, $db, @($sql))
    [void]$view.GetType().InvokeMember("Execute", "InvokeMethod", $null, $view, $null)
    $record = $view.GetType().InvokeMember("Fetch", "InvokeMethod", $null, $view, $null)
    $value = $null
    if ($null -ne $record) {
        $value = [string]$record.GetType().InvokeMember("StringData", "GetProperty", $null, $record, @(1))
    }
    [void]$view.GetType().InvokeMember("Close", "InvokeMethod", $null, $view, $null)
    return $value
}

# Backticks quote MSI SQL identifiers; doubled (``) inside a double-quoted
# PowerShell string yields a single literal backtick.
$facts = [ordered]@{
    build_name              = Get-One $database "SELECT ``Value`` FROM ``Property`` WHERE ``Property``='AI_BUILD_NAME'"
    default_type            = Get-One $database "SELECT ``Value`` FROM ``Property`` WHERE ``Property``='INSTALL_FIPS_TYPE'"
    hide_condition          = Get-One $database "SELECT ``Condition`` FROM ``ControlCondition`` WHERE ``Dialog_``='OptionsDlg' AND ``Control_``='RadioButtonGroup_1' AND ``Action``='Hide'"
    force_current_condition = Get-One $database "SELECT ``Condition`` FROM ``ControlEvent`` WHERE ``Dialog_``='OptionsDlg' AND ``Control_``='OptionsDlgDialogInitializer'"
}

$facts | ConvertTo-Json -Compress
