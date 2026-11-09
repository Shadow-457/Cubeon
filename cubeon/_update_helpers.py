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
$job = $null
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
try {
    Directory-Safe $directory
    Regular $JobPath
    if ((Get-Item -LiteralPath $JobPath).Length -gt 32768) { throw 'Invalid update job size.' }
    $job = [IO.File]::ReadAllText($JobPath) | ConvertFrom-Json
    if ($job.schema -ne 1 -or $job.kind -ne 'windows' -or $job.sha256 -cnotmatch '^[a-f0-9]{64}$' -or
        $job.old_sha256 -cnotmatch '^[a-f0-9]{64}$' -or $job.token -cnotmatch '^[a-f0-9]{32}$' -or
        $job.size -lt 1024 -or $job.size -gt 1073741824 -or $job.parent_pid -le 0) { throw 'Invalid update job.' }
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
    [IO.File]::WriteAllText((Join-Path $directory 'ready.tmp'), $job.token)
    [IO.File]::Move((Join-Path $directory 'ready.tmp'), (Join-Path $directory 'ready'))
    $deadline = [DateTime]::UtcNow.AddSeconds($job.parent_wait)
    while (-not (Signal-Matches 'go')) {
        if ((Signal-Matches 'cancel') -or $parent.HasExited -or [DateTime]::UtcNow -ge $deadline) {
            $outcome = 'cancelled'; exit 0
        }
        Start-Sleep -Milliseconds 200
    }
    while (-not $parent.WaitForExit(200)) {
        if (Signal-Matches 'cancel') { $outcome = 'cancelled'; exit 0 }
        if ([DateTime]::UtcNow -ge $deadline) { throw 'Cubeon did not exit. No installation started.' }
    }
    if (Signal-Matches 'cancel') { $outcome = 'cancelled'; exit 0 }
    $committed = $true
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
    if (-not $setup.WaitForExit(600000)) {
        # Never kill a setup in the middle of its transactional swap.
        throw 'The installer is still running after ten minutes. Check Cubeon-Setup.log.'
    }
    if ($setup.ExitCode -ne 0) { throw ('Setup failed with code ' + $setup.ExitCode + '. Check Cubeon-Setup.log.') }
    $outcome = 'installed'
    if (Test-Path -LiteralPath $job.failed) { Regular $job.failed; Remove-Item -LiteralPath $job.failed }
    exit 0
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
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
}
'''
