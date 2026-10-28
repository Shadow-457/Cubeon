"""Build the picker CJK font from NotoSansCJKsc-Regular.otf (SIL OFL 1.1).

Usage: python3 tools/subset_language_font.py /path/to/NotoSansCJKsc-Regular.otf
Requires fontTools in the development Python. Source: notofonts/noto-cjk,
Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf. Re-run when CJK names
or translation tables gain characters. Keeps copyright and license metadata.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from fontTools import subset
    from fontTools.ttLib import TTFont
    from cubeon import i18n, lang
    source = TTFont(sys.argv[1])
    text = ''.join(chr(c) for c in range(32,127))
    for code,native,english,_rtl in i18n.LANGUAGES:
        text += native + english
        if code in ('zh-cn','ja','ko'):
            text += ''.join(lang.table_for(code).values())
    options = subset.Options()
    options.name_IDs = [0,1,2,3,4,5,6,13,14]
    options.name_languages = ['*']
    subsetter = subset.Subsetter(options=options)
    subsetter.populate(text=text)
    subsetter.subset(source)
    for record in source['name'].names:
        if record.nameID in (1,3,4,6):
            name = 'CubeonLanguageCJK-Regular' if record.nameID in (3,6) else 'Cubeon Language CJK'
            record.string = name.encode(record.getEncoding())
    cff = source['CFF '].cff
    cff.fontNames = ['CubeonLanguageCJK-Regular']
    cff.topDictIndex[0].FullName = 'Cubeon Language CJK Regular'
    cff.topDictIndex[0].FamilyName = 'Cubeon Language CJK'
    destination = ROOT/'assets/fonts/CubeonLanguageCJK.otf'
    source.save(destination)
    print(f'{destination.name}: {destination.stat().st_size // 1024} KB')

if __name__ == '__main__':
    main()
