# -*- coding: utf-8 -*-
"""
SWEA Solving Club -> 팀 레포 자동 동기화

하는 일
  1) 그날의 problem box(문제 목록) 페이지에서 문제들을 읽어온다
  2) 각 문제마다  daily/<날짜>/<팀>/SWEA-<번호>/  폴더를 만들고
     - readme.md       : "# 제목 난이도" + "## [바로가기](링크)"
     - <원본파일명>.txt : SWEA에서 받은 sample input 을 파일명 그대로 저장
     을 생성한다

사용법
  python swea_sync.py                  # 열려 있는 브라우저의 SWEA 탭을 인식해서 진행
  python swea_sync.py "<문제목록 URL>"  # URL 직접 지정
  python swea_sync.py --inspect        # 페이지 구조 덤프 (셀렉터가 안 맞을 때)
자세한 내용은 README.md 참고.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import urllib.request
from datetime import date
from pathlib import Path
from urllib.parse import quote

import bootstrap

# playwright 는 '아직 안 깔렸을 수도 있는' 패키지라 여기서 바로 import 하지 않는다.
# bootstrap.ensure_packages() 로 설치를 마친 뒤 load_playwright() 가 채워 넣는다.
sync_playwright = None


class PWTimeout(Exception):
    """playwright 를 아직 못 불러왔을 때 쓰는 자리표시자."""


def load_playwright():
    global sync_playwright, PWTimeout
    from playwright.sync_api import sync_playwright as _sp, TimeoutError as _pt
    sync_playwright, PWTimeout = _sp, _pt

# 윈도우 콘솔(cp949)에서 한글 로그가 깨지지 않도록
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = Path(__file__).resolve().parent
SWEA_HOST = "swexpertacademy.com"
LIST_URL_HINTS = ("problemBoxDetail", "problemBox", "probBoxId", "solvingClub")

# 창을 띄웠을 때 처음 보여줄 페이지 (앞에서부터 시도).
# SWEA 메인 루트가 먼저다. 로그인 버튼이 여기 있고, 로그인 후 클럽으로 이동하면 된다.
# (login.do 는 본문이 빈 페이지, clubList.do 는 HTTP 405 라 둘 다 못 쓴다)
LANDING_URLS = (
    f"https://{SWEA_HOST}/main/main.do",
    f"https://{SWEA_HOST}/main/talk/solvingClub/clubMain.do",
)


# ---------------------------------------------------------------- config

SETTINGS_FILE = "settings.txt"

# settings.txt 에서 쓸 수 있는 키 이름들. 한글/영문 아무거나 써도 되게 한다.
KEY_ALIASES = {
    "repo_path":   ("경로", "레포경로", "레포", "저장소", "repo", "repo_path", "path"),
    "team":        ("팀", "팀이름", "조", "team"),
    "date":        ("날짜", "date", "day"),
    "list_url":    ("문제목록", "문제목록주소", "목록", "url", "list_url"),
    "headless":    ("창숨김", "숨김", "백그라운드", "headless"),
    "folder_title": ("폴더에제목", "폴더제목", "제목폴더", "foldertitle", "folder_title"),
    "folder_box":  ("폴더에박스", "폴더박스", "박스이름", "folderbox", "folder_box"),
    "readme":      ("readme", "readme생성", "리드미", "설명파일"),
    "rename_folders": ("폴더이름갱신", "이름갱신", "폴더갱신", "renamefolders", "rename_folders"),
    "layout":      ("폴더구조", "경로구조", "구조", "디렉토리", "layout", "folder_layout", "structure"),
    "profile_dir": ("브라우저프로필", "프로필", "profile", "profile_dir"),
    "cdp_port":    ("포트", "port", "cdp_port"),
}
TODAY_WORDS = ("", "오늘", "today", "auto", "자동")
TRUE_WORDS = ("예", "네", "응", "y", "yes", "true", "1", "on", "켬")
FALSE_WORDS = ("아니오", "아니요", "아뇨", "n", "no", "false", "0", "off", "끔")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_bool(value, field):
    v = str(value).strip().lower()
    if v in TRUE_WORDS:
        return True
    if v in ("",) or v in FALSE_WORDS:
        return False
    sys.exit(f"'{field}' 는 예 / 아니오 로 적어주세요. 지금 값: {value!r}")


def _canon_key(raw):
    """'브라우저 프로필', 'repo path' 처럼 띄어쓰기가 섞여도 알아듣게 한다."""
    k = re.sub(r"[\s_-]+", "", (raw or "")).lower()
    for canon, aliases in KEY_ALIASES.items():
        for a in aliases:
            if k == re.sub(r"[\s_-]+", "", a).lower():
                return canon
    return None


def _read_text_any(path):
    """인코딩이 뭐든 최대한 읽어낸다.

    조원이 메모장으로 열어 'ANSI'(cp949)로 저장해버리는 일이 흔해서,
    UTF-8(BOM 포함/미포함) -> cp949 순으로 시도한다.
    """
    data = path.read_bytes()
    for enc in ("utf-8-sig", "cp949", "utf-8"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def read_settings_file(path):
    """settings.txt 를 읽어 dict 로 돌려준다. '키 = 값', '#' 은 주석."""
    values, unknown = {}, []
    if not path.exists():
        return values, unknown

    for lineno, raw in enumerate(_read_text_any(path).splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            unknown.append(f"{lineno}행: '=' 가 없어 무시함 -> {line}")
            continue
        key, _, val = line.partition("=")
        canon = _canon_key(key)
        if not canon:
            unknown.append(f"{lineno}행: 모르는 항목 '{key.strip()}'")
            continue
        values[canon] = val.strip().strip('"').strip("'")
    return values, unknown


def set_setting_value(path, canon_key, value):
    """settings.txt 의 값 하나만 바꾼다.

    주석과 빈 줄, 인코딩(BOM), 줄바꿈 방식을 그대로 유지한다.
    설명이 잔뜩 달린 파일이라 통째로 다시 쓰면 안 된다.
    """
    raw = path.read_bytes()
    has_bom = raw.startswith(b"\xef\xbb\xbf")
    text = _read_text_any(path)
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()

    replaced = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, _, _old = line.partition("=")
        if _canon_key(key) == canon_key:
            lines[i] = f"{key}= {value}".rstrip()
            replaced = True
            break

    if not replaced:                     # 없던 항목이면 끝에 추가
        names = KEY_ALIASES.get(canon_key) or (canon_key,)
        lines += ["", f"{names[0]} = {value}"]

    out = newline.join(lines) + newline
    path.write_bytes(out.encode("utf-8-sig" if has_bom else "utf-8"))
    return replaced


def check_repo_path(text):
    """사람이 입력한 레포 경로를 다듬고 살펴본다.

    반환: (쓸 수 있나, 정리된 경로, 알려줄 말)
    붙여넣기 하면 따옴표가 딸려오는 일이 흔해서 먼저 떼어낸다.
    """
    raw = (text or "").strip().strip('"').strip("'").strip()
    if not raw:
        return False, "", "경로가 비어 있습니다."

    try:
        p = Path(raw).expanduser()
    except Exception:
        return False, raw, "경로 형태가 아닙니다."

    if not p.exists():
        return False, str(p), f"그런 폴더가 없습니다: {p}"
    if not p.is_dir():
        return False, str(p), f"폴더가 아니라 파일입니다: {p}"

    p = p.resolve()
    # 반 레포처럼 daily 폴더가 있으면 그걸 힌트로 상위/하위를 한 번 맞춰준다.
    # 없어도 상관없다 - 폴더 구조는 사용자가 정하니까.
    if (p / "daily").is_dir():
        return True, str(p), "확인했습니다. (daily 폴더 있음)"
    if p.name == "daily" and p.parent.is_dir():
        return True, str(p.parent), f"daily 안쪽을 고르신 것 같아 상위로 잡았습니다: {p.parent}"
    for child in sorted(x for x in p.iterdir() if x.is_dir()):
        if (child / "daily").is_dir():
            return True, str(child), f"바로 아래 {child.name} 폴더에 daily 가 있어 그쪽으로 잡았습니다."
    return True, str(p), "확인했습니다."


def load_config(args, strict=True) -> dict:
    """기본값 < settings.txt < 명령줄 옵션 순으로 덮어쓴다."""
    cfg = {
        "repo_path": "",
        "team": "",
        "date": "",
        "list_url": "",
        "headless": "",
        "folder_title": "",     # 폴더명에 문제 제목까지 넣을지 (기본: 번호만)
        "folder_box": "",       # 폴더명에 문제 박스 이름까지 넣을지
        "readme": "예",          # readme.md 를 만들지 (기본: 만든다)
        "rename_folders": "",   # 이미 있는 폴더 이름을 지금 설정에 맞게 바꿀지
        "layout": "",           # 문제 폴더들이 들어갈 상위 경로 (레포 기준 상대 경로)
        "profile_dir": "",
        "cdp_port": 9222,
    }

    spath = settings_path()
    file_values, unknown = read_settings_file(spath)
    for w in unknown:
        print(f"[!] {settings_label()} {w}")
    cfg.update({k: v for k, v in file_values.items() if v != ""})

    # 명령줄 옵션이 있으면 그게 이긴다
    if args.repo:
        cfg["repo_path"] = args.repo
    if args.team:
        cfg["team"] = args.team
    if args.date:
        cfg["date"] = args.date
    if args.url:
        cfg["list_url"] = args.url
    if getattr(args, "layout", None):
        cfg["layout"] = args.layout

    try:
        cfg["layout"] = check_layout(cfg["layout"])
    except ValueError as e:
        sys.exit(f"{SETTINGS_FILE} 의 '폴더구조' 가 잘못됐습니다.\n  {e}")

    cfg["headless"] = parse_bool(cfg["headless"], "창숨김")
    if args.headless:
        cfg["headless"] = True
    if args.show:
        cfg["headless"] = False

    cfg["folder_title"] = parse_bool(cfg["folder_title"], "폴더에제목")
    if args.folder_title:
        cfg["folder_title"] = True
    if args.no_folder_title:
        cfg["folder_title"] = False

    cfg["folder_box"] = parse_bool(cfg["folder_box"], "폴더에박스")
    if args.folder_box:
        cfg["folder_box"] = True
    if args.no_folder_box:
        cfg["folder_box"] = False

    cfg["readme"] = parse_bool(cfg["readme"], "readme")
    if args.no_readme:
        cfg["readme"] = False

    cfg["rename_folders"] = parse_bool(cfg["rename_folders"], "폴더이름갱신")
    if args.rename_folders:
        cfg["rename_folders"] = True
    if args.no_rename_folders:
        cfg["rename_folders"] = False

    # 날짜: 비어 있거나 '오늘' 이면 오늘 날짜
    if str(cfg["date"]).strip().lower() in TODAY_WORDS:
        cfg["date"] = date.today().isoformat()
    elif not DATE_RE.match(str(cfg["date"]).strip()):
        sys.exit(f"날짜 형식이 잘못됐습니다: {cfg['date']!r}\n"
                 f"  YYYY-MM-DD 로 적어주세요. 예) 2026-09-01\n"
                 f"  오늘 날짜를 쓰려면 {SETTINGS_FILE} 의 '날짜' 를 비워두면 됩니다.")
    cfg["date"] = str(cfg["date"]).strip()

    if not cfg["profile_dir"]:
        cfg["profile_dir"] = str(Path.home() / ".swea_sync" / "chrome-profile")

    try:
        cfg["cdp_port"] = int(str(cfg["cdp_port"]).strip())
    except ValueError:
        sys.exit(f"포트는 숫자여야 합니다: {cfg['cdp_port']!r}")

    if not spath.exists():
        sys.exit(f"{spath} 가 없습니다.\n"
                 f"  배포받은 {SETTINGS_FILE} 을 이 폴더에 두고 다시 실행해주세요.")
    # strict=False 면 비어 있어도 그냥 돌려준다. 부르는 쪽에서 설정 마법사를 띄운다.
    if strict and not cfg["repo_path"]:
        sys.exit(f"{SETTINGS_FILE} 의 '경로' 가 비어 있습니다.\n"
                 f"  문제 폴더들을 만들어 넣을 최상위 폴더 경로를 적어주세요.\n"
                 f"  예)  경로 = C:/Users/내계정/PycharmProjects/algorithm")
    if strict and not cfg["team"]:
        sys.exit(f"{SETTINGS_FILE} 의 '팀' 이 비어 있습니다.\n"
                 f"  자기 조 폴더명을 적어주세요.  예)  팀 = team-E")
    # 창숨김은 열린 탭을 볼 수 없으니 문제 목록 주소가 있어야 한다.
    # 없으면 막는 대신 창을 띄운다 (그래야 탭을 보고 진행할 수 있다).
    if cfg["headless"] and not cfg["list_url"]:
        print(f"[i] '문제목록' 주소가 없어서 이번엔 창을 띄웁니다."
              f"  (창숨김으로 쓰려면 {SETTINGS_FILE} 의 '문제목록' 을 채워주세요)")
        cfg["headless"] = False
    return cfg


# ---------------------------------------------------------------- browser

def _debug_port_alive(endpoint, timeout=2.0) -> bool:
    """CDP HTTP 엔드포인트가 응답하는지만 가볍게 확인한다.

    connect_over_cdp 를 바로 여러 번 때리면 websocket 연결이 쌓여서 오히려
    핸드셰이크가 타임아웃난다. 그래서 먼저 HTTP 로 살아있는지만 본다.
    """
    try:
        with urllib.request.urlopen(f"{endpoint}/json/version", timeout=timeout) as r:
            json.loads(r.read().decode("utf-8"))
        return True
    except Exception:
        return False


def kill_process_tree(proc):
    """창숨김으로 띄운 브라우저를 확실히 정리한다.

    CDP 로 붙은 경우 browser.close() 만으로는 자식 프로세스가 남는다.
    보이지 않는 창이라 사용자가 눈치챌 수 없으므로 프로세스 트리째 종료한다.
    """
    if proc is None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True, timeout=15)
        else:
            proc.terminate()
    except Exception:
        pass


def attach_browser(pw, cfg):
    """이미 열려 있는 브라우저에 붙고, 없으면 새로 띄운다. 반환: (context, launched_now, proc)

    브라우저는 이 스크립트와 별개 프로세스로 띄운다. 그래야 스크립트가 끝나도
    창이 살아 있어서, 다음 실행 때 로그인 세션과 열어둔 탭을 그대로 재사용한다.
    """
    endpoint = f"http://127.0.0.1:{cfg['cdp_port']}"
    headless = cfg["headless"]
    launched = False
    proc = None

    # 창숨김은 어디까지나 '가능하면' 이다. 안 되는 상황이면 조용히 창을 띄운다.
    # 실행 파일 하나로 끝내려면, 막다른 길을 만들지 않는 게 중요하다.
    if headless and _debug_port_alive(endpoint):
        print("[i] 자동화용 크롬 창이 이미 떠 있어서 그 창을 씁니다. (창숨김 해제)")
        headless = cfg["headless"] = False

    if not _debug_port_alive(endpoint):
        profile = Path(cfg["profile_dir"])
        if headless and not any(profile.glob("**/Cookies")):
            print("[i] 아직 SWEA 로그인 기록이 없어서 이번엔 창을 띄웁니다.")
            print("    로그인해두면 다음 실행부터 창숨김으로 돕니다.")
            headless = cfg["headless"] = False
        profile.mkdir(parents=True, exist_ok=True)
        exe, kind = bootstrap.ensure_browser(pw.chromium.executable_path,
                                             auto_yes=cfg.get("auto_yes", False))
        if not exe:
            sys.exit(f"브라우저를 준비하지 못했습니다 ({kind}).")
        if kind != "playwright Chromium":
            print(f"[i] PC 에 있는 {kind} 를 씁니다. (Chromium 을 따로 받지 않아도 됩니다)")
        cmd = [
            exe,
            f"--remote-debugging-port={cfg['cdp_port']}",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            # 시작 페이지는 반드시 about:blank.
            # 느린 페이지를 첫 타깃으로 열면 CDP 핸드셰이크가 타임아웃난다.
            "about:blank",
        ]
        cmd[-1:-1] = ["--headless=new", "--window-size=1400,1000"] if headless else ["--start-maximized"]
        creation = (getattr(subprocess, "DETACHED_PROCESS", 0)
                    | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        proc = subprocess.Popen(cmd, creationflags=creation, close_fds=True)
        print("[i] 브라우저를 " + ("창 없이(창숨김) 띄웠습니다" if headless else "새로 띄웠습니다")
              + f" (프로필: {profile})")
        launched = True

        for _ in range(30):
            time.sleep(1)
            if _debug_port_alive(endpoint):
                break
        else:
            sys.exit(f"브라우저가 뜨지 않았습니다 ({endpoint}).\n"
                     "  대부분은 이전에 쓰던 자동화용 크롬이 아직 살아 있어서입니다.\n"
                     "  작업 관리자에서 chrome.exe 를 정리하거나 PC를 재시작한 뒤 다시 실행해주세요.\n"
                     f"  그래도 안 되면 {SETTINGS_FILE} 의 '포트' 를 9223 등으로 바꿔보세요.")
    else:
        print(f"[i] 실행 중인 브라우저를 찾았습니다 ({endpoint})")

    try:
        browser = pw.chromium.connect_over_cdp(endpoint, timeout=30000)
    except Exception as e:
        sys.exit(f"브라우저에 연결하지 못했습니다 ({endpoint}): {type(e).__name__}\n"
                 f"자동화용 크롬 창을 모두 닫고 다시 실행해보세요.")
    if not browser.contexts:
        sys.exit("브라우저 컨텍스트를 찾지 못했습니다. 창을 닫고 다시 실행해주세요.")
    return browser.contexts[0], launched, proc


def find_swea_page(ctx, url, headless=False):
    """작업 대상 페이지를 정한다. url 이 있으면 그 URL 로, 없으면 열린 SWEA 탭을 찾는다."""
    if url:
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded")
        return page

    if headless:
        sys.exit("창숨김 모드에서는 문제 목록 주소가 필요합니다.\n"
                 f"  {SETTINGS_FILE} 의 '문제목록' 에 그날 문제 박스 주소를 붙여넣거나,\n"
                 "  python swea_sync.py \"<문제목록 주소>\" 처럼 실행해주세요.\n"
                 "  (창을 띄워 쓰는 방식이면 창숨김 = 아니오 로 두면 됩니다)")

    page = _pick_list_tab(ctx)
    if page:
        print(f"[i] 열려 있는 SWEA 탭을 사용합니다:\n    {page.url}")
        return page

    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    if SWEA_HOST not in page.url:
        goto_landing(page)
    print()
    print("  브라우저 오른쪽 위 '로그인' 으로 로그인한 뒤,")
    print("  Solving Club > 우리 반 클럽 > 오늘 풀 '문제 박스' 페이지를 열어주세요.")
    try:
        input("  준비되면 이 창에서 Enter > ")
    except (EOFError, KeyboardInterrupt):
        sys.exit("\n입력을 받지 못해 중단했습니다.")
    return _pick_list_tab(ctx) or page


def goto_landing(page):
    """로그인부터 시작할 수 있게 SWEA 메인 페이지를 연다."""
    for url in LANDING_URLS:
        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=45000)
            if resp is None or resp.ok:
                return url
        except Exception:
            continue
    return None


def _pick_list_tab(ctx):
    """열린 탭 중 '문제 목록'에 가장 가까운 탭을 고른다.

    1순위: 실제로 문제 행(.widget-box-sub)이 그려져 있는 SWEA 탭
    2순위: URL 에 probBoxId / problemBox 가 있는 SWEA 탭
    """
    fallback = None
    for page in ctx.pages:
        try:
            u = page.url
        except Exception:
            continue
        if SWEA_HOST not in u:
            continue
        try:
            if page.locator(ROW_SELECTOR).count():
                return page
        except Exception:
            pass
        if fallback is None and any(h in u for h in LIST_URL_HINTS):
            fallback = page
    return fallback


# ---------------------------------------------------------------- scraping

DIFF_RE = re.compile(r"\bD[1-5]\b")


def norm(text):
    text = unicodedata.normalize("NFC", text or "")
    return re.sub(r"\s+", " ", text).strip()


ROW_SELECTOR = ".widget-box-sub"
CLICK_PROBLEM_RE = re.compile(r"""clickProblem\(\s*['"]([^'"]+)['"]\s*,\s*['"]([^'"]+)['"]""")
BOX_TITLE_RE = re.compile(r"^(.*?)\s*\(\s*(\d+)\s*\)\s*$")


ROWS_JS = """els => els.map(el => {
    const q = s => el.querySelector(s);
    const num  = q('.week_num');
    const link = q('.week_text a');

    // 제목: 이미 푼 문제는 앵커 안에 <span class="badge">정답</span> 이 들어온다.
    // 배지를 떼고 순수 제목만 뽑는다.
    let title = '';
    if (link) {
        const clone = link.cloneNode(true);
        clone.querySelectorAll('.badge').forEach(b => b.remove());
        title = (clone.textContent || '').trim();
    }

    // 난이도: 오른쪽 툴바의 배지가 난이도다.
    // (앵커 안 '정답' 배지를 집지 않도록 D1~D5 형태인지 확인한다)
    let diff = '';
    const toolbar = q('.widget-toolbar-sub .badge');
    if (toolbar) diff = (toolbar.textContent || '').trim();
    if (!/\\bD[1-5]\\b/.test(diff)) {
        diff = '';
        for (const b of el.querySelectorAll('.badge')) {
            const t = (b.textContent || '').trim();
            if (/^D[1-5]$/.test(t)) { diff = t; break; }
        }
    }

    return {
        num:   num  ? (num.textContent || '').trim() : '',
        title: title,
        href:  link ? (link.getAttribute('href') || '') : '',
        badge: diff
    };
})"""

BOX_INFO_JS = """() => {
    const v = id => (document.getElementById(id) || {}).value || '';
    const h4 = document.querySelector('.right_con .club_box_tit')
            || document.querySelector('.club_box_tit');
    // 클럽 이름은 왼쪽 패널 제목이다. (.club_name 은 회원 이름이라 쓰면 안 된다)
    const club = document.querySelector('.left_con h3')
              || document.querySelector('[class*=club_tit]');
    return {
        solveclubId: v('solveclubId'),
        probBoxId:   v('probBoxId'),
        boxTitleRaw: h4 ? (h4.innerText || '').trim() : '',
        clubName:    club ? (club.innerText || '').trim() : ''
    };
}"""

PAGE_SIZE = 30          # 사이트가 주는 최대값 (10 / 20 / 30)
MAX_PAGES = 50          # 무한 루프 방지용 상한


def read_box_info(page):
    """문제 박스 페이지에서 링크 조립·폴더 이름에 필요한 전역 값을 읽는다."""
    info = page.evaluate(BOX_INFO_JS)
    m = BOX_TITLE_RE.match(info.get("boxTitleRaw", ""))
    info["boxTitle"] = m.group(1).strip() if m else norm(info.get("boxTitleRaw", ""))
    info["boxCnt"] = m.group(2) if m else ""
    info["clubName"] = norm(info.get("clubName", ""))
    return info


def parse_rows(page, ctxinfo, seen):
    """지금 보이는 페이지의 문제 행들을 읽는다. seen 에 있는 건 건너뛴다."""
    out = []
    for r in page.eval_on_selector_all(ROW_SELECTOR, ROWS_JS):
        mm = CLICK_PROBLEM_RE.search(r["href"] or "")
        if not mm:
            continue
        cid, ptype = mm.group(1), mm.group(2)
        if cid in seen:
            continue
        seen.add(cid)

        num = re.sub(r"\D", "", r["num"] or "")
        title = norm(r["title"])
        dm = DIFF_RE.search(norm(r["badge"]))
        out.append({
            "number": num or None,
            "title": title or None,
            "difficulty": dm.group(0) if dm else None,
            "contest_prob_id": cid,
            "type": ptype,
            "url": build_problem_url(ctxinfo, cid, ptype),
        })
    return out


def box_page_url(ctxinfo, page_index, page_size=None):
    """문제 박스의 N번째 페이지 주소. 사이트가 pageSize / pageIndex 를 GET 으로 받는다."""
    if page_size is None:
        page_size = PAGE_SIZE           # 기본 인자로 묶으면 정의 시점 값에 고정되므로 여기서 읽는다
    return (f"https://{SWEA_HOST}/main/talk/solvingClub/problemBoxDetail.do"
            f"?solveclubId={quote(ctxinfo.get('solveclubId', ''), safe='')}"
            f"&probBoxId={quote(ctxinfo.get('probBoxId', ''), safe='')}"
            f"&pageSize={page_size}&pageIndex={page_index}")


def collect_problems(page, ctx=None, on_page=None):
    """문제 박스의 문제를 전부 긁는다. 여러 페이지로 나뉘어 있으면 끝까지 넘긴다.

    실제 DOM 구조:
      <div class="widget-box-sub">
        <span class="week_num">4836 .</span>
        <span class="week_text">
          <a href="javascript:clickProblem('CCCCprobIdCCCC','PROBLEM');">제목</a>
        </span>
        <span class="badge badge-a">D2 </span>
      </div>
    번호·제목·난이도·contestProbId·type 이 전부 목록에 있어서
    상세 페이지를 열지 않고도 readme 에 쓸 링크를 그대로 조립할 수 있다.

    페이지 넘기기는 사용자가 보고 있는 탭이 아니라 새 탭에서 한다.
    (ctx 가 없으면 지금 탭 한 페이지만 읽는다)
    """
    page.wait_for_load_state("domcontentloaded")
    try:
        page.wait_for_selector(ROW_SELECTOR, timeout=15000)
    except PWTimeout:
        return [], {}

    ctxinfo = read_box_info(page)
    seen = set()
    problems = parse_rows(page, ctxinfo, seen)

    expected = int(ctxinfo["boxCnt"]) if str(ctxinfo["boxCnt"]).isdigit() else None
    if expected is None or len(problems) >= expected or ctx is None \
            or not ctxinfo.get("probBoxId"):
        return problems, ctxinfo

    # 한 페이지에 다 안 들어온다. 새 탭에서 30개씩으로 놓고 끝까지 넘긴다.
    work = ctx.new_page()
    try:
        problems, seen = [], set()      # 30개씩 기준으로 처음부터 다시 읽는다
        for idx in range(1, MAX_PAGES + 1):
            work.goto(box_page_url(ctxinfo, idx), wait_until="domcontentloaded",
                      timeout=60000)
            try:
                work.wait_for_selector(ROW_SELECTOR, timeout=8000)
            except PWTimeout:
                break                   # 행이 없는 페이지 = 끝
            got = parse_rows(work, ctxinfo, seen)
            if not got:
                break                   # 새로 읽힌 게 없으면 끝
            problems += got
            if on_page:
                on_page(idx, len(got), len(problems), expected)
            if len(problems) >= expected:
                break
    finally:
        work.close()
    return problems, ctxinfo


def build_problem_url(ctxinfo, contest_prob_id, ptype):
    """team-E readme 에 쓰던 것과 동일한 형태의 바로가기 링크를 만든다."""
    params = {
        "solveclubId": ctxinfo.get("solveclubId", ""),
        "contestProbId": contest_prob_id,
        "probBoxId": ctxinfo.get("probBoxId", ""),
        "type": ptype,
        "problemBoxTitle": ctxinfo.get("boxTitle", ""),
        "problemBoxCnt": ctxinfo.get("boxCnt", ""),
    }
    query = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in params.items())
    return f"https://{SWEA_HOST}/main/talk/solvingClub/problemView.do?{query}"


def _say(ui, msg):
    """실행 중 한 줄 알림. ui 가 있으면 꾸며서, 없으면 기존 형식으로."""
    if ui:
        ui.step(msg)
    else:
        print(f"      - {msg}")


# 1순위가 실제로 확인된 셀렉터. 나머지는 페이지가 바뀔 때를 위한 예비.
DOWNLOAD_SELECTORS = [
    'a[href*="Down.do"][href*="downType=in"]',
    'a[href*="downType=in"]',
    'a[href*="contestProbDown.do"]',
    'a[href*="fileDownload"]',
    "a[download]",
]


def download_sample_input(page, dest_dir, force, ui=None):
    """sample input 링크를 찾아 SWEA 원본 파일명 그대로 저장한다.

    SWEA 는 링크 텍스트 자체가 파일명이다 (예: "sample_input.txt", "input.txt").
    그래서 링크 텍스트를 1순위로 쓰고, 없으면 브라우저가 알려준 이름을 쓴다.
    """
    for sel in DOWNLOAD_SELECTORS:
        try:
            loc = page.locator(sel).first
            if not loc.count():
                continue
            link_name = norm(loc.inner_text())
            with page.expect_download(timeout=20000) as dl_info:
                loc.click()
            dl = dl_info.value
            name = link_name if link_name.lower().endswith(".txt") else ""
            name = name or dl.suggested_filename or "sample_input.txt"
            name = Path(name).name  # 경로 구분자 방어
            target = dest_dir / name
            if target.exists() and not force:
                _say(ui, f"input 이미 있음, 건너뜀: {name}")
                return name
            dl.save_as(str(target))
            _say(ui, f"input 저장: {name}")
            return name
        except PWTimeout:
            continue
        except Exception:
            continue
    return None


def dump_anchors(page, label):
    anchors = page.eval_on_selector_all(
        "a",
        "els => els.slice(0,400).map(a => ((a.innerText||'').trim().slice(0,40)) + ' || ' + a.getAttribute('href'))",
    )
    print(f"      [inspect] {label} 의 링크 {len(anchors)}개:")
    for a in anchors:
        tail = a.split("||")[-1].strip()
        if tail and tail not in ("None", "#", "javascript:;"):
            print("        ", a)


# ---------------------------------------------------------------- output

# 윈도우 폴더명에 쓸 수 없는 글자.  [S/W 문제해결 기본] 처럼 제목에 '/' 가 흔하다.
BAD_PATH_CHARS = str.maketrans({c: "-" for c in '\\/:*?"<>|'})
TITLE_MAX = 50          # 경로가 너무 길어지지 않게 제목 부분만 잘라낸다


def safe_folder_title(title):
    """문제 제목을 폴더명에 쓸 수 있게 다듬는다."""
    name = norm(title).translate(BAD_PATH_CHARS)
    name = re.sub(r"-{2,}", "-", name)            # '- -' 처럼 겹친 하이픈 정리
    name = name.strip(" .-")                      # 윈도우는 끝의 점/공백을 못 쓴다
    if len(name) > TITLE_MAX:
        name = name[:TITLE_MAX].rstrip(" .-") + "…"
    return name


BOX_MAX = 30            # 박스 이름도 길어질 수 있으니 잘라둔다


# ---------------------------------------------------------------- 프로필
# 프로필 하나 = 레포 경로 + 그 경로에서 쓰는 설정 전부.
# profiles/<이름>.txt 로 저장하고, profiles/_current.txt 에 지금 쓰는 이름을 적어둔다.
# 파일 형식은 settings.txt 와 똑같아서 read/set_setting_value 를 그대로 쓴다.

PROFILES_DIR = "profiles"
CURRENT_MARK = "_current.txt"
DEFAULT_PROFILE = "기본"

# 프로필을 새로 만들 때 원본에서 비워야 하는 것들 (경로마다 다른 값)
PER_PROFILE_KEYS = ("repo_path", "team", "date", "list_url")


def profiles_dir() -> Path:
    return HERE / PROFILES_DIR


def valid_profile_name(name):
    """프로필 이름은 파일 이름이 된다. 못 쓰는 글자를 정리하고 비면 None."""
    name = safe_folder_title((name or "").strip())[:40].strip(" .-")
    return name or None


def profile_path(name) -> Path:
    return profiles_dir() / f"{name}.txt"


def list_profiles():
    d = profiles_dir()
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.txt") if not p.name.startswith("_"))


def current_profile() -> str:
    mark = profiles_dir() / CURRENT_MARK
    if mark.exists():
        name = _read_text_any(mark).strip()
        if name and profile_path(name).exists():
            return name
    names = list_profiles()
    return names[0] if names else ""


def set_current_profile(name):
    profiles_dir().mkdir(parents=True, exist_ok=True)
    (profiles_dir() / CURRENT_MARK).write_text(name, encoding="utf-8")


def settings_path() -> Path:
    """지금 쓰는 설정 파일. 프로필이 하나도 없으면 옛 방식(settings.txt)으로 간다."""
    name = _forced_profile or current_profile()
    if name:
        return profile_path(name)
    return HERE / SETTINGS_FILE


_forced_profile = ""        # --profile 로 이번 실행만 다른 프로필을 쓸 때


def settings_label() -> str:
    name = _forced_profile or current_profile()
    return f"프로필 '{name}'" if name else SETTINGS_FILE


def create_profile(name, source: Path | None = None, inherit=True) -> Path:
    """새 프로필 파일을 만든다.

    source 가 있으면 그걸 복사한다 (보통 지금 프로필 - 취향 설정을 물려받는다).
    없으면 배포된 settings.txt 템플릿을 쓴다. 경로마다 달라야 하는 값은 비운다.
    """
    dest = profile_path(name)
    if dest.exists():
        raise FileExistsError(f"이미 있는 프로필입니다: {name}")
    profiles_dir().mkdir(parents=True, exist_ok=True)

    template = source if (source and source.exists() and inherit) else (HERE / SETTINGS_FILE)
    if template.exists():
        dest.write_bytes(template.read_bytes())
    else:
        dest.write_text("", encoding="utf-8")
    for key in PER_PROFILE_KEYS:
        set_setting_value(dest, key, "")
    return dest


def delete_profile(name):
    p = profile_path(name)
    if p.exists():
        p.unlink()
    if current_profile() == name:
        names = list_profiles()
        if names:
            set_current_profile(names[0])
        else:
            mark = profiles_dir() / CURRENT_MARK
            if mark.exists():
                mark.unlink()


def migrate_legacy_settings():
    """예전 방식(settings.txt 하나)에서 넘어온 사람을 위해 '기본' 프로필로 옮겨준다.

    settings.txt 에 경로가 채워져 있고 profiles/ 가 아직 없을 때만.
    원본 settings.txt 는 새 프로필의 템플릿으로 계속 쓰이므로 지우지 않는다.
    """
    legacy = HERE / SETTINGS_FILE
    if profiles_dir().is_dir() and list_profiles():
        return None
    if not legacy.exists():
        return None
    values, _ = read_settings_file(legacy)
    if not values.get("repo_path"):
        return None
    profiles_dir().mkdir(parents=True, exist_ok=True)
    dest = profile_path(DEFAULT_PROFILE)
    dest.write_bytes(legacy.read_bytes())
    set_current_profile(DEFAULT_PROFILE)
    # 템플릿에 개인 경로가 남아 있으면 새 프로필을 만들 때 딸려온다
    for key in PER_PROFILE_KEYS:
        set_setting_value(legacy, key, "")
    return DEFAULT_PROFILE


# ---------------------------------------------------------------- 폴더 구조

DEFAULT_LAYOUT = "daily/{날짜}/{팀}"

# '{날짜}' 처럼 중괄호로 쓰는 자리표시자. 한글/영문 아무거나 된다.
LAYOUT_PLACEHOLDERS = {
    "날짜": "date",  "date": "date",
    "년":   "year",  "year": "year",
    "월":   "month", "month": "month",
    "일":   "day",   "day": "day",
    "팀":   "team",  "조": "team", "team": "team",
    "클럽": "club",  "club": "club",
    "박스": "box",   "box": "box",
}
PLACEHOLDER_RE = re.compile(r"\{([^{}]*)\}")


def layout_placeholders(template):
    """템플릿에 쓰인 자리표시자들을 정규화된 이름으로 돌려준다. 모르는 게 있으면 ValueError."""
    out, bad = set(), []
    for raw in PLACEHOLDER_RE.findall(template or ""):
        key = re.sub(r"\s+", "", raw).lower()
        canon = LAYOUT_PLACEHOLDERS.get(key)
        if canon:
            out.add(canon)
        else:
            bad.append(raw)
    if bad:
        raise ValueError(
            f"모르는 자리표시자: {', '.join('{' + b + '}' for b in bad)}\n"
            "  쓸 수 있는 것: {날짜} {년} {월} {일} {팀} {클럽} {박스}")
    return out


def check_layout(template):
    """폴더 구조 템플릿이 쓸 만한지 미리 본다. 값은 실행 때 채워지므로 형태만 본다."""
    t = (template or "").strip().strip('"').strip("'")
    if not t:
        return DEFAULT_LAYOUT
    layout_placeholders(t)                          # 모르는 자리표시자면 여기서 터진다
    if re.match(r"^[A-Za-z]:", t) or t.startswith(("/", "\\")):
        raise ValueError("폴더 구조는 레포 안의 상대 경로여야 합니다. 'C:/' 나 '/' 로 시작할 수 없습니다.")
    for seg in re.split(r"[\\/]+", t):
        if seg.strip() == "..":
            raise ValueError("폴더 구조에 '..' 는 쓸 수 없습니다.")
    return t


def render_layout(template, values):
    """템플릿에 실제 값을 채워 레포 아래 상대 경로(Path)를 만든다.

    values: date / year / month / day / team / club / box
    각 폴더 이름은 윈도우에서 못 쓰는 글자를 정리하고, 비어 있으면 건너뛴다.
    """
    def fill(m):
        key = re.sub(r"\s+", "", m.group(1)).lower()
        canon = LAYOUT_PLACEHOLDERS.get(key, key)
        return str(values.get(canon, "") or "")

    filled = PLACEHOLDER_RE.sub(fill, template)
    parts = []
    for seg in re.split(r"[\\/]+", filled):
        seg = safe_folder_title(seg)
        if seg and seg != "..":
            parts.append(seg)
    if not parts:
        raise ValueError(f"폴더 구조 '{template}' 를 채웠더니 비어 버렸습니다. "
                         "클럽/박스 이름을 못 읽었을 수 있습니다.")
    return Path(*parts)


def layout_values(cfg, boxinfo):
    """render_layout 에 넣을 값들."""
    d = cfg["date"]
    y, mo, dd = (d.split("-") + ["", "", ""])[:3]
    return {
        "date": d, "year": y, "month": mo, "day": dd,
        "team": cfg.get("team", ""),
        "club": (boxinfo or {}).get("clubName", ""),
        "box":  (boxinfo or {}).get("boxTitle", ""),
    }


def problem_folder(day_dir, number, title, with_title, box_name=""):
    """이 문제가 쓸 폴더를 정한다.

    형태:  SWEA-<번호>[(<박스>)][-<제목>]
      예)  SWEA-4875
           SWEA-4875-[S-W 문제해결 기본] 5일차 - 미로
           SWEA-4875(Stack2_1)-[S-W 문제해결 기본] 5일차 - 미로

    이미 SWEA-<번호> 로 시작하는 폴더가 있으면 그걸 그대로 쓴다.
    설정을 바꿨다고 해서 같은 문제에 폴더가 두 개 생기면 안 되기 때문이다.
    (`SWEA-122*` 처럼 뭉뚱그리면 SWEA-1222 와 SWEA-12234 가 섞이므로
     구분자까지 붙여 정확히 매칭한다)
    """
    existing = find_existing_folder(day_dir, number)
    if existing:
        return existing
    return day_dir / desired_folder_name(number, title, with_title, box_name)


def find_existing_folder(day_dir, number):
    """이 문제로 이미 만들어 둔 폴더를 찾는다. 없으면 None.

    `SWEA-122*` 처럼 뭉뚱그리면 SWEA-1222 와 SWEA-12234 가 섞이므로
    구분자까지 붙여 정확히 매칭한다.
    """
    for pat in (f"SWEA-{number}", f"SWEA-{number}-*", f"SWEA-{number}(*"):
        for p in sorted(day_dir.glob(pat)):
            if p.is_dir():
                return p
    return None


def desired_folder_name(number, title, with_title, box_name=""):
    """지금 설정대로라면 이 문제의 폴더 이름은 무엇인지."""
    name = f"SWEA-{number}"
    if box_name:
        box = safe_folder_title(box_name)[:BOX_MAX].strip(" .-")
        if box:
            name += f"({box})"
    if with_title:
        pretty = safe_folder_title(title)
        if pretty:
            name += f"-{pretty}"
    return name


def plan_renames(day_dir, problems, box_title, cfg):
    """이름이 달라진 폴더들을 찾아 (지금 폴더, 바꿀 폴더) 목록으로 돌려준다."""
    pairs = []
    for prob in problems:
        number, title = prob.get("number"), prob.get("title")
        if not number or not title:
            continue
        old = find_existing_folder(day_dir, number)
        if not old:
            continue
        want = desired_folder_name(number, title, cfg["folder_title"],
                                   box_title if cfg["folder_box"] else "")
        if old.name != want:
            pairs.append((old, day_dir / want))
    return pairs


def apply_renames(pairs):
    """폴더 이름을 바꾼다. 반환: (성공 목록, 실패 목록[(폴더, 사유)])"""
    done, failed = [], []
    for old, new in pairs:
        try:
            if new.exists():
                failed.append((old.name, f"'{new.name}' 이 이미 있습니다"))
                continue
            old.rename(new)
            done.append((old.name, new.name))
        except OSError as e:
            # 폴더 안 파일이 편집기 등에서 열려 있으면 윈도우가 막는다
            failed.append((old.name, f"{type(e).__name__}: {e}"))
    return done, failed


README_TMPL = "# {title}{diff}\r\n\r\n## [바로가기]({url})\r\n"


def write_readme(dest_dir, title, difficulty, url, force, ui=None):
    path = dest_dir / "readme.md"
    body = README_TMPL.format(
        title=title,
        diff=(" " + difficulty) if difficulty else "",
        url=url,
    )
    if path.exists() and not force:
        old = path.read_bytes().decode("utf-8", "replace")
        if old == body:
            _say(ui, "readme.md 동일, 건너뜀")
            return False
    path.write_bytes(body.encode("utf-8"))
    _say(ui, "readme.md 작성")
    return True


# ---------------------------------------------------------------- main

def run_sync(cfg, args, dry_run=False, ui=None):
    """실제 동기화 작업. ui 가 주어지면 꾸민 화면으로, 없으면 평범한 print 로 출력한다."""
    if ui is None:
        print(f"[i] 설정      : {settings_label()}  (경로={cfg['repo_path']} / 팀={cfg['team']} / 날짜={cfg['date']})")
        shape = "SWEA-<번호>"
        if cfg["folder_box"]:
            shape += "(<박스>)"
        if cfg["folder_title"]:
            shape += "-<제목>"
        print(f"[i] 폴더이름  : {shape}   |  readme.md {'생성' if cfg['readme'] else '생성 안 함'}")
        print(f"[i] 폴더구조  : {cfg['layout']}  (클럽/박스 이름은 페이지를 읽은 뒤 채워집니다)")

    # 창이 갑자기 뜨기 전에 무엇을 해야 하는지 먼저 알려준다.
    # 이미 떠 있거나 창숨김이면 알릴 필요가 없다.
    if ui and not cfg["headless"] and not bootstrap.browser_running(cfg["cdp_port"]):
        if not ui.browser_notice(need_navigation=not cfg["list_url"]):
            ui.notice("취소했습니다.")
            return 1

    with sync_playwright() as pw:
        ctx, launched, proc = attach_browser(pw, cfg)
        ctx.set_default_timeout(20000)
        page = find_swea_page(ctx, cfg["list_url"], cfg["headless"])

        def _on_page(idx, got, total, expected):
            msg = f"{idx}페이지: {got}개 읽음 (누적 {total}/{expected})"
            ui.notice(msg) if ui else print(f"[i] {msg}")
        problems, boxinfo = collect_problems(page, ctx=ctx, on_page=_on_page)
        if not problems:
            msg = "문제 목록을 찾지 못했습니다. 로그인이 풀렸거나 문제 박스 페이지가 아닙니다."
            if ui:
                ui.error(msg)
            else:
                print(f"[!] {msg}")
            if args.inspect:
                out = HERE / "inspect_list.html"
                out.write_text(page.content(), encoding="utf-8")
                print(f"    - 페이지 HTML 덤프: {out}")
                dump_anchors(page, "목록 페이지")
            return 1

        # 이제 클럽/박스 이름을 아니 폴더 구조를 채울 수 있다
        try:
            day_dir = Path(cfg["repo_path"]) / render_layout(cfg["layout"], layout_values(cfg, boxinfo))
        except ValueError as e:
            (ui.error if ui else print)(str(e))
            return 1
        if ui:
            ui.notice(f"대상 폴더  {day_dir}")
        else:
            print(f"[i] 대상 폴더 : {day_dir}")

        # 폴더구조에 {박스} 가 이미 들어가 있으면 문제 폴더 이름에까지 박스를 붙이는 건 중복이다
        use_box_in_name = cfg["folder_box"]
        if use_box_in_name and "box" in layout_placeholders(cfg["layout"]):
            use_box_in_name = False
            note = "폴더구조에 {박스} 가 있어서 문제 폴더 이름에는 박스를 넣지 않습니다."
            ui.notice(note) if ui else print(f"[i] {note}")

        expected = boxinfo.get("boxCnt")
        short = bool(expected and expected.isdigit() and len(problems) < int(expected))

        if ui:
            ui.box_header(boxinfo.get("boxTitle"), expected, len(problems))
        else:
            print(f"[i] 문제 박스 : {boxinfo.get('boxTitle')} ({expected})")
            print(f"[i] 문제 {len(problems)}개 발견")
        if short:
            # 페이지를 끝까지 넘겼는데도 모자라면 사이트 쪽 문제다 (평소엔 안 뜬다)
            note = (f"이 박스에는 {expected}개가 있는데 {len(problems)}개만 읽혔습니다. "
                    "페이지를 끝까지 넘겼는데도 모자랍니다. 나중에 다시 실행해보세요.")
            ui.warn(note) if ui else print(f"[!] {note}")
        if not ui:
            print()

        # 설정이 바뀌어 기존 폴더 이름이 지금 규칙과 다르면, 물어보고 바꾼다.
        # 바꾸기 전에 무엇이 어떻게 바뀌는지 먼저 보여준다.
        if cfg["rename_folders"] and not dry_run:
            pairs = plan_renames(day_dir, problems, boxinfo.get("boxTitle", ""),
                                 {**cfg, "folder_box": use_box_in_name})
            if pairs:
                go = True
                if ui:
                    go = ui.rename_preview(pairs)
                else:
                    print("[i] 폴더 이름을 바꿉니다:")
                    for old, new in pairs:
                        print(f"      {old.name}\n   -> {new.name}")
                if go:
                    done, failed = apply_renames(pairs)
                    if ui:
                        ui.rename_result(done, failed)
                    else:
                        for name, why in failed:
                            print(f"[!] {name} : {why}")

        work = None if dry_run else ctx.new_page()
        made, rows = 0, []
        for i, prob in enumerate(problems, 1):
            number, title, diff = prob["number"], prob["title"], prob["difficulty"]
            if not number or not title:
                m = f"번호/제목을 못 읽어 건너뜁니다: {prob['contest_prob_id']}"
                ui.warn(m) if ui else print(f"  {i}. [!] {m}")
                continue

            box_name = boxinfo.get("boxTitle", "") if use_box_in_name else ""
            dest = problem_folder(day_dir, number, title, cfg["folder_title"], box_name)
            folder = dest.name

            if dry_run:
                if ui:
                    rows.append((f"SWEA-{number}", folder, title, diff, "만들 예정"))
                else:
                    print(f"  {i}. {folder}  |  {title}  |  {diff or '난이도?'}")
                    print(f"      (dry-run) {dest}")
                made += 1
                continue

            if ui:
                ui.problem_line(i, folder, title, diff)
            else:
                print(f"  {i}. {folder}  |  {title}  |  {diff or '난이도?'}")

            dest.mkdir(parents=True, exist_ok=True)
            if cfg["readme"]:
                write_readme(dest, title, diff, prob["url"], args.force, ui=ui)

            work.goto(prob["url"], wait_until="domcontentloaded")
            work.wait_for_timeout(800)
            name = download_sample_input(work, dest, args.force, ui=ui)
            if not name:
                m = "sample input 다운로드 링크를 못 찾았습니다"
                ui.step(m, ok=False) if ui else print(f"      - [!] {m}")
                if args.inspect:
                    dump_anchors(work, folder)
            made += 1

        if ui:
            if dry_run:
                ui.problem_table(rows, dry_run=True)
            ui.done(made, day_dir, dry_run=dry_run)
        else:
            print(f"\n[완료] {made}개 문제 폴더 처리  ->  {day_dir}")

        if work:
            work.close()
        if launched and cfg["headless"]:
            try:
                ctx.browser.close()
            except Exception:
                pass
            kill_process_tree(proc)
            (ui.notice if ui else print)("창숨김으로 띄운 브라우저를 닫았습니다.")
    return 0


def build_parser():
    ap = argparse.ArgumentParser(description="SWEA solving club -> 팀 레포 동기화")
    ap.add_argument("url", nargs="?", help="그날의 문제 목록(problem box) URL. 생략하면 열린 탭을 사용")
    ap.add_argument("--date", help=f"daily/<날짜> (기본: {SETTINGS_FILE} 의 '날짜', 비어 있으면 오늘)")
    ap.add_argument("--team", help=f"팀 폴더명 (기본: {SETTINGS_FILE} 의 '팀')")
    ap.add_argument("--repo", help=f"문제 폴더를 만들 최상위 폴더 (기본: 프로필의 '경로')")
    ap.add_argument("--force", action="store_true", help="이미 있는 readme/input 도 덮어쓰기")
    ap.add_argument("--dry-run", action="store_true", help="파일을 쓰지 않고 무엇을 만들지만 출력")
    ap.add_argument("--inspect", action="store_true", help="페이지 HTML/링크 덤프 (셀렉터 튜닝용)")
    ap.add_argument("--headless", action="store_true", help="크롬 창을 띄우지 않고 실행 (문제 목록 주소 필요)")
    ap.add_argument("--show", action="store_true", help="창숨김 설정을 무시하고 창을 띄움 (로그인할 때)")
    ap.add_argument("--folder-title", action="store_true", help="폴더명에 문제 제목까지 넣기")
    ap.add_argument("--no-folder-title", action="store_true", help="폴더명을 SWEA-<번호> 로만")
    ap.add_argument("--folder-box", action="store_true", help="폴더명에 문제 박스 이름까지 넣기")
    ap.add_argument("--no-folder-box", action="store_true", help="폴더명에서 박스 이름 빼기")
    ap.add_argument("--no-readme", action="store_true", help="readme.md 를 만들지 않음")
    ap.add_argument("--rename-folders", action="store_true",
                    help="이미 있는 폴더 이름을 지금 설정에 맞게 바꿈")
    ap.add_argument("--no-rename-folders", action="store_true",
                    help="폴더 이름을 바꾸지 않음")
    ap.add_argument("--layout", help="폴더 구조 템플릿. 예) \"{클럽}/{박스}\"")
    ap.add_argument("--profile", help="이번 실행에 쓸 프로필 이름 (profiles/ 안의 것)")
    ap.add_argument("-y", "--yes", action="store_true", help="설치 여부를 묻지 않고 진행")
    ap.add_argument("--menu", action="store_true", help="메뉴 화면으로 시작")
    ap.add_argument("--no-menu", action="store_true", help="메뉴 없이 바로 실행")
    return ap


def wants_menu(args) -> bool:
    """메뉴를 띄울지 판단한다.

    사람이 터미널에서 옵션 없이 실행했을 때만 띄운다.
    배치나 자동 실행에서 메뉴가 뜨면 입력을 기다리다 멈춰버리기 때문이다.
    """
    if args.no_menu:
        return False
    if args.menu:
        return True
    try:
        if not sys.stdin.isatty():
            return False
    except Exception:
        return False
    given = (args.url, args.date, args.team, args.repo, getattr(args, "layout", None),
             getattr(args, "profile", None))
    flags = (args.force, args.dry_run, args.inspect, args.headless, args.show,
             args.folder_title, args.no_folder_title, args.folder_box,
             args.no_folder_box, args.no_readme,
             args.rename_folders, args.no_rename_folders)
    return not any(given) and not any(flags)


def menu_loop(args):
    """메뉴 화면. 설정을 보고, 고치고, 실행한다."""
    import ui

    save = lambda k, v: set_setting_value(settings_path(), k, v)

    def read_cfg():
        cfg = load_config(args, strict=False)
        cfg["auto_yes"] = args.yes
        return cfg, read_settings_file(settings_path())[0]

    def draw(cfg):
        """화면을 새로 그린다. 쌓지 않고 지우고 다시 그려야 화면 전환처럼 보인다."""
        ui.clear()
        ui.banner()
        ui.settings_panel(cfg, settings_label())
        ui.show_flash()

    while True:
        cfg, raw_values = read_cfg()
        draw(cfg)
        try:
            action = ui.main_menu(current_profile())
        except KeyboardInterrupt:
            action = "quit"

        if action == "quit":
            ui.notice("끝냅니다.")
            return 0

        if action == "profile":
            while True:
                cfg, _ = read_cfg()
                draw(cfg)
                try:
                    kind, name = ui.profile_menu(list_profiles(), current_profile())
                except KeyboardInterrupt:
                    break
                if kind == "back":
                    break
                if kind == "switch":
                    set_current_profile(name)
                    ui.flash(f"프로필 '{name}' 으로 전환했습니다.")
                    break
                if kind == "new":
                    try:
                        made = new_profile_flow(args, ui)
                    except Exception as e:
                        ui.error(f"프로필을 만들지 못했습니다 - {type(e).__name__}: {e}")
                        ui.pause()
                        continue
                    if made:
                        ui.flash(f"프로필 '{made}' 을 만들고 전환했습니다.")
                    break
                if kind == "delete":
                    delete_profile(name)
                    ui.flash(f"프로필 '{name}' 을 지웠습니다.")
                    if not list_profiles():
                        ui.notice("프로필이 하나도 없습니다. 새로 만들어야 합니다.")
                        if not run_setup_if_needed(args):
                            return 1
                    break
            continue

        if action == "edit":
            # 한 항목 고칠 때마다 메인으로 튕기지 않도록 설정 화면에 머문다
            while True:
                cfg, raw_values = read_cfg()
                draw(cfg)
                try:
                    stay = ui.edit_settings(cfg, raw_values, save)
                except KeyboardInterrupt:
                    break
                except Exception as e:
                    # 설정 고치다 난 오류로 프로그램 전체가 죽으면 안 된다
                    ui.error(f"설정을 바꾸지 못했습니다 - {type(e).__name__}: {e}")
                    ui.pause()
                    break
                if not stay:
                    break
            continue

        cfg, _ = read_cfg()
        if not cfg["repo_path"] or not Path(cfg["repo_path"]).exists():
            ui.error(f"레포 경로가 없습니다: {cfg['repo_path'] or '(비어 있음)'}")
            ui.notice("'설정 바꾸기' 에서 경로를 고쳐주세요.")
            ui.pause()
            continue

        ui.clear()
        try:
            run_sync(cfg, args, dry_run=(action == "dry"), ui=ui)
        except KeyboardInterrupt:
            ui.warn("중단했습니다.")
        except Exception as e:
            ui.error(f"{type(e).__name__}: {e}")
        ui.pause()


def run_setup_if_needed(args) -> bool:
    """프로필이 없거나 경로가 비어 있으면 물어봐서 채운다.

    설정 파일을 미리 손으로 고치지 않아도 첫 실행이 되도록 하는 게 목적이다.
    사람이 없는 실행(배치 등)에서는 물어볼 수 없으니 건너뛴다.
    """
    cfg = load_config(args, strict=False)
    need_team = "team" in layout_placeholders(cfg["layout"])
    if cfg["repo_path"] and (cfg["team"] or not need_team):
        return True

    try:
        interactive = sys.stdin.isatty()
    except Exception:
        interactive = False
    if not interactive:
        return True                     # 물어볼 수 없으면 기존 안내로 넘긴다

    import ui
    first = not list_profiles()         # 프로필이 하나도 없으면 이름부터 정한다
    got = ui.setup_wizard(check_repo_path, cfg["repo_path"], cfg["team"], cfg["layout"],
                          ask_name=first, existing_names=list_profiles())
    if not got:
        ui.notice("설정하지 않았습니다.")
        return False

    if first:
        name = got.pop("name", DEFAULT_PROFILE)
        create_profile(name, source=HERE / SETTINGS_FILE)
        set_current_profile(name)
    got.pop("name", None)
    for key, value in got.items():
        set_setting_value(settings_path(), key, value)
    return True


def new_profile_flow(args, ui):
    """메뉴에서 '새 프로필 만들기'. 지금 프로필의 취향을 물려받고 경로/구조/팀만 새로 묻는다."""
    cur = load_config(args, strict=False)
    got = ui.setup_wizard(check_repo_path, "", cur["team"], cur["layout"],
                          ask_name=True, existing_names=list_profiles())
    if not got:
        return None
    name = got.pop("name")
    create_profile(name, source=settings_path())
    for key, value in got.items():
        set_setting_value(profile_path(name), key, value)
    set_current_profile(name)
    return name


def main():
    args = build_parser().parse_args()

    # 필요한 패키지가 없으면 여기서 설치한다 (playwright import 보다 먼저)
    if not bootstrap.ensure_packages(auto_yes=args.yes):
        return 1
    load_playwright()

    # 예전 방식(settings.txt 하나)에서 넘어온 사람은 '기본' 프로필로 옮겨준다
    moved = migrate_legacy_settings()
    if moved:
        print(f"[i] 기존 settings.txt 를 프로필 '{moved}' 으로 옮겼습니다. (profiles/{moved}.txt)")

    # --profile: 이번 실행만 그 프로필로
    global _forced_profile
    if getattr(args, "profile", None):
        want = valid_profile_name(args.profile)
        if not want or not profile_path(want).exists():
            sys.exit(f"프로필 '{args.profile}' 이 없습니다. 있는 것: {', '.join(list_profiles()) or '(없음)'}")
        _forced_profile = want

    # 경로가 비어 있으면 여기서 물어본다 (설정 파일을 미리 안 고쳐도 되게)
    if not run_setup_if_needed(args):
        return 1

    if wants_menu(args):
        return menu_loop(args)

    cfg = load_config(args)
    cfg["auto_yes"] = args.yes
    if not Path(cfg["repo_path"]).exists():
        sys.exit(f"레포 경로가 없습니다: {cfg['repo_path']}\n"
                 f"  {SETTINGS_FILE} 의 '경로' 를 확인해주세요.")
    return run_sync(cfg, args, dry_run=args.dry_run, ui=None)


if __name__ == "__main__":
    raise SystemExit(main())
