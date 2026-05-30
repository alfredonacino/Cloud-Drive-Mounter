# How to use cloud_drive_mounter

A step-by-step guide to mounting a cloud drive as a local folder with
`cloud_mount.py`.

---

## 1. Install the prerequisites

| Requirement | Install |
|-------------|---------|
| **rclone**  | `curl https://rclone.org/install.sh \| sudo bash` &nbsp;·&nbsp; `sudo pacman -S rclone` &nbsp;·&nbsp; `sudo apt install rclone` |
| **FUSE**    | Arch: `sudo pacman -S fuse3` · Debian/Ubuntu: `sudo apt install fuse3` · macOS: install [macFUSE](https://osxfuse.github.io) |
| **Python**  | 3.9 or newer (`python3 --version`) — standard library only, nothing to `pip install` |

Make the script executable once:

```bash
chmod +x cloud_mount.py
```

---

## 2. Add a cloud drive (one time per drive)

```bash
./cloud_mount.py add
```

This launches rclone's interactive wizard. Walk through it:

1. Choose **`n`** for a new remote.
2. **Name** it something short, e.g. `gdrive`, `onedrive`, `dropbox`.
3. Pick the **provider** (`drive` = Google Drive, `onedrive`, `dropbox`, `s3`, …).
4. For most providers leave client id/secret blank (press Enter) to use rclone's
   defaults.
5. When asked to **authenticate**, say yes — a browser window opens for you to
   log in and grant access. (On a headless box, choose the "no, use a remote
   machine" option and follow the printed instructions.)
6. Accept the defaults for the rest and confirm.

Check it registered:

```bash
./cloud_mount.py remotes
```

---

## 3. Mount it

```bash
./cloud_mount.py mount gdrive
```

Your drive is now a local folder at **`~/CloudMounts/gdrive`**. Use it with any
program — file manager, editor, `cp`, `ls`, etc.:

```bash
ls ~/CloudMounts/gdrive
cp ~/Desktop/report.pdf ~/CloudMounts/gdrive/
```

### Useful mount variations

```bash
# Mount to a specific folder instead of the default
./cloud_mount.py mount gdrive /mnt/gdrive

# Mount only a sub-folder of the drive
./cloud_mount.py mount gdrive --subpath "Documents/Work"

# Read-only (safe browsing, no accidental changes)
./cloud_mount.py mount gdrive --read-only

# Pass any extra rclone flag straight through
./cloud_mount.py mount gdrive --vfs-cache-max-size 10G
```

---

## 4. Check what's mounted

```bash
./cloud_mount.py ls
```

Shows each active mount with its remote path, mount point, PID, uptime, and log
file location.

---

## 5. Unmount

```bash
./cloud_mount.py unmount gdrive      # by name
./cloud_mount.py unmount /mnt/gdrive # …or by path
./cloud_mount.py unmount --all       # everything
```

**Always unmount with this command.** It waits for any in-flight uploads to
finish before stopping rclone, so you never lose recently written files. Killing
rclone by hand can drop not-yet-uploaded writes.

> If unmount reports the mount is *busy*, close anything using it first — a shell
> `cd`'d into the folder, an open editor, a file manager tab — then try again.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `rclone is not installed` | Install rclone (see step 1). |
| `FUSE is not available` | Install `fuse3`. |
| `remote '…' not found` | Run `./cloud_mount.py remotes`; add it with `add`. |
| Mount times out | Check the log path printed on mount (under `~/.local/state/cloud_drive_mounter/logs/`). |
| New files don't appear in the cloud immediately | Normal — rclone uploads a few seconds after a file is closed. They flush fully on `unmount`. |
| `--allow-other` mount fails | Add `user_allow_other` to `/etc/fuse.conf`. |

---

## Where things live

- Mount registry: `~/.local/state/cloud_drive_mounter/mounts.json`
- Per-mount logs: `~/.local/state/cloud_drive_mounter/logs/<remote>.log`
- Default mount root: `~/CloudMounts/` (override with `CLOUD_MOUNT_ROOT`)
- rclone remote config: `~/.config/rclone/rclone.conf`
