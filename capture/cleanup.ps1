# Full revert of every machine-level change made for the capture.
$ErrorActionPreference = "Continue"
$hosts = "$env:SystemRoot\System32\drivers\etc\hosts"

Write-Output "=== 1. hosts entries ==="
takeown /f $hosts /a 2>&1 | Out-Null
icacls $hosts /grant "Administrators:F" 2>&1 | Out-Null
$keep = Get-Content $hosts | Where-Object {
    $_ -notmatch 'genai-rest\.avast\.com' -and
    $_ -notmatch 'genai-ws\.avast\.com' -and
    $_ -notmatch 'dns\.google' -and
    $_ -notmatch 'cloudflare-dns\.com' -and
    $_ -notmatch 'avast-genai2api'
}
$keep | Set-Content -Path $hosts -Encoding ASCII -ErrorAction SilentlyContinue
Write-Output ("capture entries left: " + (Select-String -Path $hosts -Pattern 'genai|dns\.google|cloudflare-dns|avast-genai2api' | Measure-Object).Count)

Write-Output "=== 2. hosts ownership ==="
icacls $hosts /setowner "BUILTIN\Administrators" 2>&1 | Out-Null
Write-Output ("owner: " + (Get-Acl $hosts).Owner)

Write-Output "=== 3. capture CA ==="
$stores = @(
    @{ Path = "HKCU:\Software\Microsoft\SystemCertificates\Root\Certificates"; Loc = "CurrentUser" },
    @{ Path = "HKLM:\SOFTWARE\Microsoft\SystemCertificates\Root\Certificates"; Loc = "LocalMachine" }
)
foreach ($s in $stores) {
    if (Test-Path $s.Path) {
        Get-ChildItem $s.Path -ErrorAction SilentlyContinue | ForEach-Object {
            $name = $_.PSChildName
            $blob = (Get-ItemProperty -Path $_.PSPath -Name Blob -ErrorAction SilentlyContinue).Blob
            if ($blob) {
                $cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2(,$blob)
                if ($cert.Subject -like "*Avast GenAI Capture CA*") {
                    Remove-Item -Path $_.PSPath -Recurse -Force -ErrorAction SilentlyContinue
                    Write-Output ("removed " + $name + " from " + $s.Loc)
                }
            }
        }
    }
}
Write-Output ("certs left: " + (Get-ChildItem Cert:\LocalMachine\Root, Cert:\CurrentUser\Root -EA SilentlyContinue |
    Where-Object { $_.Subject -like "*Avast GenAI Capture*" } | Measure-Object).Count)

Write-Output "=== 4. NRPT rules ==="
Get-DnsClientNrptRule -ErrorAction SilentlyContinue | Where-Object {
    ($_.Namespace -join ',') -match 'genai-rest|genai-ws'
} | Remove-DnsClientNrptRule -Force
Write-Output ("nrpt rules: " + (Get-DnsClientNrptRule -EA SilentlyContinue | Measure-Object).Count)

Write-Output "=== 5. DNS ==="
ipconfig /flushdns | Out-Null
Write-Output "flushed"
