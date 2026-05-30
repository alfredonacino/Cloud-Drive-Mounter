# cloud_drive_mounter

> Mount cloud drives — **Google Drive, OneDrive, Dropbox, S3, and 70+ other
> providers** — to a local folder and use them like a normal local disk.

`cloud_mount.py` is a single-file, dependency-free Python CLI that wraps
[rclone](https://rclone.org). rclone does the heavy lifting (provider OAuth,
APIs, the FUSE filesystem); this tool adds the ergonomics: adding remotes,
mounting them in the background with sensible caching, tracking which mounts are
live, and — most importantly — **unmounting without losing data** by flushing
pending uploads first.

---

## Table of contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Command reference](#command-reference)
- [Configuration](#configuration)
- [How it works](#how-it-works)
- [Troubleshooting](#troubleshooting)
- [Project structure](#project-structure)
- [Documentation](#documentation)
- [License](#license)

---

## Features

- **Any rclone backend** — Google Drive, OneDrive, Dropbox, S3, Box, pCloud,
  WebDAV, SFTP, and [70+ more](https://rclone.org/overview/).
- **Use it like a local disk** — `--vfs-cache-mode=full` by default, so random
  writes, in-place edits, and re-opening files all work.
- **Safe unmounts** — waits for in-flight uploads to drain before stopping
  rclone, so recently written files are never lost.
- **Background mounts with tracking** — `ls` shows every active mount with PID,
  uptime, and log path; stale entries from crashed mounts self-heal.
- **Zero dependencies** — pure Python standard library; nothing to `pip install`.
- **Flexible** — read-only mounts, sub-folder mounts, custom mount points, and
  pass-through of any extra `rclone mount` flag.

## Requirements

| Requirement | Notes |
|-------------|-------|
| **rclone**  | The engine. [Install guide](https://rclone.org/install/). |
| **FUSE**    | `fuse3` on Linux; [macFUSE](https://osxfuse.github.io) on macOS. |
| **Python**  | 3.9 or newer. Standard library only. |

## Installation

```bash
git clone https://gitlab.supportlab.cloud/alfreddgreat/cloud-drive-mounter.git
cd cloud-drive-mounter
chmod +x cloud_mount.py

# Install rclone + FUSE if you don't have them, e.g. on Arch:
sudo pacman -S rclone fuse3
# …or Debian/Ubuntu:
sudo apt install rclone fuse3
```

Optionally put it on your `PATH`:

```bash
ln -s "$PWD/cloud_mount.py" ~/.local/bin/cloud-mount
```

## Quick start

```bash
./cloud_mount.py add                 # configure a drive (interactive rclone wizard)
./cloud_mount.py remotes             # list configured remotes
./cloud_mount.py mount gdrive        # mount 'gdrive' under ~/CloudMounts/gdrive
ls ~/CloudMounts/gdrive              # …it's just local files now
./cloud_mount.py ls                  # show active mounts
./cloud_mount.py unmount gdrive      # flush pending uploads, then unmount
```

See **[HOW_TO_USE.md](HOW_TO_USE.md)** for a full step-by-step walkthrough
(including the Google Drive OAuth flow).

## Command reference

```
cloud_mount.py <command> [options]

  add                       Configure a new remote (interactive rclone wizard).
  remotes                   List configured remotes.
  mount <remote> [path]     Mount a remote to a local folder.
  unmount <remote|path>     Unmount a remote (use --all for everything).
  ls | status               Show active mounts.
```

### `mount` options

| Option | Description |
|--------|-------------|
| `[mountpoint]`        | Local folder (default: `~/CloudMounts/<remote>`). |
| `--subpath PATH`      | Mount only a sub-folder of the remote. |
| `--cache-mode MODE`   | `off` \| `minimal` \| `writes` \| `full` (default: `full`). |
| `--read-only`         | Mount read-only. |
| `--allow-other`       | Let other users access the mount (needs `user_allow_other` in `/etc/fuse.conf`). |
| `--foreground`        | Run in the foreground instead of as a daemon. |
| `--timeout SECONDS`   | How long to wait for the mount to appear (default: 20). |
| *any other flag*      | Forwarded verbatim to `rclone mount`, e.g. `--vfs-cache-max-size 10G`. |

## Configuration

| What | Where |
|------|-------|
| Default mount root | `~/CloudMounts/` — override with the `CLOUD_MOUNT_ROOT` env var. |
| Mount registry     | `~/.local/state/cloud_drive_mounter/mounts.json` |
| Per-mount logs     | `~/.local/state/cloud_drive_mounter/logs/<remote>.log` |
| rclone remotes     | `~/.config/rclone/rclone.conf` (managed by `rclone config`). |

## How it works

- **rclone is the engine; this script is orchestration.** Every operation shells
  out to the `rclone` binary — the script never talks to provider APIs itself.
- **A mount is a tracked background `rclone mount` process.** On `mount`, the
  script launches rclone in its own session, waits for the mount point to become
  active, and records the PID and metadata in the state file.
- **Writes upload asynchronously** (~5 s after a file is closed) — normal rclone
  behavior that keeps the mount fast.
- **Unmount is the load-bearing part.** rclone *discards* queued uploads when
  signalled, so every mount runs rclone's remote-control API on a per-mount unix
  socket; `unmount` polls `vfs/stats` and waits for all pending uploads to finish
  **before** stopping the process. Always unmount via this tool rather than
  killing rclone by hand.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `rclone is not installed` | Install rclone (see [Requirements](#requirements)). |
| `FUSE is not available` | Install `fuse3`. |
| `remote '…' not found` | Run `remotes`; add it with `add`. |
| Mount times out | Check the log under `~/.local/state/cloud_drive_mounter/logs/`. |
| New files don't appear in the cloud immediately | Normal — they upload a few seconds after close and flush fully on `unmount`. |
| Unmount says *busy* | Close anything using the folder (shells, editors, file managers), then retry. |

## Project structure

```
cloud-drive-mounter/
├── cloud_mount.py    # the CLI (all the code)
├── README.md         # this file
├── HOW_TO_USE.md     # step-by-step usage guide
├── CHANGES.md        # changelog
└── CLAUDE.md         # notes for AI coding assistants
```

## Documentation

- **[HOW_TO_USE.md](HOW_TO_USE.md)** — step-by-step guide, from install to unmount.
- **[CHANGES.md](CHANGES.md)** — changelog.
- **[CLAUDE.md](CLAUDE.md)** — architecture notes for future contributors / AI assistants.

## License

Released under the [MIT License](LICENSE).
