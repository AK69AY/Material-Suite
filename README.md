# Material Suite

**MD3 AI Workstation - Project APEX**  
A local-first, Material Design 3 dark-themed Streamlit application combining three AI-powered productivity pillars.

---

## Three Pillars

### 🧠 Coding Agent
Autonomous coding assistant with workspace exploration, language auto-detection, four specialist agent modes, and live execution terminal.

- **Workspace explorer** — scans repository for source files (`.py`, `.v`, `.c`, `.tex`, `.ys`, `.json`, `.md`)
- **Four agent modes** — Code Explainer, Bug Fixer & Refactorer, Testbench/Test Generator, Architecture & System Designer
- **Live execution** — Python, Verilog (via Icarus), C (via GCC/Clang), with static analysis fallback
- **Mermaid rendering** — architecture diagrams rendered inline
- **Local LLM** — connects to Ollama (default `http://localhost:11434`)

### 📚 NotebookLM-Style Tutor
Multi-pass research engine that ingests resources, synthesizes master study guides, and generates adaptive tests.

- **Resource ingestion** — YouTube (metadata + transcripts), articles (live fetch), PDF/text uploads, raw notes
- **Live web research** — DuckDuckGo scraping when no custom resources provided
- **Master study guide** — structured output: Core Concepts, Formulae & Diagrams, Curated Sources, Community Sentiment
- **Adaptive testing** — mixed MCQ + short-answer, configurable difficulty (Beginner → Exam-Level)
- **LLM grading** — with keyword-rubric fallback when model unavailable
- **Mastery tracking** — session-wide progress rings and answer review

### ⚡ Productivity Hub
Minimalist task management, pomodoro timer, and session scratchpad.

- **Task board** — add/edit/delete, priority pills (CRITICAL/HIGH/MEDIUM/LOW), filter views
- **Pomodoro timer** — configurable work/break intervals, auto phase switching, toast notifications
- **Session notes** — auto-persisted markdown scratchpad with one-click export

---

## Quick Start

### Prerequisites
- Python 3.10+
- [Ollama](https://ollama.ai) running locally with at least one model pulled
  ```bash
  ollama pull qwen2.5-coder:7b
  ollama pull llama3.2:3b
  ```

### Install & Run
```bash
cd Material-Suite
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # macOS/Linux
pip install -r requirements.txt
streamlit run app.py
```

Open `http://localhost:8501` in your browser.

### Configuration
Edit `config.toml` for server/theme settings. Ollama endpoint and model selection live in the sidebar (persisted in session state).

---

## Project Structure
```
Material-Suite/
├── app.py              # Main Streamlit application
├── requirements.txt    # Python dependencies
├── config.toml         # Streamlit server/theme config
├── .gitignore
└── README.md
```

---

## Tech Stack
- **Streamlit** ≥ 1.35 — web framework
- **Plotly** ≥ 5.18 — interactive charts (progress rings, bars)
- **Pandas** ≥ 2.0 — data handling
- **Requests** ≥ 2.31 — HTTP calls (Ollama, web research)
- **PyPDF** ≥ 4.0 — PDF text extraction
- **Icarus Verilog** (optional) — live Verilog simulation
- **GCC/Clang** (optional) — live C execution

---

## License
MIT