"""Copy the launcher's existing cube icons to the website's stable favicon URLs."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def main():
    shutil.copyfile(ROOT / "assets/icon_256.png", ROOT / "web/assets/favicon.png")
    shutil.copyfile(ROOT / "assets/icon.ico", ROOT / "web/favicon.ico")


if __name__ == "__main__":
    main()
