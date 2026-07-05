# KWin CTM Monitor

KWin CTM Monitor carries a small, configurable output-matrix patch across KDE
neon KWin updates without committing or redistributing KWin source or binaries.

The monitor watches APT metadata changes, builds the matching patched KWin in an
isolated Docker container, validates the result, and publishes it to a signed,
machine-local APT repository. Installation remains under Discover/`pkcon`
control.

## Safety model

- Unpatched neon KWin packages are gated while the monitor is installed.
- Builds never run inside an APT transaction.
- KWin is built in a disposable Ubuntu 24.04 container.
- VKMS provides a dedicated virtual DRM device for validation; the live GPU is
  never passed into the container.
- VKMS is loaded at boot through
  `/usr/lib/modules-load.d/kwin-ctm-monitor.conf`.
- Tests run serially under an explicitly readiness-checked Xvfb and D-Bus
  session, including KWin's complete MockDrm executable.
- Failed patch, build, or validation leaves the repository unchanged.
- Publication is atomic and retains the current and previous successful builds.
- The monitor never installs KWin.
- Nothing under `~/AMD_Saturate` is read or modified at runtime.

## Status

This repository is under active development. Do not install the package until
the KWin patch and integration tests are marked production-ready.

## Commands

```bash
kwin-ctm-monitor status
sudo kwin-ctm-monitor check
sudo kwin-ctm-monitor build
journalctl -u kwin-ctm-monitor.service
```

After patched KWin is installed, output matrices are managed with:

```bash
kwinctmctl list
kwinctmctl show DP-3
kwinctmctl set DP-3 1.6 -0.3 -0.3 -0.3 1.6 -0.3 -0.3 -0.3 1.6
kwinctmctl reset DP-3
```

Persistent changes use a compositor-owned confirmation timeout. If the output
becomes unreadable and confirmation is not received, KWin restores the previous
matrix.

## Recovery after reinstall

Install the released monitor `.deb`, enable its path unit, and refresh APT.
The machine generates a new local repository signing key and builds KWin for
the currently installed KDE neon release. Installing the monitor also loads
VKMS immediately and configures it to return after reboot. Removal deletes the
packaged boot configuration automatically; it does not unload a module that may
still be serving an active validation run.

## Licensing

Monitor code and the KWin patch are GPL-2.0-or-later. KWin remains sourced
directly from KDE under its own licensing terms.
