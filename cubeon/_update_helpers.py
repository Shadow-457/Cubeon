"""Fixed native helper scripts. All variable input is passed as data files.

These strings are imported into PyInstaller's archive; there is no external
script/data-file packaging dependency. Neither helper kills the old launcher.
"""

LINUX_HELPER = r'''#!/bin/bash
set -Eeuo pipefail
umask 077
job=$1
[[ -d "$job" && ! -L "$job" && -f "$job/job.bin" && ! -L "$job/job.bin" ]] || exit 1
mapfile -d '' -t fields < "$job/job.bin"
[[ ${#fields[@]} -ge 15 ]] || exit 1
target=${fields[0]}; download=${fields[1]}; sha=${fields[2]}; size=${fields[3]}
old_sha=${fields[4]}; old_id=${fields[5]}; dir_id=${fields[6]}; mode=${fields[7]}
parent=${fields[8]}; ticks=${fields[9]}; parent_wait=${fields[10]}; health_wait=${fields[11]}
token=${fields[12]}; lock=${fields[13]}; failed=${fields[14]}
args=("${fields[@]:15}")
[[ $sha =~ ^[a-f0-9]{64}$ && $old_sha =~ ^[a-f0-9]{64}$ && $token =~ ^[a-f0-9]{32}$ ]] || exit 1
[[ $size =~ ^[0-9]+$ && $parent =~ ^[0-9]+$ && $ticks =~ ^[0-9]+$ ]] || exit 1
[[ $mode =~ ^[0-7]{3,4}$ && $parent_wait =~ ^[0-9]+$ && $health_wait =~ ^[0-9]+$ ]] || exit 1
[[ $target = /* && $download = /* && $job = /* && $lock = /* && $failed = /* ]] || exit 1
[[ ! -L "$lock" ]] || exit 1
exec 9>"$lock"
flock -n 9 || exit 75
directory=${target%/*}
stage="$target.cubeon-update-$token.new"
backup="$target.cubeon-previous"
backup_stage="$target.cubeon-update-$token.old"
recovery="$target.cubeon-update-$token.recovery"
published=0
committed=0
child=''
child_ticks=''
outcome=failed

regular() { [[ -f "$1" && ! -L "$1" && $(stat -c %u -- "$1") = "$UID" ]]; }
digest() { local value; value=$(sha256sum < "$1"); printf '%s' "${value:0:64}"; }
signal_matches() { [[ -f "$1" && ! -L "$1" && $(<"$1") = "$token" ]]; }
directory_ok() {
    [[ ! -L "$directory" && $(readlink -f -- "$directory") = "$directory" &&
       $(stat -c '%d:%i' -- "$directory") = "$dir_id" && $(stat -c %u -- "$directory") = "$UID" ]]
}
old_ok() {
    directory_ok && regular "$target" && [[ $(readlink -f -- "$target") = "$target" &&
        $(stat -c '%d:%i:%s' -- "$target") = "$old_id" && $(digest "$target") = "$old_sha" ]]
}
new_ok() {
    regular "$1" && [[ $(stat -c %s -- "$1") = "$size" && $(digest "$1") = "$sha" ]]
}
parent_alive() {
    [[ -r /proc/$parent/stat ]] || return 1
    local line; line=$(<"/proc/$parent/stat") || return 1
    line=${line##*) }
    local parts; read -r -a parts <<< "$line"
    [[ ${parts[0]:-Z} != Z && ${parts[19]:-} = "$ticks" ]]
}
launch() {
    # A new session confines health-check termination to this launch and its
    # descendants. Close fd 9 in the child, or it would hold our flock forever.
    (exec 9>&-; exec setsid -- "$target" "${args[@]}") </dev/null >/dev/null 2>&1 &
    child=$!
    child_ticks=''
    if [[ -r /proc/$child/stat ]]; then
        local line; line=$(<"/proc/$child/stat")
        line=${line##*) }
        local parts; read -r -a parts <<< "$line"
        child_ticks=${parts[19]:-}
    fi
    printf '%s:%s' "$child" "$child_ticks" > "$job/launch.identity"
}
same_child() {
    [[ -n $child_ticks && -r /proc/$child/stat ]] || return 1
    local line; line=$(<"/proc/$child/stat") || return 1
    line=${line##*) }
    local parts; read -r -a parts <<< "$line"
    [[ ${parts[19]:-} = "$child_ticks" ]]
}
cleanup() {
    local code=$?
    trap - EXIT ERR
    set +e
    if [[ $published = 1 && $outcome != installed ]]; then
        if [[ -n $child && -n $child_ticks ]]; then
            # An extant group with no leader still contains our descendants;
            # an extant leader must match its original start ticks. Never kill
            # a new process/group that happened to reuse this PID.
            if same_child || [[ ! -e /proc/$child ]]; then kill -TERM -- "-$child" 2>/dev/null; fi
            sleep 1
            if same_child || [[ ! -e /proc/$child ]]; then kill -KILL -- "-$child" 2>/dev/null; fi
            wait "$child" 2>/dev/null
        fi
        # Do not overwrite a third-party/manual replacement that raced us.
        if directory_ok && new_ok "$target" && regular "$backup" && [[ $(digest "$backup") = "$old_sha" ]]; then
            if (set -C; : > "$recovery") && cp --reflink=auto -- "$backup" "$recovery" &&
               chmod "$mode" -- "$recovery" && sync -f "$recovery" &&
               [[ $(digest "$recovery") = "$old_sha" ]] && mv -Tf -- "$recovery" "$target" && sync -f "$directory"; then
                outcome=rolled-back
                unset CUBEON_UPDATE_JOB CUBEON_UPDATE_TOKEN
                launch
                printf 'Update startup failed; restored the previous AppImage.\n' >&2
            else
                printf 'Automatic restore failed; recovery copy is at %s\n' "$backup" >&2
            fi
        else
            printf 'Target changed; kept the recovery copy at %s\n' "$backup" >&2
        fi
    fi
    if [[ $committed = 1 && $outcome != installed ]]; then
        [[ ! -L "$failed" ]] && printf '%s\n' "$outcome" > "$failed"
        sync -f "$failed" 2>/dev/null
    fi
    printf '%s\n' "$outcome" > "$job/result"
    for temporary in "$stage" "$backup_stage" "$recovery"; do
        regular "$temporary" && rm -f -- "$temporary"
    done
    exec 9>&-
    exit "$code"
}
trap cleanup EXIT
trap 'printf "Update helper stopped at line %s.\n" "$LINENO" >&2' ERR

old_ok || { printf 'Installed AppImage changed or is redirected.\n' >&2; exit 1; }
new_ok "$download" || { printf 'Download size or SHA-256 failed.\n' >&2; exit 1; }
header=$(od -An -tx1 -N20 -- "$download" | tr -d ' \n')
[[ ${header:0:12} = 7f454c460201 && ${header:16:6} = 414902 && ${header:36:4} = 3e00 ]] || exit 1
if [[ -e "$backup" || -L "$backup" ]]; then regular "$backup" || exit 1; fi
parent_alive || { outcome=cancelled; exit 0; }
# Unique exclusive stage slots; complete copies are flushed before any rename.
(set -C; : > "$stage")
cp --reflink=auto -- "$download" "$stage"
chmod "$mode" -- "$stage"
sync -f "$stage"
new_ok "$stage" || exit 1
(set -C; : > "$backup_stage")
cp --reflink=auto --preserve=mode -- "$target" "$backup_stage"
sync -f "$backup_stage"
[[ $(digest "$backup_stage") = "$old_sha" ]] || exit 1
printf '%s' "$token" > "$job/ready.tmp"
mv -Tf -- "$job/ready.tmp" "$job/ready"

deadline=$((SECONDS + parent_wait))
while ! signal_matches "$job/go"; do
    if signal_matches "$job/cancel" || ! parent_alive || (( SECONDS >= deadline )); then
        outcome=cancelled; exit 0
    fi
    sleep 0.2
done
while parent_alive; do
    if signal_matches "$job/cancel"; then outcome=cancelled; exit 0; fi
    if (( SECONDS >= deadline )); then printf 'Cubeon did not exit; no replacement made.\n' >&2; exit 1; fi
    sleep 0.2
done
if signal_matches "$job/cancel"; then outcome=cancelled; exit 0; fi
committed=1
old_ok && new_ok "$stage" || exit 1
# Publishing the backup first leaves an intact recovery file even after power
# loss. The live image is NEVER opened for writing or removed before the rename.
if [[ -e "$backup" || -L "$backup" ]]; then regular "$backup" || exit 1; fi
mv -Tf -- "$backup_stage" "$backup"
sync -f "$directory"
mv -Tf -- "$stage" "$target"
published=1
sync -f "$directory"
export CUBEON_APPIMAGE_PATH="$target"
export CUBEON_UPDATE_JOB="$job/job.json"
export CUBEON_UPDATE_TOKEN="$token"
export CUBEON_RELAUNCH=1
launch
deadline=$((SECONDS + health_wait))
while ! signal_matches "$job/health.ok"; do
    if ! same_child || (( SECONDS >= deadline )); then
        printf 'The replacement did not acknowledge its first UI paint.\n' >&2
        exit 1
    fi
    sleep 0.2
done
outcome=installed
[[ ! -L "$failed" ]] && rm -f -- "$failed"
exit 0
'''


WINDOWS_HELPER = r'''param([Parameter(Mandatory=$true)][string]$JobPath)
$ErrorActionPreference = 'Stop'
$lock = $null
$installerStream = $null
$committed = $false
$outcome = 'failed'
$exitCode = 1
$restartRequested = $false
$showUi = $false
$job = $null
$form = $null
$progress = $null
$statusLabel = $null
$detailLabel = $null
$actionButton = $null
$uiState = @{ AllowClose = $false; Mode = 'busy'; Action = $null }
$directory = [IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($JobPath))
function Regular([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force
    if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'An update file is redirected or is not a regular file.'
    }
}
function Directory-Safe([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force
    if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'An update directory is redirected.'
    }
}
function Hash-Stream($Stream) {
    $Stream.Position = 0
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($algorithm.ComputeHash($Stream))).Replace('-', '').ToLowerInvariant() }
    finally { $algorithm.Dispose(); $Stream.Position = 0 }
}
function Hash-File([string]$Path) {
    Regular $Path
    $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    try { return Hash-Stream $stream } finally { $stream.Dispose() }
}
function Signal-Matches([string]$Name) {
    $path = Join-Path $directory $Name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $false }
    Regular $path
    return ([IO.File]::ReadAllText($path) -ceq $job.token)
}
function Registered-Target {
    $value = (Get-ItemProperty -LiteralPath 'HKCU:\Software\Cubeon' -Name InstallDir).InstallDir
    $registered = [IO.Path]::GetFullPath($value).TrimEnd('\')
    if (-not [String]::Equals($registered, $targetDir, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'The registered Cubeon installation changed.'
    }
    Directory-Safe $targetDir
    Directory-Safe (Join-Path $targetDir '_internal')
    Regular (Join-Path $targetDir 'Uninstall Cubeon.exe')
    Regular $job.target
    if ((Hash-File $job.target) -cne $job.old_sha256) { throw 'The installed Cubeon executable changed.' }
}
function Other-Cubeon {
    foreach ($candidate in @(Get-Process -Name Cubeon -ErrorAction SilentlyContinue)) {
        if ($candidate.Id -eq $job.parent_pid) { continue }
        try { $path = $candidate.MainModule.FileName }
        catch { throw 'Cannot verify another Cubeon process. Installation deferred.' }
        if ([String]::Equals([IO.Path]::GetFullPath($path), $job.target, [StringComparison]::OrdinalIgnoreCase)) {
            throw 'Another copy of this Cubeon installation is still running.'
        }
    }
}
function Pump-Ui {
    if ($script:form) { [Windows.Forms.Application]::DoEvents() }
}
function Initialize-Ui {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    [Windows.Forms.Application]::EnableVisualStyles()
    $script:form = New-Object Windows.Forms.Form
    $script:form.Text = 'Cubeon Updater'
    $script:form.StartPosition = 'CenterScreen'
    $script:form.FormBorderStyle = 'FixedDialog'
    $script:form.MaximizeBox = $false
    $script:form.MinimizeBox = $true
    $script:form.ControlBox = $false
    $script:form.ClientSize = New-Object Drawing.Size(500, 286)
    $script:form.BackColor = [Drawing.Color]::FromArgb(18, 22, 20)
    try { $script:form.Icon = [Drawing.Icon]::ExtractAssociatedIcon($job.target) } catch {}

    $brand = New-Object Windows.Forms.Label
    $brand.Text = 'CUBEON UPDATER'
    $brand.Location = New-Object Drawing.Point(30, 25)
    $brand.Size = New-Object Drawing.Size(440, 28)
    $brand.Font = New-Object Drawing.Font('Segoe UI', 15, [Drawing.FontStyle]::Bold)
    $brand.ForeColor = [Drawing.Color]::FromArgb(88, 220, 145)

    $version = New-Object Windows.Forms.Label
    $version.Text = 'Updating to version ' + $job.version
    $version.Location = New-Object Drawing.Point(32, 58)
    $version.Size = New-Object Drawing.Size(436, 22)
    $version.Font = New-Object Drawing.Font('Segoe UI', 9)
    $version.ForeColor = [Drawing.Color]::FromArgb(160, 171, 165)

    $script:statusLabel = New-Object Windows.Forms.Label
    $script:statusLabel.Location = New-Object Drawing.Point(32, 105)
    $script:statusLabel.Size = New-Object Drawing.Size(436, 28)
    $script:statusLabel.Font = New-Object Drawing.Font('Segoe UI', 12, [Drawing.FontStyle]::Bold)
    $script:statusLabel.ForeColor = [Drawing.Color]::White

    $script:detailLabel = New-Object Windows.Forms.Label
    $script:detailLabel.Location = New-Object Drawing.Point(32, 139)
    $script:detailLabel.Size = New-Object Drawing.Size(436, 42)
    $script:detailLabel.Font = New-Object Drawing.Font('Segoe UI', 9)
    $script:detailLabel.ForeColor = [Drawing.Color]::FromArgb(178, 187, 182)

    $script:progress = New-Object Windows.Forms.ProgressBar
    $script:progress.Location = New-Object Drawing.Point(32, 192)
    $script:progress.Size = New-Object Drawing.Size(436, 10)
    $script:progress.Style = 'Marquee'
    $script:progress.MarqueeAnimationSpeed = 24

    $script:actionButton = New-Object Windows.Forms.Button
    $script:actionButton.Location = New-Object Drawing.Point(318, 225)
    $script:actionButton.Size = New-Object Drawing.Size(150, 36)
    $script:actionButton.FlatStyle = 'Flat'
    $script:actionButton.FlatAppearance.BorderSize = 0
    $script:actionButton.BackColor = [Drawing.Color]::FromArgb(88, 220, 145)
    $script:actionButton.ForeColor = [Drawing.Color]::FromArgb(15, 25, 20)
    $script:actionButton.Font = New-Object Drawing.Font('Segoe UI', 9, [Drawing.FontStyle]::Bold)
    $script:actionButton.Visible = $false
    $script:actionButton.Add_Click({
        $script:uiState.Action = if ($script:uiState.Mode -eq 'success') { 'restart' } else { 'close' }
        $script:uiState.AllowClose = $true
        $script:form.Close()
    })
    $script:form.Add_FormClosing({
        param($sender, $eventArgs)
        if (-not $script:uiState.AllowClose) { $eventArgs.Cancel = $true }
    })
    $script:form.Controls.AddRange(@($brand, $version, $script:statusLabel, $script:detailLabel,
                                     $script:progress, $script:actionButton))
    $script:form.Show()
    Pump-Ui
}
function Set-Phase([string]$Status, [string]$Detail) {
    if (-not $script:form) { return }
    $script:statusLabel.Text = $Status
    $script:detailLabel.Text = $Detail
    $script:progress.Style = 'Marquee'
    $script:progress.MarqueeAnimationSpeed = 24
    Pump-Ui
}
function Show-Result([bool]$Success, [string]$Detail) {
    if (-not $script:form) { return }
    $script:uiState.Mode = if ($Success) { 'success' } else { 'failed' }
    $script:statusLabel.Text = if ($Success) { 'Update complete' } else { 'Update could not be completed' }
    $script:statusLabel.ForeColor = if ($Success) {
        [Drawing.Color]::FromArgb(88, 220, 145)
    } else {
        [Drawing.Color]::FromArgb(245, 105, 105)
    }
    $script:detailLabel.Text = $Detail
    $script:progress.MarqueeAnimationSpeed = 0
    $script:progress.Style = 'Continuous'
    $script:progress.Value = if ($Success) { 100 } else { 0 }
    $script:actionButton.Text = if ($Success) { 'Restart Cubeon' } else { 'Close' }
    $script:actionButton.Visible = $true
    $script:form.ControlBox = $true
    $script:uiState.AllowClose = $true
    $script:actionButton.Focus()
    Pump-Ui
}
function Wait-For-UiAction {
    while ($script:form -and $script:form.Visible -and -not $script:uiState.Action) {
        Pump-Ui
        Start-Sleep -Milliseconds 50
    }
    return $script:uiState.Action
}
function Backslashes([int]$Count) {
    if ($Count -le 0) { return '' }
    return ((1..$Count | ForEach-Object { '\' }) -join '')
}
function Quote-Argument([string]$Value) {
    if ($null -eq $Value) { $Value = '' }
    if ($Value.Length -gt 0 -and $Value -notmatch '[\s"]') { return $Value }
    $builder = New-Object Text.StringBuilder
    [void]$builder.Append('"')
    $slashes = 0
    foreach ($character in $Value.ToCharArray()) {
        if ($character -eq [char]92) { $slashes += 1; continue }
        if ($character -eq [char]34) {
            if ($slashes -gt 0) { [void]$builder.Append((Backslashes ($slashes * 2 + 1))) }
            else { [void]$builder.Append([char]92) }
            [void]$builder.Append([char]34)
            $slashes = 0
            continue
        }
        if ($slashes -gt 0) {
            [void]$builder.Append((Backslashes $slashes))
            $slashes = 0
        }
        [void]$builder.Append($character)
    }
    if ($slashes -gt 0) { [void]$builder.Append((Backslashes ($slashes * 2))) }
    [void]$builder.Append('"')
    return $builder.ToString()
}
function Start-Cubeon {
    Regular $job.target
    $start = New-Object Diagnostics.ProcessStartInfo
    $start.FileName = $job.target
    $start.WorkingDirectory = $targetDir
    $start.UseShellExecute = $false
    $start.Arguments = (@($job.args | ForEach-Object { Quote-Argument ([string]$_) }) -join ' ')
    $start.EnvironmentVariables['CUBEON_RELAUNCH'] = '1'
    [void][Diagnostics.Process]::Start($start)
}
try {
    Directory-Safe $directory
    Regular $JobPath
    if ((Get-Item -LiteralPath $JobPath).Length -gt 32768) { throw 'Invalid update job size.' }
    $job = [IO.File]::ReadAllText($JobPath) | ConvertFrom-Json
    if ($job.schema -ne 1 -or $job.kind -ne 'windows' -or $job.sha256 -cnotmatch '^[a-f0-9]{64}$' -or
        $job.old_sha256 -cnotmatch '^[a-f0-9]{64}$' -or $job.token -cnotmatch '^[a-f0-9]{32}$' -or
        $job.size -lt 1024 -or $job.size -gt 1073741824 -or $job.parent_pid -le 0) { throw 'Invalid update job.' }
    $showUi = ($job.show_ui -eq $true)
    $targetDir = [IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($job.target))
    if ($targetDir.Contains('"') -or $targetDir.Contains("`r") -or $targetDir.Contains("`n")) { throw 'Unsafe installation path.' }
    Directory-Safe ([IO.Path]::GetDirectoryName($job.lock))
    if (Test-Path -LiteralPath $job.lock) { Regular $job.lock }
    $lock = [IO.File]::Open($job.lock, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    Registered-Target
    Other-Cubeon
    Regular $job.download
    # Keep a non-writable, non-deletable read handle through installer exit;
    # executing the setup is allowed, altering it after verification is not.
    $installerStream = [IO.File]::Open($job.download, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    if ($installerStream.Length -ne $job.size -or (Hash-Stream $installerStream) -cne $job.sha256) {
        throw 'The installer size or SHA-256 checksum failed.'
    }
    $reader = [IO.BinaryReader]::new($installerStream, [Text.Encoding]::UTF8, $true)
    if ($reader.ReadUInt16() -ne 0x5a4d) { throw 'Invalid installer executable.' }
    $installerStream.Position = 60
    $offset = $reader.ReadUInt32()
    if ($offset -lt 64 -or $offset -gt 1048576 -or $offset -gt $installerStream.Length - 6) { throw 'Invalid PE header.' }
    $installerStream.Position = $offset
    if ($reader.ReadUInt32() -ne 0x4550 -or $reader.ReadUInt16() -notin @(0x14c, 0x8664)) { throw 'Invalid PE header.' }
    $reader.Dispose()
    $parent = [Diagnostics.Process]::GetProcessById($job.parent_pid)
    $startedMs = [long](($parent.StartTime.ToUniversalTime().Ticks - 621355968000000000) / 10000)
    if ([Math]::Abs($startedMs - [long]$job.parent_started_ms) -gt 2) { throw 'The original launcher process changed.' }
    if ($showUi) {
        Initialize-Ui
        Set-Phase 'Waiting for Cubeon to close' 'The launcher will close before any installed files are changed.'
    }
    [IO.File]::WriteAllText((Join-Path $directory 'ready.tmp'), $job.token)
    [IO.File]::Move((Join-Path $directory 'ready.tmp'), (Join-Path $directory 'ready'))
    $deadline = [DateTime]::UtcNow.AddSeconds($job.parent_wait)
    while (-not (Signal-Matches 'go')) {
        Pump-Ui
        if ((Signal-Matches 'cancel') -or $parent.HasExited -or [DateTime]::UtcNow -ge $deadline) {
            $outcome = 'cancelled'; $exitCode = 0; break
        }
        Start-Sleep -Milliseconds 100
    }
    if ($outcome -ne 'cancelled') {
        while (-not $parent.WaitForExit(100)) {
            Pump-Ui
            if (Signal-Matches 'cancel') { $outcome = 'cancelled'; $exitCode = 0; break }
            if ([DateTime]::UtcNow -ge $deadline) { throw 'Cubeon did not exit. No installation started.' }
        }
    }
    if ($outcome -ne 'cancelled') {
        if (Signal-Matches 'cancel') { $outcome = 'cancelled'; $exitCode = 0 }
        else {
            $committed = $true
            Set-Phase ('Installing Cubeon ' + $job.version) 'Your current installation is protected until setup completes.'
            Registered-Target
            Other-Cubeon
            if ((Hash-Stream $installerStream) -cne $job.sha256) { throw 'Installer bytes changed.' }
            $start = New-Object Diagnostics.ProcessStartInfo
            $start.FileName = $job.download
            # NSIS /D MUST be the final, unquoted tail, including directories with
            # spaces. Do not use a shell or C-runtime argv quoting for this string.
            $start.Arguments = '/S /D=' + $targetDir
            $start.WorkingDirectory = $directory
            $start.UseShellExecute = $false
            $start.CreateNoWindow = $true
            $setup = [Diagnostics.Process]::Start($start)
            $setupDeadline = [DateTime]::UtcNow.AddMinutes(10)
            while (-not $setup.WaitForExit(100)) {
                Pump-Ui
                if ([DateTime]::UtcNow -ge $setupDeadline) {
                    # Never kill a setup in the middle of its transactional swap.
                    throw 'The installer is still running after ten minutes. Check Cubeon-Setup.log.'
                }
            }
            if ($setup.ExitCode -ne 0) { throw ('Setup failed with code ' + $setup.ExitCode + '. Check Cubeon-Setup.log.') }
            $outcome = 'installed'
            $exitCode = 0
            if (Test-Path -LiteralPath $job.failed) { Regular $job.failed; Remove-Item -LiteralPath $job.failed }
            if ($showUi) {
                Show-Result $true 'Cubeon was updated successfully. Restart to open the new version.'
                $restartRequested = ((Wait-For-UiAction) -eq 'restart')
            }
        }
    }
} catch {
    $message = $_.Exception.Message
    [Console]::Error.WriteLine($message)
    if ($form) {
        if ($committed) {
            Show-Result $false ($message + ' Your existing installation was kept or restored.')
            [void](Wait-For-UiAction)
        } else {
            $uiState.AllowClose = $true
            $form.Close()
        }
    }
} finally {
    if ($installerStream) { $installerStream.Dispose() }
    if ($job) {
        if ($committed -and $outcome -ne 'installed') {
            if (-not (Test-Path -LiteralPath $job.failed)) { [IO.File]::WriteAllText($job.failed, $outcome) }
            else { Regular $job.failed; [IO.File]::WriteAllText($job.failed, $outcome) }
        }
        [IO.File]::WriteAllText((Join-Path $directory 'result'), $outcome)
    }
    if ($lock) { $lock.Dispose() }
    if ($form) { $form.Dispose() }
}
if ($restartRequested -and $outcome -eq 'installed') {
    try { Start-Cubeon }
    catch {
        [Console]::Error.WriteLine($_.Exception.Message)
        try { [Windows.Forms.MessageBox]::Show('Cubeon was updated, but it could not be restarted. Open Cubeon from the Start menu.', 'Cubeon Updater') } catch {}
        $exitCode = 1
    }
}
exit $exitCode
'''
