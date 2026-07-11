from pathlib import Path


VERSION_FILE = Path(__file__).resolve().parent.parent / "VERSION"
APPLICATION_VERSION = VERSION_FILE.read_text(encoding="utf-8").strip()
