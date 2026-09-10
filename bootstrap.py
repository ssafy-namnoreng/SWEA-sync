# -*- coding: utf-8 -*-
"""처음 실행할 때 필요한 것들을 대신 깔아 준다.

이 파일은 **표준 라이브러리만** 써야 한다.
아직 아무것도 안 깔린 PC 에서 가장 먼저 도는 코드이기 때문이다.
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

# (import 이름, pip 이름, 왜 필요한지)
REQUIRED = [
    ("playwright",  "playwright>=1.44", "SWEA 페이지를 읽고 파일을 받는 데 필요"),
    ("rich",        "rich>=13",         "콘솔 화면을 보기 좋게 그리는 데 필요"),
    ("questionary", "questionary>=2",   "설정을 방향키로 고르는 데 필요"),
]

YES = ("", "y", "yes", "네", "예", "ㅇ", "ㅛ")


def _has(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except Exception:
        return False


def missing_packages():
    return [(m, spec, why) for m, spec, why in REQUIRED if not _has(m)]


def _ask(prompt: str, auto_yes: bool) -> bool:
    if auto_yes:
        return True
    try:
        return input(prompt).strip().lower() in YES
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def ensure_packages(auto_yes: bool = False) -> bool:
    """없는 패키지를 pip 으로 설치한다. 이미 다 있으면 아무 것도 하지 않는다."""
    missing = missing_packages()
    if not missing:
        return True

    print()
    print("  처음 실행이라 필요한 것을 몇 개 설치해야 합니다.")
    for _, spec, why in missing:
        print(f"     - {spec:<20} {why}")
    print()

    if not _ask("  지금 설치할까요? [Y/n] ", auto_yes):
        print()
        print("  설치하지 않았습니다. 직접 하시려면 아래를 실행해주세요:")
        print(f"     {Path(sys.executable).name} -m pip install "
              + " ".join(spec for _, spec, _ in missing))
        return False

    cmd = [sys.executable, "-m", "pip", "install", *[spec for _, spec, _ in missing]]
    print(f"\n  설치 중입니다. 잠시 걸립니다...\n")
    try:
        subprocess.check_call(cmd)
    except FileNotFoundError:
        print("\n  [실패] pip 을 찾지 못했습니다. 파이썬을 다시 설치해보세요.")
        return False
    except subprocess.CalledProcessError as e:
        print(f"\n  [실패] 설치 중 오류가 났습니다 (종료 코드 {e.returncode}).")
        print("     인터넷 연결을 확인하거나, 사내망이면 프록시 설정이 필요할 수 있습니다.")
        return False

    importlib.invalidate_caches()
    still = missing_packages()
    if still:
        print("\n  [실패] 설치 후에도 다음을 찾지 못했습니다: "
              + ", ".join(m for m, _, _ in still))
        print("     터미널을 닫았다 다시 열고 실행해보세요.")
        return False

    print("\n  설치가 끝났습니다.\n")
    return True


# ---------------------------------------------------------------- 브라우저

# 이미 PC 에 있는 크롬을 찾는다. 있으면 Chromium 427MB 를 받지 않아도 된다.
SYSTEM_BROWSERS = [
    (r"C:\Program Files\Google\Chrome\Application\chrome.exe", "Google Chrome"),
    (r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe", "Google Chrome"),
    (os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"), "Google Chrome"),
    (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", "Microsoft Edge"),
    (r"C:\Program Files\Microsoft\Edge\Application\msedge.exe", "Microsoft Edge"),
]


def browser_running(port) -> bool:
    """자동화용 브라우저가 이미 떠 있는지. (안내를 띄울지 판단하는 데 쓴다)"""
    import json as _json
    import urllib.request as _req
    try:
        with _req.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as r:
            _json.loads(r.read().decode("utf-8"))
        return True
    except Exception:
        return False


def find_system_browser():
    """PC 에 깔려 있는 크롬/엣지 경로를 찾는다. 없으면 (None, None)."""
    for path, label in SYSTEM_BROWSERS:
        if path and Path(path).exists():
            return path, label
    return None, None


def ensure_browser(playwright_exe: str | None, auto_yes: bool = False):
    """쓸 브라우저를 정한다.  반환: (실행파일 경로, 무엇인지 설명) 또는 (None, 사유)

    순서
      1) playwright 로 이미 받아 둔 Chromium 이 있으면 그걸 쓴다 (기존 사용자 그대로)
      2) 없으면 PC 에 깔린 Chrome / Edge 를 쓴다  <- 427MB 를 안 받아도 된다
      3) 둘 다 없으면 그때만 Chromium 을 받겠냐고 묻는다
    """
    if playwright_exe and Path(playwright_exe).exists():
        return playwright_exe, "playwright Chromium"

    path, label = find_system_browser()
    if path:
        return path, label

    print()
    print("  자동화에 쓸 브라우저를 찾지 못했습니다.")
    print("  Chromium 을 받으면 됩니다. (약 150MB 다운로드, 1~3분)")
    print()
    if not _ask("  지금 받을까요? [Y/n] ", auto_yes):
        print("\n  받지 않았습니다. 직접 하시려면:")
        print(f"     {Path(sys.executable).name} -m playwright install chromium")
        return None, "브라우저 없음"

    try:
        subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
    except subprocess.CalledProcessError as e:
        print(f"\n  [실패] 내려받지 못했습니다 (종료 코드 {e.returncode}).")
        return None, "다운로드 실패"

    if playwright_exe and Path(playwright_exe).exists():
        return playwright_exe, "playwright Chromium"
    return None, "다운로드 후에도 찾지 못함"
