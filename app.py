import html as html_lib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

socket.setdefaulttimeout(8)

APP_DIR = Path(__file__).resolve().parent
OLLAMA_DEFAULT = "http://localhost:11434"
CODE_MODELS = [
    "qwen2.5-coder:7b",
    "deepseek-r1:8b",
    "qwen2.5:3b",
    "llama3.2:3b",
    "phi4-mini:latest",
    "granite4.2:3b",
]
SCAN_EXTENSIONS = {".v", ".py", ".c", ".tex", ".ys", ".json", ".md"}
SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules", ".pytest_cache"}

MODES = {
    "Code Explainer": (
        "You are a principal hardware and software engineer. Explain the supplied code "
        "precisely: purpose, step-by-step algorithm, syntax notes, data-path and control "
        "flow, complexity, and edge cases. Use markdown headings, numbered steps, and a "
        "short ASCII signal/data-flow diagram. Never truncate the analysis."
    ),
    "Bug Fixer & Refactorer": (
        "You are a senior static-analysis and refactoring engine. Identify concrete bugs, "
        "race conditions, off-by-one errors, unsafe constructs, and performance issues "
        "with line references. Then output a complete, optimized, production-ready rewrite "
        "in a single fenced code block. Never use placeholders such as 'rest of code here'."
    ),
    "Testbench / Test Generator": (
        "You are a verification engineer. Generate a complete self-checking testbench for "
        "the supplied code. For Verilog use Icarus-compatible constructs with $display "
        "PASS/FAIL assertions; for Python use pytest-style assertions and edge cases; for C "
        "use assert.h. Output the full test file in one fenced code block plus exact run "
        "commands. Never truncate."
    ),
    "Architecture & System Designer": (
        "You are a systems architect. Produce a structured design review: module breakdown "
        "table, interfaces, an ASCII block diagram, a Mermaid.js diagram inside a "
        "```mermaid fenced block, and trade-off analysis (latency, area, power, security). "
        "Keep the Mermaid syntax valid (flowchart TD)."
    ),
}

DIFFICULTIES = ["Beginner", "Intermediate", "Advanced", "Exam-Level"]
PRIORITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]

for key, value in {
    "module": "coding",
    "scratchpad": "",
    "scratch_lang": "Python",
    "agent_mode": "Code Explainer",
    "agent_response": None,
    "agent_response_mode": None,
    "exec_output": None,
    "exec_rc": None,
    "exec_engine": None,
    "ollama_url": OLLAMA_DEFAULT,
    "coding_model": "qwen2.5-coder:7b",
    "tutor_model": "llama3.2:3b",
    "ollama_status": None,
    "tutor_topic": "",
    "tutor_guide": None,
    "tutor_sources": None,
    "quiz": None,
    "quiz_gen": 0,
    "quiz_results": None,
    "mastery_earned": 0.0,
    "mastery_possible": 0.0,
    "tasks": [],
    "task_seq": 0,
    "task_filter": "All",
    "pomo_phase": "Work",
    "pomo_running": False,
    "pomo_started": None,
    "pomo_prior": 0.0,
    "pomo_done": 0,
    "pomo_work": 25,
    "pomo_break": 5,
    "notes": "",
}.items():
    st.session_state.setdefault(key, value)

st.set_page_config(
    page_title="Material Suite - APEX AI workstation",
    page_icon=":material/apps:",
    layout="wide",
    initial_sidebar_state="expanded",
)

MD3_CSS = """
<style>
  html, body, .stApp, [class*="css"] {
    font-family: 'Google Sans', 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  }
  h1, h2, h3 { color: #E2E2E6; font-weight: 600; letter-spacing: .2px; }
  .stApp { background: #121316; }
  section[data-testid="stSidebar"] { background: #1A1C1E !important; border-right: 1px solid #44474E; }
  section[data-testid="stSidebar"] > div { background: #1A1C1E !important; }

  .md3-brand { padding: 6px 4px 14px 4px; }
  .md3-brand-title { color: #D0BCFF; font-size: 22px; font-weight: 600; }
  .md3-brand-sub { color: #C4C6D0; font-size: 12px; margin-top: 2px; }

  .md3-hero { margin-bottom: 6px; }
  .md3-chip {
    display: inline-block; padding: 4px 14px; border-radius: 28px; font-size: 12px;
    background: rgba(208,188,255,.14); color: #D0BCFF; border: 1px solid #44474E; margin-right: 6px;
  }
  .md3-chip-teal { color: #A8C7FA; background: rgba(168,199,250,.14); }

  div[data-testid="stButton"] > button {
    border-radius: 16px;
    border: 1px solid #44474E;
    background: #2B2D32;
    color: #E2E2E6;
    font-weight: 500;
    transition: transform .16s ease, box-shadow .18s ease, background .18s ease;
    box-shadow: 0px 4px 12px rgba(0, 0, 0, 0.35);
  }
  div[data-testid="stButton"] > button:hover {
    transform: translateY(-2px);
    border-color: #D0BCFF;
    box-shadow: 0px 4px 12px rgba(0, 0, 0, 0.35), 0 0 10px rgba(208, 188, 255, 0.28);
  }
  div[data-testid="stButton"] > button[kind="primary"],
  div[data-testid="stButton"] > button[data-testid="stBaseButton-primary"] {
    background: #4F378B !important;
    color: #EADDFF !important;
    border: 1px solid #D0BCFF !important;
  }
  div[data-testid="stFormSubmitButton"] > button {
    border-radius: 16px;
    background: #4F378B; color: #EADDFF; border: 1px solid #D0BCFF;
  }

  div[data-testid="stPills"] button, div[data-testid="stSegmentedControl"] button {
    border-radius: 28px !important;
    border: 1px solid #44474E !important;
    background: #1A1C1E !important;
    color: #C4C6D0 !important;
  }
  div[data-testid="stPills"] button[aria-checked="true"],
  div[data-testid="stPills"] button[aria-pressed="true"],
  div[data-testid="stSegmentedControl"] button[aria-checked="true"],
  div[data-testid="stSegmentedControl"] button[aria-pressed="true"] {
    background: #4F378B !important;
    color: #EADDFF !important;
    border-color: #D0BCFF !important;
  }

  div[data-testid="stTextInput"] input,
  div[data-testid="stNumberInput"] input,
  div[data-testid="stTextArea"] textarea {
    border-radius: 16px !important;
    background: #2B2D32 !important;
    color: #E2E2E6 !important;
    border: 1px solid #44474E !important;
  }
  div[data-testid="stTextInput"] input:focus,
  div[data-testid="stTextArea"] textarea:focus { border-color: #D0BCFF !important; }
  div[data-baseweb="input"], div[data-baseweb="textarea"] {
    border-radius: 16px !important; border-color: #44474E !important; background: #2B2D32 !important;
  }
  div[data-baseweb="select"] > div {
    border-radius: 16px !important; background: #2B2D32 !important; border-color: #44474E !important;
  }
  div[data-testid="stFileUploader"] section {
    border-radius: 16px; border: 1px dashed #44474E; background: #1A1C1E;
  }

  div[data-testid="stVerticalBlockBorderWrapper"] {
    background: #212327 !important;
    border: 1px solid #44474E !important;
    border-radius: 24px !important;
    box-shadow: 0px 4px 12px rgba(0, 0, 0, 0.35);
  }
  details[data-testid="stExpander"] {
    background: #212327; border: 1px solid #44474E; border-radius: 24px; overflow: hidden;
  }
  div[data-testid="stMetric"] {
    background: #212327; border: 1px solid #44474E; border-radius: 24px;
    padding: 12px 16px; box-shadow: 0px 4px 12px rgba(0, 0, 0, 0.35);
  }
  div[data-testid="stMetricValue"] { color: #D0BCFF; }

  div[data-testid="stCodeBlock"], div[data-testid="stCode"] {
    background: #0D0E11 !important; border: 1px solid #44474E; border-radius: 16px;
  }
  .apex-term {
    background: #0D0E11; border: 1px solid #44474E; border-radius: 16px;
    padding: 14px 16px; margin-top: 6px;
    font-family: 'JetBrains Mono', 'Cascadia Mono', Consolas, monospace;
    font-size: 13px; color: #8BE9A8; white-space: pre-wrap; word-break: break-word;
    max-height: 420px; overflow-y: auto;
  }
  .apex-term-head { color: #A8C7FA; display: block; margin-bottom: 8px; font-weight: 600; }

  .md3-pill {
    display: inline-block; padding: 2px 12px; border-radius: 28px; font-size: 12px;
    font-weight: 600; letter-spacing: .3px; border: 1px solid transparent;
  }
  .pill-CRITICAL { color: #F2B8B5; background: rgba(242,184,181,.14); border-color: #F2B8B5; }
  .pill-HIGH     { color: #FFB4AB; background: rgba(255,180,171,.14); border-color: #FFB4AB; }
  .pill-MEDIUM   { color: #EADDFF; background: rgba(234,221,255,.12); border-color: #D0BCFF; }
  .pill-LOW      { color: #A8C7FA; background: rgba(168,199,250,.12); border-color: #A8C7FA; }

  .task-done { text-decoration: line-through; color: #7A7C85; }
  .pomo-time {
    font-size: 56px; font-weight: 700; color: #D0BCFF; text-align: center;
    font-family: 'Google Sans', 'Inter', sans-serif; letter-spacing: 2px; margin: 4px 0 8px 0;
  }
  div[data-testid="stProgress"] > div > div > div > div { background: #D0BCFF; }
  div[data-testid="stProgress"] > div > div { background: #2B2D32; border-radius: 28px; }

  [data-testid="stCaptionContainer"] { color: #C4C6D0; }
  a { color: #A8C7FA !important; }
</style>
"""

st.markdown(MD3_CSS, unsafe_allow_html=True)


def net_call(fn, *args, timeout=25, **kwargs):
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(fn, *args, **kwargs)
    try:
        return future.result(timeout=timeout), None
    except FutureTimeout:
        return None, "network timeout exhausted"
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"
    finally:
        executor.shutdown(wait=False)


def ollama_chat(system, user, model, url, temperature=0.4, timeout=240):
    def _call():
        response = requests.post(
            url.rstrip("/") + "/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "options": {"temperature": temperature, "num_ctx": 8192},
            },
            timeout=(8, timeout),
        )
        response.raise_for_status()
        return response.json().get("message", {}).get("content", "")

    return net_call(_call, timeout=timeout + 12)


def ollama_models(url):
    def _call():
        response = requests.get(url.rstrip("/") + "/api/tags", timeout=(5, 8))
        response.raise_for_status()
        return [m["name"] for m in response.json().get("models", [])]

    return net_call(_call, timeout=20)


class DDGParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.results = []
        self.mode = None
        self._url = ""

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        attrs = dict(attrs)
        classes = attrs.get("class", "")
        href = attrs.get("href", "")
        if "result__a" in classes:
            self.mode = "title"
            self._url = self._resolve(href)
        elif "result__snippet" in classes:
            self.mode = "snippet"

    def handle_endtag(self, tag):
        if tag == "a":
            self.mode = None

    def handle_data(self, data):
        text = data.strip()
        if not text or self.mode is None:
            return
        if self.mode == "title":
            self.results.append({"title": text, "url": self._url})
        elif self.mode == "snippet":
            if self.results and "snippet" not in self.results[-1]:
                self.results[-1]["snippet"] = text

    @staticmethod
    def _resolve(url):
        if url.startswith("//"):
            url = "https:" + url
        elif url.startswith("/"):
            url = urljoin("https://duckduckgo.com", url)
        if "uddg=" in url:
            query = parse_qs(urlparse(url).query)
            if "uddg" in query:
                return query["uddg"][0]
        return url


def ddg_search(query, max_results=8):
    def _call():
        response = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            timeout=(6, 12),
        )
        response.raise_for_status()
        parser = DDGParser()
        parser.feed(response.text)
        return parser.results[:max_results]

    return net_call(_call, timeout=20)


def youtube_video_id(url):
    match = re.search(r"(?:v=|youtu\.be/|/embed/)([\w-]{11})", url or "")
    return match.group(1) if match else None


def youtube_metadata(url):
    video_id = youtube_video_id(url)
    if not video_id:
        return None, "could not parse a YouTube video id"
    canonical = f"https://www.youtube.com/watch?v={video_id}"

    def _call():
        meta = {
            "video_id": video_id,
            "url": canonical,
            "title": f"YouTube video {video_id}",
            "author": "",
            "description": "",
        }
        try:
            oembed = requests.get(
                "https://www.youtube.com/oembed",
                params={"url": canonical, "format": "json"},
                timeout=(6, 10),
            )
            if oembed.status_code == 200:
                payload = oembed.json()
                meta["title"] = payload.get("title", meta["title"])
                meta["author"] = payload.get("author_name", "")
        except requests.RequestException:
            pass
        try:
            page = requests.get(
                canonical,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=(6, 12),
            )
            match = re.search(r'"shortDescription":"((?:[^"\\]|\\.)*)"', page.text)
            if match:
                meta["description"] = json.loads('"' + match.group(1) + '"')
        except (requests.RequestException, json.JSONDecodeError, ValueError):
            pass
        return meta

    return net_call(_call, timeout=25)


def html_to_text(markup):
    markup = re.sub(r"(?is)<(script|style|noscript|svg|head)[^>]*>.*?</\1>", " ", markup)
    markup = re.sub(r"(?is)<br\s*/?>|</p>|</div>|</li>", "\n", markup)
    markup = re.sub(r"(?s)<[^>]+>", " ", markup)
    markup = html_lib.unescape(markup)
    markup = re.sub(r"[ \t\r\f\v]+", " ", markup)
    markup = re.sub(r"\n\s*\n+", "\n", markup)
    return markup.strip()


def fetch_article(url, limit=4000):
    def _call():
        response = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            timeout=(6, 14),
        )
        response.raise_for_status()
        title_match = re.search(r"(?is)<title[^>]*>(.*?)</title>", response.text)
        title = html_lib.unescape(title_match.group(1).strip()) if title_match else url
        return {"url": url, "title": title, "text": html_to_text(response.text)[:limit]}

    return net_call(_call, timeout=25)


def extract_pdf_text(data, limit=8000):
    try:
        import io

        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages[:40]]
        return "\n".join(pages).strip()[:limit]
    except Exception as exc:
        return f"[pdf extraction failed: {type(exc).__name__}]"


def detect_language(text, filename=None):
    if filename:
        mapping = {
            ".v": "Verilog",
            ".py": "Python",
            ".c": "C",
            ".tex": "LaTeX",
            ".ys": "Yosys",
            ".json": "JSON",
            ".md": "Markdown",
        }
        suffix = Path(filename).suffix.lower()
        if suffix in mapping:
            return mapping[suffix]
    if not text.strip():
        return "Plain text"
    stripped = re.sub(r"(?s)//.*?\n|/\*.*?\*/", "\n", text)
    if re.search(r"\bendmodule\b|\bmodule\s+\w+\s*\(|\balways\s*@", stripped):
        return "Verilog"
    if re.search(r"^\s*(def|class|import|from)\s+\w+", stripped, re.M) or "print(" in stripped:
        return "Python"
    if re.search(r"#include\s*<|int\s+main\s*\(|printf\s*\(", stripped):
        return "C"
    if re.search(r"\\documentclass|\\begin\{document\}", stripped):
        return "LaTeX"
    if re.search(r"^\s*(read_verilog|hierarchy|synth)\b", stripped, re.M):
        return "Yosys"
    try:
        json.loads(stripped)
        return "JSON"
    except (json.JSONDecodeError, ValueError):
        pass
    if re.search(r"^#{1,6}\s+\w", stripped, re.M):
        return "Markdown"
    return "Plain text"


def scan_workspace():
    found = []
    for root, dirs, files in os.walk(APP_DIR):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for name in sorted(files):
            if Path(name).suffix.lower() in SCAN_EXTENSIONS:
                found.append(str((Path(root) / name).relative_to(APP_DIR)))
    return sorted(found)


def load_file_into_scratchpad(rel_path):
    path = APP_DIR / rel_path
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        st.session_state.agent_response = f"File load failed: {exc}"
        return
    st.session_state.scratchpad = content
    st.session_state.scratch_lang = detect_language(content, rel_path)
    st.session_state.agent_response = None


def execute_code(code, language):
    if language == "Python":
        return _run_python(code)
    if language == "Verilog":
        return _run_verilog(code)
    if language == "C":
        return _run_c(code)
    return _simulate(code, language)


def _run_python(code):
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "scratch_main.py"
        script.write_text(code, encoding="utf-8")
        flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        try:
            proc = subprocess.run(
                [sys.executable, str(script)],
                capture_output=True,
                text=True,
                timeout=15,
                cwd=tmp,
                creationflags=flags,
            )
        except subprocess.TimeoutExpired:
            return "Execution aborted: exceeded 15s wall-clock limit.", 124, "python (live)"
        output = (proc.stdout or "") + (proc.stderr or "")
        return output or "[no output]", proc.returncode, "python (live)"


def _run_verilog(code):
    iverilog = shutil.which("iverilog") or (
        "C:\\iverilog\\bin\\iverilog.exe" if Path("C:\\iverilog\\bin\\iverilog.exe").exists() else None
    )
    if not iverilog:
        return _simulate(code, "Verilog") + "\n[iverilog not found - static analysis shown]"
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "dut.v"
        source.write_text(code, encoding="utf-8")
        flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        try:
            compile_proc = subprocess.run(
                [iverilog, "-o", str(Path(tmp) / "sim.vvp"), str(source)],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=tmp,
                creationflags=flags,
            )
        except subprocess.TimeoutExpired:
            return "iverilog compile exceeded 30s.", 124, "iverilog (live)"
        log = (compile_proc.stdout or "") + (compile_proc.stderr or "")
        if compile_proc.returncode != 0:
            return "iverilog compile failed:\n" + log, compile_proc.returncode, "iverilog (live)"
        if re.search(r"\binitial\b", code) and re.search(r"\$display|\$finish|module\s+tb", code):
            try:
                sim_proc = subprocess.run(
                    ["vvp", str(Path(tmp) / "sim.vvp")] if shutil.which("vvp") else [str(Path(iverilog).with_name("vvp.exe")), str(Path(tmp) / "sim.vvp")],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    cwd=tmp,
                    creationflags=flags,
                )
                sim_log = (sim_proc.stdout or "") + (sim_proc.stderr or "")
                return log + "\n(simulated)\n" + (sim_log or "[no sim output]"), sim_proc.returncode, "iverilog (live)"
            except subprocess.TimeoutExpired:
                return log + "\n[simulation timeout 30s]", 124, "iverilog (live)"
        return (log or "") + "Compilation succeeded (no testbench detected - add an initial block to elaborate).", 0, "iverilog (live)"


def _run_c(code):
    compiler = shutil.which("gcc") or shutil.which("clang")
    if not compiler:
        return _simulate(code, "C") + "\n[no C compiler found - static analysis shown]", None, "static analysis"
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "scratch_main.c"
        source.write_text(code, encoding="utf-8")
        exe = Path(tmp) / ("scratch_main.exe" if os.name == "nt" else "scratch_main.out")
        flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        try:
            compile_proc = subprocess.run(
                [compiler, str(source), "-o", str(exe)],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=tmp,
                creationflags=flags,
            )
            if compile_proc.returncode != 0:
                return "gcc compile failed:\n" + compile_proc.stdout + compile_proc.stderr, compile_proc.returncode, "gcc (live)"
            run_proc = subprocess.run(
                [str(exe)], capture_output=True, text=True, timeout=15, cwd=tmp, creationflags=flags
            )
            return (run_proc.stdout or "") + (run_proc.stderr or ""), run_proc.returncode, "gcc (live)"
        except subprocess.TimeoutExpired:
            return "C execution exceeded time limit.", 124, "gcc (live)"


def _simulate(code, language):
    lines = code.splitlines()
    depth = max((len(line) - len(line.lstrip())) for line in lines) if lines else 0
    branches = len(re.findall(r"\b(if|for|while|case|switch|elif)\b", code))
    functions = len(re.findall(r"\b(def|function|task|int\s+\w+\s*\(|void\s+\w+\s*\()", code))
    return (
        "[static analysis - no local toolchain for this target]\n"
        f"language      : {language}\n"
        f"lines         : {len(lines)}\n"
        f"characters    : {len(code)}\n"
        f"branches      : {branches}\n"
        f"functions     : {functions}\n"
        f"max indent    : {depth}\n"
        f"est. complexity: {branches + functions + 1}"
    ), None, "static analysis"


def render_terminal(text, rc=None, engine=None):
    head = "terminal"
    if engine:
        head += f" | {engine}"
    if rc is not None:
        head += f" | exit {rc}"
    st.markdown(
        f'<div class="apex-term"><span class="apex-term-head">{html_lib.escape(head)}</span>'
        f"{html_lib.escape(text)}</div>",
        unsafe_allow_html=True,
    )


def extract_mermaid(text):
    match = re.search(r"```mermaid\s*(.*?)```", text, re.S)
    return match.group(1).strip() if match else None


def render_mermaid(diagram):
    escaped = html_lib.escape(diagram)
    body = f"""<!doctype html><html><head>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<style>body{{background:#121316;margin:0;padding:10px}}</style></head>
<body><pre class="mermaid">{escaped}</pre>
<script>try{{mermaid.initialize({{startOnLoad:true,theme:'dark',themeVariables:{{primaryColor:'#4F378B',primaryTextColor:'#EADDFF',lineColor:'#A8C7FA',fontFamily:'Inter'}}}});}}catch(e){{}}</script>
</body></html>"""
    try:
        st.html(body, unsafe_allow_javascript=True)
    except TypeError:
        st.code(diagram, language="mermaid")


def parse_json_array(text):
    cleaned = re.sub(r"```(?:json)?", "", text).strip().strip("`").strip()
    for candidate in (cleaned,):
        try:
            data = json.loads(candidate)
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, ValueError):
            pass
    match = re.search(r"\[.*\]", cleaned, re.S)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def normalize_quiz(raw):
    quiz = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        qtype = str(item.get("type", "")).lower()
        question = str(item.get("question", "")).strip()
        if not question:
            continue
        if qtype.startswith("mcq") or "options" in item:
            options = [str(o) for o in item.get("options", [])][:6]
            if len(options) < 2:
                continue
            answer = item.get("answer_index", item.get("answer"))
            if isinstance(answer, str) and answer.strip().upper()[:1] in "ABCDEF":
                answer = "ABCDEF".index(answer.strip().upper()[0])
            try:
                answer = int(answer)
            except (TypeError, ValueError):
                answer = 0
            if not 0 <= answer < len(options):
                answer = 0
            quiz.append(
                {
                    "type": "mcq",
                    "question": question,
                    "options": options,
                    "answer_index": answer,
                    "explanation": str(item.get("explanation", "")).strip(),
                }
            )
        else:
            quiz.append(
                {
                    "type": "short",
                    "question": question,
                    "rubric": str(item.get("rubric", "")).strip(),
                    "model_answer": str(item.get("model_answer", "")).strip(),
                }
            )
    return quiz


def keyword_grade(answer, rubric):
    points = [p.strip() for p in re.split(r"[;.\n]", rubric) if len(p.strip()) > 4]
    if not points:
        return (1.0 if answer.strip() else 0.0), "No rubric - presence scored."
    hits = 0
    for point in points:
        keywords = [w.lower() for w in re.findall(r"\w{4,}", point)]
        if any(word in answer.lower() for word in keywords):
            hits += 1
    return hits / len(points), f"Matched {hits}/{len(points)} rubric points."


def score_ring(value, label, suffix="%"):
    figure = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=value,
            number={"suffix": suffix, "font": {"color": "#E2E2E6"}},
            gauge={
                "axis": {"range": [0, 100], "tickcolor": "#44474E", "tickfont": {"color": "#C4C6D0"}},
                "bar": {"color": "#D0BCFF"},
                "bgcolor": "#2B2D32",
                "borderwidth": 1,
                "bordercolor": "#44474E",
                "steps": [{"range": [0, 100], "color": "#212327"}],
            },
            title={"text": label, "font": {"color": "#C4C6D0", "size": 14}},
        )
    )
    figure.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=230,
        margin={"l": 12, "r": 12, "t": 40, "b": 8},
        font={"color": "#E2E2E6"},
    )
    return figure


def history_bar(df, label):
    figure = go.Figure(
        go.Bar(
            x=df[label],
            y=df["Score"],
            marker={"color": "#A8C7FA", "line": {"color": "#D0BCFF", "width": 1}},
            text=df["Score"].round(0),
            textposition="outside",
        )
    )
    figure.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=260,
        margin={"l": 12, "r": 12, "t": 30, "b": 8},
        font={"color": "#E2E2E6"},
        xaxis={"gridcolor": "#2B2D32"},
        yaxis={"gridcolor": "#2B2D32", "range": [0, 105]},
    )
    return figure


def set_module(name):
    st.session_state.module = name


with st.sidebar:
    st.markdown(
        '<div class="md3-brand"><div class="md3-brand-title">Material Suite</div>'
        '<div class="md3-brand-sub">MD3 AI workstation - Project APEX</div></div>',
        unsafe_allow_html=True,
    )
    st.markdown("##### Navigation")
    for key, label, icon in [
        ("coding", "Coding agent", ":material/code:"),
        ("tutor", "NotebookLM portal", ":material/school:"),
        ("focus", "Productivity hub", ":material/bolt:"),
    ]:
        st.button(
            label,
            key=f"nav_{key}",
            icon=icon,
            width="stretch",
            on_click=set_module,
            args=(key,),
        )
    active = st.session_state.module
    st.markdown(
        f"<style>.st-key-nav_{active} button {{"
        "background: #4F378B !important; color: #EADDFF !important;"
        "border: 1px solid #D0BCFF !important; }</style>",
        unsafe_allow_html=True,
    )
    st.divider()
    with st.expander("Engine settings"):
        st.text_input("Ollama endpoint", key="ollama_url")
        st.selectbox("Coding model", CODE_MODELS, key="coding_model")
        st.selectbox("Tutor model", CODE_MODELS, key="tutor_model")
        if st.button("Test connection", icon=":material/wifi:", width="stretch"):
            models, err = net_call(
                lambda: requests.get(
                    st.session_state.ollama_url.rstrip("/") + "/api/tags", timeout=(6, 10)
                ).json(),
                timeout=15,
            )
            if err:
                st.session_state.ollama_status = ("error", err)
            else:
                st.session_state.ollama_status = ("ok", len(models.get("models", [])))
        status = st.session_state.ollama_status
        if status:
            if status[0] == "ok":
                st.badge(f"Ollama online - {status[1]} models", color="green")
            else:
                st.badge("Ollama offline", color="red")
                st.caption(status[1])
    st.caption("3 modules | session-state persistence | local LLM + live web ingestion")


def render_coding_agent():
    st.markdown("## Autonomous coding agent")
    st.caption("File explorer, language auto-detection, four agent modes, and a live execution terminal.")

    left, right = st.columns([1, 1.25])
    with left:
        st.markdown("#### Workspace explorer")
        files = scan_workspace()
        selected = st.selectbox("Repository files", options=["-"] + files, key="file_pick")
        st.button(
            "Open in scratchpad",
            icon=":material/folder_open:",
            width="stretch",
            disabled=selected == "-",
            on_click=load_file_into_scratchpad,
            args=(selected,),
        )
        st.selectbox(
            "Scratchpad language",
            ["Python", "Verilog", "C", "LaTeX", "Yosys", "JSON", "Markdown", "Plain text"],
            key="scratch_lang",
        )
        code = st.text_area(
            "Code scratchpad - paste or load any source",
            height=320,
            key="scratchpad",
            placeholder="Paste Verilog / Python / C / LaTeX here, or open a workspace file.",
        )
        st.caption(f"Auto-detected language: {detect_language(code)}")

    with right:
        st.markdown("#### Agent modes")
        mode = st.pills(
            "Agent mode",
            list(MODES),
            selection_mode="single",
            key="agent_mode",
            label_visibility="collapsed",
        )
        run_agent = st.button(
            "Run agent",
            type="primary",
            icon=":material/auto_awesome:",
            width="stretch",
            disabled=not code.strip(),
        )
        if run_agent:
            with st.spinner(f"{mode} via {st.session_state.coding_model}..."):
                prompt = (
                    f"Language: {detect_language(code)}\n"
                    f"Target goal: {mode}\n\nSource code:\n```\n{code[:12000]}\n```"
                )
                response, err = ollama_chat(
                    MODES[mode],
                    prompt,
                    st.session_state.coding_model,
                    st.session_state.ollama_url,
                )
            if err:
                st.error(f"Agent engine unavailable: {err}. Start Ollama or check the endpoint in settings.")
            else:
                st.session_state.agent_response = response
                st.session_state.agent_response_mode = mode

        if st.session_state.agent_response:
            st.markdown(
                f'<span class="md3-pill pill-LOW">{html_lib.escape(str(st.session_state.agent_response_mode))}</span>',
                unsafe_allow_html=True,
            )
            with st.container(border=True):
                st.markdown(st.session_state.agent_response)
            mermaid = extract_mermaid(st.session_state.agent_response)
            if mermaid:
                st.markdown("##### Rendered architecture diagram")
                render_mermaid(mermaid)

    st.markdown("#### Execution terminal")
    exec_col1, exec_col2 = st.columns([3, 1])
    detected = detect_language(code)
    exec_options = ["Python", "Verilog", "C", "Plain text"]
    default_index = exec_options.index(detected) if detected in exec_options else 3
    with exec_col1:
        exec_lang = st.selectbox("Execution target", exec_options, index=default_index, key="exec_lang")
    with exec_col2:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        exec_clicked = st.button(
            "Execute",
            icon=":material/terminal:",
            width="stretch",
            disabled=not code.strip(),
        )
    if exec_clicked:
        with st.spinner("Executing in sandboxed subprocess..."):
            out, rc, engine = execute_code(code, exec_lang)
        st.session_state.exec_output = out
        st.session_state.exec_rc = rc
        st.session_state.exec_engine = engine
    if st.session_state.exec_output is not None:
        render_terminal(st.session_state.exec_output, st.session_state.exec_rc, st.session_state.exec_engine)
    else:
        render_terminal("idle - paste code and press Execute. Python and Verilog run live; other targets fall back to static analysis.")


def render_tutor():
    st.markdown("## AI tutoring & study engine")
    st.caption("NotebookLM-style multi-pass research: ingestion -> master study guide -> adaptive testing.")

    topic = st.text_input(
        "Topic / subject (required)",
        key="tutor_topic",
        placeholder="e.g. RISC-V out-of-order execution, Quantum key distribution",
    )

    with st.expander("Resource drawer - optional uploads, links and notes"):
        yt_url = st.text_input("YouTube URL", key="tutor_yt")
        article_url = st.text_input("Article / documentation URL", key="tutor_url")
        raw_notes = st.text_area("Raw text notes", key="tutor_notes", height=120)
        uploads = st.file_uploader(
            "Upload PDF / text documents",
            type=["pdf", "txt", "md"],
            accept_multiple_files=True,
            key="tutor_files",
        )
        st.caption("Leave empty to auto-trigger live DuckDuckGo research scraping + YouTube metadata lookup.")

    col1, col2 = st.columns(2)
    with col1:
        difficulty = st.selectbox("Test difficulty", DIFFICULTIES, index=1, key="quiz_difficulty")
    with col2:
        question_count = st.slider("Question count", 3, 10, 5, key="quiz_count")

    action_col1, action_col2 = st.columns(2)
    gen_guide = action_col1.button(
        "Generate master study guide",
        type="primary",
        icon=":material/menu_book:",
        width="stretch",
        disabled=not topic.strip(),
    )
    gen_quiz = action_col2.button(
        "Generate adaptive test",
        icon=":material/quiz:",
        width="stretch",
        disabled=not topic.strip(),
    )

    if gen_guide:
        with st.status("Multi-pass analysis running...", expanded=True) as status:
            sources = {"videos": [], "readings": [], "notes": [], "context": [], "warnings": []}
            st.write("Pass 1/3 - ingesting resources")
            custom_supplied = False
            if yt_url.strip():
                meta, err = youtube_metadata(yt_url.strip())
                if err:
                    sources["warnings"].append(f"YouTube lookup failed: {err}")
                    sources["videos"].append({"title": yt_url, "url": yt_url, "summary": "metadata unavailable"})
                else:
                    sources["videos"].append(
                        {
                            "title": f"{meta['title']} ({meta['author']})",
                            "url": meta["url"],
                            "summary": meta["description"][:400],
                        }
                    )
                    sources["context"].append(f"YouTube: {meta['title']}\n{meta['description'][:2000]}")
                custom_supplied = True
            if article_url.strip():
                article, err = fetch_article(article_url.strip())
                if err:
                    sources["warnings"].append(f"Article fetch failed: {err}")
                else:
                    sources["readings"].append(
                        {"title": article["title"], "url": article["url"], "summary": article["text"][:300]}
                    )
                    sources["context"].append(f"Article: {article['title']}\n{article['text']}")
                custom_supplied = True
            for upload in uploads or []:
                data = upload.read()
                if upload.name.lower().endswith(".pdf"):
                    text = extract_pdf_text(data)
                else:
                    text = data.decode("utf-8", errors="replace")
                sources["notes"].append({"name": upload.name, "chars": len(text)})
                sources["context"].append(f"Upload {upload.name}:\n{text[:4000]}")
                custom_supplied = True
            if raw_notes.strip():
                sources["context"].append(f"Personal notes:\n{raw_notes[:4000]}")
                custom_supplied = True

            if not custom_supplied:
                st.write("Pass 1/3 - no custom resources; running live web research")
                results, err = ddg_search(topic, max_results=8)
                if err:
                    sources["warnings"].append(f"Web search failed: {err}")
                else:
                    for result in results:
                        entry = {
                            "title": result.get("title", ""),
                            "url": result.get("url", ""),
                            "summary": result.get("snippet", ""),
                        }
                        if "youtube.com" in entry["url"] or "youtu.be" in entry["url"]:
                            sources["videos"].append(entry)
                        else:
                            sources["readings"].append(entry)
                        sources["context"].append(
                            f"Search result: {entry['title']} ({entry['url']})\n{entry['summary']}"
                        )
                sentiment, err = ddg_search(f"{topic} discussion opinions review", max_results=5)
                if err:
                    sources["warnings"].append(f"Sentiment search failed: {err}")
                else:
                    for result in sentiment:
                        sources["context"].append(
                            f"Community signal: {result.get('title','')}\n{result.get('snippet','')}"
                        )

            st.write("Pass 2/3 - synthesizing master study guide")
            link_lines = []
            for kind, items in (("Video", sources["videos"]), ("Reading", sources["readings"])):
                for item in items[:10]:
                    link_lines.append(f"- [{kind}] {item['title']} - {item['url']}")
            context_blob = "\n\n".join(sources["context"])[:12000]
            system = (
                "You are an elite academic tutor building a rigorous, exam-ready study guide. "
                "Be technically precise, cite the provided links, and use clear markdown structure."
            )
            user = (
                f"Topic: {topic}\n\n"
                f"Available resources:\n{chr(10).join(link_lines) or '- none'}\n\n"
                f"Research context:\n{context_blob}\n\n"
                "Produce a Master Study Guide with EXACTLY these sections:\n"
                "## Core Conceptual Breakdown\n"
                "## Key Formulae, Equations & System Diagrams (use ASCII diagrams)\n"
                "## Curated Video & Reading List (reference the provided URLs as markdown links)\n"
                "## Community Sentiment & Key Q&A Insights\n"
                "Ground every claim in the context. Be thorough."
            )
            guide, err = ollama_chat(
                system, user, st.session_state.tutor_model, st.session_state.ollama_url, temperature=0.3
            )
            if err:
                status.update(label="Engine unavailable", state="error")
                st.error(f"Tutor engine unavailable: {err}. Verify Ollama and the selected model.")
                return
            st.write("Pass 3/3 - finalizing sources")
            st.session_state.tutor_guide = guide
            st.session_state.tutor_sources = sources
            status.update(label="Study guide ready", state="complete")

    if st.session_state.tutor_guide:
        with st.container(border=True):
            st.markdown(st.session_state.tutor_guide)
        sources = st.session_state.tutor_sources or {"videos": [], "readings": [], "warnings": []}
        for warning in sources.get("warnings", []):
            st.warning(warning)
        rows = [
            {"Type": "Video", **item} for item in sources.get("videos", [])
        ] + [{"Type": "Reading", **item} for item in sources.get("readings", [])]
        if rows:
            st.markdown("#### Verified source index")
            st.dataframe(
                pd.DataFrame(rows),
                hide_index=True,
                width="stretch",
                column_config={
                    "url": st.column_config.LinkColumn("Link", display_text="open"),
                    "summary": st.column_config.TextColumn("Summary", width="large"),
                },
            )

    if gen_quiz:
        context = (st.session_state.tutor_guide or "")[:4000]
        with st.spinner(f"Generating {question_count} {difficulty} questions..."):
            system = (
                "You are an expert exam writer. Output STRICT JSON only - a single array, no prose, "
                "no markdown fences. Each element is an object."
            )
            user = (
                f"Topic: {topic}\nDifficulty: {difficulty}\n"
                f"Generate {question_count} questions mixing multiple-choice and short-answer.\n"
                f"Context (may be empty):\n{context}\n\n"
                "MCQ object schema: {\"type\":\"mcq\",\"question\":str,\"options\":[4 strings],"
                "\"answer_index\":int,\"explanation\":str}\n"
                "Short-answer object schema: {\"type\":\"short\",\"question\":str,\"rubric\":str,"
                "\"model_answer\":str}\n"
                "Return only the JSON array."
            )
            raw, err = ollama_chat(
                system, user, st.session_state.tutor_model, st.session_state.ollama_url, temperature=0.5
            )
        if err:
            st.error(f"Test generation failed: {err}")
        else:
            parsed = parse_json_array(raw)
            quiz = normalize_quiz(parsed) if parsed else []
            if not quiz:
                st.error("The model did not return valid JSON. Try again or switch the tutor model.")
                with st.expander("Raw model output"):
                    st.code(raw)
            else:
                st.session_state.quiz = quiz
                st.session_state.quiz_gen += 1
                st.session_state.quiz_results = None

    if st.session_state.quiz:
        render_quiz()


def render_quiz():
    quiz = st.session_state.quiz
    gen = st.session_state.quiz_gen
    st.markdown("### Adaptive test")
    with st.form(key=f"quiz_form_{gen}"):
        for index, question in enumerate(quiz):
            if question["type"] == "mcq":
                st.markdown(f"**Q{index + 1}.** {question['question']}")
                st.radio(
                    f"q{index}",
                    options=list(range(len(question["options"]))),
                    format_func=lambda i, q=question: f"{'ABCDEF'[i]}. {q['options'][i]}",
                    key=f"gen{gen}_mcq_{index}",
                    label_visibility="collapsed",
                )
            else:
                st.markdown(f"**Q{index + 1} (short answer).** {question['question']}")
                if question.get("rubric"):
                    st.caption(f"Rubric: {question['rubric']}")
                st.text_area(
                    f"q{index}",
                    key=f"gen{gen}_sa_{index}",
                    label_visibility="collapsed",
                    height=90,
                )
            st.markdown("<hr style='border-color:#2B2D32'>", unsafe_allow_html=True)
        submitted = st.form_submit_button("Submit answers", type="primary", icon=":material/check:")

    if submitted:
        results = []
        for index, question in enumerate(quiz):
            if question["type"] == "mcq":
                chosen = st.session_state.get(f"gen{gen}_mcq_{index}")
                correct = chosen == question["answer_index"]
                results.append(
                    {
                        "index": index,
                        "type": "mcq",
                        "score": 1.0 if correct else 0.0,
                        "selected": question["options"][chosen] if chosen is not None else "(none)",
                        "expected": question["options"][question["answer_index"]],
                        "feedback": question.get("explanation", ""),
                    }
                )
        short_items = [
            (i, q, st.session_state.get(f"gen{gen}_sa_{i}", ""))
            for i, q in enumerate(quiz)
            if q["type"] == "short"
        ]
        if short_items:
            system = "You are a strict exam grader. Output STRICT JSON only: an array of objects."
            user = (
                "Grade each short answer against its rubric on a 0-1 scale.\n"
                + "\n".join(
                    f"id={i}\nquestion={q['question']}\nrubric={q.get('rubric','')}\n"
                    f"model_answer={q.get('model_answer','')}\nstudent_answer={ans}"
                    for i, q, ans in short_items
                )
                + "\nReturn [{\"id\":int,\"score\":float,\"feedback\":str}]."
            )
            raw, err = ollama_chat(
                system, user, st.session_state.tutor_model, st.session_state.ollama_url, temperature=0.1
            )
            graded = parse_json_array(raw) if not err else None
            graded_map = {int(g["id"]): g for g in graded or [] if isinstance(g, dict) and "id" in g}
            for i, q, ans in short_items:
                if i in graded_map:
                    score = max(0.0, min(1.0, float(graded_map[i].get("score", 0))))
                    feedback = str(graded_map[i].get("feedback", ""))
                else:
                    score, feedback = keyword_grade(ans, q.get("rubric", ""))
                    if err:
                        feedback += " [LLM grader offline - keyword rubric fallback]"
                results.append(
                    {
                        "index": i,
                        "type": "short",
                        "score": score,
                        "selected": ans or "(blank)",
                        "expected": q.get("model_answer", ""),
                        "feedback": feedback,
                    }
                )
        results.sort(key=lambda item: item["index"])
        earned = sum(item["score"] for item in results)
        possible = float(len(results))
        st.session_state.quiz_results = results
        st.session_state.mastery_earned += earned
        st.session_state.mastery_possible += possible

    if st.session_state.quiz_results:
        results = st.session_state.quiz_results
        earned = sum(item["score"] for item in results)
        possible = len(results)
        pct = (earned / possible * 100) if possible else 0.0
        mastery = (
            st.session_state.mastery_earned / st.session_state.mastery_possible * 100
            if st.session_state.mastery_possible
            else 0.0
        )
        metric_col1, metric_col2 = st.columns([1, 1])
        with metric_col1:
            st.plotly_chart(score_ring(pct, "Latest test score"), width="stretch", key="score_ring")
        with metric_col2:
            st.plotly_chart(score_ring(mastery, "Session mastery"), width="stretch", key="mastery_ring")
            st.metric("Points earned", f"{earned:.1f} / {possible:.0f}")
        st.markdown("#### Answer review")
        for item in results:
            good = item["score"] >= 1.0 if item["type"] == "mcq" else item["score"] >= 0.6
            with st.expander(f"{'PASS' if good else 'REVIEW'} - Q{item['index'] + 1} ({item['type']}, {item['score']:.2f})"):
                st.markdown(f"**Your answer:** {item['selected']}")
                if item["type"] == "mcq":
                    st.markdown(f"**Correct:** {item['expected']}")
                elif item["expected"]:
                    st.markdown(f"**Model answer:** {item['expected']}")
                if item["feedback"]:
                    st.info(item["feedback"])


def toggle_task(task_id):
    for task in st.session_state.tasks:
        if task["id"] == task_id:
            task["done"] = not task["done"]


def delete_task(task_id):
    st.session_state.tasks = [t for t in st.session_state.tasks if t["id"] != task_id]


def add_task(title, priority):
    st.session_state.task_seq += 1
    st.session_state.tasks.append(
        {"id": st.session_state.task_seq, "title": title, "priority": priority, "done": False}
    )


@st.fragment(run_every=1)
def pomodoro_widget():
    phase = st.session_state.pomo_phase
    duration = (st.session_state.pomo_work if phase == "Work" else st.session_state.pomo_break) * 60
    running = st.session_state.pomo_running
    if running and st.session_state.pomo_started is not None:
        elapsed = st.session_state.pomo_prior + (time.time() - st.session_state.pomo_started)
    else:
        elapsed = st.session_state.pomo_prior
        running = False
    if running and duration and elapsed >= duration:
        if phase == "Work":
            st.session_state.pomo_done += 1
            st.session_state.pomo_phase = "Break"
        else:
            st.session_state.pomo_phase = "Work"
        st.session_state.pomo_prior = 0.0
        st.session_state.pomo_started = time.time()
        st.toast(f"{st.session_state.pomo_phase} session started")
        phase = st.session_state.pomo_phase
        duration = (st.session_state.pomo_work if phase == "Work" else st.session_state.pomo_break) * 60
        elapsed = 0.0
    remaining = max(duration - elapsed, 0)
    minutes, seconds = divmod(int(remaining), 60)
    st.markdown(f'<div class="pomo-time">{minutes:02d}:{seconds:02d}</div>', unsafe_allow_html=True)
    st.progress(min(elapsed / duration, 1.0) if duration else 0.0)
    st.caption(f"{phase} session | {st.session_state.pomo_done} pomodoros completed")
    col1, col2, col3 = st.columns(3)
    if col1.button("Start", icon=":material/play_arrow:", width="stretch", disabled=st.session_state.pomo_running):
        st.session_state.pomo_running = True
        st.session_state.pomo_started = time.time()
    if col2.button("Pause", icon=":material/pause:", width="stretch", disabled=not st.session_state.pomo_running):
        if st.session_state.pomo_started is not None:
            st.session_state.pomo_prior += time.time() - st.session_state.pomo_started
        st.session_state.pomo_running = False
        st.session_state.pomo_started = None
    if col3.button("Reset", icon=":material/restart_alt:", width="stretch"):
        st.session_state.pomo_running = False
        st.session_state.pomo_started = None
        st.session_state.pomo_prior = 0.0
        st.session_state.pomo_phase = "Work"


def render_productivity():
    st.markdown("## Minimalist productivity hub")
    st.caption("Task manager, focus pomodoro, and session scratchpad with markdown export.")

    task_col, ring_col = st.columns([1.6, 1])
    with task_col:
        st.markdown("#### Quick task creator")
        with st.form("task_form", clear_on_submit=True):
            title = st.text_input("Task", placeholder="Draft RTL for the crossbar controller")
            priority = st.selectbox("Priority", PRIORITIES, index=2)
            submitted = st.form_submit_button("Add task", icon=":material/add:", type="primary")
        if submitted:
            if title.strip():
                add_task(title.strip(), priority)
            else:
                st.warning("Task title cannot be empty.")

        filter_choice = st.pills(
            "Filter", ["All", "Pending", "Completed"], key="task_filter"
        )
        tasks = st.session_state.tasks
        filtered = [
            task
            for task in tasks
            if filter_choice == "All"
            or (filter_choice == "Pending" and not task["done"])
            or (filter_choice == "Completed" and task["done"])
        ]
        if not filtered:
            st.info("No tasks in this view.")
        for task in filtered:
            with st.container(border=True):
                row = st.columns([0.5, 5, 3, 0.7])
                with row[0]:
                    st.checkbox(
                        "done",
                        value=task["done"],
                        key=f"task_chk_{task['id']}",
                        on_change=toggle_task,
                        args=(task["id"],),
                        label_visibility="collapsed",
                    )
                with row[1]:
                    css_class = "task-done" if task["done"] else ""
                    st.markdown(
                        f'<span class="{css_class}" style="font-size:15px">{html_lib.escape(task["title"])}</span>',
                        unsafe_allow_html=True,
                    )
                with row[2]:
                    st.markdown(
                        f'<span class="md3-pill pill-{task["priority"]}">{task["priority"]}</span>',
                        unsafe_allow_html=True,
                    )
                with row[3]:
                    st.button(
                        "Delete",
                        key=f"task_del_{task['id']}",
                        icon=":material/delete:",
                        help="Delete task",
                        on_click=delete_task,
                        args=(task["id"],),
                    )
    with ring_col:
        st.markdown("#### Progress")
        done = sum(1 for task in st.session_state.tasks if task["done"])
        total = len(st.session_state.tasks)
        pct = (done / total * 100) if total else 0.0
        st.plotly_chart(score_ring(pct, f"{done} of {total} complete"), width="stretch", key="task_ring")

    st.divider()
    focus_col, notes_col = st.columns([1, 1])
    with focus_col:
        st.markdown("#### Focus pomodoro")
        config_col1, config_col2 = st.columns(2)
        with config_col1:
            st.number_input("Work minutes", min_value=1, max_value=90, step=1, key="pomo_work")
        with config_col2:
            st.number_input("Break minutes", min_value=1, max_value=30, step=1, key="pomo_break")
        with st.container(border=True):
            pomodoro_widget()
    with notes_col:
        st.markdown("#### Session notes")
        st.text_area(
            "Scratchpad (auto-saved to session state)",
            key="notes",
            height=280,
            placeholder="Capture decisions, formulas, and follow-ups...",
        )
        export = f"# Material Suite - session notes\n\n{st.session_state.notes}\n"
        st.download_button(
            "Export markdown",
            data=export.encode("utf-8"),
            file_name="material_suite_notes.md",
            mime="text/markdown",
            icon=":material/download:",
            width="stretch",
        )
        st.caption(f"{len(st.session_state.notes)} characters | auto-persisted in st.session_state")


st.markdown(
    '<div style="margin-bottom:8px"><span class="md3-pill pill-LOW">MATERIAL YOU</span> '
    '<span class="md3-pill pill-MEDIUM">MD3 DARK</span> '
    '<span class="md3-pill pill-CRITICAL">LOCAL-FIRST</span></div>',
    unsafe_allow_html=True,
)

module = st.session_state.module
if module == "coding":
    render_coding_agent()
elif module == "tutor":
    render_tutor()
elif module == "focus":
    render_productivity()