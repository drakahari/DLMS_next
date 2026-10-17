param([string]$BuildName = 'webview2-host-candidate-01', [switch]$AiRaceProbe)
$ErrorActionPreference = 'Stop'
if ($BuildName -notmatch '^webview2-host-candidate-[0-9]{2}$') { throw 'Use a separate bounded host build name' }
$projectRoot = Split-Path $PSScriptRoot -Parent
$inputRoot = Join-Path $projectRoot '.gate1/windows-native/webview2-inputs-01'
$payload = Join-Path $projectRoot ".gate1/windows-native/$BuildName/payload"
$expectedHash = '56f7f4b8bf9aee4b8efefbbdd4f67d5f74ebd1b100ed0806da71bf76af481aa9'
if ((Get-FileHash "$inputRoot/webview2.nupkg" -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedHash) { throw 'SDK checksum mismatch' }
$archive = [IO.Compression.ZipFile]::OpenRead("$inputRoot/webview2.nupkg")
try {
    foreach ($member in @('lib/net462/Microsoft.Web.WebView2.Core.dll','lib/net462/Microsoft.Web.WebView2.WinForms.dll','runtimes/win-x64/native/WebView2Loader.dll','LICENSE.txt')) {
        $stream = $archive.GetEntry($member).Open()
        try { $expected = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($stream)) } finally { $stream.Dispose() }
        if ((Get-FileHash "$inputRoot/sdk/$member" -Algorithm SHA256).Hash -ne $expected) { throw "Extracted SDK input mismatch: $member" }
    }
} finally { $archive.Dispose() }
$compiler = 'C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe'
if (!(Test-Path $compiler)) { throw 'Missing .NET Framework compiler; ask before installing prerequisites' }
if (Test-Path $payload) { throw 'Preserve existing payload; choose a separate build name' }
New-Item -ItemType Directory -Path $payload | Out-Null
Copy-Item "$inputRoot/sdk/lib/net462/Microsoft.Web.WebView2.Core.dll" $payload
Copy-Item "$inputRoot/sdk/lib/net462/Microsoft.Web.WebView2.WinForms.dll" $payload
Copy-Item "$inputRoot/sdk/runtimes/win-x64/native/WebView2Loader.dll" $payload
Copy-Item "$inputRoot/sdk/LICENSE.txt" $payload
New-Item -ItemType Directory -Path "$payload/extension" | Out-Null
Copy-Item "$PSScriptRoot/extension/manifest.json" "$payload/extension/manifest.json"
Copy-Item "$PSScriptRoot/extension/rules.json" "$payload/extension/rules.json"
$hostSource = Join-Path $projectRoot 'windows_webview2/Host.cs'
$surfaceSource = Join-Path $projectRoot 'windows_webview2/BrowserSurface.cs'
$metadataSource = Join-Path $projectRoot 'windows_webview2/FetchMetadata.cs'
$handoffSource = Join-Path $projectRoot 'windows_webview2/BrowserHandoff.cs'
$aiSource = Join-Path $projectRoot 'windows_webview2/AiActions.cs'
$aiScripts = Join-Path $projectRoot 'windows_webview2/AiScripts.cs'
$aiLease = Join-Path $projectRoot 'windows_webview2/AiActionLease.cs'
$requestProtocol = Join-Path $projectRoot 'windows_webview2/RequestProtocol.cs'
$defines = @()
if ($AiRaceProbe) {
    $defines = @('/define:DLMS_AI_TEST')
    'INSTRUMENTED source-host timing probe; never package' | Set-Content "$payload/../AI-RACE-PROBE"
}
& $compiler /nologo /target:winexe /platform:x64 /optimize+ @defines "/out:$payload/DLMS-WebView2-Host.exe" /reference:System.dll /reference:System.Core.dll /reference:System.Drawing.dll /reference:System.Windows.Forms.dll /reference:System.Web.Extensions.dll "/reference:$payload/Microsoft.Web.WebView2.Core.dll" $hostSource $surfaceSource $metadataSource $handoffSource $aiSource $aiScripts $aiLease $requestProtocol
if ($LASTEXITCODE -ne 0) { throw 'Host compilation failed; retain failed payload' }
Get-ChildItem $payload -File -Recurse | Get-FileHash -Algorithm SHA256 | Select-Object Path,Hash | ConvertTo-Json | Set-Content "$payload/../SHA256.json"
