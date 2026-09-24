# Dump the package-structure facts of an MSI database as JSON.
# Consumed by tests/test_package.py through conftest.msi_package_facts().
#
# Reports what a silent install cannot observe: the platform the package
# declares, the bitness of every component, the upgrade detection rows and the
# feature list the SDK dialog hands to UpdateFeaturesInstallStates.
#
# Driven through reflection (InvokeMember), like msi_query.ps1: that is the
# reliable way to reach MSI's parameterized properties from PowerShell.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$MsiPath
)
$ErrorActionPreference = "Stop"

$installer = New-Object -ComObject WindowsInstaller.Installer

function Invoke-Get($obj, [string]$name, [object[]]$argv) {
    return $obj.GetType().InvokeMember($name, "GetProperty", $null, $obj, $argv)
}
function Invoke-Call($obj, [string]$name, [object[]]$argv) {
    return $obj.GetType().InvokeMember($name, "InvokeMethod", $null, $obj, $argv)
}

# OpenDatabase(path, 0): 0 = msiOpenDatabaseModeReadOnly
$database = Invoke-Call $installer "OpenDatabase" @($MsiPath, 0)

function Get-Rows {
    # Rows of a query as arrays of strings. [int] casts matter: COM rejects the
    # PSObject-wrapped integers PowerShell would otherwise pass.
    param($db, [string]$sql)
    $view = Invoke-Call $db "OpenView" @($sql)
    [void](Invoke-Call $view "Execute" $null)
    $rows = New-Object System.Collections.ArrayList
    while ($true) {
        $record = Invoke-Call $view "Fetch" $null
        if ($null -eq $record) { break }
        $count = [int](Invoke-Get $record "FieldCount" $null)
        $values = @()
        for ($i = 1; $i -le $count; $i++) { $values += [string](Invoke-Get $record "StringData" @([int]$i)) }
        [void]$rows.Add($values)
    }
    [void](Invoke-Call $view "Close" $null)
    return $rows   # enumerated into the pipeline one row (string[]) at a time
}

function Test-Table {
    param($db, [string]$name)
    $state = [int](Invoke-Get $db "TablePersistent" @($name))   # a parameterized property
    return ($state -eq 1)   # 1 = MSICONDITION_TRUE, the table exists
}

# Summary information property 7 is the Template: "<platform>;<languages>".
$summary = Invoke-Get $installer "SummaryInformation" @($MsiPath, 0)
$template = [string](Invoke-Get $summary "Property" @([int]7))

# Backticks quote MSI SQL identifiers; doubled (``) in a double-quoted string.
$components = @(Get-Rows $database "SELECT ``Component``, ``Attributes`` FROM ``Component``" |
    ForEach-Object { [ordered]@{ name = $_[0]; attributes = [int]$_[1] } })

$upgrade = @()
if (Test-Table $database "Upgrade") {
    $upgrade = @(Get-Rows $database "SELECT ``ActionProperty``, ``Attributes``, ``VersionMin``, ``VersionMax`` FROM ``Upgrade``" |
        ForEach-Object { [ordered]@{ action_property = $_[0]; attributes = [int]$_[1]; version_min = $_[2]; version_max = $_[3] } })
}

$features = @(Get-Rows $database "SELECT ``Feature`` FROM ``Feature``" | ForEach-Object { $_[0] })

$conditions = @()
if (Test-Table $database "Condition") {
    $conditions = @(Get-Rows $database "SELECT ``Feature_``, ``Level``, ``Condition`` FROM ``Condition``" |
        ForEach-Object { [ordered]@{ feature = $_[0]; level = [int]$_[1]; condition = $_[2] } })
}

$sdkFeatureLists = @(Get-Rows $database "SELECT ``Argument`` FROM ``ControlEvent`` WHERE ``Dialog_``='SDKDlg' AND ``Control_``='Next' AND ``Event``='[CustomActionData]'" |
    ForEach-Object { $_[0] })

[ordered]@{
    template                      = $template
    components                    = $components
    upgrade                       = $upgrade
    features                      = $features
    feature_conditions            = $conditions
    sdk_next_custom_action_data   = $sdkFeatureLists
} | ConvertTo-Json -Compress -Depth 4
