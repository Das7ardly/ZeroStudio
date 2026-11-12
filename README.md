# ZeroStudio

A friendlier front end for MKVToolNix: multiplex, extract (gMKVExtractGUI-style, but batch) and in-place header editing in one window, with a shared job queue.

## 1.9.0

- Batch episodes: the Rules card shows the everyday rules (keep audio, keep subtitles, added subtitle language and name); the rest sits behind "More rules", which lists the active ones while closed. One "Add files" button takes episodes, subtitles and audio together. The page scrolls on small screens.
- One file: sources start as one row per file, the Tracks table gets the room. Open a source with its arrow to untick chapters or tags.
- Language fields (`bul, eng`) turn amber and name the unknown code when one is mistyped.
- Status bar: "N problems" keeps every skipped file and failed job; click it for the list.
- Keyboard: Ctrl+O add files, Ctrl+Enter start, Delete remove the selection.
- Radio buttons are visible, all button icons are the same line style.
- Added subtitles: the code page is detected from the text (cp1251, cp1252, KOI8-R ...) instead of always using the fallback; the fallback wins ties.
- Added audio or subtitle files that also hold video or chapters no longer bring those along.
- Batch: two episodes with the same name in different folders get separate output files.

## 1.8.1 (bug fixes)

- Subtitle and audio language comes only from tags after the title, the episode marker or the year. `La.Casa.de.Papel.S01E01.srt` is no longer German and `The.Office.UK.S01E01.srt` no longer Ukrainian; untagged files get the "Added subtitles" language.
- Pairing uses the exact season and episode number first, then the longest matching name: `S01E10` no longer lands on `S01E1`, `Aliens.srt` no longer on `Alien.mkv`.
- "Remove SDH / CC / Signs" ignores words of the title (`Hi.Score.Girl`, `Love.Song`).
- One file: sources are added in the order you picked them, and unreadable files are listed in one message.
- UTF-8 subtitles larger than 2 MB are no longer treated as cp1251 (mux and Subtitles to UTF-8).
- Removing a running job deletes its unfinished output and temp file.
- Extract: files of one run never share an output name; an attachment with the same name and size in several files is saved once.
- Tests: `python -m pytest tests` and `QT_QPA_PLATFORM=offscreen python tests/gui_check.py <media dir>`.

## Install (Windows 10/11, 64-bit)

- **ZeroStudio-Setup-1.9.0.exe**: installs for your user only (no admin), adds Start menu and optional desktop shortcuts, uninstalls from Settings > Apps.
- **ZeroStudio-Portable-1.9.0.exe**: unpacks the app into a folder you choose; run `ZeroStudio.exe` from there.

No Python needed. On first start ZeroStudio offers to download MKVToolNix (free, portable, about 30 MB) into its own folder, or you can point it to an MKVToolNix you already have. Settings > MKVToolNix has "Download / update automatically" for later updates.

Windows SmartScreen may warn because the exe isn't code-signed: click "More info" then "Run anyway".

## Run from source

Install Python 3.10+ and MKVToolNix, then double-click `run.bat` (first run installs PySide6). Mac/Linux: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/python main.py`.

## Build the Windows exe

`tools/build_windows_on_linux.sh` builds the frozen app with PyInstaller under Wine and makes the installer and portable exe with NSIS (Ubuntu 24.04). On Windows itself: `pip install pyinstaller PySide6-Essentials`, `python -m PyInstaller packaging/zerostudio.spec`, then `makensis packaging/installer.nsi`.

## Pages

**Multiplex** - add files (drag and drop works everywhere), tick tracks, set language, name, Default/Forced, delay in ms, reorder, keep/drop attachments, add fonts, chapters file, split by size/duration/chapters, append parts (CD1 + CD2). External subtitles get their language from the file name (`Movie.bg.srt` -> bul) and non-UTF-8 files are flagged with your fallback code page (cp1251 by default). "Smart defaults" sets the Default flags from your preferred languages and skips default subtitles when the default audio is already in your language. "Show command" prints the exact mkvmerge command.

**Multiplex > One file** shows everything inside each source like the Extract page: every track with codec, resolution/fps or channels/sample rate, language, name and flags, attachments, chapters and tags. Chapters and tags can be unticked per source.

**Multiplex > Batch episodes** - drop a season and a folder of subtitles (or one folder with both). Subtitles are paired with episodes by `S01E02`, `1x02`, `E02`, `- 02` or matching file name; the language comes from the file name (`.bg.`, `bul`, `[BG]`) or the "Added subtitles" language. Set "Keep audio" and "Keep subtitles" (e.g. `bul, eng`, in order of preference) and every other language is dropped from every episode. The first kept audio language becomes Default, added Bulgarian subs go first and become Default unless the audio is already Bulgarian (Smart), and non-UTF-8 subs are read as cp1251. Each episode row shows the audio/subtitle languages it has now next to what it will have after muxing; expand it to see every track: original language and flags on the left, new position, language and flags on the right, or "removed" in red. Added subtitle files show as "+ file.srt" with the code page that will be converted; output goes to a `muxed` subfolder (or a folder you pick) with the original names. Subtitle clean-up: "Remove SDH / CC / Signs" (hearing-impaired flag, or SDH, HI, CC, Signs or Songs in the track or file name, e.g. English[CC], English[Signs]), "Remove PGS / image subs" and "Only one subtitle per language" (keeps your added file first, then text over PGS, then regular over SDH; forced subtitles stay). The only subtitle of a language is never removed by the SDH/PGS options. Add audio files (dubs: .ac3 .eac3 .aac .dts .mka .flac .opus ...) the same way as subtitles, with a language, name and delay in ms. "Audio by track" / "Subs by track" pick tracks by number in every episode instead of by language: "Keep only tracks 1, 3" or "Remove tracks 2-4" (1 = first audio or first subtitle track; the numbers are shown in the list as "Audio 2", "Subtitles 4"). Every track in the episode list has a tick box: untick to remove it, tick to keep it, whatever the rules say; right-click a track to keep or remove the same track in all episodes, matched by language or by track number ("Undo my ticks" resets). On the One file tab, the "Keep audio / subtitles" row does the same filtering for a single file.

**Extract** - load many MKVs (or MP4, M4V, MOV, AVI, TS/M2TS/MTS, MPG/VOB, FLV, OGM, WebM: anything mkvmerge can read; these are copied into a temporary MKV without re-encoding, extracted, and the temp file is deleted) or a whole folder, set the track selectors once (Video / Audio / Subtitles: all, none, first, default, by language, by position like "1,3" or "2-4", forced only, all except forced) and the same tracks get ticked in every file; manual ticks still work, see the final file name of each item before you start, then extract tracks, attachments, chapters (XML or simple), tags, timestamps and cues. One job per file, runs in parallel. Name template placeholders: `{base} {id} {num} {type} {lang} {name} {codec} {title}`.

**Quick edit** - mkvpropedit in place, no remux: title, track names, languages, Default/Forced/Enabled flags, delete or add attachments. "Apply to all matching files" copies the track settings to every loaded file with the same track layout (a whole season in one click).

**Subtitles to UTF-8** - drop subtitle files or folders. Each file's encoding is detected (UTF-8, Windows-1251, KOI8-R, ISO-8859-5, DOS 866, Windows-1250/1252 and more) and shown with a preview of the real text; if the letters look wrong, change "Read as" and the preview updates. Convert replaces the file and keeps a .bak copy by default (or writes name.utf8.srt, or into a folder). Optional BOM for TVs and old players. Files that are already UTF-8 are skipped.

**Jobs panel** - shared queue at the bottom: progress, stop, run again, view log + command, show in folder. Unfinished jobs survive a restart. **History** keeps every finished job with its log.

## Where things are

Settings, queue and history: `%LOCALAPPDATA%\ZeroStudio`. All engine arguments go through a UTF-8 JSON option file (`mkvmerge @file.json`), so Cyrillic names and titles are safe on any Windows code page.

## Brand

The wordmark (ZER + glowing ring as the zero, light streak, STUDIO, ASHKELAD TOOLKIT) and the app icon are drawn in code (`zerostudio/ui/brand.py`) in the UI accent colour, so they stay sharp at any size and follow the theme. `assets/zerostudio.ico` (16-256 px) and `assets/zerostudio.png` are ready for a desktop shortcut or a future .exe build.

## Layout

```
main.py                    entry point
zerostudio/engine.py        finds mkvmerge/mkvextract/mkvpropedit
zerostudio/mediainfo.py     mkvmerge -J parsing, codec -> extension, naming
zerostudio/commands.py      job spec -> command-line arguments (pure, testable)
zerostudio/jobs.py          QProcess queue, progress parsing, persistence
zerostudio/ui/              pages, queue panel, theme, icons
```
