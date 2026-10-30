"""Bundle a compact static Inter subset for the companion client's custom screens."""
from pathlib import Path
from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
import json

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "mod/src/main/resources/assets/cubeon-client/font"


def main():
    font = TTFont(ROOT / "assets/fonts/Inter.ttf", recalcTimestamp=False)
    copyright_text = font["name"].getDebugName(0)
    if "fvar" in font:
        font = instantiateVariableFont(font, {"wght": 400, "opsz": 14}, inplace=True)
    options = subset.Options()
    options.recalc_timestamp = False
    options.name_IDs = [0, 1, 2, 3, 4, 5, 6, 13, 14]
    worker = subset.Subsetter(options=options)
    worker.populate(unicodes=list(range(32, 384)) + list(range(0x2000, 0x2070)) + list(range(0x2190, 0x2194)))
    worker.subset(font)
    for record in font["name"].names:
        if record.nameID in (1, 3, 4, 6):
            value = "CubeonUI-Regular" if record.nameID == 6 else "Cubeon UI Regular" if record.nameID == 4 else "Cubeon UI"
            record.string = value.encode(record.getEncoding())
    TARGET.mkdir(parents=True, exist_ok=True)
    font.save(TARGET / "ui.ttf")
    providers = {"providers": [
        {"type": "ttf", "file": "cubeon-client:ui.ttf", "size": 10,
         "oversample": 6, "shift": [0, 0]},
        {"type": "reference", "id": "minecraft:default"},
    ]}
    (TARGET / "ui.json").write_text(json.dumps(providers, indent=2) + "\n", encoding="utf-8")
    original_license = (ROOT / "assets/fonts/Noto-LICENSE.txt").read_text(encoding="utf-8")
    license_body = original_license[original_license.index("-----------------------------------------------------------"):]
    (TARGET / "OFL-Inter.txt").write_text(
        "Cubeon UI: a static subset of Inter Regular.\n" + copyright_text + "\n\n" + license_body,
        encoding="utf-8",
    )
    print(f"Generated {TARGET / 'ui.ttf'} ({(TARGET / 'ui.ttf').stat().st_size} bytes).")


if __name__ == "__main__":
    main()
