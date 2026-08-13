"""网页版需求对话澄清（零第三方依赖，仅用标准库 http.server）。

- 每个浏览器标签 / 每次「新建对话」= 一个 session；服务端在内存持有 Clarifier 状态，
  支持**同时多开对话**。
- 流程：多轮对话（AI 追问边界）→ 用户点「开始工作」→ 把需求确认单写入本地
  `requirements/`，并用它（结合 docs/ 已有文档）启动 Orchestrator 后台执行。
- 启动：`python -m agents web [--port 8000] [--mock] [--doc] [--no-sandbox]`
"""
import datetime
import json
import os
import re
import threading
import uuid

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import prompts
from .conversation import Clarifier
from .config import load_dotenv, get_llm, is_mock, set_project_root, get_project_root
from .scheduler import Scheduler
from .orchestrator import Orchestrator

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQ_DIR = os.path.join(ROOT, "requirements")
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webui")
INDEX_HTML = os.path.join(STATIC_DIR, "index.html")

SESSIONS = {}                 # sid -> Session
SESSIONS_LOCK = threading.Lock()

# 服务端级默认（由 `agents web` 启动参数决定）
_DEFAULTS = {"use_sandbox": True, "doc": True}


def _write_requirement(sid, title, spec):
    """把需求确认单写入本地 requirements/，返回绝对路径。"""
    os.makedirs(REQ_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    fname = f"req-{stamp}-{sid[:6]}.md"
    path = os.path.join(REQ_DIR, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(spec)
    return path


class Session:
    """单个对话会话：持有 Clarifier、消息记录、后台任务。"""

    def __init__(self, sid, llm):
        self.id = sid
        self.llm = llm
        self.lock = threading.Lock()
        self.messages = []          # [{role:'user'|'assistant', text}]
        self.title = "新对话"
        self.requirement_path = None
        self.job = None
        self.job_error = None
        self.running = False
        self.clarifier = Clarifier(llm)
        self.project = _DEFAULTS.get("project")   # 本会话绑定的后端项目（可在「开始工作」时指定）
        # 开场白
        opening = self.clarifier.start()
        self.messages.append({"role": "assistant", "text": opening})

    def send(self, text):
        with self.lock:
            self.clarifier.submit(text)
            self.messages.append({"role": "user", "text": text})
            self.messages.append({"role": "assistant", "text": self.clarifier.pending})
            if self.title == "新对话" and text.strip():
                self.title = text.strip()[:24]
            return self.clarifier.pending, self.clarifier.done

    def start_work(self, project=None):
        with self.lock:
            if project:
                set_project_root(project)
                _DEFAULTS["project"] = get_project_root() if project else None
            self.project = _DEFAULTS.get("project")
            spec = self.clarifier.finalize()
            self.requirement_path = _write_requirement(self.id, self.title, spec)
            self.running = True
            t = threading.Thread(target=self._run, args=(spec,), daemon=True)
            t.start()
            return self.requirement_path

    def _run(self, spec):
        try:
            project = _DEFAULTS.get("project")
            orch = Orchestrator(Scheduler(self.llm, project_root=project))
            job = orch.run(spec, use_sandbox=_DEFAULTS["use_sandbox"],
                           doc=_DEFAULTS["doc"], project_root=project)
            self.job = job
        except Exception as e:  # 异常也记录，便于前端展示
            self.job_error = str(e)
        finally:
            self.running = False

    def summary(self):
        with self.lock:
            if self.job is not None:
                job = self.job
                return {"state": job.state, "error": job.error,
                        "stages": job.stages, "dir": job.dir,
                        "job_id": job.job_id, "requirement_path": self.requirement_path,
                        "project": self.project}
            if self.running:
                return {"state": "running", "error": self.job_error,
                        "stages": [], "dir": None, "job_id": None,
                        "requirement_path": self.requirement_path, "project": self.project}
            return {"state": "error" if self.job_error else "idle",
                    "error": self.job_error,
                    "stages": [], "dir": None, "job_id": None,
                    "requirement_path": self.requirement_path, "project": self.project}


def _new_session(llm):
    sid = uuid.uuid4().hex
    with SESSIONS_LOCK:
        SESSIONS[sid] = Session(sid, llm)
    return sid


_ID_RE = re.compile(r"^/api/sessions/([0-9a-f]+)(/.*)?$")


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, obj, status=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, path):
        try:
            with open(path, "rb") as f:
                data = f.read()
        except FileNotFoundError:
            self.send_error(404, "not found")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def do_GET(self):
        parsed = self.path.split("?")[0]
        if parsed in ("/", "/index.html"):
            self._send_html(INDEX_HTML)
            return
        if parsed == "/api/sessions":
            with SESSIONS_LOCK:
                listing = [{"id": s.id, "title": s.title,
                            "count": len(s.messages),
                            "state": s.summary()["state"]}
                           for s in SESSIONS.values()]
            self._send_json(listing)
            return
        m = _ID_RE.match(parsed)
        if m:
            sid = m.group(1)
            sub = m.group(2) or ""
            with SESSIONS_LOCK:
                sess = SESSIONS.get(sid)
            if sess is None:
                self._send_json({"error": "session not found"}, 404)
                return
            if sub == "":
                self._send_json({"id": sess.id, "title": sess.title,
                                 "messages": sess.messages, "summary": sess.summary()})
            elif sub == "/job":
                self._send_json(sess.summary())
            else:
                self._send_json({"error": "unknown subpath"}, 404)
            return
        self.send_error(404, "not found")

    def do_POST(self):
        parsed = self.path.split("?")[0]
        if parsed == "/api/sessions":
            llm = get_llm()
            sid = _new_session(llm)
            with SESSIONS_LOCK:
                sess = SESSIONS[sid]
            self._send_json({"id": sid, "title": sess.title})
            return
        m = _ID_RE.match(parsed)
        if m:
            sid = m.group(1)
            sub = m.group(2) or ""
            with SESSIONS_LOCK:
                sess = SESSIONS.get(sid)
            if sess is None:
                self._send_json({"error": "session not found"}, 404)
                return
            body = self._body()
            if sub == "/message":
                text = (body.get("text") or "").strip()
                if not text:
                    self._send_json({"error": "empty text"}, 400)
                    return
                assistant, done = sess.send(text)
                self._send_json({"assistant": assistant, "done": done,
                                 "messages": sess.messages})
                return
            if sub == "/start":
                path = sess.start_work(body.get("project"))
                self._send_json({"requirement_path": path,
                                 "message": "需求文档已写入，任务已启动",
                                 "project": sess.project})
                return
            self._send_json({"error": "unknown subpath"}, 404)
            return
        self.send_error(404, "not found")

    # 静默默认日志，避免刷屏
    def log_message(self, fmt, *args):
        pass


def run(host="127.0.0.1", port=8000, mock=False, doc=True, no_sandbox=False, project=None):
    load_dotenv()
    if mock:
        os.environ["AGENTS_MOCK"] = "1"
    if project:
        set_project_root(project)
    _DEFAULTS["doc"] = doc
    _DEFAULTS["use_sandbox"] = not no_sandbox
    _DEFAULTS["project"] = get_project_root() if project else None
    mode = "MOCK(离线)" if is_mock() else f"LLM({os.environ.get('OPENAI_MODEL', '?')})"
    print(f"[agents-web] 启动：http://{host}:{port}  模式={mode}  "
          f"文档阶段={'开' if doc else '关'}  沙箱={'开' if _DEFAULTS['use_sandbox'] else '关'}")
    if _DEFAULTS["project"]:
        print(f"[agents-web] 目标项目：{_DEFAULTS['project']}")
    print(f"[agents-web] 需求文档将写入：{REQ_DIR}")
    httpd = ThreadingHTTPServer((host, port), Handler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[agents-web] 已停止")
    finally:
        httpd.server_close()
