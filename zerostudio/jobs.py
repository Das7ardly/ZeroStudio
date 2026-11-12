"""Job queue: runs mkvmerge / mkvextract / mkvpropedit with QProcess (non-blocking)."""
import json
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass, field

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

from .commands import quote_cmd
from .engine import child_env
from .paths import data_dir, sub_dir

QUEUED, RUNNING, DONE, WARN, ERROR, STOPPED = "Queued", "Running", "Done", "Done (warnings)", "Error", "Stopped"
ACTIVE = (QUEUED, RUNNING)
FINISHED = (DONE, WARN, ERROR, STOPPED)
KIND_TOOL = {"mux": "mkvmerge", "extract": "mkvextract", "edit": "mkvpropedit"}
_PROGRESS = re.compile(r"#GUI#progress\s+(\d+)%")


@dataclass
class Job:
    kind: str                     # mux | extract | edit
    title: str
    args: list
    output: str = ""              # file or folder to open/show
    delete_on_fail: str = ""      # partial output to remove on error/stop (mux)
    pre_args: list = field(default_factory=list)  # optional mkvmerge step run first (remux non-MKV for extract)
    temp_file: str = ""           # removed when the job ends, whatever the result
    stage: int = 0                # 0 = pre step (if any), 1 = main tool
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: str = QUEUED
    progress: int = 0
    message: str = ""
    log: list = field(default_factory=list)
    created: float = field(default_factory=time.time)
    started: float = 0.0
    finished: float = 0.0

    @property
    def in_pre(self):
        return bool(self.pre_args) and self.stage == 0

    @property
    def tool(self):
        return "mkvmerge" if self.in_pre else KIND_TOOL[self.kind]

    def to_dict(self):
        d = asdict(self)
        d["log"] = self.log[-50:]
        return d

    @classmethod
    def from_dict(cls, d):
        names = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in d.items() if k in names})


class JobQueue(QObject):
    job_added = Signal(str)
    job_changed = Signal(str)
    job_removed = Signal(str)
    job_finished = Signal(str)
    counts_changed = Signal()

    def __init__(self, engine, settings, history=None, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.settings = settings
        self.history = history
        self.jobs = []                 # ordered list of Job
        self.procs = {}                # job id -> QProcess
        self._buffers = {}
        self._stopping = set()
        self._removed = {}             # job id -> Job removed from the list while its engine was still running
        self._save_timer = QTimer(self, singleShot=True, interval=500, timeout=self.save)

    # ---------- public API ----------
    def get(self, job_id):
        for j in self.jobs:
            if j.id == job_id:
                return j
        return None

    def index_of(self, job_id):
        for i, j in enumerate(self.jobs):
            if j.id == job_id:
                return i
        return -1

    def add(self, job: Job):
        self.jobs.append(job)
        self.job_added.emit(job.id)
        self._changed_counts()
        self._pump()
        return job

    def stop(self, job_id):
        job = self.get(job_id)
        if not job:
            return
        if job.status == RUNNING and job_id in self.procs:
            self._stopping.add(job_id)
            self.procs[job_id].kill()
        elif job.status == QUEUED:
            job.status = STOPPED
            job.message = "Stopped before start"
            self._emit(job)

    def retry(self, job_id):
        job = self.get(job_id)
        if job and job.status in (ERROR, STOPPED, WARN, DONE):
            job.status, job.progress, job.message, job.log = QUEUED, 0, "", []
            job.stage = 0
            self._emit(job)
            self._pump()

    def remove(self, job_id):
        job = self.get(job_id)
        if not job:
            return
        if job.status == RUNNING and job_id in self.procs:
            self._removed[job_id] = job    # _done() deletes its partial output once the engine has exited
            self.stop(job_id)
        self.jobs.remove(job)
        self.job_removed.emit(job_id)
        self._changed_counts()

    def clear_finished(self):
        for j in [j for j in self.jobs if j.status in (DONE, WARN)]:
            self.remove(j.id)

    def stop_all(self):
        for j in list(self.jobs):
            if j.status in ACTIVE:
                self.stop(j.id)

    def counts(self):
        r = sum(1 for j in self.jobs if j.status == RUNNING)
        q = sum(1 for j in self.jobs if j.status == QUEUED)
        e = sum(1 for j in self.jobs if j.status == ERROR)
        return r, q, e

    def busy(self):
        return any(j.status in ACTIVE for j in self.jobs)

    def command_line(self, job):
        main = quote_cmd(self.engine.tool(KIND_TOOL[job.kind]) or KIND_TOOL[job.kind], job.args)
        if job.pre_args:
            return quote_cmd(self.engine.tool("mkvmerge") or "mkvmerge", job.pre_args) + "\n" + main
        return main

    # ---------- running ----------
    def _pump(self):
        running = sum(1 for j in self.jobs if j.status == RUNNING)
        limit = max(1, int(self.settings.max_parallel or 1))
        for job in self.jobs:
            if running >= limit:
                break
            if job.status == QUEUED:
                self._start(job)
                running += 1
        self._changed_counts()

    def _start(self, job, keep_log=False):
        program = self.engine.tool(job.tool)
        if not program:
            job.status, job.message = ERROR, "MKVToolNix not found. Set its folder in Settings."
            self._remove_temp(job)
            self._finish_bookkeeping(job)
            return
        optfile = sub_dir("tmp") / f"{job.id}.json"
        # Force UTF-8 console output so logs with Cyrillic names read correctly on any Windows code page
        args = job.pre_args if job.in_pre else job.args
        optfile.write_text(json.dumps(["--output-charset", "UTF-8"] + args, ensure_ascii=False), encoding="utf-8")
        proc = QProcess(self)
        env = QProcessEnvironment()
        for k, v in child_env().items():
            env.insert(k, v)
        proc.setProcessEnvironment(env)
        proc.setProcessChannelMode(QProcess.MergedChannels)
        proc.readyReadStandardOutput.connect(lambda jid=job.id: self._read(jid))
        proc.finished.connect(lambda code, st, jid=job.id: self._done(jid, code, st))
        proc.errorOccurred.connect(lambda err, jid=job.id: self._error(jid, err))
        self.procs[job.id] = proc
        self._buffers[job.id] = b""
        if keep_log:
            job.status = RUNNING
        else:
            job.status, job.progress, job.message, job.log = RUNNING, 0, "", []
            job.started = time.time()
        job.log.append("$ " + quote_cmd(program, args))
        self._emit(job)
        proc.start(program, ["@" + str(optfile)])

    def _read(self, job_id):
        proc, job = self.procs.get(job_id), self.get(job_id)
        if not proc or not job:
            return
        buf = self._buffers.get(job_id, b"") + bytes(proc.readAllStandardOutput())
        *lines, rest = re.split(rb"\r\n|\n|\r", buf)
        self._buffers[job_id] = rest
        changed = False
        for raw in lines:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            m = _PROGRESS.match(line)
            if m:
                pct = int(m.group(1))
                if job.pre_args:  # two steps: remux = 0-50 %, extract = 50-100 %
                    pct = pct // 2 + (0 if job.in_pre else 50)
                job.progress = pct
                changed = True
                continue
            if line.startswith("#GUI#error"):
                line = "Error: " + line[len("#GUI#error"):].strip()
                job.message = line
            elif line.startswith("#GUI#warning"):
                line = "Warning: " + line[len("#GUI#warning"):].strip()
                if not job.message:
                    job.message = line
            elif line.startswith("#GUI#"):
                continue
            job.log.append(line)
            if len(job.log) > 2000:
                del job.log[1:500]
            changed = True
        if changed:
            self._emit(job)

    def _error(self, job_id, err):
        job = self.get(job_id)
        if job and err == QProcess.FailedToStart:
            job.status, job.message = ERROR, f"Could not start {job.tool}"
            self._cleanup(job_id)
            self._remove_temp(job)
            self._finish_bookkeeping(job)

    def _done(self, job_id, code, status):
        job = self.get(job_id)
        self._read(job_id)
        rest = self._buffers.get(job_id, b"").decode("utf-8", "replace").strip()
        if job and rest and not rest.startswith("#GUI#"):
            job.log.append(rest)
        self._cleanup(job_id)
        if not job:
            gone = self._removed.pop(job_id, None)
            self._stopping.discard(job_id)
            if gone:
                self._remove_partial(gone)
                self._remove_temp(gone)
                QTimer.singleShot(0, self._pump)
            return
        if job_id in self._stopping:
            self._stopping.discard(job_id)
            job.status, job.message = STOPPED, "Stopped by user"
        elif status == QProcess.CrashExit:
            job.status, job.message = ERROR, job.message or f"{job.tool} crashed"
        elif job.in_pre and code in (0, 1):
            job.stage = 1             # remux done: run the real tool on the temp file
            job.log.append("Remux to temporary MKV finished, extracting...")
            self._start(job, keep_log=True)
            return
        elif code == 0:
            job.status, job.progress = DONE, 100
            job.message = ""
        elif code == 1:
            job.status, job.progress = WARN, 100
        else:
            job.status = ERROR
            if not job.message:
                tail = [line for line in job.log[1:] if line.strip()]
                job.message = tail[-1] if tail else f"{job.tool} exited with code {code}"
        if job.status in (ERROR, STOPPED):
            self._remove_partial(job)
        self._remove_temp(job)
        self._finish_bookkeeping(job)

    @staticmethod
    def _remove_partial(job):
        if job.delete_on_fail:
            try:
                os.remove(job.delete_on_fail)
            except OSError:
                pass

    @staticmethod
    def _remove_temp(job):
        if job.temp_file:
            try:
                os.remove(job.temp_file)
            except OSError:
                pass

    def _cleanup(self, job_id):
        proc = self.procs.pop(job_id, None)
        if proc:
            proc.deleteLater()
        self._buffers.pop(job_id, None)
        try:
            os.remove(sub_dir("tmp") / f"{job_id}.json")
        except OSError:
            pass

    def _finish_bookkeeping(self, job):
        job.finished = time.time()
        self._emit(job)
        if self.history is not None:
            try:
                self.history.add(job.kind, job.title, job.output, job.status, job.message,
                                 "\n".join(job.log[-300:]), self.command_line(job))
            except Exception:
                pass
        self.job_finished.emit(job.id)
        QTimer.singleShot(0, self._pump)

    def _emit(self, job):
        self.job_changed.emit(job.id)
        self._changed_counts()

    def _changed_counts(self):
        self.counts_changed.emit()
        self._save_timer.start()

    def shutdown(self):
        """Kill running engines (app is closing); partial mux outputs are removed."""
        for job_id, proc in list(self.procs.items()):
            job = self.get(job_id) or self._removed.pop(job_id, None)
            proc.blockSignals(True)
            proc.kill()
            proc.waitForFinished(3000)
            if job and job.delete_on_fail:
                try:
                    os.remove(job.delete_on_fail)
                except OSError:
                    pass
            if job:
                self._remove_temp(job)
            self._cleanup(job_id)
        self.save()

    # ---------- persistence ----------
    @staticmethod
    def _path():
        return data_dir() / "queue.json"

    def save(self):
        keep = [j.to_dict() for j in self.jobs if j.status in (QUEUED, RUNNING, STOPPED, ERROR)]
        for d in keep:
            if d["status"] in (RUNNING, QUEUED):
                d["status"], d["message"], d["progress"] = STOPPED, "Interrupted (app closed)", 0
            d["stage"] = 0
        try:
            tmp = self._path().with_suffix(".tmp")
            tmp.write_text(json.dumps(keep, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self._path())
        except OSError:
            pass

    def restore(self):
        try:
            items = json.loads(self._path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for d in items:
            try:
                job = Job.from_dict(d)
            except TypeError:
                continue
            self.jobs.append(job)
            self.job_added.emit(job.id)
        self.counts_changed.emit()
