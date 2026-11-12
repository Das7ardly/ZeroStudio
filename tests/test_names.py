"""File-name heuristics: language, SDH tags, episode pairing, UTF-8 check. Run: python -m pytest tests"""
import os

import pytest

from zerostudio import subconv
from zerostudio.batch import episode_key, is_sdh, match_subtitles
from zerostudio.languages import guess_from_filename
from zerostudio.mediainfo import Track, detect_text_charset


@pytest.mark.parametrize("name,lang", [
    ("La.Casa.de.Papel.S01E01.srt", None), ("The.Office.UK.S01E01.1080p.srt", None),
    ("The.French.Dispatch.2021.srt", None), ("The.Italian.Job.srt", None), ("Hello.Mr.Robot.S01E01.srt", None),
    ("Henry.VI.Part.2.srt", None), ("Da.Vinci.Demons.S01E02.srt", None), ("Hi.Score.Girl.S01E01.srt", None),
    ("Show.S01E01.WEB-DL.DD5.1.H.264-NTb.srt", None),
    ("Show.S01E01.bg.srt", "bul"), ("La.Casa.de.Papel.S01E01.bg.srt", "bul"), ("Movie.bg.srt", "bul"),
    ("Movie [English].ass", "eng"), ("Movie_forced.eng.srt", "eng"), ("Movie.eng.forced.srt", "eng"),
    ("The.French.Dispatch.2021.bul.srt", "bul"), ("Show.S01E02.en.hi.srt", "eng"), ("Movie.hi.srt", "hin"),
    ("Show - 07 [BG].srt", "bul"), ("Show.1x02.Bulgarian.srt", "bul"), ("The.Office.UK.S01E01.en.srt", "eng"),
])
def test_language_from_name(name, lang):
    assert guess_from_filename(name) == lang


def test_language_uses_video_name():
    assert guess_from_filename("The.Italian.Job.srt", "The.Italian.Job.mkv") is None
    assert guess_from_filename("The.Italian.Job.bg.srt", "The.Italian.Job.mkv") == "bul"
    assert guess_from_filename("Der.Pass.German.srt", "Der.Pass.mkv") == "ger"


@pytest.mark.parametrize("name,kind", [
    ("Hi.Score.Girl.S01E01.bg.srt", ""), ("Love.Song.S01E02.bul.srt", ""), ("Signs.2002.bg.srt", ""),
    ("CC.Show.S01E01.srt", ""), ("The.Deaf.S01E01.srt", ""), ("Show.S01E01.bg.srt", ""),
    ("Show.S01E01.eng.sdh.srt", "SDH"), ("Show.S01E01.en.hi.srt", "SDH"), ("Show.S01E01.eng.cc.srt", "CC"),
    ("Show.S01E01.Signs.Songs.srt", "Signs"), ("Movie.eng.sdh.srt", "SDH"), ("Movie.2019.en.cc.srt", "CC"),
])
def test_sdh_from_name(name, kind):
    assert is_sdh(Track(0, "subtitles", "SubRip"), name) == kind


def test_sdh_track_name_still_counts():
    assert is_sdh(Track(0, "subtitles", "SubRip", name="English SDH")) == "SDH"
    assert is_sdh(Track(0, "subtitles", "SubRip", name="English[CC]"), "Hi.Show.S01E01.srt") == "CC"


def test_pairing_unpadded_numbers():
    eps = ["Show.S01E1.mkv", "Show.S01E10.mkv", "Show.S01E11.mkv"]
    got, un = match_subtitles(eps, ["Show.S01E10.srt", "Show.S01E11.bg.srt", "Show.S01E1.srt"])
    assert got == {"Show.S01E1.mkv": ["Show.S01E1.srt"], "Show.S01E10.mkv": ["Show.S01E10.srt"],
                   "Show.S01E11.mkv": ["Show.S01E11.bg.srt"]} and not un


def test_pairing_longest_name_and_loose_number():
    assert match_subtitles(["Alien.mkv", "Aliens.mkv"], ["Aliens.srt", "Alien.bg.srt"])[0] == {
        "Alien.mkv": ["Alien.bg.srt"], "Aliens.mkv": ["Aliens.srt"]}
    assert match_subtitles(["Show - 1.mkv", "Show - 10.mkv"], ["Show - 10.srt"])[0]["Show - 10.mkv"] == ["Show - 10.srt"]
    got, un = match_subtitles(["Show.S01E02.1080p.mkv", "Show.S01E03.1080p.mkv"], ["show 02.srt", "Other - 09.srt"])
    assert got["Show.S01E02.1080p.mkv"] == ["show 02.srt"] and un == ["Other - 09.srt"]
    got, _ = match_subtitles(["Show.S01E02.1080p.WEB.mkv"], ["Show.S01E02.1080p.WEB.bg.srt"])
    assert got["Show.S01E02.1080p.WEB.mkv"] == ["Show.S01E02.1080p.WEB.bg.srt"]


@pytest.mark.parametrize("name,key", [
    ("Se7en.1995.mkv", None), ("Blade2.mkv", None), ("Show.S01E02.mkv", (1, 2)), ("Show.2x05.mkv", (2, 5)),
    ("Show - 07 [720p].mkv", (0, 7)), ("The.100.E05.mkv", (0, 5)), ("Show.Ep12.mkv", (0, 12)),
    ("Movie.1920x1080.mkv", None),
])
def test_episode_key(name, key):
    assert episode_key(name) == key


def test_big_utf8_subtitle_is_not_cp1251(tmp_path):
    p = tmp_path / "big.ass"
    p.write_bytes(b"a" + "Здравей свят\n".encode("utf-8") * 120000)     # 2 MB sample stops inside a letter
    assert os.path.getsize(p) > 2_000_000
    assert detect_text_charset(str(p), "cp1251") == ""
    assert subconv.detect(subconv.read(str(p), 2_000_000))[0] == "utf-8"
    q = tmp_path / "old.srt"
    q.write_bytes("Здравей, как си?\n".encode("cp1251") * 50)
    assert detect_text_charset(str(q), "cp1251") == "cp1251"
    assert subconv.detect(q.read_bytes())[0] == "cp1251"


def test_charset_is_detected_not_assumed(tmp_path):
    fr = tmp_path / "fr.srt"
    fr.write_bytes("Café déjà vu, naïve façade\nÀ bientôt, garçon. Noël, cœur\n".encode("cp1252") * 20)
    assert detect_text_charset(str(fr), "cp1251") == "cp1252"
    ru = tmp_path / "ru.srt"
    ru.write_bytes("Привет, как дела? Хорошо.\n".encode("koi8_r") * 20)
    assert detect_text_charset(str(ru), "cp1251") == "KOI8-R"
    bg = tmp_path / "bg.srt"
    bg.write_bytes("Здравей, как си? Добре съм, благодаря.\n".encode("cp1251") * 20)
    assert detect_text_charset(str(bg), "cp1251") == "cp1251"
    assert detect_text_charset(str(bg), "cp1252") == "cp1251"
    assert detect_text_charset(str(bg), "Big5") == "Big5"       # a fallback we cannot judge is used as is


def test_added_file_with_other_tracks():
    from zerostudio.batch import Rules, plan_episode
    from zerostudio.commands import build_mux_args
    from zerostudio.mediainfo import MediaFile
    ep = MediaFile("Show.S01E01.mkv", tracks=[Track(0, "video", "AVC"), Track(1, "audio", "AC-3", language="eng")])
    dub = MediaFile("Show.S01E01.bg.mka", tracks=[Track(0, "video", "MJPEG"), Track(1, "audio", "AAC")])
    spec, _ = plan_episode(ep, [("Show.S01E01.bg.mka", dub)], Rules(), "out.mkv")
    args = build_mux_args(spec)
    i = args.index("Show.S01E01.bg.mka")
    before = args[args.index("Show.S01E01.mkv") + 1:i]
    assert "--no-video" in before and "--no-chapters" in before
    assert spec["track_order"] == [[0, 0], [1, 1], [0, 1]]
