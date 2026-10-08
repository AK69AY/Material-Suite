import html as html_lib
import json
import os
import re
import shlex
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
SCAN_EXTENSIONS = {".py", ".v", ".sv", ".c", ".h", ".cpp", ".md", ".json", ".txt", ".toml", ".yaml", ".yml", ".cfg", ".sh"}
SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".pytest_cache", ".streamlit"}
DIFFICULTIES = ["Beginner", "Intermediate", "Advanced", "Exam-Level"]
PRIORITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]

AGENT_MODES = {
    "Code Explainer": (
        "You are a principal software engineer. Explain the supplied code precisely: "
        "purpose, step-by-step algorithm, syntax notes, data-path and control flow, "
        "complexity, and edge cases. Use markdown headings, numbered steps, and a short "
        "ASCII signal/data-flow diagram. Never truncate the analysis."
    ),
    "Bug Fixer & Refactorer": (
        "You are a senior static-analysis and refactoring engine. Identify concrete bugs, "
        "race conditions, off-by-one errors, unsafe constructs, and performance issues "
        "with line references. Then output a complete, optimized, production-ready rewrite "
        "in a single fenced code block. Never use placeholders such as 'rest of code here'."
    ),
    "Test Generator": (
        "You are a verification engineer. Generate a complete self-checking test suite for "
        "the supplied code. For Python use pytest-style assertions and edge cases; for "
        "Verilog use Icarus-compatible $display PASS/FAIL; for C use assert.h. Output the "
        "full test file in one fenced code block plus exact run commands. Never truncate."
    ),
    "Architecture Designer": (
        "You are a systems architect. Produce a structured design review: module breakdown "
        "table, interfaces, an ASCII block diagram, a Mermaid.js diagram inside a "
        "```mermaid fenced block, and trade-off analysis. Keep Mermaid syntax valid."
    ),
    "File Patcher": (
        "You are a code patching engine. Given the current file content, produce the "
        "COMPLETE updated file with the requested changes applied. Output ONLY the full "
        "file content inside a single fenced code block with the correct language tag. "
        "Do not include explanations outside the code block. Never use placeholders."
    ),
}


# --- INITIALIZE SESSION STATE SAFELY AT THE TOP OF MAIN ---
# Priority: Streamlit Secrets -> user sidebar override -> local default.
if "ollama_url" not in st.session_state:
    try:
        _secret_url = str(st.secrets.get("OLLAMA_URL") or "").strip()
    except Exception:
        _secret_url = ""
    st.session_state.ollama_url = _secret_url or OLLAMA_DEFAULT

if "selected_heavy_model" not in st.session_state:
    st.session_state.selected_heavy_model = "deepseek-r1:8b"

if "selected_coder_model" not in st.session_state:
    st.session_state.selected_coder_model = "qwen2.5-coder:7b"

if "selected_fast_model" not in st.session_state:
    st.session_state.selected_fast_model = "phi4-mini:latest"

for key, value in {
    "module": "coding",
    "ollama_url": OLLAMA_DEFAULT,
    "ollama_models": [],
    "ollama_status": None,
    "models_discovered": False,
    "model_heavy_sel": "(auto)",
    "model_coder_sel": "(auto)",
    "model_fast_sel": "(auto)",
    "ws_dir": str(APP_DIR),
    "ws_files": [],
    "ws_selected_file": None,
    "ws_file_content": "",
    "ws_edit_mode": False,
    "ws_editor_content": "",
    "agent_mode": "Code Explainer",
    "agent_response": None,
    "agent_response_mode": None,
    "agent_generated_code": "",
    "agent_custom_instructions": "",
    "exec_output": None,
    "exec_rc": None,
    "exec_engine": None,
    "sandbox_history": [],
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
    page_title="Material Suite",
    page_icon=":material/apps:",
    layout="wide",
    initial_sidebar_state="expanded",
)

MD3_CSS = """
<style>
  @import url('https://fonts.googleapis.com/css2?family=Google+Sans:wght@400;500;600;700&family=Inter:wght@400;500;600&display=swap');

  html, body, .stApp, [class*="css"] {
    font-family: 'Google Sans', 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  }
  .stApp { background: #111216; }
  h1, h2, h3, h4 { color: #E2E2E6; font-weight: 600; letter-spacing: .2px; }
  h1 { font-size: 2rem; }
  h2 { font-size: 1.5rem; }

  section[data-testid="stSidebar"] { background: #1A1C20 !important; border-right: 1px solid #44474E; }
  section[data-testid="stSidebar"] > div { background: #1A1C20 !important; }
  section[data-testid="stSidebar"] .block-container { padding-top: 1rem; }

  .md3-brand { padding: 4px 4px 12px 4px; }
  .md3-brand-title { color: #D0BCFF; font-size: 24px; font-weight: 700; letter-spacing: .3px; }
  .md3-brand-sub { color: #C4C6D0; font-size: 12px; margin-top: 2px; }

  div[data-testid="stButton"] > button {
    border-radius: 24px;
    border: 1px solid #44474E;
    background: #22252A;
    color: #E2E2E6;
    font-weight: 500;
    transition: transform .16s ease, box-shadow .18s ease, background .18s ease;
    box-shadow: 0px 4px 16px rgba(0,0,0,0.4);
  }
  div[data-testid="stButton"] > button:hover {
    transform: translateY(-2px);
    border-color: #D0BCFF;
    box-shadow: 0px 4px 16px rgba(0,0,0,0.4), 0 0 12px rgba(208,188,255,0.25);
  }
  div[data-testid="stButton"] > button[kind="primary"],
  div[data-testid="stButton"] > button[data-testid="stBaseButton-primary"] {
    background: #4F378B !important;
    color: #EADDFF !important;
    border: 1px solid #D0BCFF !important;
  }
  div[data-testid="stFormSubmitButton"] > button {
    border-radius: 24px;
    background: #4F378B; color: #EADDFF; border: 1px solid #D0BCFF;
    box-shadow: 0px 4px 16px rgba(0,0,0,0.4);
  }

  div[data-testid="stPills"] button, div[data-testid="stSegmentedControl"] button {
    border-radius: 24px !important;
    border: 1px solid #44474E !important;
    background: #1A1C20 !important;
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
    background: #22252A !important;
    color: #E2E2E6 !important;
    border: 1px solid #44474E !important;
  }
  div[data-testid="stTextInput"] input:focus,
  div[data-testid="stTextArea"] textarea:focus { border-color: #D0BCFF !important; }
  div[data-baseweb="input"], div[data-baseweb="textarea"] {
    border-radius: 16px !important; border-color: #44474E !important; background: #22252A !important;
  }
  div[data-baseweb="select"] > div {
    border-radius: 16px !important; background: #22252A !important; border-color: #44474E !important;
  }
  div[data-testid="stFileUploader"] section {
    border-radius: 16px; border: 1px dashed #44474E; background: #1A1C20;
  }

  div[data-testid="stVerticalBlockBorderWrapper"] {
    background: #22252A !important;
    border: 1px solid #44474E !important;
    border-radius: 24px !important;
    box-shadow: 0px 4px 16px rgba(0,0,0,0.4);
  }
  details[data-testid="stExpander"] {
    background: #22252A; border: 1px solid #44474E; border-radius: 24px; overflow: hidden;
    box-shadow: 0px 4px 16px rgba(0,0,0,0.4);
  }
  details[data-testid="stExpander"] summary { border-radius: 24px; }
  div[data-testid="stMetric"] {
    background: #22252A; border: 1px solid #44474E; border-radius: 24px;
    padding: 12px 16px; box-shadow: 0px 4px 16px rgba(0,0,0,0.4);
  }
  div[data-testid="stMetricValue"] { color: #D0BCFF; }

  div[data-testid="stCodeBlock"], div[data-testid="stCode"] {
    background: #0D0E11 !important; border: 1px solid #44474E; border-radius: 16px;
  }
  .ms-term {
    background: #0D0E11; border: 1px solid #44474E; border-radius: 16px;
    padding: 14px 16px; margin-top: 6px;
    font-family: 'JetBrains Mono', 'Cascadia Mono', Consolas, monospace;
    font-size: 13px; color: #8BE9A8; white-space: pre-wrap; word-break: break-word;
    max-height: 480px; overflow-y: auto;
    box-shadow: 0px 4px 16px rgba(0,0,0,0.4);
  }
  .ms-term-head { color: #A8C7FA; display: block; margin-bottom: 8px; font-weight: 600; }

  .md3-pill {
    display: inline-block; padding: 3px 14px; border-radius: 24px; font-size: 12px;
    font-weight: 600; letter-spacing: .3px; border: 1px solid transparent; margin-right: 4px;
  }
  .pill-CRITICAL { color: #F2B8B5; background: rgba(242,184,181,.14); border-color: #F2B8B5; }
  .pill-HIGH     { color: #FFB4AB; background: rgba(255,180,171,.14); border-color: #FFB4AB; }
  .pill-MEDIUM   { color: #EADDFF; background: rgba(234,221,255,.12); border-color: #D0BCFF; }
  .pill-LOW      { color: #A8C7FA; background: rgba(168,199,250,.12); border-color: #A8C7FA; }
  .pill-OK       { color: #8BE9A8; background: rgba(139,233,168,.12); border-color: #8BE9A8; }
  .pill-OFF      { color: #F2B8B5; background: rgba(242,184,181,.14); border-color: #F2B8B5; }

  .ms-offline-banner {
    background: rgba(242,184,181,.1); border: 1px solid #F2B8B5; border-radius: 16px;
    padding: 12px 16px; color: #F2B8B5; font-size: 14px; margin-bottom: 8px;
  }
  .ms-offline-banner code {
    background: rgba(242,184,181,.15); padding: 2px 8px; border-radius: 8px;
    font-family: 'JetBrains Mono', Consolas, monospace;
  }

  .task-done { text-decoration: line-through; color: #7A7C85; }
  .pomo-time {
    font-size: 56px; font-weight: 700; color: #D0BCFF; text-align: center;
    font-family: 'Google Sans', 'Inter', sans-serif; letter-spacing: 2px; margin: 4px 0 8px 0;
  }
  div[data-testid="stProgress"] > div > div > div > div { background: #D0BCFF; }
  div[data-testid="stProgress"] > div > div { background: #22252A; border-radius: 24px; }

  [data-testid="stCaptionContainer"] { color: #C4C6D0; }
  a { color: #A8C7FA !important; }

  div[data-testid="stTabs"] button[aria-selected="true"] {
    border-bottom: 2px solid #D0BCFF; color: #D0BCFF;
  }

  .ms-file-item {
    padding: 6px 12px; border-radius: 12px; cursor: pointer;
    font-family: 'JetBrains Mono', Consolas, monospace; font-size: 13px;
    color: #C4C6D0; transition: background .12s;
  }
  .ms-file-item:hover { background: #22252A; color: #E2E2E6; }
</style>
"""


st.markdown(MD3_CSS, unsafe_allow_html=True)


def net_call(fn, *args, timeout=25, service=None, **kwargs):
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(fn, *args, **kwargs)
    try:
        return future.result(timeout=timeout), None
    except FutureTimeout:
        return None, "network timeout exhausted"
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, OSError):
        if service == "ollama":
            url = st.session_state.get("ollama_url", OLLAMA_DEFAULT)
            return None, (
                f"⚠️ Could not connect to Ollama at {url}. If running on Streamlit Cloud, "
                "ensure your ngrok/tunnel is active and paste the public tunnel URL above. "
                "Run: ngrok http 11434 locally."
            )
        return None, "connection failed or timed out (check network / tunnel availability)"
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"
    finally:
        executor.shutdown(wait=False)


def discover_models(url):
    def _call():
        r = requests.get(url.rstrip("/") + "/api/tags", timeout=(3, 6))
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]
    models, err = net_call(_call, timeout=12, service="ollama")
    return models or [], err


def classify_models(models):
    buckets = {"heavy": [], "coder": [], "fast": []}
    for m in models:
        ml = m.lower()
        if any(k in ml for k in ("deepseek-r1", "-r1:", "r1:8", "r1:14", "r1:32", "reasoning", "o1", "qwen3:32", "qwen3:14", "qwq")):
            buckets["heavy"].append(m)
        elif any(k in ml for k in ("coder", "codellama", "deepseek-coder", "starcoder", "codegemma", "qwen2.5-coder")):
            buckets["coder"].append(m)
        else:
            buckets["fast"].append(m)
    if not buckets["heavy"]:
        buckets["heavy"] = list(models[:1])
    if not buckets["coder"]:
        buckets["coder"] = list(models[:1])
    if not buckets["fast"]:
        buckets["fast"] = list(models[:1])
    return buckets


def get_model_for_task(task):
    models = st.session_state.ollama_models
    if not models:
        return None
    sel_key = f"model_{task}_sel"
    override = st.session_state.get(sel_key, "(auto)")
    if override and override != "(auto)" and override in models:
        return override
    buckets = classify_models(models)
    bucket = buckets.get(task, [])
    return bucket[0] if bucket else models[0]


def ollama_chat(system, user, model, url, temperature=0.4, timeout=240):
    if not model:
        return None, "no model available - Ollama offline or no models installed"
    def _call():
        r = requests.post(
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
        r.raise_for_status()
        return r.json().get("message", {}).get("content", "")
    return net_call(_call, timeout=timeout + 12, service="ollama")


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
        r = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            timeout=(6, 12),
        )
        r.raise_for_status()
        parser = DDGParser()
        parser.feed(r.text)
        return parser.results[:max_results]
    return net_call(_call, timeout=20)


def youtube_video_id(url):
    match = re.search(r"(?:v=|youtu\.be/|/embed/)([\w-]{11})", url or "")
    return match.group(1) if match else None


def youtube_metadata(url):
    vid = youtube_video_id(url)
    if not vid:
        return None, "could not parse a YouTube video id"
    canonical = f"https://www.youtube.com/watch?v={vid}"
    def _call():
        meta = {"video_id": vid, "url": canonical, "title": f"YouTube video {vid}", "author": "", "description": ""}
        try:
            oe = requests.get("https://www.youtube.com/oembed", params={"url": canonical, "format": "json"}, timeout=(6, 10))
            if oe.status_code == 200:
                p = oe.json()
                meta["title"] = p.get("title", meta["title"])
                meta["author"] = p.get("author_name", "")
        except requests.RequestException:
            pass
        try:
            page = requests.get(canonical, headers={"User-Agent": "Mozilla/5.0"}, timeout=(6, 12))
            m = re.search(r'"shortDescription":"((?:[^"\\]|\\.)*)"', page.text)
            if m:
                meta["description"] = json.loads('"' + m.group(1) + '"')
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
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}, timeout=(6, 14))
        r.raise_for_status()
        tm = re.search(r"(?is)<title[^>]*>(.*?)</title>", r.text)
        title = html_lib.unescape(tm.group(1).strip()) if tm else url
        return {"url": url, "title": title, "text": html_to_text(r.text)[:limit]}
    return net_call(_call, timeout=25)


def extract_pdf_text(data, limit=8000):
    try:
        import io
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        pages = [p.extract_text() or "" for p in reader.pages[:40]]
        return "\n".join(pages).strip()[:limit]
    except Exception as exc:
        return f"[pdf extraction failed: {type(exc).__name__}]"


def detect_language(text, filename=None):
    if filename:
        mapping = {".py": "Python", ".v": "Verilog", ".sv": "Verilog", ".c": "C", ".h": "C",
                    ".cpp": "C++", ".md": "Markdown", ".json": "JSON", ".toml": "TOML",
                    ".yaml": "YAML", ".yml": "YAML", ".sh": "Shell", ".txt": "Plain text"}
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
    try:
        json.loads(stripped)
        return "JSON"
    except (json.JSONDecodeError, ValueError):
        pass
    if re.search(r"^#{1,6}\s+\w", stripped, re.M):
        return "Markdown"
    return "Plain text"


def list_workspace_files(directory):
    root = Path(directory)
    if not root.is_dir():
        return []
    found = []
    for r, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for name in sorted(files):
            if Path(name).suffix.lower() in SCAN_EXTENSIONS:
                found.append(str((Path(r) / name).relative_to(root)))
    return sorted(found)


def read_workspace_file(directory, rel_path):
    path = Path(directory) / rel_path
    try:
        return path.read_text(encoding="utf-8", errors="replace"), None
    except OSError as exc:
        return None, str(exc)


def write_workspace_file(directory, rel_path, content):
    path = Path(directory) / rel_path
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return True, None
    except OSError as exc:
        return False, str(exc)


def extract_code_blocks(text):
    return re.findall(r"```(?:\w+)?\n(.*?)```", text, re.S)


def extract_primary_code(text, language=None):
    if language:
        lang_blocks = re.findall(rf"```{re.escape(language)}\n(.*?)```", text, re.S)
        if lang_blocks:
            return max(lang_blocks, key=len)
    blocks = extract_code_blocks(text)
    return max(blocks, key=len) if blocks else ""


def parse_json_array(text):
    cleaned = re.sub(r"```(?:json)?", "", text).strip().strip("`").strip()
    try:
        data = json.loads(cleaned)
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
    for item in raw or []:
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
            quiz.append({"type": "mcq", "question": question, "options": options,
                         "answer_index": answer, "explanation": str(item.get("explanation", "")).strip()})
        else:
            quiz.append({"type": "short", "question": question,
                         "rubric": str(item.get("rubric", "")).strip(),
                         "model_answer": str(item.get("model_answer", "")).strip()})
    return quiz


def keyword_grade(answer, rubric):
    points = [p.strip() for p in re.split(r"[;.\n]", rubric) if len(p.strip()) > 4]
    if not points:
        return (1.0 if answer.strip() else 0.0), "No rubric - presence scored."
    hits = sum(1 for p in points if any(w.lower() in answer.lower() for w in re.findall(r"\w{4,}", p)))
    return hits / len(points), f"Matched {hits}/{len(points)} rubric points."


def run_sandbox_command(cmd, cwd, timeout=30):
    flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    try:
        proc = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=cwd, creationflags=flags,
        )
        return (proc.stdout or "") + (proc.stderr or ""), proc.returncode
    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout}s", 124
    except Exception as exc:
        return f"Error: {type(exc).__name__}: {exc}", 1


def execute_code(code, language):
    if language == "Python":
        return _run_python(code)
    if language == "C":
        return _run_c(code)
    return _static_analysis(code, language)


def _run_python(code):
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "scratch_main.py"
        script.write_text(code, encoding="utf-8")
        flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        try:
            proc = subprocess.run([sys.executable, str(script)], capture_output=True,
                                  text=True, timeout=15, cwd=tmp, creationflags=flags)
        except subprocess.TimeoutExpired:
            return "Execution aborted: exceeded 15s wall-clock limit.", 124, "python (live)"
        output = (proc.stdout or "") + (proc.stderr or "")
        return output or "[no output]", proc.returncode, "python (live)"


def _run_c(code):
    compiler = shutil.which("gcc") or shutil.which("clang")
    if not compiler:
        return _static_analysis(code, "C") + ("\n[no C compiler found]", None, "static analysis")
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "scratch_main.c"
        source.write_text(code, encoding="utf-8")
        exe = Path(tmp) / ("scratch_main.exe" if os.name == "nt" else "scratch_main.out")
        flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        try:
            cp = subprocess.run([compiler, str(source), "-o", str(exe)], capture_output=True,
                                text=True, timeout=30, cwd=tmp, creationflags=flags)
            if cp.returncode != 0:
                return "compile failed:\n" + (cp.stdout or "") + (cp.stderr or ""), cp.returncode, "gcc (live)"
            rp = subprocess.run([str(exe)], capture_output=True, text=True, timeout=15, cwd=tmp, creationflags=flags)
            return (rp.stdout or "") + (rp.stderr or ""), rp.returncode, "gcc (live)"
        except subprocess.TimeoutExpired:
            return "C execution exceeded time limit.", 124, "gcc (live)"


def _static_analysis(code, language):
    lines = code.splitlines()
    depth = max((len(l) - len(l.lstrip())) for l in lines) if lines else 0
    branches = len(re.findall(r"\b(if|for|while|case|switch|elif)\b", code))
    functions = len(re.findall(r"\b(def|function|task|void\s+\w+\s*\()", code))
    return (
        "[static analysis - no local toolchain for this target]\n"
        f"language       : {language}\n"
        f"lines          : {len(lines)}\n"
        f"characters     : {len(code)}\n"
        f"branches       : {branches}\n"
        f"functions      : {functions}\n"
        f"max indent     : {depth}\n"
        f"est. complexity: {branches + functions + 1}"
    ), None, "static analysis"


def render_terminal(text, rc=None, engine=None):
    head = "terminal"
    if engine:
        head += f" | {engine}"
    if rc is not None:
        head += f" | exit {rc}"
    st.markdown(
        f'<div class="ms-term"><span class="ms-term-head">{html_lib.escape(head)}</span>'
        f"{html_lib.escape(text)}</div>",
        unsafe_allow_html=True,
    )


def score_ring(value, label, suffix="%"):
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=value,
        number={"suffix": suffix, "font": {"color": "#E2E2E6"}},
        gauge={"axis": {"range": [0, 100], "tickcolor": "#44474E", "tickfont": {"color": "#C4C6D0"}},
               "bar": {"color": "#D0BCFF"}, "bgcolor": "#22252A",
               "borderwidth": 1, "bordercolor": "#44474E",
               "steps": [{"range": [0, 100], "color": "#1A1C20"}]},
        title={"text": label, "font": {"color": "#C4C6D0", "size": 14}},
    ))
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      height=230, margin={"l": 12, "r": 12, "t": 40, "b": 8},
                      font={"color": "#E2E2E6"})
    return fig


def extract_mermaid(text):
    match = re.search(r"```mermaid\s*(.*?)```", text, re.S)
    return match.group(1).strip() if match else None


def render_mermaid(diagram):
    escaped = html_lib.escape(diagram)
    body = f"""<!doctype html><html><head>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<style>body{{background:#111216;margin:0;padding:10px}}</style></head>
<body><pre class="mermaid">{escaped}</pre>
<script>try{{mermaid.initialize({{startOnLoad:true,theme:'dark',themeVariables:{{primaryColor:'#4F378B',primaryTextColor:'#EADDFF',lineColor:'#A8C7FA',fontFamily:'Inter'}}}});}}catch(e){{}}</script>
</body></html>"""
    try:
        st.html(body, unsafe_allow_javascript=True)
    except TypeError:
        st.code(diagram, language="mermaid")


if not st.session_state.models_discovered:
    _models, _derr = discover_models(st.session_state.ollama_url)
    st.session_state.ollama_models = _models
    st.session_state.models_discovered = True
    if _models:
        st.session_state.ollama_status = ("ok", len(_models))
    else:
        st.session_state.ollama_status = (
            "error",
            _derr or "Could not reach Ollama",
        )


def set_module(name):
    st.session_state.module = name


def _on_endpoint_change():
    st.session_state.models_discovered = False
    st.session_state.ollama_models = []
    st.session_state.ollama_status = None


with st.sidebar:
    st.markdown(
        '<div class="md3-brand"><div class="md3-brand-title">Material Suite</div>'
        '<div class="md3-brand-sub">Multi-model AI workstation</div></div>',
        unsafe_allow_html=True,
    )
    st.markdown("##### Navigation")
    for key, label, icon in [
        ("coding", "Coding Engine", ":material/code:"),
        ("tutor", "NotebookLM Scout", ":material/school:"),
        ("focus", "Productivity Hub", ":material/bolt:"),
    ]:
        st.button(label, key=f"nav_{key}", icon=icon, width="stretch",
                  on_click=set_module, args=(key,))
    active = st.session_state.module
    st.markdown(
        f"<style>.st-key-nav_{active} button {{"
        "background: #4F378B !important; color: #EADDFF !important;"
        "border: 1px solid #D0BCFF !important; }</style>",
        unsafe_allow_html=True,
    )
    st.divider()

    status = st.session_state.ollama_status
    if status and status[0] == "ok":
        st.badge(f"Ollama online - {status[1]} models", color="green")
    elif status and status[0] == "error":
        _url = html_lib.escape(str(st.session_state.ollama_url))
        st.markdown(
            f'<div class="ms-offline-banner">'
            f'<strong>⚠️ Could not connect to Ollama at <code>{_url}</code>.</strong><br>'
            'If running on Streamlit Cloud, ensure your ngrok/tunnel is active and paste '
            'the public tunnel URL below. Run: <code>ngrok http 11434</code> locally.</div>',
            unsafe_allow_html=True,
        )
        if status[1]:
            st.caption(str(status[1]))
        st.badge("Ollama offline", color="red")
    else:
        st.caption("Checking Ollama connection...")

    st.text_input(
        "Ollama API Endpoint (Local or Tunnel URL)",
        key="ollama_url",
        on_change=_on_endpoint_change,
        placeholder="http://localhost:11434 or https://xxxx.ngrok-free.app",
        help="Local default: http://localhost:11434. On Streamlit Cloud, paste your "
             "public ngrok/Cloudflare tunnel URL (run: ngrok http 11434).",
    )

    with st.expander("Model Router", expanded=False):
        models = st.session_state.ollama_models
        if not models:
            st.caption("No models discovered.")
            if st.button("Rediscover Models", icon=":material/refresh:", width="stretch"):
                _m, _e = discover_models(st.session_state.ollama_url)
                st.session_state.ollama_models = _m
                st.session_state.models_discovered = True
                st.session_state.ollama_status = (
                    ("ok", len(_m)) if _m else ("error", _e or "Could not reach Ollama")
                )
                st.rerun()
        else:
            buckets = classify_models(models)
            st.caption(f"{len(models)} local models discovered")
            st.caption(
                f"Heavy: {', '.join(buckets['heavy'][:2]) or 'n/a'} | "
                f"Coder: {', '.join(buckets['coder'][:2]) or 'n/a'} | "
                f"Fast: {', '.join(buckets['fast'][:2]) or 'n/a'}"
            )
            opts = ["(auto)"] + models
            st.selectbox("Heavy reasoning", opts, key="model_heavy_sel",
                         help="Architecture planning, deep synthesis, test generation")
            st.selectbox("Coding engine", opts, key="model_coder_sel",
                         help="Syntax generation, bug fixing, file patching")
            st.selectbox("Fast summarization", opts, key="model_fast_sel",
                         help="Snippet parsing, quick summaries, status checks")
            if st.button("Rediscover Models", icon=":material/refresh:", width="stretch"):
                _m, _e = discover_models(st.session_state.ollama_url)
                st.session_state.ollama_models = _m
                st.session_state.models_discovered = True
                st.session_state.ollama_status = (
                    ("ok", len(_m)) if _m else ("error", _e or "Could not reach Ollama")
                )
                st.rerun()

    st.caption("3 modules | multi-model routing | local or tunnel")


def render_coding_engine():
    st.markdown("## Coding Engine")
    st.caption("File-mutating workspace: inspect, patch, and execute real files on disk.")

    hdr1, hdr2, hdr3 = st.columns([4, 1.2, 1.2])
    with hdr1:
        new_dir = st.text_input("Workspace directory", key="ws_dir_input",
                                value=st.session_state.ws_dir, label_visibility="collapsed",
                                placeholder="e.g. F:/MyProject")
    with hdr2:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        if st.button("Scan", icon=":material/refresh:", width="stretch"):
            st.session_state.ws_dir = new_dir
            st.session_state.ws_files = list_workspace_files(new_dir)
            st.session_state.ws_selected_file = None
            st.session_state.ws_file_content = ""
            st.rerun()
    with hdr3:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        st.metric("Files", len(st.session_state.ws_files), border=True)

    if not st.session_state.ws_files:
        st.session_state.ws_files = list_workspace_files(st.session_state.ws_dir)

    files = st.session_state.ws_files

    tab_inspect, tab_agent, tab_sandbox = st.tabs(
        ["File Inspector", "Agent & Patch", "Execution Sandbox"]
    )

    with tab_inspect:
        if not files:
            st.info("No matching files found in this directory. Adjust the path and scan again.")
        else:
            sel_col, edit_col = st.columns([3, 1])
            with sel_col:
                options = ["(select a file)"] + files
                picked = st.selectbox("File", options, key="ws_file_pick",
                                      index=(options.index(st.session_state.ws_selected_file)
                                             if st.session_state.ws_selected_file in options else 0))
            with edit_col:
                st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
                edit_toggle = st.toggle("Edit mode", value=st.session_state.ws_edit_mode,
                                        key="ws_edit_toggle")
                st.session_state.ws_edit_mode = edit_toggle

            if picked and picked != "(select a file)":
                if picked != st.session_state.ws_selected_file:
                    content, err = read_workspace_file(st.session_state.ws_dir, picked)
                    if err:
                        st.error(f"Read failed: {err}")
                    else:
                        st.session_state.ws_selected_file = picked
                        st.session_state.ws_file_content = content
                        st.session_state.ws_editor_content = content

                if st.session_state.ws_selected_file:
                    full_path = str(Path(st.session_state.ws_dir) / st.session_state.ws_selected_file)
                    lang = detect_language(st.session_state.ws_file_content, st.session_state.ws_selected_file)
                    st.caption(f"{full_path} | {len(st.session_state.ws_file_content.splitlines())} lines | {lang}")

                    if st.session_state.ws_edit_mode:
                        edited = st.text_area(
                            "Edit file content",
                            value=st.session_state.ws_editor_content,
                            key="ws_editor",
                            height=500,
                            label_visibility="collapsed",
                        )
                        st.session_state.ws_editor_content = edited
                        save_col, cancel_col = st.columns([1, 1])
                        with save_col:
                            if st.button("Save to Disk", icon=":material/save:",
                                         type="primary", width="stretch"):
                                ok, werr = write_workspace_file(
                                    st.session_state.ws_dir,
                                    st.session_state.ws_selected_file,
                                    st.session_state.ws_editor_content,
                                )
                                if ok:
                                    st.session_state.ws_file_content = st.session_state.ws_editor_content
                                    st.toast(f"Saved {st.session_state.ws_selected_file}", icon=":material/check:")
                                    st.rerun()
                                else:
                                    st.error(f"Write failed: {werr}")
                        with cancel_col:
                            if st.button("Discard Changes", icon=":material/undo:", width="stretch"):
                                st.session_state.ws_editor_content = st.session_state.ws_file_content
                                st.rerun()
                    else:
                        st.code(st.session_state.ws_file_content, language=lang.lower(),
                                line_numbers=True, wrap_lines=True)

    with tab_agent:
        if not st.session_state.ws_selected_file:
            st.info("Select a file in the Inspector tab first to use it as agent context. "
                    "Or paste code below.")
        left, right = st.columns([1.2, 1])
        with left:
            mode = st.pills("Agent mode", list(AGENT_MODES), selection_mode="single",
                            key="agent_mode_pills", label_visibility="collapsed")
            if mode:
                st.session_state.agent_mode = mode
            instructions = st.text_area(
                "Additional instructions (optional)",
                key="agent_instructions",
                height=80,
                placeholder="e.g. Fix the off-by-one error in the loop on line 42",
            )
            ctx = st.session_state.ws_file_content or ""
            st.caption(f"Context: {st.session_state.ws_selected_file or 'none'} ({len(ctx)} chars)")

            run = st.button("Run Agent", type="primary", icon=":material/auto_awesome:",
                            width="stretch", disabled=not (ctx.strip() or instructions.strip()))
            if run:
                model = get_model_for_task("coder")
                prompt_parts = []
                if ctx:
                    lang = detect_language(ctx, st.session_state.ws_selected_file)
                    prompt_parts.append(f"Language: {lang}\nFile: {st.session_state.ws_selected_file}\n\nCurrent code:\n```\n{ctx[:14000]}\n```")
                if instructions.strip():
                    prompt_parts.append(f"\nUser instructions: {instructions.strip()}")
                prompt = "\n\n".join(prompt_parts)
                with st.spinner(f"Running {st.session_state.agent_mode} via {model or 'no model'}..."):
                    resp, err = ollama_chat(AGENT_MODES[st.session_state.agent_mode], prompt, model,
                                            st.session_state.ollama_url)
                if err:
                    st.error(f"Agent failed: {err}. Ensure Ollama is running.")
                else:
                    st.session_state.agent_response = resp
                    st.session_state.agent_response_mode = st.session_state.agent_mode
                    code = extract_primary_code(resp)
                    st.session_state.agent_generated_code = code

        with right:
            if st.session_state.agent_response:
                st.markdown(
                    f'<span class="md3-pill pill-LOW">{html_lib.escape(str(st.session_state.agent_response_mode))}</span>'
                    f'<span class="md3-pill pill-MEDIUM">{html_lib.escape(get_model_for_task("coder") or "n/a")}</span>',
                    unsafe_allow_html=True,
                )
                with st.container(border=True):
                    st.markdown(st.session_state.agent_response)
                mermaid = extract_mermaid(st.session_state.agent_response)
                if mermaid:
                    st.markdown("##### Architecture diagram")
                    render_mermaid(mermaid)

        if st.session_state.agent_generated_code:
            st.markdown("#### Generated code")
            code_lang = detect_language(st.session_state.agent_generated_code)
            st.code(st.session_state.agent_generated_code, language=code_lang.lower(), wrap_lines=True)

            wc1, wc2, wc3 = st.columns([2, 2, 1])
            with wc1:
                target = st.selectbox(
                    "Write to file",
                    ["(new file)"] + files,
                    key="agent_write_target",
                    index=(files.index(st.session_state.ws_selected_file) + 1
                           if st.session_state.ws_selected_file in files else 0),
                )
            with wc2:
                if target == "(new file)":
                    new_name = st.text_input("New filename", key="agent_new_filename",
                                             placeholder="src/new_module.py")
                else:
                    st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
                    st.caption(f"Overwrite: {target}")
            with wc3:
                st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
                if st.button("Write to File", icon=":material/edit_document:",
                             type="primary", width="stretch"):
                    rel = new_name.strip() if target == "(new file)" and "new_name" in dir() else target
                    if target == "(new file)":
                        rel = st.session_state.get("agent_new_filename", "").strip()
                    if not rel:
                        st.warning("Enter a filename.")
                    else:
                        ok, werr = write_workspace_file(st.session_state.ws_dir, rel,
                                                        st.session_state.agent_generated_code)
                        if ok:
                            st.toast(f"Wrote {rel}", icon=":material/check:")
                            st.session_state.ws_files = list_workspace_files(st.session_state.ws_dir)
                            st.rerun()
                        else:
                            st.error(f"Write failed: {werr}")

    with tab_sandbox:
        st.markdown("#### Quick actions")
        qa1, qa2, qa3, qa4 = st.columns(4)
        preset_cmds = {
            "py_compile app.py": "Compile check",
            "python -V": "Python version",
            "dir": "List files (Windows)",
            "ls": "List files (Unix)",
        }
        cols = [qa1, qa2, qa3, qa4]
        for col, (cmd, label) in zip(cols, preset_cmds.items()):
            with col:
                if st.button(label, width="stretch", key=f"preset_{cmd}"):
                    out, rc = run_sandbox_command(cmd, st.session_state.ws_dir, timeout=15)
                    st.session_state.exec_output = out
                    st.session_state.exec_rc = rc
                    st.session_state.exec_engine = cmd
                    st.rerun()

        st.markdown("#### Custom command")
        sc1, sc2 = st.columns([4, 1])
        with sc1:
            custom_cmd = st.text_input("Command", key="sandbox_cmd",
                                       placeholder="e.g. python -m pytest -q")
        with sc2:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            if st.button("Run", icon=":material/terminal:", type="primary", width="stretch"):
                if custom_cmd.strip():
                    with st.spinner("Executing..."):
                        out, rc = run_sandbox_command(custom_cmd.strip(), st.session_state.ws_dir, timeout=60)
                    st.session_state.exec_output = out
                    st.session_state.exec_rc = rc
                    st.session_state.exec_engine = custom_cmd.strip()
                    st.session_state.sandbox_history.append(
                        {"cmd": custom_cmd.strip(), "rc": rc, "time": time.strftime("%H:%M:%S")}
                    )
                    st.rerun()

        if st.session_state.exec_output is not None:
            render_terminal(st.session_state.exec_output, st.session_state.exec_rc,
                            st.session_state.exec_engine)
        else:
            render_terminal(
                "idle - run a quick action or type a custom command.\n"
                f"cwd: {st.session_state.ws_dir}"
            )

        if st.session_state.sandbox_history:
            with st.expander(f"Command history ({len(st.session_state.sandbox_history)})"):
                for entry in reversed(st.session_state.sandbox_history[-20:]):
                    rc_display = entry["rc"] if entry["rc"] is not None else "-"
                    st.code(f"[{entry['time']}] {entry['cmd']}  ->  exit {rc_display}",
                            language="text")


def render_tutor():
    st.markdown("## NotebookLM Scout")
    st.caption("Zero-click web scouting -> multi-source synthesis -> adaptive testing.")

    topic = st.text_input("Topic", key="tutor_topic",
                          placeholder="e.g. RISC-V Vector Extensions, Transformer Attention")

    with st.expander("Optional resources (auto-scout runs regardless)"):
        yt_url = st.text_input("YouTube URL", key="tutor_yt")
        article_url = st.text_input("Article URL", key="tutor_url")
        raw_notes = st.text_area("Personal notes", key="tutor_notes", height=100)
        uploads = st.file_uploader("Upload PDF / text", type=["pdf", "txt", "md"],
                                   accept_multiple_files=True, key="tutor_files")

    col1, col2 = st.columns(2)
    with col1:
        difficulty = st.selectbox("Difficulty", DIFFICULTIES, index=1, key="quiz_difficulty")
    with col2:
        question_count = st.slider("Questions", 3, 10, 5, key="quiz_count")

    action1, action2 = st.columns(2)
    gen_guide = action1.button("Generate Study Guide", type="primary",
                               icon=":material/menu_book:", width="stretch",
                               disabled=not topic.strip())
    gen_quiz = action2.button("Generate Test", icon=":material/quiz:", width="stretch",
                              disabled=not topic.strip())

    if gen_guide:
        with st.status("Scouting and synthesizing...", expanded=True) as status:
            sources = {"videos": [], "readings": [], "notes": [], "context": [], "warnings": []}

            st.write("Pass 1/3 - auto-scouting the web")
            results, err = ddg_search(topic, max_results=8)
            if err:
                sources["warnings"].append(f"Web search failed: {err}")
            else:
                for r in results:
                    entry = {"title": r.get("title", ""), "url": r.get("url", ""),
                             "summary": r.get("snippet", "")}
                    if "youtube.com" in entry["url"] or "youtu.be" in entry["url"]:
                        sources["videos"].append(entry)
                    else:
                        sources["readings"].append(entry)
                    sources["context"].append(
                        f"Search result: {entry['title']} ({entry['url']})\n{entry['summary']}"
                    )

            yt_results, yt_err = ddg_search(f"{topic} site:youtube.com", max_results=5)
            if not yt_err and yt_results:
                for r in yt_results:
                    entry = {"title": r.get("title", ""), "url": r.get("url", ""),
                             "summary": r.get("snippet", "")}
                    sources["videos"].append(entry)
                    sources["context"].append(
                        f"YouTube search: {entry['title']} ({entry['url']})\n{entry['summary']}"
                    )

            sentiment, s_err = ddg_search(f"{topic} explained tutorial guide", max_results=5)
            if not s_err and sentiment:
                for r in sentiment:
                    sources["context"].append(
                        f"Supplemental: {r.get('title','')}\n{r.get('snippet','')}"
                    )

            st.write("Pass 1/3 - merging optional custom resources")
            if yt_url.strip():
                meta, y_err = youtube_metadata(yt_url.strip())
                if y_err:
                    sources["warnings"].append(f"YouTube lookup: {y_err}")
                else:
                    sources["videos"].append(
                        {"title": f"{meta['title']} ({meta['author']})", "url": meta["url"],
                         "summary": meta["description"][:400]}
                    )
                    sources["context"].append(f"Custom YouTube: {meta['title']}\n{meta['description'][:2000]}")
            if article_url.strip():
                art, a_err = fetch_article(article_url.strip())
                if a_err:
                    sources["warnings"].append(f"Article fetch: {a_err}")
                else:
                    sources["readings"].append(
                        {"title": art["title"], "url": art["url"], "summary": art["text"][:300]}
                    )
                    sources["context"].append(f"Custom article: {art['title']}\n{art['text']}")
            for upload in uploads or []:
                data = upload.read()
                text = extract_pdf_text(data) if upload.name.lower().endswith(".pdf") else data.decode("utf-8", errors="replace")
                sources["notes"].append({"name": upload.name, "chars": len(text)})
                sources["context"].append(f"Upload {upload.name}:\n{text[:4000]}")
            if raw_notes.strip():
                sources["context"].append(f"Personal notes:\n{raw_notes[:4000]}")

            st.write("Pass 2/3 - synthesizing with heavy reasoning model")
            link_lines = []
            for kind, items in (("Video", sources["videos"]), ("Reading", sources["readings"])):
                for item in items[:10]:
                    link_lines.append(f"- [{kind}] {item['title']} - {item['url']}")
            context_blob = "\n\n".join(sources["context"])[:14000]
            heavy_model = get_model_for_task("heavy")
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
            guide, g_err = ollama_chat(system, user, heavy_model, st.session_state.ollama_url, temperature=0.3)
            if g_err:
                status.update(label="Engine unavailable", state="error")
                st.error(f"Synthesis failed: {g_err}. Start Ollama and try again.")
                return

            st.write("Pass 3/3 - finalizing")
            st.session_state.tutor_guide = guide
            st.session_state.tutor_sources = sources
            status.update(label="Study guide ready", state="complete")
            st.toast("Study guide generated", icon=":material/check:")

    if st.session_state.tutor_guide:
        with st.container(border=True):
            st.markdown(st.session_state.tutor_guide)
        sources = st.session_state.tutor_sources or {"videos": [], "readings": [], "warnings": []}
        for w in sources.get("warnings", []):
            st.warning(w)
        rows = ([{"Type": "Video", **i} for i in sources.get("videos", [])] +
                [{"Type": "Reading", **i} for i in sources.get("readings", [])])
        if rows:
            st.markdown("#### Source index")
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                         column_config={
                             "url": st.column_config.LinkColumn("Link", display_text="open"),
                             "summary": st.column_config.TextColumn("Summary", width="large"),
                         })

    if gen_quiz:
        ctx = (st.session_state.tutor_guide or "")[:5000]
        with st.spinner(f"Generating {question_count} {difficulty} questions..."):
            heavy_model = get_model_for_task("heavy")
            system = (
                "You are an expert exam writer. Output STRICT JSON only - a single array, no prose, "
                "no markdown fences."
            )
            user = (
                f"Topic: {topic}\nDifficulty: {difficulty}\n"
                f"Generate {question_count} questions mixing multiple-choice and conceptual challenges.\n"
                f"Context:\n{ctx}\n\n"
                'MCQ schema: {"type":"mcq","question":str,"options":[4 strings],'
                '"answer_index":int,"explanation":str}\n'
                'Short schema: {"type":"short","question":str,"rubric":str,"model_answer":str}\n'
                "Return only the JSON array."
            )
            raw, q_err = ollama_chat(system, user, heavy_model, st.session_state.ollama_url, temperature=0.5)
        if q_err:
            st.error(f"Test generation failed: {q_err}")
        else:
            parsed = parse_json_array(raw)
            quiz = normalize_quiz(parsed) if parsed else []
            if not quiz:
                st.error("Model did not return valid JSON. Try again or switch the heavy model.")
                with st.expander("Raw output"):
                    st.code(raw)
            else:
                st.session_state.quiz = quiz
                st.session_state.quiz_gen += 1
                st.session_state.quiz_results = None
                st.toast(f"Quiz ready: {len(quiz)} questions", icon=":material/quiz:")

    if st.session_state.quiz:
        _render_quiz()


def _render_quiz():
    quiz = st.session_state.quiz
    gen = st.session_state.quiz_gen
    st.markdown("### Adaptive Test")
    with st.form(key=f"quiz_form_{gen}"):
        for index, question in enumerate(quiz):
            if question["type"] == "mcq":
                st.markdown(f"**Q{index + 1}.** {question['question']}")
                st.radio(f"q{index}", options=list(range(len(question["options"]))),
                         format_func=lambda i, q=question: f"{'ABCDEF'[i]}. {q['options'][i]}",
                         key=f"gen{gen}_mcq_{index}", label_visibility="collapsed")
            else:
                st.markdown(f"**Q{index + 1} (short answer).** {question['question']}")
                if question.get("rubric"):
                    st.caption(f"Rubric: {question['rubric']}")
                st.text_area(f"q{index}", key=f"gen{gen}_sa_{index}",
                             label_visibility="collapsed", height=90)
            st.markdown("<hr style='border-color:#2B2D32'>", unsafe_allow_html=True)
        submitted = st.form_submit_button("Submit answers", type="primary", icon=":material/check:")

    if submitted:
        results = []
        for index, question in enumerate(quiz):
            if question["type"] == "mcq":
                chosen = st.session_state.get(f"gen{gen}_mcq_{index}")
                correct = chosen == question["answer_index"]
                results.append({
                    "index": index, "type": "mcq",
                    "score": 1.0 if correct else 0.0,
                    "selected": question["options"][chosen] if chosen is not None else "(none)",
                    "expected": question["options"][question["answer_index"]],
                    "feedback": question.get("explanation", ""),
                })
        short_items = [(i, q, st.session_state.get(f"gen{gen}_sa_{i}", ""))
                       for i, q in enumerate(quiz) if q["type"] == "short"]
        if short_items:
            fast_model = get_model_for_task("fast")
            system = "You are a strict exam grader. Output STRICT JSON only: an array of objects."
            user = (
                "Grade each short answer against its rubric on a 0-1 scale.\n"
                + "\n".join(
                    f"id={i}\nquestion={q['question']}\nrubric={q.get('rubric','')}\n"
                    f"model_answer={q.get('model_answer','')}\nstudent_answer={ans}"
                    for i, q, ans in short_items
                )
                + '\nReturn [{"id":int,"score":float,"feedback":str}].'
            )
            raw, g_err = ollama_chat(system, user, fast_model, st.session_state.ollama_url, temperature=0.1)
            graded = parse_json_array(raw) if not g_err else None
            graded_map = {int(g["id"]): g for g in graded or [] if isinstance(g, dict) and "id" in g}
            for i, q, ans in short_items:
                if i in graded_map:
                    score = max(0.0, min(1.0, float(graded_map[i].get("score", 0))))
                    feedback = str(graded_map[i].get("feedback", ""))
                else:
                    score, feedback = keyword_grade(ans, q.get("rubric", ""))
                    if g_err:
                        feedback += " [LLM grader offline - keyword fallback]"
                results.append({"index": i, "type": "short", "score": score,
                                "selected": ans or "(blank)",
                                "expected": q.get("model_answer", ""), "feedback": feedback})
        results.sort(key=lambda item: item["index"])
        earned = sum(item["score"] for item in results)
        possible = float(len(results))
        st.session_state.quiz_results = results
        st.session_state.mastery_earned += earned
        st.session_state.mastery_possible += possible
        st.toast(f"Scored {earned:.1f}/{possible:.0f}", icon=":material/grade:")

    if st.session_state.quiz_results:
        results = st.session_state.quiz_results
        earned = sum(item["score"] for item in results)
        possible = len(results)
        pct = (earned / possible * 100) if possible else 0.0
        mastery = (st.session_state.mastery_earned / st.session_state.mastery_possible * 100
                   if st.session_state.mastery_possible else 0.0)
        m1, m2 = st.columns([1, 1])
        with m1:
            st.plotly_chart(score_ring(pct, "Latest test score"), width="stretch", key="score_ring")
        with m2:
            st.plotly_chart(score_ring(mastery, "Session mastery"), width="stretch", key="mastery_ring")
            st.metric("Points", f"{earned:.1f} / {possible:.0f}")
        st.markdown("#### Answer review")
        for item in results:
            good = item["score"] >= 1.0 if item["type"] == "mcq" else item["score"] >= 0.6
            label = f"{'PASS' if good else 'REVIEW'} - Q{item['index'] + 1} ({item['type']}, {item['score']:.2f})"
            with st.expander(label):
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
    st.caption(f"{phase} | {st.session_state.pomo_done} pomodoros completed")
    c1, c2, c3 = st.columns(3)
    if c1.button("Start", icon=":material/play_arrow:", width="stretch",
                 disabled=st.session_state.pomo_running):
        st.session_state.pomo_running = True
        st.session_state.pomo_started = time.time()
    if c2.button("Pause", icon=":material/pause:", width="stretch",
                 disabled=not st.session_state.pomo_running):
        if st.session_state.pomo_started is not None:
            st.session_state.pomo_prior += time.time() - st.session_state.pomo_started
        st.session_state.pomo_running = False
        st.session_state.pomo_started = None
    if c3.button("Reset", icon=":material/restart_alt:", width="stretch"):
        st.session_state.pomo_running = False
        st.session_state.pomo_started = None
        st.session_state.pomo_prior = 0.0
        st.session_state.pomo_phase = "Work"


def render_productivity():
    st.markdown("## Productivity Hub")
    st.caption("Task board, focus timer, and session notes with markdown export.")

    task_col, ring_col = st.columns([1.6, 1])
    with task_col:
        st.markdown("#### Tasks")
        with st.form("task_form", clear_on_submit=True):
            title = st.text_input("Task", placeholder="Describe the task...")
            priority = st.selectbox("Priority", PRIORITIES, index=2)
            submitted = st.form_submit_button("Add task", icon=":material/add:", type="primary")
        if submitted:
            if title.strip():
                add_task(title.strip(), priority)
                st.toast(f"Added: {title.strip()}", icon=":material/add:")
            else:
                st.warning("Task title cannot be empty.")
        filter_choice = st.pills("Filter", ["All", "Pending", "Completed"], key="task_filter")
        tasks = st.session_state.tasks
        filtered = [t for t in tasks
                    if filter_choice == "All"
                    or (filter_choice == "Pending" and not t["done"])
                    or (filter_choice == "Completed" and t["done"])]
        if not filtered:
            st.info("No tasks in this view.")
        for task in filtered:
            with st.container(border=True):
                row = st.columns([0.5, 5, 3, 0.7])
                with row[0]:
                    st.checkbox("done", value=task["done"], key=f"task_chk_{task['id']}",
                                on_change=toggle_task, args=(task["id"],), label_visibility="collapsed")
                with row[1]:
                    css = "task-done" if task["done"] else ""
                    st.markdown(
                        f'<span class="{css}" style="font-size:15px">{html_lib.escape(task["title"])}</span>',
                        unsafe_allow_html=True,
                    )
                with row[2]:
                    st.markdown(
                        f'<span class="md3-pill pill-{task["priority"]}">{task["priority"]}</span>',
                        unsafe_allow_html=True,
                    )
                with row[3]:
                    st.button("Delete", key=f"task_del_{task['id']}", icon=":material/delete:",
                              help="Delete task", on_click=delete_task, args=(task["id"],))
    with ring_col:
        st.markdown("#### Progress")
        done = sum(1 for t in st.session_state.tasks if t["done"])
        total = len(st.session_state.tasks)
        pct = (done / total * 100) if total else 0.0
        st.plotly_chart(score_ring(pct, f"{done}/{total} complete"), width="stretch", key="task_ring")

    st.divider()
    focus_col, notes_col = st.columns([1, 1])
    with focus_col:
        st.markdown("#### Focus timer")
        cc1, cc2 = st.columns(2)
        with cc1:
            st.number_input("Work minutes", min_value=1, max_value=90, step=1, key="pomo_work")
        with cc2:
            st.number_input("Break minutes", min_value=1, max_value=30, step=1, key="pomo_break")
        with st.container(border=True):
            pomodoro_widget()
    with notes_col:
        st.markdown("#### Session notes")
        st.text_area("Scratchpad", key="notes", height=280,
                     placeholder="Capture decisions, formulas, follow-ups...")
        export = f"# Material Suite - session notes\n\n{st.session_state.notes}\n"
        st.download_button("Export markdown", data=export.encode("utf-8"),
                           file_name="material_suite_notes.md", mime="text/markdown",
                           icon=":material/download:", width="stretch")
        st.caption(f"{len(st.session_state.notes)} chars | auto-persisted")


module = st.session_state.module
if module == "coding":
    render_coding_engine()
elif module == "tutor":
    render_tutor()
elif module == "focus":
    render_productivity()
