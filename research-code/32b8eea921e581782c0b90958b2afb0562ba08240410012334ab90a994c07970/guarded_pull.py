"""Pull one pinned image with conservative admission and an append-only disk record."""

import argparse
import json
import platform
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def admission_estimate(existing, compressed):
    if existing < 0 or compressed <= 0:
        raise ValueError("Positive compressed size and nonnegative existing budget required")
    return existing + compressed * 10 + 5_000_000_000


def free_bytes():
    if "microsoft" in platform.release().lower():
        value = subprocess.check_output(
            ["powershell.exe", "-NoProfile", "-Command", "(Get-PSDrive C).Free"], timeout=15
        )
        return int(value.decode().strip())
    return shutil.disk_usage("/").free


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    parser.add_argument("--compressed-bytes", type=int, required=True)
    parser.add_argument("--existing-bytes", type=int, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if "@sha256:" not in args.image:
        raise SystemExit("Pinned digest required")
    target = args.output
    if target is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        target = ROOT / "docs/research/image-admissions" / (stamp + ".json")
    if not target.resolve().is_relative_to(ROOT / "docs/research"):
        raise SystemExit("Admission record must stay inside repository research directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise SystemExit("Refusing to overwrite an admission record")
    estimate = admission_estimate(args.existing_bytes, args.compressed_bytes)
    report = {
        "image": args.image,
        "compressed_bytes": args.compressed_bytes,
        "admission_estimate": estimate,
        "existing_budget_bytes": args.existing_bytes,
        "working_limit_bytes": 24_000_000_000,
        "task_limit_bytes": 30_000_000_000,
        "physical_vhdx_peak": "not established by free-space delta",
        "state": "pending",
    }
    proc = None
    try:
        if estimate > 24_000_000_000:
            raise RuntimeError("Conservative estimate exceeds working budget")
        baseline = free_bytes()
        report["host_free_before_bytes"] = baseline
        if baseline < estimate:
            raise RuntimeError("Insufficient filesystem space for conservative admission")
        proc = subprocess.Popen(["docker", "pull", args.image], stdout=subprocess.DEVNULL)
        peak = 0
        while proc.poll() is None:
            growth = max(0, baseline - free_bytes())
            peak = max(peak, growth)
            if args.existing_bytes + growth >= 24_000_000_000:
                raise RuntimeError("Disk guard stopped pull")
            time.sleep(2)
        if proc.returncode:
            raise RuntimeError("Docker pull failed with exit " + str(proc.returncode))
        info = json.loads(subprocess.check_output(["docker", "image", "inspect", args.image]))[0]
        report.update(
            state="pulled",
            id=info["Id"],
            unpacked_bytes=info["Size"],
            observed_host_free_delta_peak=peak,
        )
    except Exception as error:
        report.update(state="rejected-or-failed", reason=type(error).__name__ + ": " + str(error))
        raise
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        with target.open("x") as output:
            json.dump(report, output, indent=2)
            output.write("\n")
        print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
