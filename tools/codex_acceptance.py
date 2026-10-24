"""Reproducible, side-effect-free test entry point for Codex/CI.

This script never connects to Telegram or OSM. Demo output is generated in a
temporary directory and both credentials and real customer data are unnecessary.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
RESTRICTED = {
    "leadhunter/mailer.py",
    "data/approved_recipients.json",
    "data/mail_sent.json",
    ".env",
}


def command(args: list[str], *, cwd: Path = ROOT, env=None) -> None:
    proc = subprocess.run(args, cwd=cwd, env=env, check=False)
    if proc.returncode:
        raise SystemExit(f"FAIL: {' '.join(args)} (exit {proc.returncode})")


def verify_tracked_files() -> None:
    tracked = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=False, capture_output=True
    )
    if tracked.returncode != 0:
        print("NOTE: no Git checkout; tracked-file verification unavailable")
        return
    paths = {p.decode("utf-8") for p in tracked.stdout.split(b"\0") if p}
    offenders = [
        path for path in paths
        if path in RESTRICTED or path.startswith(".env.")
        or (path.startswith("data/") and path.endswith(".private.json"))
    ]
    if offenders:
        raise SystemExit("FAIL: private data paths tracked in public repo: " + ", ".join(sorted(offenders)))
    print("PASS: no prohibited private-data filenames tracked")


def verify_config() -> None:
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    digest = (ROOT / ".github/workflows/lead-digest.yml").read_text(encoding="utf-8")
    assert "python tools/codex_acceptance.py" in ci
    assert "cron: '23 7 * * 1-5'" in digest
    assert "secrets.TELEGRAM_BOT_TOKEN" in digest
    assert "secrets.TELEGRAM_CHAT_ID" in digest
    assert "python -m leadhunter live" in digest
    assert "contents: write" in digest
    print("PASS: CI, owner secrets and weekdays 10:23 TRT cron configured")
    print("NOTE: cron config is NOT proof that a scheduled run happened")


def verify_demo() -> None:
    with tempfile.TemporaryDirectory(prefix="musteri-avcisi-codex-") as tmp:
        env = dict(os.environ)
        env.pop("TELEGRAM_BOT_TOKEN", None)
        env.pop("TELEGRAM_CHAT_ID", None)
        env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        command([sys.executable, "-m", "leadhunter", "demo"], cwd=Path(tmp), env=env)
        demo = (Path(tmp) / "dist/telegram-demo.txt").read_text(encoding="utf-8")
        expected = (
            "🔴 WEB SİTESİ FIRSATI",
            "🟢 OTOMASYON FIRSATI",
            "Premium web sitesi kapsamı:",
            "premium bir web sitesi",
            "Sonraki adım:",
            "DEMO — GERÇEK İŞLETME DEĞİL",
        )
        for item in expected:
            if item not in demo:
                raise SystemExit("FAIL: synthetic demo missing: " + item)
        if demo.count("🎯 <b>YENİ MÜŞTERİ FIRSATI</b>") != 2:
            raise SystemExit("FAIL: demo should contain exactly two fake examples")
    print("PASS: isolated red/green premium demo (no real messages)")


def main() -> None:
    print("=== Codex acceptance: offline only ===", flush=True)
    for file in (ROOT / "leadhunter").rglob("*.py"):
        compile(file.read_bytes(), str(file), "exec")
    for folder in (ROOT / "tests", ROOT / "tools"):
        for file in folder.rglob("*.py"):
            compile(file.read_bytes(), str(file), "exec")
    print("PASS: Python syntax", flush=True)
    command([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"])
    verify_tracked_files()
    verify_config()
    verify_demo()
    print("PASS: all OFFLINE Codex acceptance gates")
    print("LIVE Telegram send and scheduled GitHub run require separate evidence")


if __name__ == "__main__":
    main()
