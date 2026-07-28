param(
    [Parameter(Mandatory = $true)]
    [string]$OutputRoot,

    [string]$Ffmpeg = "ffmpeg.exe",

    [string]$Ffprobe = "ffprobe.exe"
)

$ErrorActionPreference = "Stop"

$resolvedOutput = [System.IO.Path]::GetFullPath($OutputRoot)
New-Item -ItemType Directory -Force -Path $resolvedOutput | Out-Null

$srtPath = Join-Path $resolvedOutput "phase0-external.srt"
$assPath = Join-Path $resolvedOutput "phase0-embedded.ass"
$sdrPath = Join-Path $resolvedOutput "phase0-sdr-h264.mkv"
$hdrPath = Join-Path $resolvedOutput "phase0-hdr-hevc10.mkv"
$pgsPath = Join-Path $resolvedOutput "phase0-pgs-sample.mkv"

@"
1
00:00:00,500 --> 00:00:03,500
Cinema Paradiso external SRT proof

2
00:00:04,000 --> 00:00:07,000
Seeking and subtitle timing remain file-specific
"@ | Set-Content -LiteralPath $srtPath -Encoding utf8

@"
[Script Info]
Title: Cinema Paradiso Phase 0
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 720

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,42,&H00F2D7A0,&H000000FF,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,2,1,2,20,20,38,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.50,0:00:04.00,Default,,0,0,0,,Cinema Paradiso embedded ASS proof
Dialogue: 0,0:00:04.50,0:00:08.00,Default,,0,0,0,,Audio and subtitle tracks can be switched
"@ | Set-Content -LiteralPath $assPath -Encoding utf8

& $Ffmpeg -hide_banner -loglevel error -y `
    -f lavfi -i "testsrc2=size=1280x720:rate=30:duration=10" `
    -f lavfi -i "sine=frequency=440:sample_rate=48000:duration=10" `
    -f lavfi -i "sine=frequency=880:sample_rate=48000:duration=10" `
    -i $srtPath `
    -i $assPath `
    -map 0:v:0 -map 1:a:0 -map 2:a:0 -map 3:0 -map 4:0 `
    -c:v libx264 -preset veryfast -crf 22 -pix_fmt yuv420p `
    -c:a:0 aac -b:a:0 160k `
    -c:a:1 ac3 -b:a:1 384k `
    -c:s:0 srt -c:s:1 ass `
    -metadata:s:a:0 language=eng -metadata:s:a:0 title="AAC English" `
    -metadata:s:a:1 language=fra -metadata:s:a:1 title="AC-3 French" `
    -metadata:s:s:0 language=eng -metadata:s:s:0 title="Embedded SRT" `
    -metadata:s:s:1 language=spa -metadata:s:s:1 title="Embedded ASS" `
    -t 10 $sdrPath
if ($LASTEXITCODE -ne 0) {
    throw "Failed to generate the SDR fixture."
}

$x265Parameters = "hdr-opt=1:repeat-headers=1:colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc:master-display=G(13250,34500)B(7500,3000)R(34000,16000)WP(15635,16450)L(10000000,1):max-cll=1000,400"
& $Ffmpeg -hide_banner -loglevel error -y `
    -f lavfi -i "testsrc2=size=640x360:rate=24:duration=8" `
    -f lavfi -i "sine=frequency=330:sample_rate=48000:duration=8" `
    -f lavfi -i "sine=frequency=660:sample_rate=48000:duration=8" `
    -map 0:v:0 -map 1:a:0 -map 2:a:0 `
    -c:v libx265 -preset ultrafast -crf 28 -pix_fmt yuv420p10le `
    -x265-params $x265Parameters `
    -color_primaries bt2020 -color_trc smpte2084 -colorspace bt2020nc `
    -strict experimental `
    -c:a:0 dca -b:a:0 768k `
    -c:a:1 truehd `
    -metadata:s:a:0 language=jpn -metadata:s:a:0 title="DTS Japanese" `
    -metadata:s:a:1 language=eng -metadata:s:a:1 title="TrueHD English" `
    -t 8 $hdrPath
if ($LASTEXITCODE -ne 0) {
    throw "Failed to generate the HEVC/HDR fixture."
}

$pgsUrl = "https://samples.ffmpeg.org/sub/PGS/supsample.mkv"
Invoke-WebRequest -Uri $pgsUrl -OutFile $pgsPath

$fixtures = @(
    @{ id = "sdr-h264"; path = $sdrPath; source = "generated" },
    @{ id = "hdr-hevc10"; path = $hdrPath; source = "generated" },
    @{ id = "pgs"; path = $pgsPath; source = $pgsUrl },
    @{ id = "external-srt"; path = $srtPath; source = "generated" },
    @{ id = "embedded-ass-source"; path = $assPath; source = "generated" }
)

$manifestFixtures = foreach ($fixture in $fixtures) {
    $item = Get-Item -LiteralPath $fixture.path
    $probe = $null
    if ($item.Extension -in ".mkv", ".mp4", ".m2ts", ".ts") {
        $probeJson = & $Ffprobe -v error `
            -show_entries "stream=index,codec_name,codec_type,pix_fmt,color_space,color_transfer,color_primaries:stream_tags=language,title" `
            -of json $item.FullName
        if ($LASTEXITCODE -ne 0) {
            throw "ffprobe failed for fixture $($fixture.id)."
        }
        $probe = ($probeJson -join [Environment]::NewLine) | ConvertFrom-Json
    }
    [ordered]@{
        id = $fixture.id
        file = $item.Name
        source = $fixture.source
        size = $item.Length
        sha256 = (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash
        probe = $probe
    }
}

$manifest = [ordered]@{
    schema = "cp-player-phase0-fixtures-v1"
    generated_utc = [DateTime]::UtcNow.ToString("o")
    fixtures = $manifestFixtures
}
$manifest | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $resolvedOutput "fixtures.json") -Encoding utf8

Write-Output (Join-Path $resolvedOutput "fixtures.json")
