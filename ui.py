# -*- coding: utf-8 -*-
"""콘솔 화면(TUI).

rich 로 그리고 questionary 로 고른다.
bootstrap.ensure_packages() 가 끝난 뒤에만 import 해야 한다.
"""
from __future__ import annotations

import unicodedata
from datetime import date

import questionary
from questionary import Style
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# legacy_windows=False 가 중요하다. rich 가 옛 Win32 콘솔 API 로 쓰면
# 콘솔 코드페이지(cp949)로 인코딩하다 '-' 같은 글자에서 터진다.
# 이미 stdout 을 UTF-8 로 맞춰뒀으므로 ANSI 경로로 보내는 게 안전하다.
console = Console(legacy_windows=False)

# 파란 계열로 통일. 터미널 기본색과 싸우지 않게 굵기 위주로 강조한다.
ASK = Style([
    ("qmark",       "fg:#4a9eff bold"),
    ("question",    "bold"),
    ("pointer",     "fg:#4a9eff bold"),
    ("highlighted", "fg:#4a9eff bold"),
    ("selected",    "fg:#4a9eff"),
    ("answer",      "fg:#4a9eff bold"),
])

ACCENT = "#4a9eff"


# ---------------------------------------------------------------- 글자 폭
# 한글은 터미널에서 두 칸을 차지한다. 파이썬의 f"{s:<32}" 는 글자 수로만 세기 때문에
# 한글이 섞이면 열이 안 맞는다. 실제로 보이는 폭으로 맞춰야 한다.

def disp_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1
               for c in str(text))


def pad(text: str, width: int) -> str:
    return str(text) + " " * max(0, width - disp_width(text))


_flash = ""


def flash(msg):
    """다음 화면에 한 줄 띄울 메시지를 남긴다."""
    global _flash
    _flash = msg


def show_flash():
    global _flash
    if _flash:
        console.print(Text(f"  {_flash}", style=ACCENT))
        console.print()
        _flash = ""


def clear():
    """화면을 지운다. 새 화면으로 넘어갈 때마다 부른다."""
    try:
        console.clear()
    except Exception:
        pass

# ---------------------------------------------------------------- 물어보기
# questionary(prompt_toolkit)는 진짜 윈도우 콘솔이 아니면 못 돈다.
# Git Bash / MSYS 에서 실행하면 NoConsoleScreenBufferError 로 죽어버린다.
# 그래서 한 번 실패하면 번호 입력 방식으로 갈아탄다.

_plain = False       # 이 터미널에서는 방향키 UI 를 아예 못 쓴다
_warned = False

# 터미널 자체가 방향키 UI 를 못 받는 경우에만 계속 번호 입력으로 간다.
# 그 외의 일시적인 실패까지 굳혀버리면, 한 번 삐끗한 뒤로 계속 번호 입력이 된다.
PERMANENT_ERRORS = ("NoConsoleScreenBufferError", "NoConsoleScreenBuffer")


def _fallback(exc):
    """방향키 UI 가 실패했을 때. 영구적인 문제일 때만 번호 입력으로 굳힌다."""
    global _plain, _warned
    permanent = type(exc).__name__ in PERMANENT_ERRORS
    if permanent:
        _plain = True
    if not _warned:
        _warned = True
        if permanent:
            console.print(Text("  (이 터미널은 방향키 선택을 지원하지 않아 번호 입력으로 진행합니다)",
                               style="yellow"))
            console.print(Text("  (cmd 창이나 START.bat 으로 실행하면 방향키를 쓸 수 있습니다)",
                               style="dim"))
        else:
            console.print(Text(f"  (이 항목만 번호 입력으로 진행합니다 - {type(exc).__name__})",
                               style="dim"))
        console.print()


def _input(prompt):
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        print()
        return None


SEP = object()      # 목록 사이의 구분선.  ("── 위치 ──", SEP) 처럼 쓴다


def ask_select(message, choices, default=None):
    """choices: [(보여줄 글, 값[, 설명]), ...]  반환: 값 또는 취소 시 None

    설명이 있으면 방향키로 그 항목에 갔을 때 아래에 한 줄로 띄운다.
    값이 SEP 이면 고를 수 없는 구분선으로 그린다.
    """
    if not _plain:
        try:
            qc = []
            for c in choices:
                lab, val = c[0], c[1]
                if val is SEP:
                    qc.append(questionary.Separator(lab))
                else:
                    qc.append(questionary.Choice(lab, value=val,
                                                 description=c[2] if len(c) > 2 else None))
            return questionary.select(
                message, choices=qc, default=default,
                style=ASK, qmark=">", show_description=True,
            ).ask()
        except Exception as e:
            _fallback(e)

    # 번호 입력 방식: 구분선은 제목처럼, 설명은 항목 아래 흐리게
    console.print(Text(f"> {message}", style="bold"))
    pickable = []
    for c in choices:
        lab, val = c[0], c[1]
        if val is SEP:
            console.print(Text(f"   {lab}", style=f"bold {ACCENT}"))
            continue
        pickable.append(c)
        console.print(Text(f"   {len(pickable)}) {lab}", style="dim"))
        if len(c) > 2 and c[2]:
            console.print(Text(f"        {c[2]}", style="dim italic"))
    while True:
        raw = _input("   번호: ")
        if raw is None:
            return None
        raw = raw.strip()
        if raw.isdigit() and 1 <= int(raw) <= len(pickable):
            return pickable[int(raw) - 1][1]
        console.print(Text(f"   1 ~ {len(pickable)} 사이 번호를 입력해주세요.", style="yellow"))


def ask_text(message, default=""):
    if not _plain:
        try:
            return questionary.text(message, default=default or "",
                                    style=ASK, qmark=">").ask()
        except Exception as e:
            _fallback(e)

    hint = f" [{default}]" if default else ""
    raw = _input(f"> {message}{hint}: ")
    if raw is None:
        return None
    return raw.strip() or default


def ask_confirm(message, default=True, plain=False):
    """plain=True 면 방향키 UI 를 아예 시도하지 않는다.

    playwright 실행 컨텍스트 안에서는 prompt_toolkit 이 자기 이벤트 루프를
    못 잡아 실패할 수 있다. 그런 자리는 처음부터 평범한 입력으로 받는다.
    """
    if not _plain and not plain:
        try:
            return questionary.confirm(message, default=default,
                                       style=ASK, qmark=">").ask()
        except Exception as e:
            _fallback(e)

    raw = _input(f"> {message} [{'Y/n' if default else 'y/N'}]: ")
    if raw is None:
        return None
    raw = raw.strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes", "네", "예", "ㅇ")


def banner():
    console.print()
    console.print(Text("  SWEA 문제 폴더 자동 생성기", style=f"bold {ACCENT}"))
    console.print(Text("  문제 목록에서 폴더 - readme - sample input 을 한 번에", style="dim"))
    console.print()


def settings_panel(cfg, settings_file="settings.txt"):
    """지금 설정을 한눈에 보여준다. settings_file 자리에 프로필 이름이 온다."""
    t = Table.grid(padding=(0, 2))
    t.add_column(style="dim", justify="right", min_width=9)
    t.add_column()

    today = date.today().isoformat()
    date_txt = f"{cfg['date']}" + ("  [dim](오늘)[/dim]" if cfg["date"] == today else "")

    shape = "SWEA-<번호>"
    if cfg["folder_box"]:
        shape += "(<박스>)"
    if cfg["folder_title"]:
        shape += "-<제목>"

    t.add_row("경로", str(cfg["repo_path"]))
    t.add_row("팀", str(cfg["team"]))
    t.add_row("날짜", date_txt)
    t.add_row("폴더구조", str(cfg.get("layout") or "daily/{날짜}/{팀}"))
    t.add_row("폴더이름", shape)
    t.add_row("readme", "만듦" if cfg["readme"] else "[dim]안 만듦[/dim]")
    t.add_row("브라우저", "창 숨김" if cfg["headless"] else "창 띄움")

    # expand=False: 넓은 터미널에서 패널이 끝까지 늘어나 휑해 보이는 걸 막는다
    console.print(Panel(t, title=f"[dim]{settings_file}[/dim]", title_align="left",
                        border_style="grey42", padding=(1, 2), expand=False))


def main_menu(profile_name=""):
    """무엇을 할지 고른다. 반환: run | dry | edit | profile | quit"""
    choice = ask_select("무엇을 할까요?", [
        ("실행하기",      "run",     "문제 목록을 읽어 폴더 · readme · sample input 을 만듭니다."),
        ("미리보기",      "dry",     "파일은 만들지 않고 무엇이 만들어질지만 보여줍니다."),
        ("설정 바꾸기",   "edit",    "지금 프로필의 설정을 고칩니다."),
        (f"프로필  ({profile_name})" if profile_name else "프로필",
                          "profile", "레포마다 다른 설정을 프로필로 나눠 씁니다. 전환 · 새로 만들기 · 삭제."),
        ("끝내기",        "quit",    ""),
    ])
    return choice or "quit"


# ---------------------------------------------------------------- 첫 설정

TEAMS = ["team-A", "team-B", "team-C", "team-D", "team-E"]


def ask_profile_name(existing=(), default="기본"):
    """새 프로필 이름. 이미 있는 이름이면 다시 묻는다."""
    console.print()
    console.print(Text("  프로필 이름", style=f"bold {ACCENT}"))
    console.print(Text("  레포 하나에 설정 한 벌입니다. 나중에 다른 레포용 프로필을 더 만들 수 있습니다.",
                       style="dim"))
    console.print()
    import swea_sync
    while True:
        text = ask_text("이름", default=default)
        if text is None:
            return None
        name = swea_sync.valid_profile_name(text)
        if not name:
            error("이름을 비울 수 없습니다.")
            continue
        if name in existing:
            error(f"'{name}' 은 이미 있습니다. 다른 이름을 적어주세요.")
            continue
        return name


def ask_repo_path(check, current=""):
    """레포 경로를 물어본다. 실제로 있는 폴더인지 확인하고, 아니면 다시 묻는다.

    check(text) -> (쓸 수 있나, 정리된 경로, 알려줄 말)
    반환: 확정된 경로, 취소하면 None
    """
    console.print()
    console.print(Text("  algorithm 레포 경로", style=f"bold {ACCENT}"))
    console.print(Text("  git clone 받은 algorithm 폴더를 알려주세요.", style="dim"))
    console.print(Text("  탐색기 주소창에서 복사해 붙여넣으면 됩니다. (따옴표는 있어도 됩니다)",
                       style="dim"))
    console.print()

    while True:
        text = ask_text("경로", default=current)
        if text is None:
            return None

        ok, resolved, msg = check(text)
        if not ok:
            error(msg)
            console.print(Text("  다시 입력해주세요.", style="dim"))
            console.print()
            current = text.strip().strip('"').strip("'")
            continue

        console.print()
        console.print(Text(f"  {resolved}", style="bold"))
        console.print(Text(f"  {msg}", style="dim"))
        console.print()
        if ask_confirm("이 경로가 맞나요?", default=True):
            return resolved
        current = resolved
        console.print()


def ask_team(current=""):
    """조 이름을 고른다. 목록에 없으면 직접 입력."""
    console.print()
    console.print(Text("  우리 조", style=f"bold {ACCENT}"))
    console.print(Text("  폴더 구조의 {팀} 자리에 들어갑니다.", style="dim"))
    console.print()

    choices = [(t, t) for t in TEAMS] + [("직접 입력", "__other__")]
    picked = ask_select("조", choices,
                        default=current if current in TEAMS else None)
    if picked is None:
        return None
    if picked != "__other__":
        return picked

    while True:
        text = ask_text("조 폴더명", default=current)
        if text is None:
            return None
        text = text.strip()
        if text:
            return text
        error("비워둘 수 없습니다.")


LAYOUT_EXAMPLES = [
    ("daily/{날짜}/{팀}",        "기본. 반 레포 규칙"),
    ("{클럽}/{박스}",            "클럽 이름 / 문제 박스 이름"),
    ("{팀}/{날짜}",              "조별로 모아두기"),
    ("{년}/{월}/{일}/{팀}",      "연/월/일 로 나누기"),
    ("daily/{날짜}/{팀}/{박스}", "기본 구조 안에 박스 폴더 하나 더"),
]


def ask_layout(current=""):
    """폴더 구조 템플릿을 고르거나 직접 입력한다. 모르는 자리표시자면 다시 묻는다."""
    console.print()
    console.print(Text("  폴더 구조", style=f"bold {ACCENT}"))
    console.print(Text("  문제 폴더들이 들어갈 위치입니다. 레포 기준 상대 경로이고,", style="dim"))
    console.print(Text("  {날짜} {년} {월} {일} {팀} {클럽} {박스} 를 쓸 수 있습니다.", style="dim"))
    console.print()

    choices = [(f"{pad(t, 28)}  {desc}", t) for t, desc in LAYOUT_EXAMPLES]
    choices.append(("직접 입력", "__custom__"))
    default = current if current in [t for t, _ in LAYOUT_EXAMPLES] else None
    picked = ask_select("어떤 구조로 할까요?", choices, default=default)
    if picked is None:
        return None
    if picked != "__custom__":
        return picked

    import swea_sync
    while True:
        text = ask_text("폴더 구조", default=current)
        if text is None:
            return None
        try:
            return swea_sync.check_layout(text)
        except ValueError as e:
            error(str(e).splitlines()[0])
            for line in str(e).splitlines()[1:]:
                console.print(Text(f"  {line.strip()}", style="dim"))
            console.print()


def setup_wizard(check_path, current_path="", current_team="", current_layout="",
                 ask_name=False, existing_names=()):
    """처음 실행할 때(또는 새 프로필을 만들 때) 필요한 것을 차례로 묻는다.

    순서: 프로필 이름(옵션) -> 레포 경로 -> 폴더 구조 -> 팀(구조에 {팀} 이 있을 때만)
    반환: dict 또는 취소 시 None
    """
    import swea_sync

    console.print()
    console.print(Text("  몇 가지만 정하면 됩니다.", style=f"bold {ACCENT}"))
    console.print(Text("  나중에 메뉴의 '설정 바꾸기' 에서 언제든 고칠 수 있습니다.", style="dim"))

    got = {}
    if ask_name:
        name = ask_profile_name(existing_names)
        if name is None:
            return None
        got["name"] = name

    path = ask_repo_path(check_path, current_path)
    if path is None:
        return None
    got["repo_path"] = path

    layout = ask_layout(current_layout or "daily/{날짜}/{팀}")
    if layout is None:
        return None
    got["layout"] = layout

    if "team" in swea_sync.layout_placeholders(layout):
        team = ask_team(current_team)
        if team is None:
            return None
        got["team"] = team
    else:
        got["team"] = ""

    console.print()
    console.print(Text("  저장했습니다.", style=f"bold {ACCENT}"))
    for k, label in (("name", "프로필"), ("repo_path", "경로"), ("layout", "구조"), ("team", "팀")):
        if got.get(k):
            console.print(Text(f"    {pad(label, 6)} {got[k]}", style="dim"))
    console.print()
    return got


# ---------------------------------------------------------------- 프로필

def profile_menu(names, current):
    """프로필 화면. 반환: ("switch", 이름) | ("new", None) | ("delete", 이름) | ("back", None)"""
    console.print()
    choices = []
    if names:
        choices.append(("── 프로필 ──", SEP))
        for n in names:
            mark = "*" if n == current else " "
            choices.append((f"{mark} {n}", ("switch", n),
                            "이 프로필로 전환합니다." if n != current else "지금 쓰는 프로필입니다."))
    choices.append(("── 관리 ──", SEP))
    choices.append(("새 프로필 만들기", ("new", None),
                    "다른 레포나 다른 폴더 구조를 위한 설정 한 벌을 새로 만듭니다."))
    if names:
        choices.append(("프로필 삭제", ("delete", None), "설정 파일을 지웁니다. 만든 폴더는 그대로 둡니다."))
    choices.append(("<- 돌아가기", ("back", None), ""))

    picked = ask_select("프로필", choices)
    if not picked or picked[0] == "back":
        return ("back", None)
    if picked[0] == "delete":
        target = ask_select("어느 프로필을 지울까요?",
                            [(n, n) for n in names] + [("<- 취소", "__cancel__")])
        if not target or target == "__cancel__":
            return ("back", None)
        if ask_confirm(f"'{target}' 프로필을 지울까요? (만든 폴더는 남습니다)", default=False):
            return ("delete", target)
        return ("back", None)
    return picked


# ---------------------------------------------------------------- 설정 편집

# 카테고리별로 나눈다. (키, 보여줄 이름, 설명) - 설명은 방향키로 그 항목에 갔을 때 아래에 뜬다
SETTING_GROUPS = [
    ("위치", [
        ("repo_path", "경로",
         "git clone 받은 algorithm 레포 폴더. 이 안에 문제 폴더를 만듭니다."),
        ("layout", "폴더 구조",
         "문제 폴더들이 들어갈 위치. {날짜} {팀} {클럽} {박스} 같은 자리표시자를 씁니다."),
        ("team", "팀",
         "폴더 구조의 {팀} 자리에 들어갈 이름. 구조에 {팀} 이 없으면 쓰이지 않습니다."),
    ]),
    ("폴더 이름", [
        ("folder_title", "문제 제목 넣기",
         "SWEA-1974 -> SWEA-1974-스도쿠 검증 처럼 폴더 이름에 문제 제목을 붙입니다."),
        ("folder_box", "박스 이름 넣기",
         "SWEA-1974 -> SWEA-1974(Stack2_1) 처럼 문제 박스 이름을 붙입니다. 구조에 {박스} 가 있으면 자동으로 뺍니다."),
        ("rename_folders", "기존 폴더 이름 갱신",
         "이미 만든 폴더 이름도 지금 규칙에 맞게 바꿉니다. 바꾸기 전에 목록을 보여주고 확인합니다."),
    ]),
    ("만드는 것", [
        ("readme", "readme.md 만들기",
         "문제마다 제목 · 난이도 · 바로가기 링크가 든 readme.md 를 만듭니다. 끄면 폴더와 input 만 받습니다."),
    ]),
    ("실행", [
        ("date", "날짜",
         "{날짜} 자리에 들어갈 날짜. 비우면 오늘. 지난 날짜를 채워 넣을 때만 적습니다."),
        ("headless", "창 숨기고 실행",
         "크롬 창 없이 조용히 돕니다. 로그인이 안 돼 있거나 문제 목록 주소가 없으면 창을 띄웁니다."),
        ("list_url", "문제 목록 주소",
         "그날 문제 박스 페이지 주소. 창 숨김일 때 필요합니다. 창을 띄워 쓰면 비워둬도 됩니다."),
    ]),
]
EDITABLE = [(k, lb) for _, items in SETTING_GROUPS for k, lb, _ in items]
YESNO_KEYS = ("folder_title", "folder_box", "readme", "headless", "rename_folders")


def _yesno(label, current):
    return ask_select(label, [("예", "예"), ("아니오", "아니오")],
                      default="예" if current else "아니오")


def edit_settings(cfg, raw_values, save):
    """설정을 하나 골라 바꾼다. save(canon_key, value) 로 파일에 기록한다.

    반환: 설정 화면에 머물면 True, 메인으로 돌아가면 False
    """
    shown = {
        "repo_path": cfg["repo_path"] or "(비어 있음)",
        "layout": raw_values.get("layout", "") or "daily/{날짜}/{팀}",
        "team": cfg["team"] or "(비어 있음)",
        "date": raw_values.get("date", "") or "(오늘)",
        "list_url": raw_values.get("list_url", "") or "(비어 있음)",
    }
    for k in YESNO_KEYS:
        shown[k] = "예" if cfg[k] else "아니오"

    w = max(disp_width(lb) for _, lb in EDITABLE)
    BACK = "__back__"
    choices = []
    for group, items in SETTING_GROUPS:
        choices.append((f"── {group} ──", SEP))
        for key, label, desc in items:
            choices.append((f"{pad(label, w)}    {str(shown[key])[:44]}", key, desc))
    choices.append(("─" * 14, SEP))
    choices.append(("<- 돌아가기", BACK, ""))

    labels = dict(EDITABLE)
    key = ask_select("무엇을 바꿀까요?", choices)
    if not key or key == BACK or key not in labels:
        return False

    if key in YESNO_KEYS:
        value = _yesno(labels[key], cfg[key])
    elif key == "date":
        value = ask_text("날짜 (YYYY-MM-DD, 비우면 오늘)",
                         default=raw_values.get("date", ""))
    elif key == "layout":
        value = ask_layout(raw_values.get("layout", ""))
    elif key == "team":
        value = ask_team(cfg["team"])
    else:
        value = ask_text(labels[key], default=str(raw_values.get(key, "") or ""))

    if value is None:
        return True                     # 값 입력만 취소한 것이니 설정 화면에 머문다
    save(key, value.strip())
    flash(f"저장했습니다 - {labels[key]} = {value.strip() or '(비움)'}")
    return True


# ---------------------------------------------------------------- 실행 화면

def browser_notice(need_navigation=True):
    """브라우저를 띄우기 전에 무엇을 해야 하는지 먼저 알려준다.

    창이 갑자기 떠서 뭘 해야 할지 모르는 상황을 없애는 게 목적이다.
    반환: 계속할지 여부
    """
    body = Table.grid(padding=(0, 1))
    body.add_column()
    body.add_row(Text("잠시 후 자동화 전용 크롬 창이 열립니다.", style="bold"))
    body.add_row(Text("평소 쓰는 크롬과 별개 창이라 탭·북마크는 건드리지 않습니다.",
                      style="dim"))
    body.add_row("")

    steps = [
        ("1", "창 오른쪽 위 [bold]로그인[/bold] 으로 SWEA 에 로그인"),
    ]
    if need_navigation:
        steps += [
            ("2", "[bold]Solving Club[/bold] > 우리 반 클럽 으로 이동"),
            ("3", "오늘 풀 [bold]문제 박스[/bold] 페이지 열기"),
            ("4", "이 창으로 돌아와 [bold]Enter[/bold]"),
        ]
    else:
        steps += [("2", "이 창으로 돌아와 [bold]Enter[/bold]  (문제 박스는 자동으로 엽니다)")]

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style=ACCENT, justify="right", width=2)
    grid.add_column()
    for num, text in steps:
        grid.add_row(num, text)
    body.add_row(grid)
    body.add_row("")
    tail = ("이미 로그인돼 있으면 문제 박스만 열고 돌아오시면 됩니다."
            if need_navigation else
            "이미 로그인돼 있으면 그냥 Enter 를 누르시면 됩니다.")
    body.add_row(Text(tail, style="dim"))

    console.print(Panel(body, title=f"[bold {ACCENT}]브라우저를 띄웁니다[/]",
                        title_align="left", border_style=ACCENT,
                        padding=(1, 3), expand=False))
    console.print()
    ans = ask_confirm("지금 띄울까요?", default=True)
    console.print()
    return bool(ans)



def box_header(box_title, box_cnt, found):
    line = Text("  문제 박스  ", style="dim")
    line.append(str(box_title or "?"), style=f"bold {ACCENT}")
    line.append(f"   문제 {found}개", style="dim")
    if box_cnt and str(box_cnt).isdigit() and found < int(box_cnt):
        line.append(f"  (박스에는 {box_cnt}개)", style="yellow")
    console.print(line)
    console.print()


def rename_preview(pairs):
    """폴더 이름을 바꾸기 전에 무엇이 어떻게 바뀌는지 보여주고 확인받는다."""
    t = Table(box=None, pad_edge=False, padding=(0, 2), show_edge=False)
    t.add_column("지금", style="dim", overflow="fold")
    t.add_column("", width=2)
    t.add_column("바꿀 이름", style="bold", overflow="fold")
    for old, new in pairs:
        t.add_row(old.name, "->", new.name)

    console.print(Panel(
        t, title=f"[bold {ACCENT}]폴더 이름을 바꿉니다[/]", title_align="left",
        border_style=ACCENT, padding=(1, 3), expand=False,
    ))
    console.print(Text("  폴더 안의 풀이 파일도 같이 따라갑니다.", style="dim"))
    console.print(Text("  이미 커밋한 날짜라면 git 에서 삭제+추가로 잡혀 MR 이 지저분해질 수 있습니다.",
                       style="yellow"))
    console.print()
    # 이 확인은 playwright 실행 중에 뜬다. 방향키 UI 를 쓰면 실패하면서
    # 세션 전체가 번호 입력으로 바뀌어 버리므로 처음부터 평범한 입력으로 받는다.
    ans = ask_confirm("바꿀까요?", default=False, plain=True)
    console.print()
    return bool(ans)


def rename_result(done, failed):
    for old, new in done:
        console.print(Text(f"  이름 바꿈  {old}", style="dim"))
        console.print(Text(f"          -> {new}", style=ACCENT))
    for name, why in failed:
        warn(f"{name} : {why}")
    if done or failed:
        console.print()


def problem_line(i, folder, title, diff):
    """실행 중 한 문제를 시작할 때 찍는 두 줄."""
    line = Text(f"  {i}. ", style="dim")
    line.append(title, style="bold")
    line.append(f"   {diff or '-'}", style=ACCENT)
    console.print(line)
    console.print(Text(f"     {folder}", style="dim"))


def step(msg, ok=True):
    console.print(Text(f"       {'-' if ok else '!'} {msg}",
                       style="dim" if ok else "yellow"))


def problem_table(rows, dry_run=False):
    """rows: (번호, 폴더명, 제목, 난이도, 결과문구) 목록"""
    t = Table(box=None, pad_edge=False, padding=(0, 2), show_edge=False)
    t.add_column("#", style="dim", width=2, justify="right")
    t.add_column("문제", style="bold")
    t.add_column("난이도", justify="center", width=6)
    t.add_column("폴더")
    t.add_column("결과" if not dry_run else "만들 위치", style="dim")
    for i, (num, folder, title, diff, result) in enumerate(rows, 1):
        t.add_row(str(i), f"{num}  {title}", diff or "-", folder, result)
    console.print(t)
    console.print()


def done(count, day_dir, dry_run=False):
    if dry_run:
        console.print(Text(f"  미리보기 끝 - {count}개 문제. 파일은 만들지 않았습니다.", style="dim"))
    else:
        console.print(Text(f"  완료 - {count}개 문제", style=f"bold {ACCENT}"))
        console.print(Text(f"  {day_dir}", style="dim"))
    console.print()


def notice(msg, style="dim"):
    console.print(Text(f"  {msg}", style=style))


def warn(msg):
    console.print(Text(f"  ! {msg}", style="yellow"))


def error(msg):
    console.print(Text(f"  x {msg}", style="red"))


def pause():
    try:
        if not _plain:
            questionary.press_any_key_to_continue("계속하려면 아무 키나 누르세요...",
                                                  style=ASK).ask()
            return
    except Exception as e:
        _fallback(e)
    _input("   계속하려면 Enter...")
