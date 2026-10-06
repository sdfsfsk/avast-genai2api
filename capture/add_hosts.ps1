$hosts = "$env:SystemRoot\System32\drivers\etc\hosts"

# make sure we can write
takeown /f $hosts /a 2>&1 | Out-Null
icacls $hosts /grant "Administrators:F" 2>&1 | Out-Null

$entries = @(
  "",
  "# --- avast-genai2api capture ---",
  "127.0.0.1 genai-rest.avast.com",
  "127.0.0.1 genai-ws.avast.com",
  "127.0.0.1 dns.google",
  "127.0.0.1 cloudflare-dns.com",
  "# --- end capture ---"
)
Add-Content -Path $hosts -Value $entries -Encoding ASCII

Write-Output "=== verification ==="
Select-String -Path $hosts -Pattern "genai|dns\.google|cloudflare-dns" |
    ForEach-Object { Write-Output $_.Line }
