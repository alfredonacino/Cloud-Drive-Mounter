#!/usr/bin/env python3
"""
cloud_mount.py — Mount cloud drives (Google Drive, OneDrive, Dropbox, S3, …)
to a local folder and use them like a normal local drive.

This is a thin, friendly wrapper around `rclone mount`. rclone handles the
provider OAuth/APIs and the FUSE filesystem; this script handles the ergonomics:
adding remotes, mounting them in the background with sane caching defaults,
tracking which mounts are live, and cleanly unmounting them.

Quick start:
    ./cloud_mount.py add                 # interactive: configure a new remote
    ./cloud_mount.py remotes             # list configured remotes
    ./cloud_mount.py mount gdrive        # mount remote 'gdrive' under ~/CloudMounts/gdrive
    ./cloud_mount.py ls                  # show active mounts
    ./cloud_mount.py unmount gdrive      # unmount it
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

# --------------------------------------------------------------------------- #
# Configuration / paths
# --------------------------------------------------------------------------- #

APP_NAME = "cloud_drive_mounter"
STATE_DIR = Path(
    os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")
) / APP_NAME
STATE_FILE = STATE_DIR / "mounts.json"
LOG_DIR = STATE_DIR / "logs"
DEFAULT_MOUNT_ROOT = Path(
    os.environ.get("CLOUD_MOUNT_ROOT", Path.home() / "CloudMounts")
)

# ANSI colors (disabled when not a tty)
_TTY = sys.stdout.isatty()
def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _TTY else text
def ok(t): return _c("32", t)
def warn(t): return _c("33", t)
def err(t): return _c("31", t)
def bold(t): return _c("1", t)


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def die(msg: str, code: int = 1) -> "NoReturn":  # type: ignore[name-defined]
    print(err(f"error: {msg}"), file=sys.stderr)
    sys.exit(code)


def rclone_bin() -> str:
    path = shutil.which("rclone")
    if not path:
        die(
            "rclone is not installed or not on PATH.\n"
            "  Install it from https://rclone.org/install/ — e.g.:\n"
            "    curl https://rclone.org/install.sh | sudo bash\n"
            "    # or:  sudo pacman -S rclone   /   sudo apt install rclone"
        )
    return path


def have_fuse() -> bool:
    return bool(shutil.which("fusermount") or shutil.which("fusermount3"))


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, **kw)


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {"mounts": {}}
    try:
        return json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {"mounts": {}}


def save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(STATE_FILE)


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def is_mountpoint(path: Path) -> bool:
    """True if `path` is currently an active mount point."""
    try:
        return os.path.ismount(str(path))
    except OSError:
        # A stale FUSE mount can raise; treat as still-mounted so we try to clean it.
        return True


# --------------------------------------------------------------------------- #
# rclone introspection
# --------------------------------------------------------------------------- #

def list_remotes() -> list[str]:
    proc = run(
        [rclone_bin(), "listremotes"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        die(f"failed to list remotes:\n{proc.stderr.strip()}")
    return [line.rstrip(":") for line in proc.stdout.splitlines() if line.strip()]


def require_remote(name: str) -> str:
    name = name.rstrip(":")
    remotes = list_remotes()
    if name not in remotes:
        listing = ", ".join(remotes) if remotes else "(none configured)"
        die(
            f"remote '{name}' not found.\n"
            f"  Configured remotes: {listing}\n"
            f"  Add one with:  {sys.argv[0]} add"
        )
    return name


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #

def cmd_add(args: argparse.Namespace) -> int:
    """Launch rclone's interactive config to add/edit a remote."""
    print(bold("Launching rclone interactive config…"))
    print(
        "Tip: choose your provider (e.g. 'drive' for Google Drive, "
        "'onedrive', 'dropbox', 's3') and follow the prompts.\n"
    )
    return run([rclone_bin(), "config"]).returncode


def cmd_remotes(args: argparse.Namespace) -> int:
    remotes = list_remotes()
    if not remotes:
        print(warn("No remotes configured yet."))
        print(f"Add one with:  {bold(sys.argv[0] + ' add')}")
        return 0
    print(bold("Configured remotes:"))
    for r in remotes:
        print(f"  • {r}")
    return 0


def _reconcile_state(state: dict) -> dict:
    """Drop dead/no-longer-mounted entries from state, return cleaned copy."""
    live = {}
    for name, info in state.get("mounts", {}).items():
        mp = Path(info["mountpoint"])
        if pid_alive(info["pid"]) and is_mountpoint(mp):
            live[name] = info
    cleaned = {"mounts": live}
    if cleaned != state:
        save_state(cleaned)
    return cleaned


def cmd_mount(args: argparse.Namespace) -> int:
    if not have_fuse():
        die("FUSE is not available (no fusermount). Install fuse/fuse3 to mount.")

    remote = require_remote(args.remote)
    # Trailing-slash only: a leading '/' is meaningful for some backends (e.g.
    # local), and cloud backends tolerate it, so don't strip it.
    subpath = args.subpath.rstrip("/") if args.subpath else ""
    remote_spec = f"{remote}:{subpath}"

    mountpoint = (
        Path(args.mountpoint).expanduser().resolve()
        if args.mountpoint
        else (DEFAULT_MOUNT_ROOT / remote).resolve()
    )

    state = _reconcile_state(load_state())
    if remote in state["mounts"]:
        info = state["mounts"][remote]
        die(
            f"remote '{remote}' is already mounted at {info['mountpoint']} "
            f"(pid {info['pid']}).\n  Unmount first:  {sys.argv[0]} unmount {remote}"
        )

    mountpoint.mkdir(parents=True, exist_ok=True)
    if is_mountpoint(mountpoint):
        die(f"{mountpoint} is already a mount point. Unmount it first.")
    if any(mountpoint.iterdir()):
        die(f"mount point {mountpoint} is not empty — refusing to mount over it.")

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"{remote}.log"

    # Per-mount rclone remote-control socket. We use it at unmount time to wait
    # for the VFS write-back queue to drain — rclone does NOT flush pending
    # uploads when it receives a signal, so without this writes can be lost.
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    rc_sock = STATE_DIR / f"rc-{remote}.sock"
    try:
        rc_sock.unlink()  # clear a stale socket from a crashed run
    except FileNotFoundError:
        pass

    # VFS cache makes the mount behave like a real local disk: random writes,
    # in-place edits, and re-opening files all work. 'full' caches file content
    # on demand; 'writes' only caches files being written.
    cmd = [
        rclone_bin(), "mount", remote_spec, str(mountpoint),
        f"--vfs-cache-mode={args.cache_mode}",
        "--vfs-cache-max-age=24h",
        "--dir-cache-time=12h",
        "--poll-interval=15s",
        "--log-file", str(log_file),
        "--log-level", "INFO",
        "--rc", "--rc-no-auth", f"--rc-addr=unix://{rc_sock}",
    ]
    if args.read_only:
        cmd.append("--read-only")
    if args.allow_other:
        cmd.append("--allow-other")
    cmd += args.rclone_args or []

    if args.foreground:
        print(bold(f"Mounting {remote_spec} → {mountpoint} (foreground, Ctrl-C to stop)"))
        return run(cmd).returncode

    # Background daemon. rclone has --daemon, but we manage the process ourselves
    # so we can track the PID and tear it down reliably.
    print(f"Mounting {bold(remote_spec)} → {bold(str(mountpoint))} …")
    with open(log_file, "a") as lf:
        proc = subprocess.Popen(
            cmd, stdout=lf, stderr=lf,
            stdin=subprocess.DEVNULL, start_new_session=True,
        )

    # Wait for the mount to come up (or the process to die).
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            tail = _tail(log_file, 15)
            die(f"rclone exited (code {proc.returncode}). Last log lines:\n{tail}")
        if is_mountpoint(mountpoint):
            break
        time.sleep(0.25)
    else:
        proc.send_signal(signal.SIGTERM)
        tail = _tail(log_file, 15)
        die(f"timed out waiting for mount to appear. Last log lines:\n{tail}")

    state["mounts"][remote] = {
        "remote": remote_spec,
        "mountpoint": str(mountpoint),
        "pid": proc.pid,
        "log": str(log_file),
        "rc_sock": str(rc_sock),
        "cache_mode": args.cache_mode,
        "read_only": args.read_only,
        "started": int(time.time()),
    }
    save_state(state)

    print(ok(f"✓ mounted. Browse it at {mountpoint}"))
    print(f"  log:     {log_file}")
    print(f"  unmount: {sys.argv[0]} unmount {remote}")
    return 0


def _tail(path: Path, n: int) -> str:
    try:
        lines = path.read_text(errors="replace").splitlines()
        return "\n".join("    " + l for l in lines[-n:])
    except OSError:
        return "    (no log available)"


def _pending_uploads(rc_sock: str) -> int | None:
    """Return queued+in-progress VFS uploads via rclone's RC, or None if unknown."""
    if not rc_sock or not Path(rc_sock).exists():
        return None
    proc = run(
        [rclone_bin(), "rc", "--unix-socket", rc_sock, "vfs/stats"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return None
    try:
        dc = json.loads(proc.stdout).get("diskCache", {})
        return int(dc.get("uploadsQueued", 0)) + int(dc.get("uploadsInProgress", 0))
    except (json.JSONDecodeError, ValueError, TypeError):
        return None


def _drain_uploads(rc_sock: str, timeout: float = 120.0) -> None:
    """Block until rclone's write-back queue is empty (or timeout).

    rclone discards queued uploads when signalled, so we must let them finish
    before we terminate the process — otherwise recent writes are lost.
    """
    pending = _pending_uploads(rc_sock)
    if pending is None or pending == 0:
        return
    print(f"  waiting for {pending} pending upload(s) to finish…")
    deadline = time.time() + timeout
    while time.time() < deadline:
        pending = _pending_uploads(rc_sock)
        if pending is None or pending == 0:
            return
        time.sleep(0.5)
    print(warn(f"  still {pending} upload(s) pending after {timeout:.0f}s — "
               "proceeding anyway (data may remain in the local VFS cache)."))


def _unmount_path(mountpoint: Path) -> bool:
    """Try to unmount a FUSE mount point. Returns True on success."""
    for tool, flag in (("fusermount3", "-u"), ("fusermount", "-u"), ("umount", "")):
        if not shutil.which(tool):
            continue
        argv = [tool, flag, str(mountpoint)] if flag else [tool, str(mountpoint)]
        proc = run(argv, capture_output=True, text=True)
        if proc.returncode == 0:
            return True
    # Lazy unmount as a last resort for a busy mount.
    if shutil.which("fusermount3") or shutil.which("fusermount"):
        tool = "fusermount3" if shutil.which("fusermount3") else "fusermount"
        if run([tool, "-uz", str(mountpoint)], capture_output=True).returncode == 0:
            return True
    return False


def cmd_unmount(args: argparse.Namespace) -> int:
    state = load_state()
    targets: list[tuple[str, dict]] = []

    if args.all:
        targets = list(state["mounts"].items())
        if not targets:
            print(warn("nothing mounted."))
            return 0
    else:
        name = args.remote.rstrip(":")
        if name in state["mounts"]:
            targets = [(name, state["mounts"][name])]
        else:
            # Allow passing a mount-point path too.
            p = Path(args.remote).expanduser().resolve()
            match = [
                (n, i) for n, i in state["mounts"].items()
                if Path(i["mountpoint"]) == p
            ]
            if match:
                targets = match
            elif is_mountpoint(p):
                targets = [(str(p), {"mountpoint": str(p), "pid": None})]
            else:
                die(f"'{args.remote}' is not a known or active mount.")

    rc = 0
    for name, info in targets:
        mp = Path(info["mountpoint"])
        print(f"Unmounting {bold(name)} ({mp}) …")

        # IMPORTANT: rclone does NOT flush its write-back queue when signalled,
        # so first wait (via the RC socket) for pending uploads to finish; only
        # then terminate the process. This is what prevents data loss on unmount.
        _drain_uploads(info.get("rc_sock", ""))

        pid = info.get("pid")
        if pid and pid_alive(pid):
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            # Give it time to flush uploads + tear down (up to ~15s).
            for _ in range(150):
                if not pid_alive(pid) and not is_mountpoint(mp):
                    break
                time.sleep(0.1)

        # Fall back to an explicit unmount only if something is still mounted
        # (e.g. an externally-started mount with no tracked pid, or a stuck one).
        if is_mountpoint(mp):
            _unmount_path(mp)

        # Last resort: if rclone is still alive after unmount, force it down.
        if pid and pid_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

        if not is_mountpoint(mp):
            print(ok(f"✓ unmounted {name}"))
            sock = info.get("rc_sock")
            if sock:
                try:
                    Path(sock).unlink()
                except FileNotFoundError:
                    pass
            state["mounts"].pop(name, None)
        else:
            print(err(f"✗ failed to unmount {mp} — it may be busy (a shell/app inside it?)"))
            rc = 1

    save_state(state)
    return rc


def cmd_list(args: argparse.Namespace) -> int:
    state = _reconcile_state(load_state())
    mounts = state["mounts"]
    if not mounts:
        print(warn("No active mounts."))
        return 0
    print(bold("Active mounts:"))
    for name, info in mounts.items():
        age = int(time.time()) - info.get("started", int(time.time()))
        ro = " (read-only)" if info.get("read_only") else ""
        print(f"  {ok('●')} {bold(name)}{ro}")
        print(f"      remote:     {info['remote']}")
        print(f"      mountpoint: {info['mountpoint']}")
        print(f"      pid:        {info['pid']}   uptime: {_fmt_age(age)}")
        print(f"      log:        {info['log']}")
    return 0


def _fmt_age(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h{m}m"
    if m:
        return f"{m}m{s}s"
    return f"{s}s"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=Path(sys.argv[0]).name,
        description="Mount cloud drives (Google Drive, OneDrive, Dropbox, S3, …) "
                    "to a local folder via rclone.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("add", help="interactively configure a new cloud remote"
                   ).set_defaults(func=cmd_add)
    for alias in ("remotes", "providers"):
        sub.add_parser(alias, help="list configured remotes"
                       ).set_defaults(func=cmd_remotes)

    m = sub.add_parser("mount", help="mount a remote to a local folder")
    m.add_argument("remote", help="name of a configured remote (see 'remotes')")
    m.add_argument("mountpoint", nargs="?",
                   help=f"local folder (default: {DEFAULT_MOUNT_ROOT}/<remote>)")
    m.add_argument("--subpath", default="",
                   help="mount only a sub-folder of the remote")
    m.add_argument("--cache-mode", default="full",
                   choices=["off", "minimal", "writes", "full"],
                   help="VFS cache mode (default: full = behaves like a local disk)")
    m.add_argument("--read-only", action="store_true", help="mount read-only")
    m.add_argument("--allow-other", action="store_true",
                   help="let other users access the mount (needs user_allow_other in /etc/fuse.conf)")
    m.add_argument("--foreground", action="store_true",
                   help="run in foreground instead of as a background daemon")
    m.add_argument("--timeout", type=float, default=20.0,
                   help="seconds to wait for the mount to appear (default: 20)")
    # Any flags this parser doesn't recognize (collected via parse_known_args)
    # are forwarded verbatim to 'rclone mount' — e.g.  mount gdrive --no-modtime
    m.set_defaults(func=cmd_mount)

    u = sub.add_parser("unmount", aliases=["umount"],
                       help="unmount a remote (by name or mount path)")
    u.add_argument("remote", nargs="?", default="", help="remote name or mount path")
    u.add_argument("--all", action="store_true", help="unmount everything")
    u.set_defaults(func=cmd_unmount)

    for alias in ("ls", "list", "status"):
        sub.add_parser(alias, help="show active mounts"
                       ).set_defaults(func=cmd_list)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args, extras = parser.parse_known_args(argv)
    # Unknown flags are forwarded to 'rclone mount'; for any other command an
    # unrecognized argument is a genuine mistake.
    if args.command == "mount":
        args.rclone_args = extras
    elif extras:
        parser.error(f"unrecognized arguments: {' '.join(extras)}")
    # 'unmount' with neither a name nor --all is a usage error.
    if args.command in ("unmount", "umount") and not args.all and not args.remote:
        parser.error("specify a remote name/path or use --all")
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\ninterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
