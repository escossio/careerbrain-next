"""Deny network/process I/O during contract checks and synthetic test execution."""

import sys


def enable() -> None:
    def audit(event, args):
        if event.startswith("socket.") or event in {"subprocess.Popen", "os.system", "os.posix_spawn"}:
            raise RuntimeError("OFFLINE_IO_BLOCKED")
    sys.addaudithook(audit)
