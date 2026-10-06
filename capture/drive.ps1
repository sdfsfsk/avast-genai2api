param(
    [string]$Action = "click",      # click | type | key
    [int]$X = 0,
    [int]$Y = 0,
    [string]$Text = "",
    [int]$VK = 0x0D,
    [int]$SettleMs = 1200
)

Add-Type -TypeDefinition @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public class K {
  [DllImport("user32.dll")] public static extern IntPtr PostMessage(IntPtr h, uint msg, IntPtr w, IntPtr l);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetPhysicalCursorPos(int X, int Y);
  [DllImport("user32.dll")] public static extern IntPtr WindowFromPhysicalPoint(POINT p);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr h, ref POINT p);
  [DllImport("user32.dll")] public static extern IntPtr GetFocus();
  [DllImport("user32.dll")] public static extern IntPtr GetAncestor(IntPtr h, uint f);
  [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X, Y; }
  public const uint WM_MOUSEMOVE=0x0200, WM_LBUTTONDOWN=0x0201, WM_LBUTTONUP=0x0202;
  public const uint WM_CHAR=0x0102, WM_KEYDOWN=0x0100, WM_KEYUP=0x0101, WM_UNICHAR=0x0109;

  public static void Click(IntPtr h, int x, int y) {
    POINT o = new POINT();
    ClientToScreen(h, ref o);
    int cx = x - o.X, cy = y - o.Y;
    IntPtr lp = (IntPtr)((cy << 16) | (cx & 0xFFFF));
    PostMessage(h, WM_MOUSEMOVE, IntPtr.Zero, lp);
    System.Threading.Thread.Sleep(80);
    PostMessage(h, WM_LBUTTONDOWN, (IntPtr)1, lp);
    System.Threading.Thread.Sleep(80);
    PostMessage(h, WM_LBUTTONUP, IntPtr.Zero, lp);
  }
  public static void Type(IntPtr h, string s) {
    foreach (char c in s) {
      PostMessage(h, WM_CHAR, (IntPtr)c, IntPtr.Zero);
      System.Threading.Thread.Sleep(35);
    }
  }
  public static void Key(IntPtr h, int vk) {
    PostMessage(h, WM_KEYDOWN, (IntPtr)vk, IntPtr.Zero);
    System.Threading.Thread.Sleep(60);
    PostMessage(h, WM_KEYUP, (IntPtr)vk, IntPtr.Zero);
  }
}
"@

$main = (Get-Process AvastUI | Where-Object { $_.MainWindowHandle -ne 0 }).MainWindowHandle
[K]::SetForegroundWindow([IntPtr]$main) | Out-Null
Start-Sleep -Milliseconds 500

if ($Action -eq "click") {
    $pt = New-Object K+POINT
    $pt.X = $X; $pt.Y = $Y
    [K]::SetPhysicalCursorPos($X, $Y) | Out-Null
    Start-Sleep -Milliseconds 400
    $hit = [K]::WindowFromPhysicalPoint($pt)
    Write-Output ("click target hwnd=$hit at ($X,$Y)")
    [K]::Click($hit, $X, $Y)
    Write-Output "click posted"
}
elseif ($Action -eq "type") {
    $pt = New-Object K+POINT
    $pt.X = $X; $pt.Y = $Y
    $hit = [K]::WindowFromPhysicalPoint($pt)
    [K]::Click($hit, $X, $Y)
    Start-Sleep -Milliseconds $SettleMs
    [K]::Type($hit, $Text)
    Write-Output ("typed: " + $Text)
    Start-Sleep -Milliseconds 400
    [K]::Key($hit, $VK)
    Write-Output "key sent"
}
elseif ($Action -eq "key") {
    $pt = New-Object K+POINT
    $pt.X = $X; $pt.Y = $Y
    $hit = [K]::WindowFromPhysicalPoint($pt)
    [K]::Key($hit, $VK)
    Write-Output "key sent"
}
