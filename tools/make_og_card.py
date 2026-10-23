"""
Regenerates the site's Open Graph / link-preview card: web/assets/og.png.

The card is HTML, not a drawing. It reuses the site's own faces and palette
(web/assets/fonts/*, the custom properties at the top of web/assets/site.css),
so it cannot drift away from the brand, and the launcher window in it is the
same screenshot the landing page's hero uses (web/assets/cubeon-play.png).

Every content page declares it, so it must stay a real 1200x630:
    <meta property="og:image" content="https://cubeon.ylet.online/assets/og.png" />

Two traps, both hit while writing this:

  * Do NOT render with `google-chrome --headless --screenshot
    --window-size=1200,630`. New headless opens a real window and the frame
    eats ~70px of height, so the page's own background stops short of the
    bottom of the frame - while the PNG still comes out 2400x1260, so the
    capture *looks* right. The symptom is a dead black band across the bottom.
    Playwright's explicit `viewport` has no frame to steal from it.
  * Render at device_scale_factor=2 and halve it. Minecraftia is a pixel font,
    so an integer 2x source lands back on its exact pixel grid instead of being
    resampled into a blur.

Needs the local Chrome (channel="chrome") plus playwright and pillow:
    python3 tools/make_og_card.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "web", "assets", "og.png")
HTML = os.path.join(ROOT, "tools", "og-card.html")  # source; NOT under web/
# Keep it out of web/: everything in that directory is published AND
# tools/test_web_download_count.py asserts every web/*.html page wires
# assets/site.js, which a card source neither can nor should.
W, H = 1200, 630

# Clipboard of what the card says. Keep it in step with web/index.html's hero.
HEADLINE = "Minecraft, but better."
LEDE = ("A free desktop launcher for Windows and Linux: play offline under any "
        "name, and keep mods, skins and versions in one window. No account, "
        "no adverts.")
CHIPS = ["Free", "Windows + Linux", "No account"]
FOOT = "cubeon.ylet.online"

TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Cubeon - Open Graph card</title>
<style>
  /* The site's own faces and palette (web/assets/site.css), so the card cannot
     drift away from the brand. Paths are absolute file:// URLs on purpose: this
     document is loaded straight off disk, and a relative url() would resolve
     against the card's own folder. */
  @font-face{{font-family:'Minecraftia';src:url('{fonts}/Minecraftia-Regular.ttf') format('truetype')}}
  @font-face{{font-family:'Inter';src:url('{fonts}/Inter.ttf') format('truetype')}}

  :root{{
    --paper:#050505; --card:#0B0D0A;
    --ink:#DDF6D5; --text-soft:#9DB394; --hint:#68755F;
    --grass:#46BA34; --grass-dark:#5FD24B; --grass-soft:#052400; --grass-line:#39422F;
    --dirt:#7A4A24; --line:#242B1E;
  }}
  *{{box-sizing:border-box;margin:0;padding:0}}
  html,body{{width:{w}px;height:{h}px;overflow:hidden}}
  /* Every background layer lives on the body - the first attempt used
     absolutely-positioned divs whose radial had already faded out by the time
     it reached the bottom edge, which left a flat dead band across the card. */
  body{{
    background-color:var(--paper);
    background-image:
      repeating-linear-gradient(0deg,rgba(36,43,30,.5) 0 1px,transparent 1px 60px),
      repeating-linear-gradient(90deg,rgba(36,43,30,.5) 0 1px,transparent 1px 60px),
      radial-gradient(1000px 700px at 78% 14%,rgba(70,186,52,.20),rgba(70,186,52,0) 72%),
      radial-gradient(900px 640px at -6% 108%,rgba(5,36,0,.9),rgba(5,36,0,0) 70%),
      linear-gradient(180deg,#070C06,#050505 68%);
    font-family:'Inter',system-ui,sans-serif;
    color:var(--text-soft);
    display:flex;
    flex-direction:column;
  }}

  .card{{flex:1;min-height:0;padding:0 56px;display:flex;align-items:center;gap:62px}}
  .col-text{{width:500px;flex:none}}

  .brand{{display:flex;align-items:center;gap:14px}}
  .brand img{{width:40px;height:40px}}
  .brand span{{font-family:'Minecraftia';font-size:30px;color:var(--ink);line-height:1}}
  .rule{{width:104px;height:7px;background:var(--grass-dark);margin:18px 0 0 54px}}

  h1{{
    margin-top:24px;
    font-family:'Minecraftia';
    font-weight:400;
    font-size:37px;
    line-height:1.17;
    letter-spacing:.005em;
    text-transform:uppercase;
    color:var(--ink);
    max-width:500px;
  }}
  .lede{{margin-top:18px;font-size:17.5px;line-height:1.45;color:var(--text-soft);font-weight:500;max-width:470px}}

  .chips{{display:flex;gap:10px;margin-top:26px}}
  .chip{{font-family:'Minecraftia';font-size:12px;letter-spacing:.04em;text-transform:uppercase;padding:8px 12px;border:2px solid var(--grass-line);color:var(--ink);background:rgba(11,13,10,.6)}}
  .chip.on{{background:var(--grass);border-color:var(--grass);color:#04120A}}

  .foot{{margin-top:26px;display:flex;align-items:center;gap:10px;font-family:'Minecraftia';font-size:13px;letter-spacing:.03em;color:var(--hint);text-transform:uppercase}}
  .foot i{{width:10px;height:10px;background:var(--grass-dark);display:block}}

  /* the launcher window gets the hero shot's treatment: 3px ink border, hard
     8px grass shadow, zero radius */
  .shot{{width:526px;flex:none;border:3px solid var(--ink);box-shadow:8px 8px 0 var(--grass);background:var(--card);overflow:hidden}}
  .shot img{{display:block;width:100%;height:auto}}
  .bar{{flex:none;height:6px;background:var(--dirt)}}
</style>
</head>
<body>
  <div class="card">
    <div class="col-text">
      <div class="brand">
        <img src="file://{cube}" alt="" />
        <span>Cubeon</span>
      </div>
      <div class="rule"></div>

      <h1>{headline}</h1>
      <p class="lede">{lede}</p>

      <div class="chips">
        <span class="chip on">{chip0}</span>
        <span class="chip">{chip1}</span>
        <span class="chip">{chip2}</span>
      </div>

      <div class="foot"><i></i> {foot}</div>
    </div>

    <div class="shot">
      <img src="file://{shot}" alt="" />
    </div>
  </div>
  <div class="bar"></div>
</body>
</html>
"""


def build_html():
    fonts = os.path.join(ROOT, "web", "assets", "fonts")
    cube = os.path.join(ROOT, "assets", "icon_512.png")
    shot = os.path.join(ROOT, "web", "assets", "cubeon-play.png")
    for path in (cube, shot, os.path.join(fonts, "Inter.ttf"),
                 os.path.join(fonts, "Minecraftia-Regular.ttf")):
        if not os.path.exists(path):
            raise SystemExit(f"missing asset: {path}")
    return TEMPLATE.format(
        w=W, h=H, fonts=fonts, cube=cube, shot=shot,
        headline=HEADLINE, lede=LEDE,
        chip0=CHIPS[0], chip1=CHIPS[1], chip2=CHIPS[2], foot=FOOT,
    )


def main():
    try:
        from playwright.sync_api import sync_playwright
        from PIL import Image
    except ImportError as exc:
        raise SystemExit(f"playwright + pillow are required ({exc})")

    html = build_html()
    with open(HTML, "w", encoding="utf-8") as fh:
        fh.write(html)

    big = OUT + ".2x.png"
    with sync_playwright() as p:
        # channel="chrome": use the machine's Chrome, so there is no second
        # ~150MB browser download just to draw one card.
        browser = p.chromium.launch(channel="chrome",
                                    args=["--no-sandbox", "--hide-scrollbars"])
        page = browser.new_page(viewport={"width": W, "height": H},
                                device_scale_factor=2)
        page.goto("file://" + HTML)
        page.wait_for_timeout(600)   # let the pixel font and screenshot settle
        page.screenshot(path=big)
        browser.close()

    im = Image.open(big).convert("RGB")
    if im.size != (W * 2, H * 2):
        raise SystemExit(f"viewport was not {W}x{H}: captured {im.size}")
    # Halve it, so Minecraftia's pixel grid lands on exact pixels.
    im.resize((W, H), Image.LANCZOS).save(OUT, optimize=True)
    os.remove(big)
    print(f"wrote {os.path.relpath(OUT, ROOT)} ({W}x{H}), "
          f"source {os.path.relpath(HTML, ROOT)}")


if __name__ == "__main__":
    main()
