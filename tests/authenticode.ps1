[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$FilePath
)
$ErrorActionPreference = 'Stop'

$s = Get-AuthenticodeSignature -FilePath $FilePath
$obj = [ordered]@{
    Status          = $s.Status.ToString()
    StatusMessage   = $s.StatusMessage
    SignerCert      = if ($s.SignerCertificate) {
        @{
            Subject    = $s.SignerCertificate.Subject
            Issuer     = $s.SignerCertificate.Issuer
            Thumbprint = $s.SignerCertificate.Thumbprint
            NotAfter   = $s.SignerCertificate.NotAfter.ToString('o')
        }
    } else { $null }
    TimeStamperCert = if ($s.TimeStamperCertificate) {
        @{
            Subject  = $s.TimeStamperCertificate.Subject
            NotAfter = $s.TimeStamperCertificate.NotAfter.ToString('o')
        }
    } else { $null }
}
$obj | ConvertTo-Json -Depth 4
