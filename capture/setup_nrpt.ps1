# Temporary DNS override for the capture window.
# NRPT rules redirect only these two names to the local resolver, leaving the
# hosts file (and everything Avast self-defense watches) untouched.
param([switch]$Remove)

$namespaces = @("genai-rest.avast.com", "genai-ws.avast.com")

if ($Remove) {
    Get-DnsClientNrptRule | Where-Object { $namespaces -contains $_.Namespace } | ForEach-Object {
        Remove-DnsClientNrptRule -Name $_.Name -Force
        Write-Output ("removed rule " + $_.Name)
    }
    ipconfig /flushdns | Out-Null
    Write-Output "NRPT rules removed"
    exit 0
}

foreach ($ns in $namespaces) {
    $existing = Get-DnsClientNrptRule | Where-Object { $_.Namespace -eq $ns }
    if ($existing) {
        Write-Output ("exists: " + $ns)
        continue
    }
    Add-DnsClientNrptRule -Namespace $ns -NameServers "127.0.0.1" -ErrorAction Stop
    Write-Output ("added: " + $ns)
}

ipconfig /flushdns | Out-Null
Write-Output "=== rules now ==="
Get-DnsClientNrptRule | Where-Object { $namespaces -contains $_.Namespace } |
    Select-Object Namespace, NameServers | Format-Table -AutoSize | Out-String | Write-Output
Write-Output "=== resolution check ==="
Resolve-DnsName genai-rest.avast.com -Type A -ErrorAction SilentlyContinue |
    Select-Object Name, IPAddress | Format-Table -AutoSize | Out-String | Write-Output
