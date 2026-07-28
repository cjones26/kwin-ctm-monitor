# KWin CTM Monitor

KWin CTM Monitor is a local package builder and update service for a patched
version of KWin. The patched KWin adds user-configurable color transformation
matrices to KDE Plasma's Wayland session.

Under X11, `xrandr` can change a monitor's color transformation matrix. Under
Plasma Wayland, KWin owns that part of the display pipeline and does not provide
an equivalent user-facing control. A normal Wayland application cannot work
around that. KWin itself has to support it.

The repository carries the required KWin patch. When KDE neon updates KWin,
the monitor rebuilds a matching set of patched `.deb` packages and publishes
them to a signed APT repo on the local machine.

## Components

| Piece | What it does |
| --- | --- |
| The KWin patch | Adds per-monitor SDR matrix support to KWin's DRM display backend. |
| `kwin-ctm-monitor` | Watches KDE neon for KWin updates, applies the patch, builds replacement KWin packages, tests them, and publishes them locally. |
| `kwinctmctl` | Talks to the patched KWin over D-Bus to set, inspect, or reset a matrix. |
| `kwinctmctl-restore` | Reapplies the last confirmed matrix for each output when you run it in an already usable Wayland session. It is not installed as a global autostart hook. |

Installing `kwin-ctm-monitor` does not change the running KWin. It starts a
build of the patched KWin packages. Install those packages through Discover or
`pkcon`, then reboot into Plasma Wayland.

## Installation flow

1. Install the monitor package from this repo.
2. The monitor downloads the exact KDE neon KWin source currently offered to
   the machine.
3. It applies the patch, compiles KWin in Docker, runs the tests, and creates a
   local signed APT repository.
4. Install the resulting KWin update with Discover or `pkcon`.
5. Reboot into Plasma Wayland and set a matrix with `kwinctmctl`.

Development release. Validation covers KDE neon Noble with KWin 6.7.x on AMD
hardware. The patch is not part of upstream KWin.

## What is a CTM?

CTM means color transformation matrix. It is a 3x3 set of numbers that mixes
the red, green, and blue channels before the image reaches the monitor. A CTM
can change saturation, tint, channel balance, or perform another linear RGB
transform.

The matrix below increases saturation.

```text
 1.6  -0.3  -0.3
-0.3   1.6  -0.3
-0.3  -0.3   1.6
```

No matrix is compiled into KWin. `kwinctmctl` accepts any valid 3x3 matrix
supported by the display hardware and stores it per monitor UUID.

## Why an ICC profile or KWin effect is not enough

An ICC profile describes color characteristics and color-space conversions. It
is useful for calibration and color management, but it is not a reliable way to
request the exact arbitrary matrix previously sent through X11.

KWin effects operate in compositor rendering. They are not the same thing as a
persistent matrix in the output's hardware color pipeline and cannot provide
the same output-level behavior. The patch therefore works in KWin's DRM
backend, where output color operations are already managed.

## What gets installed

Building the monitor package requires only the normal Debian packaging tools.
The KWin compiler toolchain runs inside an Ubuntu 24.04 Docker container.

The host package installs the following files and configuration.

- a one-shot systemd service started after successful APT metadata refreshes;
- `kwinctmctl`;
- an APT preference that selects local `+local` packages while retaining Neon packages for recovery;
- a disabled local APT source, enabled only after the first successful build;
- the KWin patch and the patch-maintenance skill;
- `kwinctmctl-restore`, available as a manual command but not autostarted.

The patch changes packages built from the `kwin` source package, including
`kwin-wayland` and `kwin-common`. The patched packages provide the new
compositor behavior. Discover/PackageKit remains responsible for installing
them.

## Requirements

Current support is limited to this setup.

- KDE neon based on Ubuntu 24.04 (Noble);
- Plasma/KWin 6.7.x;
- systemd;
- Docker;
- a physical DRM device with primary and render nodes;
- enough room for a clean KWin build. Keep roughly 10 GB free and expect a
  temporary CPU/RAM spike while C++ and LTO jobs are running.

Check for both DRM nodes before installing.

```bash
ls -l /dev/dri/card* /dev/dri/renderD*
```

The monitor maps the matching primary and render nodes into the disposable
container. The MockDrm test intercepts KMS operations; the render node provides
the GBM device required to initialize the test environment. The monitor does
not load a virtual display driver on the host.

## Build and install the monitor

Clone the repo and build the monitor package.

```bash
git clone https://github.com/cjones26/kwin-ctm-monitor.git
cd kwin-ctm-monitor
sudo apt install build-essential debhelper python3
dpkg-buildpackage --build=binary --no-sign
pkcon install-local ../kwin-ctm-monitor_0.1.17-1_all.deb
```

`build-essential`, `debhelper`, and `python3` are needed only to produce the
monitor `.deb`. Runtime dependencies are declared by that package; PackageKit
installs any that are missing. The KWin compiler toolchain does not remain on
the host because it is installed inside the disposable container.

PackageKit labels a standalone local `.deb` as untrusted because it did not
arrive through an authenticated APT repository. Review the source and verify
the package checksum before approving the transaction. The KWin repository
created by the monitor is signed with a key generated during installation.

Installing the monitor creates a one-shot build request. Build output is
available in the system journal.

```bash
journalctl -fu kwin-ctm-monitor.service
```

On a 16-thread desktop, a clean KWin build has been taking about 12–20 minutes.
Slower CPUs or dependency downloads can push that past 30 minutes. Every new
KWin source version is a clean build. Patch development can reuse a configured
build tree, but published packages are built from a fresh source tree so stale
objects cannot enter the local repository.

Check the machine-readable result from another terminal.

```bash
watch -n 10 kwin-ctm-monitor status
```

A successful run ends with `"state": "published"`. Only then does the service
change the local source from `Enabled: no` to `Enabled: yes`.

## Install the patched KWin

Refresh PackageKit and inspect the candidate.

```bash
pkcon refresh force
apt-cache policy kwin-wayland
pkcon get-updates | grep -E 'kwin-(wayland|common|data|dev)'
```

The candidate version must contain the local rebuild suffix, currently
`+local1`.

```bash
pkcon update kwin-wayland kwin-common kwin-data kwin-dev
dpkg-query -W kwin-wayland kwin-common kwin-data kwin-dev
```

Reboot and select Plasma (Wayland). `kwin-x11` is a separate package and
remains untouched.

## Use `kwinctmctl`

List outputs first. UUIDs are preferred because connector names can move after
a cable or dock change.

```bash
kwinctmctl list
kwinctmctl show '<OUTPUT-UUID>'
```

Test a matrix with compositor-owned rollback.

```bash
kwinctmctl set '<OUTPUT-UUID>' \
  1.6 -0.3 -0.3 \
 -0.3  1.6 -0.3 \
 -0.3 -0.3  1.6 \
  --timeout 20
```

KWin applies the matrix temporarily and asks for confirmation. If the screen is
wrong or unreadable, leave it alone; KWin restores the previous value when the
timeout expires. Avoid `--force` until a matrix has been tested interactively.

Reset one output.

```bash
kwinctmctl reset '<OUTPUT-UUID>'
```

Confirmed matrices are stored in KWin's output configuration, per UUID. No
matrix is hard-coded in the repository, and existing X11 color scripts are not
read or modified.

KWin does not restore a matrix during output setup. A matrix is only set
through the D-Bus path used by `kwinctmctl`, after the compositor is already
running. That is deliberate: plasmalogin can reuse compositor state across the
greeter and the user session, and applying CTM during login has caused black
screens on real hardware.

`kwinctmctl-restore` is installed, but it is not wired into KDE autostart. Run
it manually after the Wayland desktop is visible if you want to reapply saved
matrices for all outputs:

```bash
kwinctmctl-restore
```

If you later add your own autostart hook, treat it as local policy and test it
carefully. Start with manual `kwinctmctl set` and rollback. Do not make
`--force` the first thing that touches display state after login.

### Local user services

The package does not install a KDE autostart hook for CTM restore. On this
workstation, restore is handled by user units outside this repo. They live in
`~/.config/systemd/user` and call scripts under `~/AMD_Saturate`.

```bash
systemctl --user status amd-saturate-ctm.service
systemctl --user status amd-saturate-ctm-unlock.service
```

`amd-saturate-ctm.service` runs once after the Plasma Wayland session is up.
`amd-saturate-ctm-unlock.service` keeps a small watcher running and reapplies
the matrix after screen unlock. That second unit exists because display sleep
and lock/unlock can reset the hardware CTM even though KWin and the session are
still alive.

Enable them on a machine where `~/AMD_Saturate` exists and has the matching
scripts.

```bash
systemctl --user daemon-reload
systemctl --user enable --now amd-saturate-ctm.service
systemctl --user enable --now amd-saturate-ctm-unlock.service
```

Disable them before debugging login or display-manager problems.

```bash
systemctl --user disable --now amd-saturate-ctm.service
systemctl --user disable --now amd-saturate-ctm-unlock.service
```

These units are intentionally not packaged here. They are session policy for a
specific workstation, not a safe default for every Plasma Wayland login.

## HDR behavior

The custom matrix applies only to SDR. KWin suspends it while HDR is active and
restores it when that output returns to SDR. Applying the same matrix to both
signal paths would not reproduce the original X11 SDR behavior and can break
HDR color handling.

`kwinctmctl show '<OUTPUT-UUID>'` reports KWin's current `hdr` state. Test the
transition both ways before relying on it.

## How update handling works

An APT post-update hook starts the one-shot monitor after package metadata has
finished refreshing. A new Neon KWin version starts this job.

1. Fetch the exact Neon source package with `apt-get source`.
2. Apply `patches/custom-output-ctm.patch` with fuzz disabled.
3. Start a disposable Noble container and create the local package version with
   Debian's `dch`.
4. Build KWin and run serial unit/MockDrm validation under D-Bus and Xvfb,
   using the host GPU nodes for GBM initialization.
5. Validate package names and versions.
6. Publish into a signed local APT repo using an atomic symlink swap.

Publication keeps the current and previous successful builds. A failed patch,
compile, or test leaves the previous repo untouched and records the failure at
`/var/lib/kwin-ctm-monitor/status.json`.

The APT pin gives locally built `+local` packages priority over Neon packages.
It does not disable the Neon repository, so official packages remain available
for recovery if the local repository is removed.

## Gotchas

- There is no software approximation. New matrices are rejected unless the DRM
  pipeline can represent them exactly. If hardware rejects a matrix, or a full
  presentation later fails while one is active, KWin falls back to an identity
  hardware matrix and records a critical log entry instead of leaving the
  session unusable.
- The build requires access to matching DRM primary and render nodes. Typical
  hosted CI containers do not expose these devices; use a VM or self-hosted
  runner for equivalent validation.
- `journalctl` includes compiler command lines. Build logs can become large.
- KWin internals move. A future Neon update may compile cleanly but still need
  a semantic patch review. The bundled `update-kwin-ctm-patch` skill documents
  the invariants but does not replace testing the display path.
- Validation covers AMD hardware. Other DRM drivers may expose different
  color-pipeline capabilities.

## Useful commands

```bash
kwin-ctm-monitor status
kwin-ctm-monitor check
sudo kwin-ctm-monitor build
systemctl status kwin-ctm-monitor.service
journalctl -u kwin-ctm-monitor.service
```

Manual `build` is mostly for recovery. Normal updates are triggered by APT
metadata changes.

## Reset a matrix without uninstalling anything

Reset each configured output while the patched KWin is still running.

```bash
kwinctmctl list
kwinctmctl reset '<OUTPUT-UUID>'
```

Do this before downgrading KWin. Official KWin ignores the extra matrix field in
`~/.config/kwinoutputconfig.json`, but resetting first prevents the old setting
from returning if the patch is installed again later.

## Remove the monitor and return to official KWin

Removing `kwin-ctm-monitor` stops future builds, but it does not downgrade KWin.
The patched KWin packages remain installed. Rollback requires removing the
monitor and downgrading KWin.

Remove the monitor through PackageKit, then purge its retained build state.

```bash
pkcon remove kwin-ctm-monitor
sudo apt purge kwin-ctm-monitor
pkcon refresh force
```

Purging the package removes the systemd units, APT pin, generated local source,
repository key, `/var/lib/kwin-ctm-monitor`, and the build cache.

Resolve the newest official Neon KWin version at removal time.

```bash
official_version="$(
  apt-cache madison kwin-wayland |
  awk -F'|' '{
    version=$2
    gsub(/^[[:space:]]+|[[:space:]]+$/, "", version)
    if (version ~ /zneon/ && version !~ /\+(ctm|local)/) {
      print version
      exit
    }
  }'
)"

test -n "$official_version" || {
  echo "No official KDE neon KWin version found" >&2
  exit 1
}

printf 'Downgrading to %s\n' "$official_version"
```

Install the resolved version for all four replaced packages.

```bash
sudo apt-get install --allow-downgrades \
  "kwin-wayland=$official_version" \
  "kwin-common=$official_version" \
  "kwin-data=$official_version" \
  "kwin-dev=$official_version"
```

Reboot and verify that no installed KWin version contains `+ctm` or `+local`.

```bash
systemctl reboot

# Run after logging back in:
dpkg-query -W kwin-wayland kwin-common kwin-data kwin-dev
```

The source checkout and any `.deb` copied outside the repo are user files; the
package manager does not delete them. Remove those separately to erase all
local project artifacts.

## License

Monitor code and the carried patch are GPL-2.0-or-later. KWin source and
binaries are fetched from KDE neon and retain their upstream licensing.
