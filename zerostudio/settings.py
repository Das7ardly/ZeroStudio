"""Settings stored as JSON. Unknown keys are ignored so old/new versions coexist."""
import json
from dataclasses import asdict, dataclass, field, fields

from .paths import data_dir


@dataclass
class Settings:
    mkvtoolnix_dir: str = ""
    max_parallel: int = 2
    # Mux
    mux_out_dir: str = ""                 # empty = next to first source
    pref_audio_langs: str = "bul, eng"
    pref_sub_langs: str = "bul"
    smart_defaults_on_add: bool = True
    fallback_sub_charset: str = "cp1251"
    # Batch mux
    batch_audio_keep: str = "bul, eng"
    batch_sub_keep: str = "bul, eng"
    batch_keep_und: bool = True
    batch_drop_embedded_subs: bool = False
    batch_ext_lang: str = "bul"
    batch_ext_name: str = ""
    batch_drop_sdh: bool = False
    batch_drop_image_subs: bool = False
    batch_one_sub_per_lang: bool = False
    batch_ext_audio_lang: str = "bul"
    batch_ext_audio_name: str = ""
    batch_ext_audio_delay: str = "0"
    batch_audio_by_num: str = "off"
    batch_audio_nums: str = ""
    batch_sub_by_num: str = "off"
    batch_sub_nums: str = ""
    batch_default_sub: str = "smart"
    batch_reorder: bool = True
    batch_out_mode: str = "subfolder"     # subfolder | custom | same
    batch_out_dir: str = ""
    batch_more_rules: bool = False        # "More rules" section open
    # Extract
    extract_out_mode: str = "source"      # source | custom
    extract_out_dir: str = ""
    extract_template: str = "{base}_track{id}_[{lang}]"
    extract_subfolder: bool = False
    extract_types: list = field(default_factory=lambda: ["attachments", "chapters"])
    extract_selectors: dict = field(default_factory=lambda: {
        "video": {"mode": "all"}, "audio": {"mode": "all"}, "subtitles": {"mode": "all"}})
    extract_timestamps: bool = False
    extract_cues: bool = False
    chapters_simple: bool = False
    # Misc
    last_dir: str = ""
    queue_panel_size: int = 170
    window_geometry: str = ""

    @staticmethod
    def path():
        return data_dir() / "settings.json"

    @classmethod
    def load(cls) -> "Settings":
        s = cls()
        try:
            raw = json.loads(cls.path().read_text(encoding="utf-8"))
            names = {f.name for f in fields(cls)}
            for k, v in raw.items():
                if k in names:
                    setattr(s, k, v)
        except Exception:
            pass
        return s

    def save(self):
        tmp = self.path().with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path())
