"""Exercise production HUD layout/input geometry with the bundled UI font."""
from pathlib import Path
import json
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("javac") and shutil.which("java"), "JDK required")
class ClientUiTests(unittest.TestCase):
    def test_layout_and_preview(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            labels = json.loads((ROOT / "mod/src/main/resources/assets/cubeon-client/lang/en_us.json").read_text())
            (folder / "labels.properties").write_text("\n".join(f"{key}={value}" for key, value in labels.items()), encoding="utf-8")
            harness = folder / "UiTest.java"
            harness.write_text(r'''
import com.cubeon.client.ui.*;
import com.cubeon.client.emotes.*;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.Properties;
import javax.imageio.ImageIO;
import java.util.HashMap;
import java.awt.image.RescaleOp;
public class UiTest {
 static void check(boolean value,String reason) { if(!value)throw new AssertionError(reason); }
 static class Canvas implements EmoteWheel.Canvas {
  final BufferedImage image; final Graphics2D graphics; final Properties labels; int calls,quads;
  static final HashMap<String,BufferedImage> textures=new HashMap<>();
  static final int DISPLAY_SCALE=3;
  Canvas(int w,int h,Font font,Properties labels) {
   this.labels=labels;image=new BufferedImage(w*DISPLAY_SCALE,h*DISPLAY_SCALE,BufferedImage.TYPE_INT_ARGB);graphics=image.createGraphics();
   graphics.scale(DISPLAY_SCALE,DISPLAY_SCALE);
   graphics.setColor(new Color(0x050505));graphics.fillRect(0,0,w,h);graphics.setFont(font);
   graphics.setRenderingHint(RenderingHints.KEY_TEXT_ANTIALIASING,RenderingHints.VALUE_TEXT_ANTIALIAS_ON);
   graphics.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_BILINEAR);
  }
  public void fill(int x0,int y0,int x1,int y1,int color) {
   check(x0>=0&&y0>=0&&x1<=image.getWidth()/DISPLAY_SCALE&&y1<=image.getHeight()/DISPLAY_SCALE&&x1>=x0&&y1>=y0,"Drawing stays in the GUI: "+x0+","+y0+","+x1+","+y1);
   graphics.setColor(new Color(color,true));graphics.fillRect(x0,y0,x1-x0,y1-y0);calls++;
  }
  public int width(String value) { return graphics.getFontMetrics().stringWidth(value); }
  public String translate(String key) { return labels.getProperty(key,key); }
  public boolean textures(){return true;}
  public void image(String path,int x,int y,int w,int h,int u,int v,int rw,int rh,int tw,int th,int color){
   check(x>=0&&y>=0&&x+w<=image.getWidth()/DISPLAY_SCALE&&y+h<=image.getHeight()/DISPLAY_SCALE,"Texture bounds: "+path);
   try {
    BufferedImage atlas=textures.get(path);
    if(atlas==null){atlas=ImageIO.read(new File(System.getProperty("cubeon.ui.assets"),path));textures.put(path,atlas);}
    check(atlas.getWidth()==tw&&atlas.getHeight()==th,"Native UV dimensions match the packaged atlas: "+path);
    check(u>=0&&v>=0&&u+rw<=tw&&v+rh<=th,"UV bounds: "+path);
    var source=atlas.getSubimage(u,v,rw,rh);
    var op=new RescaleOp(new float[]{((color>>>16)&255)/255f,((color>>>8)&255)/255f,(color&255)/255f,(color>>>24)/255f},new float[4],null);
    var tinted=op.filter(source,null);
    graphics.drawImage(tinted,x,y,x+w,y+h,0,0,rw,rh,null);quads++;
   }catch(IOException error){throw new RuntimeException(error);}
  }
  public void text(String value,int centerX,int y,int color) {
   check(centerX-width(value)/2>=0&&centerX+(width(value)+1)/2<=image.getWidth()/DISPLAY_SCALE&&y>=0&&y+9<=image.getHeight()/DISPLAY_SCALE,"Text remains readable inside the GUI: "+value);
   graphics.setColor(new Color(color,true));graphics.drawString(value,centerX-width(value)/2,y+9);
  }
  void save(String name)throws Exception { ImageIO.write(image,"png",new File(name)); }
 }
 static void bounds(HudMenu menu,int w,int h) {
  for(int id=0;id<HudMenu.ACTION_COUNT;id++) {
   var r=menu.control(id);if(r==null)continue;
   check(r.w()>0&&r.h()>0&&r.x()>=0&&r.y()>=0&&r.x()+r.w()<=w&&r.y()+r.h()<=h,"Control fits at GUI scale: "+id);
   check(menu.hit(r.x()+r.w()/2,r.y()+r.h()/2)==id,"Distinct hit target: "+id);
   for(int j=0;j<id;j++) {
    var q=menu.control(j);if(q==null)continue;
    check(r.x()+r.w()<=q.x()||q.x()+q.w()<=r.x()||r.y()+r.h()<=q.y()||q.y()+q.h()<=r.y(),"Controls never overlap: "+id+","+j);
   }
  }
 }
 public static void main(String[] args)throws Exception {
  Font font=Font.createFont(Font.TRUETYPE_FONT,new File(args[1])).deriveFont(10f);
  Properties labels=new Properties();try(var reader=new InputStreamReader(new FileInputStream(args[0]),StandardCharsets.UTF_8)){labels.load(reader);}
  check(HudMenu.featureCount()==19&&HudMenu.overlayIndex(49)==-1,"Removed features leave no stale overlay actions");
  check(HudMenu.nextBlurIntensity(1)==1.25f && HudMenu.nextBlurIntensity(2)==.25f,"Blur intensity advances and wraps predictably");
  HudMenu.Settings settings=new HudMenu.Settings(){
   public boolean visible(int overlay){return overlay%2==0;}public float scale(int overlay){return new float[]{1,.75f,1.5f,1.25f,2}[overlay%5];}
   public boolean health(){return false;}public boolean animations(){return true;}public boolean wingDepth(){return true;}public boolean otherCosmetics(){return false;}public boolean cameraBlur(){return false;}public float blurIntensity(){return 1f;}
  };
  for(int[] size:new int[][]{{320,240},{520,304},{640,360},{960,540}}) {
   int w=size[0],h=size[1];HudMenu menu=new HudMenu();menu.layout(w,h);
   Canvas canvas=new Canvas(w,h,font,labels);Thread.sleep(180);menu.render(canvas,w,h,0,0,settings);
   boolean[] visited=new boolean[HudMenu.featureCount()];
   for(int page=0;page<menu.pages();page++) {
    menu.render(canvas,w,h,0,0,settings);bounds(menu,w,h);
    for(int i=0;i<visited.length;i++)if(menu.control(HudMenu.DETAIL+i)!=null)visited[i]=true;
    menu.scroll(1);menu.layout(w,h);
   }
   for(boolean seen:visited)check(seen,"Every feature is reachable through pagination");
   for(int i=0;i<HudMenu.featureCount();i++) {
    menu.activate(HudMenu.DETAIL+i);menu.layout(w,h);bounds(menu,w,h);
    menu.render(canvas,w,h,0,0,settings);
    check(menu.control(HudMenu.BACK)!=null,"Details always have Back");
    if(i<13)check(menu.control(HudMenu.toggleAction(i)+1)!=null&&menu.control(HudMenu.toggleAction(i)+2)!=null,"Every overlay has move and independent size controls");
    menu.activate(HudMenu.BACK);menu.layout(w,h);
   }
   menu.activate(HudMenu.CATEGORY+4);menu.layout(w,h);
   check(menu.control(HudMenu.SPRINT)!=null&&menu.control(0)==null,"Movement filters to auto sprint");
   menu.activate(HudMenu.CATEGORY);menu.focusSearchShortcut();menu.type('/');check(menu.query().isEmpty(),"Search shortcut does not add a slash to the query");
   for(int cp:"Potion".codePoints().toArray())menu.type(cp);
   menu.layout(w,h);check(menu.control(HudMenu.toggleAction(7))!=null&&menu.control(0)==null,"Search matches translated feature titles");
   check(menu.backspace()&&menu.query().equals("Potio"),"Search deletes a character");
   menu.type(0x1f332);menu.backspace();check(menu.query().equals("Potio"),"Search deletion preserves Unicode boundaries");
   for(int n=0;n<5;n++)menu.backspace();menu.back();menu.layout(w,h);
   check(menu.hit(0,0)==HudMenu.NONE,"Backdrop clicks never change preferences");
   menu.step(1);int focused=menu.selection();
   check(menu.control(focused)!=null,"Keyboard skips hidden controls");
   menu.render(canvas,w,h,0,0,settings);check(menu.selection()==focused,"Stationary pointer preserves keyboard focus");
   var target=menu.control(HudMenu.SEARCH);menu.render(canvas,w,h,target.x()+1,target.y()+1,settings);
   check(menu.selection()==HudMenu.SEARCH,"Pointer restores hover selection");
   Canvas preview=new Canvas(w,h,font,labels);menu.render(preview,w,h,0,0,settings);
   check(preview.calls<2000&&preview.quads<600,"Catalogue drawing stays bounded per frame");
   preview.save("/tmp/cubeon-green-hud-"+h+".png");
   Canvas editor=new Canvas(w,h,font,labels);editor.fill(w/2-26,h/2-8,w/2+26,h/2+8,0xFF131711);
   editor.text("120 FPS",w/2,h/2-4,ClientUi.TEXT);
   HudEditorChrome.render(editor,w,h,"Move FPS",0,0,w/2-26,h/2-8,52,16,true);
   editor.save("/tmp/cubeon-green-editor-"+h+".png");
   int panel=Math.min(340,w-24),left=(w-panel)/2;
   check(HudEditorChrome.done(w,h,left+panel-44,h-28),"Done is reachable by pointer");
   check(!HudEditorChrome.done(w,h,left+12,h-28),"Help label cannot close the editor");
   HudEditorChrome.render(editor,w,h,"Move FPS",0,0,0,0,52,16,false);
   HudEditorChrome.render(editor,w,h,"Move FPS",0,0,w-52,h-16,52,16,false);
   menu.activate(HudMenu.CATEGORY);menu.layout(w,h);menu.scroll(-100);menu.layout(w,h);
   var previous=menu.control(0);menu.layout(w+80,h);
   check(menu.control(0)!=null,"Resize preserves reachable first feature");
   check(menu.control(0).x()!=previous.x()||menu.control(0).w()!=previous.w(),"Resize recomputes card bounds");
   Canvas wheelCanvas=new Canvas(w,h,font,labels);var wheel=new EmoteWheel();Thread.sleep(160);
   wheel.render(wheelCanvas,w,h,w/2,h/2-60,true,true);wheelCanvas.save("/tmp/cubeon-green-wheel-"+h+".png");
   check(wheelCanvas.calls<100&&wheelCanvas.quads<100,"Smooth wheel uses a bounded number of textured quads");
   for(int count=1;count<=8;count++){
    var names=java.util.Arrays.copyOf(EmoteState.NAMES,count);
    var variant=new EmoteWheel(names);
    Canvas variantCanvas=new Canvas(w,h,font,labels);variant.render(variantCanvas,w,h,0,0,true,true);
   }
  }
  System.out.println("Custom font, feature catalogue, search, categories, all details, minimum GUI scale, text/draw bounds, keyboard/pointer focus, resize, drag toolbar/edge frames and wheel previews passed.");
 }
}
''', encoding="utf-8")
            shared = ROOT / "mod/src/main/java/com/cubeon/client"
            sources = [harness, shared / "Json.java", shared / "Bridge.java", shared / "hud/HudFeatures.java",
                       *sorted((shared / "ui").glob("*.java")), *sorted((shared / "emotes").glob("*.java"))]
            result = subprocess.run(["javac", "--release", "17", "-d", str(folder), *map(str, sources)], capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run(["java", "-Djava.awt.headless=true",
                                     "-Dcubeon.ui.assets=" + str(ROOT / "mod/src/main/resources/assets/cubeon-client"),
                                     "-cp", str(folder), "UiTest", str(folder / "labels.properties"),
                                     str(ROOT / "mod/src/main/resources/assets/cubeon-client/font/ui.ttf")], capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout.strip())


if __name__ == "__main__":
    unittest.main()
