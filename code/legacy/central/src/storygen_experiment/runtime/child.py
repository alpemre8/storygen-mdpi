"""Exec a stage with Linux regular-filesystem writes confined to its owned run.

Uses the host's existing Landlock ABI (/usr/include/linux/landlock.h); no install,
sudo, scientific monkeypatch, network restriction or ambient parent change.
"""

from pathlib import Path
import argparse
import ctypes
import os
import platform


def restrict_writes(root):
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "aarch64"}:
        raise RuntimeError("Write confinement requires supported Linux Landlock")
    lib = ctypes.CDLL(None, use_errno=True)
    abi = lib.syscall(444, 0, 0, 1)
    if abi < 3:
        raise RuntimeError("Landlock ABI >=3 required for truncation-safe confinement")

    class Rules(ctypes.Structure):
        _fields_ = [("handled_access_fs", ctypes.c_uint64)]

    class Rule(ctypes.Structure):
        _pack_ = 1
        _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]

    # Write/truncate/remove/create/reparent. Read, execution and device ioctl remain available.
    mask = (1 << 1) | sum(1 << i for i in range(4, 15))
    attr = Rules(mask)
    fd = lib.syscall(444, ctypes.byref(attr), ctypes.sizeof(attr), 0)
    if fd < 0:
        raise OSError(ctypes.get_errno(), "Landlock ruleset")

    def allow(path, rights):
        parent = os.open(path, os.O_PATH | os.O_CLOEXEC)
        try:
            rule = Rule(rights, parent)
            if lib.syscall(445, fd, 1, ctypes.byref(rule), 0) < 0:
                raise OSError(ctypes.get_errno(), "Landlock path rule " + str(path))
        finally:
            os.close(parent)

    try:
        allow(Path(root).resolve(), mask)
        # Existing character devices are runtime interfaces, never scientific file output roots.
        for path in [Path("/dev/null"), *Path("/dev/dri").glob("*")]:
            if path.exists():
                allow(path, 1 << 1)
        if lib.prctl(38, 1, 0, 0, 0) < 0:
            raise OSError(ctypes.get_errno(), "PR_SET_NO_NEW_PRIVS")
        if lib.syscall(446, fd, 0) < 0:
            raise OSError(ctypes.get_errno(), "Landlock restrict_self")
    finally:
        os.close(fd)
    return abi


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("command", nargs=argparse.REMAINDER)
    a = p.parse_args()
    command = a.command[1:] if a.command[:1] == ["--"] else a.command
    if not command:
        raise ValueError("Executable argv required")
    env = dict(os.environ)
    provider = env.pop("STORYGEN_EXECUTION_PYTHONPATH", "")
    env["PYTHONPATH"] = provider
    restrict_writes(a.root)
    os.execve(command[0], command, env)


if __name__ == "__main__":
    main()
