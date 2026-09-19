"""Create an installable archive containing runtime files only."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

root = Path(__file__).resolve().parents[1]
destination = root / ".artifacts" / "astrbot_plugin_orderui.zip"
destination.parent.mkdir(exist_ok=True)
files = [
    root / name for name in ("main.py", "metadata.yaml", "requirements.txt", "README.md", "LICENSE")
]
for directory in ("orderui", "pages", ".astrbot-plugin"):
    files.extend(
        path
        for path in (root / directory).rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    )
with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
    for path in sorted(files):
        archive.write(path, Path("astrbot_plugin_orderui") / path.relative_to(root))
with ZipFile(destination) as archive:
    assert archive.testzip() is None
    assert "astrbot_plugin_orderui/pages/manage/index.html" in archive.namelist()
print(destination)
