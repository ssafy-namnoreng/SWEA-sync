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


def ask_select(message, choices, default=None):
    """choices: [(보여줄 글, 값), ...]  반환: 값 또는 취소 시 None"""
    if not _plain:
        try:
            return questionary.select(
                message,
                choices=[questionary.Choice(lab, value=val) for lab, val in choices],
                default=default, style=ASK, qmark=">",
            ).ask()
        except Exception as e:
            _fallback(e)

    console.print(Text(f"> {message}", style="bold"))
    for i, (lab, _v) in enumerate(choices, 1):
        console.print(Text(f"   {i}) {lab}", style="dim"))
    while True:
        raw = _input("   번호: ")
        if raw is None:
            return None
        raw = raw.strip()
        if raw.isdigit() and 1 <= int(raw) <= len(choices):
            return choices[int(raw) - 1][1]
        console.print(Text(f"   1 ~ {len(choices)} 사이 번호를 입력해주세요.", style="yellow"))


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
    """지금 설정을 한눈에 보여준다."""
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


def main_menu():
    """무엇을 할지 고른다. 반환: run | dry | edit | quit"""
    choice = ask_select("무엇을 할까요?", [
        ("실행하기 - 폴더와 파일을 만듭니다", "run"),
        ("미리보기 - 파일은 안 만들고 확인만", "dry"),
        ("설정 바꾸기", "edit"),
        ("끝내기", "quit"),
    ])
    return choice or "quit"


# ---------------------------------------------------------------- 첫 설정

TEAMS = ["team-A", "team-B", "team-C", "team-D", "team-E"]


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
    console.print(Text("  daily/<날짜>/<조> 아래에 파일을 만듭니다.", style="dim"))
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


def setup_wizard(check_path, current_path="", current_team=""):
    """처음 실행할 때 경로와 조를 물어본다. 반환: dict 또는 취소 시 None"""
    console.print()
    console.print(Text("  처음이시군요. 두 가지만 정하면 됩니다.", style=f"bold {ACCENT}"))
    console.print(Text("  나중에 메뉴의 '설정 바꾸기' 에서 언제든 고칠 수 있습니다.", style="dim"))

    path = ask_repo_path(check_path, current_path)
    if path is None:
        return None
    team = ask_team(current_team)
    if team is None:
        return None

    console.print()
    console.print(Text("  저장했습니다.", style=f"bold {ACCENT}"))
    console.print(Text(f"    경로  {path}", style="dim"))
    console.print(Text(f"    팀    {team}", style="dim"))
    console.print()
    return {"repo_path": path, "team": team}


# ---------------------------------------------------------------- 설정 편집

def _yesno(label, current):
    return ask_select(label, [("예", "예"), ("아니오", "아니오")],
                      default="예" if current else "아니오")


EDITABLE = [
    ("repo_path",    "경로 (algorithm 레포 위치)"),
    ("team",         "팀 (team-A ~ team-E)"),
    ("date",         "날짜 (비우면 오늘)"),
    ("layout",       "폴더 구조 (예: {클럽}/{박스})"),
    ("folder_title", "폴더 이름에 문제 제목 넣기"),
    ("folder_box",   "폴더 이름에 문제 박스 이름 넣기"),
    ("readme",       "readme.md 만들기"),
    ("rename_folders", "기존 폴더 이름도 갱신하기"),
    ("headless",     "창 숨기고 실행하기"),
    ("list_url",     "문제 목록 주소 (창 숨김일 때 필요)"),
]


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
    picked = ask_select("어떤 구조로 할까요?", choices)
    if picked is None:
        return None
    if picked != "__custom__":
        return picked

    # 직접 입력: swea_sync.check_layout 으로 형태를 확인한다 (순환 import 를 피해 여기서 가져온다)
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


def edit_settings(cfg, raw_values, save):
    """설정을 하나 골라 바꾼다. save(canon_key, value) 로 파일에 기록한다.

    반환: 바꿨으면 True (설정을 다시 읽어야 함)
    """
    labels = {k: lb for k, lb in EDITABLE}
    shown = {
        "repo_path": cfg["repo_path"],
        "team": cfg["team"],
        "date": raw_values.get("date", "") or "(오늘)",
        "layout": raw_values.get("layout", "") or "daily/{날짜}/{팀}",
        "folder_title": "예" if cfg["folder_title"] else "아니오",
        "folder_box": "예" if cfg["folder_box"] else "아니오",
        "readme": "예" if cfg["readme"] else "아니오",
        "rename_folders": "예" if cfg["rename_folders"] else "아니오",
        "headless": "예" if cfg["headless"] else "아니오",
        "list_url": raw_values.get("list_url", "") or "(비어 있음)",
    }
    # value=None 을 주면 questionary 가 '값 없음'으로 보고 제목 문자열을 돌려준다.
    # 그래서 돌아가기는 반드시 따로 표시값을 준다.
    BACK = "__back__"
    w = max(disp_width(labels[k]) for k, _ in EDITABLE)
    choices = [(f"{pad(labels[k], w)}    {str(shown[k])[:44]}", k) for k, _ in EDITABLE]
    choices.append(("<- 돌아가기", BACK))

    key = ask_select("무엇을 바꿀까요?", choices)
    if not key or key == BACK or key not in labels:
        return False

    if key in ("folder_title", "folder_box", "readme", "headless", "rename_folders"):
        value = _yesno(labels[key], cfg[key])
    elif key == "date":
        value = ask_text("날짜 (YYYY-MM-DD, 비우면 오늘)",
                         default=raw_values.get("date", ""))
    elif key == "layout":
        value = ask_layout(raw_values.get("layout", ""))
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
