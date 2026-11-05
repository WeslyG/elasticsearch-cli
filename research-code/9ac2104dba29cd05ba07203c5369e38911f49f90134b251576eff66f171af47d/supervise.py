"""Bound a research process tree inside the Linux devcontainer."""

import argparse
import os
import signal
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not args.command or not 0 < args.timeout <= 1800:
        raise SystemExit("A bounded command is required")
    process = subprocess.Popen(args.command, start_new_session=True)
    try:
        return process.wait(timeout=args.timeout)
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)
        print(
            "Research process-tree deadline/interruption; evidence may be partial", file=sys.stderr
        )
        return 124


if __name__ == "__main__":
    raise SystemExit(main())
