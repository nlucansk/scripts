#!/usr/bin/env python3
# alias_runner_fancy.py
# Colorful alias runner TUI for zsh aliases
# Dependency: prompt_toolkit (3.x). Python 3.13 compatible.

import os
import re
import json
import shlex
import shutil
import pathlib
import subprocess
from typing import List, Dict, Tuple, Optional, Any

# ---- Config ----
HOME = pathlib.Path.home()
DEFAULT_RC = HOME / ".zshrc"
NOTES_PATH = HOME / ".alias_runner_notes.json"
CLEAR_BEFORE_RUN = os.environ.get("ALIAS_RUNNER_CLEAR", "1") not in ("0", "false", "False", "")

# ---- prompt_toolkit imports ----
from prompt_toolkit import Application
from prompt_toolkit.layout import Layout, HSplit, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.widgets import Frame
from prompt_toolkit.styles import Style
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.shortcuts.dialogs import input_dialog, message_dialog
from prompt_toolkit.shortcuts import prompt as ptk_prompt

# ---- Parsing aliases ----
ALIAS_RE = re.compile(
    r"""^\s*alias\s+([A-Za-z0-9_+.\-]+)\s*=\s*(['"])(.*?)\2(?:\s*#\s*(.*))?\s*$"""
)
SOURCE_RE = re.compile(r"""^\s*(?:source|\.)\s+(['"]?)([^'"]+)\1\s*$""")


def load_notes() -> Dict[str, str]:
    if NOTES_PATH.exists():
        try:
            return json.loads(NOTES_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_notes(notes: Dict[str, str]) -> None:
    tmp = NOTES_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(notes, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(NOTES_PATH)


def expand_path(p: str, base_dir: pathlib.Path) -> pathlib.Path:
    p = os.path.expandvars(os.path.expanduser(p))
    pp = pathlib.Path(p)
    if not pp.is_absolute():
        pp = (base_dir / p).resolve()
    return pp


def parse_aliases_from_file(path: pathlib.Path) -> Tuple[List[dict], List[pathlib.Path]]:
    aliases, sources = [], []
    if not path.exists() or not path.is_file():
        return aliases, sources

    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return aliases, sources

    base_dir = path.parent
    prev_note_buffer: Optional[str] = None
    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()

        # follow simple 'source' or '.' includes (also handles dirs and globs)
        msrc = SOURCE_RE.match(line)
        if msrc:
            src_raw = msrc.group(2).strip()
            expanded = expand_path(src_raw, base_dir)
            try:
                if any(ch in src_raw for ch in ["*", "?", "["]):
                    if os.path.isabs(src_raw):
                        for g in sorted(pathlib.Path(os.path.dirname(src_raw)).glob(os.path.basename(src_raw))):
                            if g.is_file():
                                sources.append(g)
                    else:
                        for g in sorted(base_dir.glob(src_raw)):
                            if g.is_file():
                                sources.append(g)
                else:
                    if expanded.exists():
                        sources.append(expanded)
            except Exception:
                pass
            continue

        # standalone note lines above alias: "# note: ..." or "#: ..."
        if stripped.startswith("#") and ("note:" in stripped.lower() or stripped.startswith("#:")):
            note_text = stripped.lstrip("#").strip()
            note_text = re.sub(r"^note:\s*", "", note_text, flags=re.I)
            prev_note_buffer = note_text or None
            continue

        m = ALIAS_RE.match(line)
        if not m:
            continue
        name, _, body, trailing_note = m.groups()
        note = trailing_note.strip() if trailing_note else ""
        if prev_note_buffer:
            note = (prev_note_buffer + (f" | {note}" if note else "")) or note
            prev_note_buffer = None

        aliases.append(
            {"name": name, "body": body, "note": note, "file": str(path), "line": lineno}
        )

    return aliases, sources


def collect_aliases(root_rc: pathlib.Path) -> List[dict]:
    seen, queue = set(), [root_rc]
    merged: Dict[str, dict] = {}
    while queue:
        cur = queue.pop(0)
        if cur in seen:
            continue
        seen.add(cur)
        a_list, srcs = parse_aliases_from_file(cur)
        for a in a_list:
            merged[a["name"]] = a  # last wins
        for s in srcs:
            try:
                if s.is_dir():
                    for f in sorted(s.glob("**/*")):
                        if f.is_file() and f.suffix in (".zsh", ".sh"):
                            queue.append(f)
                elif s.exists():
                    queue.append(s)
            except Exception:
                pass
    return sorted(merged.values(), key=lambda x: x["name"].lower())


# ---- Matching / filtering ----
def tokens(s: str) -> List[str]:
    return [t for t in s.lower().split() if t]


def match_score(alias: dict, needle: str) -> int:
    if not needle.strip():
        return 1
    hay = " ".join([alias["name"], alias["body"], alias.get("note", "")]).lower()
    return sum(1 for t in tokens(needle) if t in hay)


def filter_aliases(items: List[dict], needle: str) -> List[dict]:
    scored = [(match_score(a, needle), a) for a in items]
    scored.sort(key=lambda x: (-x[0], x[1]["name"].lower()))
    return [a for s, a in scored if s > 0 or not needle.strip()]


# ---- Runner ----
def ensure_zsh() -> str:
    zshi = shutil.which("zsh")
    if not zshi:
        raise RuntimeError("zsh not found on PATH.")
    return zshi


def _clear_screen():
    print("\033[0m\033[2J\033[H", end="", flush=True)


def run_alias(body: str, extra_args: List[str]) -> int:
    zsh_bin = ensure_zsh()
    cmd = body
    if extra_args:
        cmd = f"{cmd} {' '.join(shlex.quote(a) for a in extra_args)}"
    if CLEAR_BEFORE_RUN:
        _clear_screen()
    print(f"→ Executing: {cmd}\n")
    return subprocess.run([zsh_bin, "-ic", cmd]).returncode


# ---- Styles ----
STYLE = Style.from_dict({
    "frame.border": "fg:#5f5f5f",
    "frame.label": "bold fg:#00afff",
    "accent": "bold fg:#00afff",
    "note": "fg:#00d787",
    "dim": "fg:#888888",
    "danger": "bold fg:#ff5f5f",
    "warn": "bold fg:#ffaf00",
    "sel": "reverse",
    "kbd": "bold",
    "footer": "fg:#aaaaaa",
    "title": "bold",
    "status": "fg:#aaaaaa italic",
})

HELP_FT: FormattedText = [
    ("class:title", "Keys  "),
    ("class:kbd", "↑/↓"), ("", " navigate   "),
    ("class:kbd", "PgUp/PgDn"), ("", " fast   "),
    ("class:kbd", "/"), ("", " search   "),
    ("class:kbd", "Enter"), ("", " run   "),
    ("class:kbd", "e"), ("", " edit note   "),
    ("class:kbd", "i"), ("", " info   "),
    ("class:kbd", "r"), ("", " reload   "),
    ("class:kbd", "?"), ("", " help   "),
    ("class:kbd", "q"), ("", " quit"),
]


# ---- App State ----
class AppState:
    def __init__(self, rc_path: pathlib.Path):
        self.rc_path = rc_path
        self.notes = load_notes()
        self.aliases = collect_aliases(rc_path)
        for a in self.aliases:
            if a["name"] in self.notes:
                a["note"] = self.notes[a["name"]]
        self.query = ""
        self.filtered = filter_aliases(self.aliases, self.query)
        self.cursor = 0
        self.status = "Ready — press q to quit."

    def set_status(self, msg: str):
        self.status = msg

    def reload(self):
        self.notes = load_notes()
        self.aliases = collect_aliases(self.rc_path)
        for a in self.aliases:
            if a["name"] in self.notes:
                a["note"] = self.notes[a["name"]]
        self.apply_filter(self.query)
        self.set_status("Reloaded — press q to quit.")

    def apply_filter(self, q: str):
        self.query = q
        self.filtered = filter_aliases(self.aliases, q)
        self.cursor = 0 if self.filtered else -1
        self.set_status(f"Filtered: {len(self.filtered)}/{len(self.aliases)} — press q to quit.")

    def current(self) -> Optional[dict]:
        if 0 <= self.cursor < len(self.filtered):
            return self.filtered[self.cursor]
        return None


# ---- Rendering helpers ----
def highlight_fragments(text: str, needle: str, base_style: str = "") -> FormattedText:
    if not needle.strip():
        return FormattedText([(f"class:{base_style}" if base_style else "", text)])
    toks = list({t for t in tokens(needle)})
    pattern = re.compile("|".join(re.escape(t) for t in toks), flags=re.IGNORECASE)
    frags: List[Tuple[str, str]] = []
    last = 0
    for m in pattern.finditer(text):
        if m.start() > last:
            frags.append((f"class:{base_style}" if base_style else "", text[last:m.start()]))
        frags.append(("class:accent", text[m.start():m.end()]))
        last = m.end()
    if last < len(text):
        frags.append((f"class:{base_style}" if base_style else "", text[last:]))
    return FormattedText(frags)


def render_list(state: AppState, height: int) -> FormattedText:
    out: List[Tuple[str, str]] = []
    # counter: filtered / total
    out.append(("class:title", f"  Aliases ({len(state.filtered)}/{len(state.aliases)})\n"))
    out.append(("class:dim", "  ───────────────────────────────────────────\n"))
    visible = state.filtered[: max(0, height - 4)]  # leave room for status line
    for i, a in enumerate(visible):
        mark = "➤ " if i == state.cursor else "  "
        sel_style = "class:sel" if i == state.cursor else ""
        name_frag = highlight_fragments(a["name"], state.query)
        row_frags: List[Tuple[str, str]] = []
        row_frags.append((sel_style, mark))
        for st, tx in name_frag:
            st2 = f"{sel_style} {st}".strip() if sel_style else st
            row_frags.append((st2, tx))
        note = a.get("note", "")
        if note:
            row_frags.append(("", "  "))
            row_frags.append((f"{sel_style} class:note".strip(), f"[note: {note}]"))
        row_frags.append(("", "\n"))
        out.extend(row_frags)
    # status line inside the list frame (so it’s always visible)
    out.append(("class:status", f"\n  {state.status}\n"))
    return FormattedText(out)


def render_detail(a: Optional[dict], q: str) -> FormattedText:
    if not a:
        return FormattedText([("", "No selection\n")])
    frags: List[Tuple[str, str]] = []
    frags.extend([("class:title", "Alias"), ("", ": "), ("class:accent", a["name"]), ("", "\n")])
    frags.extend([("class:title", "Command"), ("", ": ")])
    frags.extend(highlight_fragments(a["body"], q))
    frags.append(("", "\n"))
    frags.extend([("class:title", "Note"), ("", ": "), ("class:note", a.get("note", "")), ("", "\n")])
    frags.extend([("class:title", "Defined at"), ("", ": "), ("class:dim", f"{a['file']}:{a['line']}"), ("", "\n")])
    return FormattedText(frags)


# ---- Build one TUI run; return an action dict to the outer loop ----
def build_app(state: AppState) -> Application:
    def search_text():
        ft: List[Tuple[str, str]] = []
        ft.extend([("class:title", "Search"), ("", ": ")])
        if state.query:
            ft.extend(highlight_fragments(state.query, state.query, base_style="accent"))
        else:
            ft.append(("class:dim", "∅"))
        return FormattedText(ft)

    search_ctrl = FormattedTextControl(search_text)
    search_win = Frame(Window(search_ctrl, height=1), title="Filter")

    list_ctrl = FormattedTextControl(lambda: render_list(state, height=40), focusable=True)
    list_win = Frame(Window(list_ctrl, wrap_lines=False), title="Alias List")

    right_ctrl = FormattedTextControl(lambda: render_detail(state.current(), state.query))
    right_win = Frame(Window(right_ctrl, wrap_lines=True), title="Details")

    footer_text = HELP_FT
    footer_ctrl = FormattedTextControl(lambda: footer_text)
    footer = Window(footer_ctrl, height=1, style="class:footer")

    root_container = HSplit([
        VSplit([search_win, right_win], padding=1, padding_char=" "),
        VSplit([list_win], padding=0),
        footer
    ])

    kb = KeyBindings()

    @kb.add("down")
    def _(event):
        if state.cursor < len(state.filtered) - 1:
            state.cursor += 1

    @kb.add("up")
    def _(event):
        if state.cursor > 0:
            state.cursor -= 1

    @kb.add("pageup")
    def _(event):
        state.cursor = max(0, state.cursor - 10)

    @kb.add("pagedown")
    def _(event):
        state.cursor = min(max(0, len(state.filtered) - 1), state.cursor + 10)

    @kb.add("/")
    def _(event):
        q = ptk_prompt("Filter (/ to search, empty to clear): ", default=state.query or "")
        state.apply_filter(q)

    @kb.add("escape")
    def _(event):
        state.apply_filter("")

    @kb.add("r")
    def _(event):
        state.reload()

    @kb.add("i")
    async def _(event):
        a = state.current()
        if not a:
            state.set_status("No selection. Press q to quit.")
            return
        await message_dialog(
            title=f"Alias Info: {a['name']}",
            text=f"Command:\n{a['body']}\n\nNote:\n{a.get('note','')}\n\nDefined at:\n{a['file']}:{a['line']}"
        ).run_async()
        state.set_status("Info closed. Press q to quit.")

    @kb.add("e")
    async def _(event):
        a = state.current()
        if not a:
            state.set_status("No selection. Press q to quit.")
            return
        current = a.get("note", "")
        new_note = await input_dialog(
            title=f"Edit note for {a['name']}",
            text="Note (empty to clear):",
            ok_text="Save",
            cancel_text="Cancel",
            default=current
        ).run_async()
        if new_note is None:
            state.set_status("Edit cancelled. Press q to quit.")
            return
        if new_note.strip():
            state.notes[a["name"]] = new_note.strip()
        else:
            state.notes.pop(a["name"], None)
        save_notes(state.notes)
        state.reload()
        state.set_status("Note saved. Press q to quit.")

    @kb.add("enter")
    async def _(event):
        a = state.current()
        if not a:
            state.set_status("No selection. Press q to quit.")
            return
        extra = await input_dialog(
            title=f"Run {a['name']}",
            text=f"Extra args to append to:\n{a['body']}\n(Leave empty for none)"
        ).run_async()
        if extra is None:
            state.set_status("Run cancelled. Press q to quit.")
            return
        extra_args = shlex.split(extra) if extra else []
        event.app.exit(result={"action": "run", "body": a["body"], "extra": extra_args})

    @kb.add("?")
    async def _(event):
        await message_dialog(
            title="Help",
            text=("Use / to search; ↑/↓ to move; Enter to run; e to edit note; "
                  "i for details; r to reload; Esc to clear search; q to quit.")
        ).run_async()
        state.set_status("Help closed. Press q to quit.")

    @kb.add("q")
    def _(event):
        event.app.exit(result={"action": "quit"})

    app = Application(
        layout=Layout(root_container),
        key_bindings=kb,
        full_screen=True,
        mouse_support=True,
        style=STYLE,
    )
    return app


def main():
    rc = os.environ.get("ALIAS_RUNNER_RC", str(DEFAULT_RC))
    rc_path = pathlib.Path(os.path.expanduser(rc))
    if not rc_path.exists():
        print(f"Could not find {rc_path}. Set ALIAS_RUNNER_RC to your zshrc if needed.", flush=True)
        raise SystemExit(1)

    state = AppState(rc_path)

    while True:
        app = build_app(state)
        result: Any = app.run()

        if isinstance(result, dict) and result.get("action") == "quit":
            break

        if isinstance(result, dict) and result.get("action") == "run":
            body = result.get("body", "")
            extra = result.get("extra", [])
            try:
                code = run_alias(body, extra)
            except Exception as e:
                code = None
                print(f"\nError: {e}\n")

            # Friendly post-run prompt
            if code is not None:
                print(f"\nExit code: {code}")
            choice = input("\nPress Enter to return to menu, or type 'q' to quit: ").strip().lower()
            if choice == "q":
                break

            state.reload()
            continue

        # Cancel or no action: loop back with a clean status message.
        state.set_status("Ready — press q to quit.")
        continue


if __name__ == "__main__":
    main()