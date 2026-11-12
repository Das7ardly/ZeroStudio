"""Headless end-to-end check with real mkvmerge. Usage: QT_QPA_PLATFORM=offscreen python tests/gui_check.py <media dir>
The media dir needs Show.S01E0{1,2,3}.1080p.WEB-DL.mkv (+ .srt in cp1251) and Font.S01E0{1,2}.mkv (same font attached)."""
import glob, json, os, shutil, subprocess, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
work = tempfile.mkdtemp(prefix="zs-check-")
os.environ["ZEROSTUDIO_DATA_DIR"] = os.path.join(work, "data")
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from zerostudio.engine import Engine
from zerostudio.jobs import Job
from zerostudio.settings import Settings
from zerostudio.ui import theme
from zerostudio.ui.main_window import MainWindow

media = os.path.join(work, "media")
shutil.copytree(sys.argv[1], media)
app = QApplication(sys.argv); theme.apply(app)
QMessageBox.warning = staticmethod(lambda *a, **k: print("  [dialog]", a[1], "|", a[2].replace("\n", " ")[:90]))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
win = MainWindow(Settings.load(), Engine("")); win.show()
ok = True
def check(name, cond):
    global ok; ok = ok and bool(cond); print(("PASS " if cond else "FAIL ") + name)
def wait(cond, secs=40):
    end = time.time() + secs
    while not cond() and time.time() < end:
        loop = QEventLoop(); QTimer.singleShot(50, loop.quit); loop.exec()
    return cond()
def ident(path):
    return json.loads(subprocess.run(["mkvmerge", "-J", path], capture_output=True).stdout)
mkvs = sorted(glob.glob(media + "/Show*.mkv")); srts = sorted(glob.glob(media + "/Show*.srt"))

# 4. One file keeps the order files were added in, 20 times in a row
mux = win.pages["mux"].single
good = 0
for _ in range(20):
    mux.reset(); mux.add_files([mkvs[0], srts[0], mkvs[1], srts[1], os.path.join(media, "nope.mkv")])
    wait(lambda: mux._pending == 0)
    good += [i["path"] for i in mux.inputs] == [mkvs[0], srts[0], mkvs[1], srts[1]]
check(f"one file: source order kept ({good}/20), one dialog for the unreadable file", good == 20)
check("one file: output named after the first file", os.path.basename(mux.out_edit.text()) == "Show.S01E01.1080p.WEB-DL (muxed).mkv")

# batch: real mux of 3 episodes, subs tagged bul + cp1251
batch = win.pages["mux"].batch
batch.add_paths(mkvs + srts); wait(lambda: batch._pending == 0 and len(batch.plans) == 3)
batch.start(); wait(lambda: not win.queue.busy() and len(win.queue.jobs) == 3)
outs = sorted(glob.glob(media + "/muxed/*.mkv"))
info = [ident(o) for o in outs]
langs = [[t["properties"].get("language") for t in d["tracks"]] for d in info]
check(f"batch: 3 episodes muxed, tracks {langs[0] if langs else None}", len(outs) == 3 and all(l == ["und", "eng", "bul"] for l in langs))
txt = subprocess.run(["mkvextract", outs[0], "tracks", f"2:{work}/s.srt"], capture_output=True) and open(f"{work}/s.srt", encoding="utf-8").read()
check("batch: cp1251 subtitle became real Cyrillic", "Здравей" in txt)

# 6. removing a running job deletes its partial output and temp file
fake = os.path.join(work, "slow.sh"); partial = os.path.join(work, "partial.mkv"); temp = os.path.join(work, "temp.mkv")
open(fake, "w").write(f"#!/bin/sh\necho x > '{partial}'\necho x > '{temp}'\nsleep 30\n"); os.chmod(fake, 0o755)
real = dict(win.engine.paths); win.engine.paths["mkvmerge"] = fake
job = win.queue.add(Job("mux", "slow", ["x"], output=partial, delete_on_fail=partial, temp_file=temp))
check("remove: job started and wrote a partial file", wait(lambda: os.path.exists(partial) and os.path.exists(temp), 10))
win.queue.remove(job.id)
check("remove: partial output and temp file deleted, process gone",
      wait(lambda: not os.path.exists(partial) and not os.path.exists(temp) and not win.queue.procs, 10))
win.engine.paths.update(real)

# 7. extract: the same font in two episodes is written once, different tracks never collide
ex = win.pages["extract"]; fonts = sorted(glob.glob(media + "/Font*.mkv"))
ex.tpl_edit.setText("{lang}")                      # worst case: a template without the file name
ex.add_files(fonts); wait(lambda: ex._pending == 0 and len(ex.files) == 2)
n0 = len(win.queue.jobs)
taken, seen, specs = set(), {}, []
for e in ex.files:
    spec, names, _ = ex.plan(e, taken, seen); specs.append(spec)
files = [t["file"] for s in specs for t in s["tracks"]] + [a["file"] for s in specs for a in s["attachments"]]
check(f"extract: {len(files)} outputs, all different", len(files) == len(set(f.lower() for f in files)))
check("extract: shared font extracted by the first file only", [len(s["attachments"]) for s in specs] == [1, 0])
ex.start(); wait(lambda: not win.queue.busy() and len(win.queue.jobs) == n0 + 2)
st = [j.status for j in win.queue.jobs[n0:]]
got = sorted(os.path.basename(f) for f in files if os.path.exists(f))
check(f"extract: both jobs {st}, {len(got)} files on disk", st == ["Done", "Done"] and len(got) == len(files))
win.queue.shutdown(); shutil.rmtree(work, ignore_errors=True)
print("ALL OK" if ok else "SOMETHING FAILED"); os._exit(0 if ok else 1)
