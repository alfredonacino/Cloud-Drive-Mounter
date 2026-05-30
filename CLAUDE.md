# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-file Python CLI (`cloud_mount.py`, stdlib only) that wraps **rclone** to
mount cloud drives (Google Drive, OneDrive, Dropbox, S3, …) to local folders.
There is no build step and no dependencies — run the script directly.

## Commands

```bash
./cloud_mount.py add|remotes|mount|unmount|ls   # main subcommands
python3 -m py_compile cloud_mount.py            # syntax check (used as the smoke test)
```

There is no test suite. To exercise the mount/read/write/unmount lifecycle
**without cloud credentials**, point rclone at a throwaway `local` remote:

```bash
export RCLONE_CONFIG=$(mktemp); printf '[tl]\ntype = local\n' > "$RCLONE_CONFIG"
export CLOUD_MOUNT_ROOT=/tmp/cmtest                 # mount under a temp dir
SRC=$(mktemp -d); echo hi > "$SRC/f.txt"
./cloud_mount.py mount tl --subpath "$SRC"          # mounts the temp dir via FUSE
./cloud_mount.py unmount tl
```

## Architecture / things that aren't obvious from a single read

- **rclone is the engine; this script is orchestration.** It shells out to the
  `rclone` binary for everything (`listremotes`, `config`, `mount`, `rc`). It
  never talks to provider APIs itself.
- **Mount = a tracked background `rclone mount` process.** `cmd_mount` launches
  it with `start_new_session=True`, waits for `os.path.ismount()` to go true,
  then records `{pid, mountpoint, log, rc_sock, …}` in the state file.
- **State file:** `~/.local/state/cloud_drive_mounter/mounts.json` (the registry
  of live mounts), plus per-mount logs and RC sockets in the same dir.
  `_reconcile_state()` drops entries whose pid is dead or whose mountpoint is no
  longer mounted — `ls` and `mount` call it to self-heal after crashes.
- **Unmount must not lose data — this is the load-bearing invariant.** rclone's
  VFS uploads writes asynchronously (~5 s after close) and **discards the queue
  when signalled**. So `cmd_unmount` first calls `_drain_uploads()`, which polls
  `rclone rc --unix-socket <sock> vfs/stats` (`diskCache.uploadsQueued` +
  `uploadsInProgress`) until the queue is empty, and only then SIGTERMs the
  process. Every mount is therefore started with
  `--rc --rc-no-auth --rc-addr=unix://<sock>`. Do not "simplify" unmount to a
  bare `fusermount -u` or a plain kill — that reintroduces silent data loss.
- **Arg forwarding:** `main()` uses `parse_known_args`; unknown flags on `mount`
  are passed through verbatim to `rclone mount`, but are an error for any other
  subcommand. (Don't use `argparse.REMAINDER` — it greedily swallows the
  script's own options like `--subpath`.)
- **`--cache-mode full` is the default on purpose** — it makes the mount behave
  like a real local disk (random writes, in-place edits). Lower modes change
  semantics, so don't change the default casually.
