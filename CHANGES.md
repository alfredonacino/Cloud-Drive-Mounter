# Changelog

All notable changes to this project are documented here.
The format is loosely based on [Keep a Changelog](https://keepachangelog.com).

## [0.1.0] — 2026-05-30

Initial release.

### Added
- `cloud_mount.py` — a single-file, dependency-free Python CLI that mounts cloud
  drives (Google Drive, OneDrive, Dropbox, S3, and 70+ rclone providers) to a
  local folder.
- Subcommands:
  - `add` — interactive rclone wizard to configure a new remote.
  - `remotes` — list configured remotes.
  - `mount` — mount a remote in the background with sane VFS-cache defaults;
    supports `--subpath`, custom mount point, `--read-only`, `--allow-other`,
    `--cache-mode`, `--foreground`, `--timeout`, and pass-through of any extra
    `rclone mount` flag.
  - `unmount` (`--all`, or by name/path) — unmount safely.
  - `ls` / `status` — show active mounts with PID, uptime, and log path.
- Background mount tracking via a state file at
  `~/.local/state/cloud_drive_mounter/mounts.json`, with self-healing of stale
  entries from crashed mounts.
- Per-mount log files under `~/.local/state/cloud_drive_mounter/logs/`.
- `CLOUD_MOUNT_ROOT` env var to override the default mount location.
- Documentation: `README.md`, `HOW_TO_USE.md`, and `CLAUDE.md`.

### Notable design decisions / fixes made during development
- **No data loss on unmount.** rclone uploads writes asynchronously and discards
  its queue when signalled. Each mount now runs rclone's remote-control API on a
  per-mount unix socket; `unmount` polls `vfs/stats` and waits for all pending
  uploads to drain before stopping the process. Verified with a write-then-
  immediately-unmount test on a 2 MB file.
- **Correct argument forwarding.** Switched from `argparse.REMAINDER` (which
  greedily swallowed the script's own `--subpath` option) to `parse_known_args`,
  so unknown flags forward to `rclone mount` while staying errors elsewhere.
- **`--vfs-cache-mode=full` default**, so the mount behaves like a real local
  disk (random writes, in-place edits, re-opening files).
