"""Exercise production wheel geometry and render an optional Java2D preview."""
from pathlib import Path
import json
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("javac") and shutil.which("java"), "JDK required")
class WheelTests(unittest.TestCase):
    def test_picker_geometry(self):
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            labels = json.loads((ROOT / "mod/src/main/resources/assets/cubeon-client/lang/en_us.json").read_text())
            (temp / "labels.properties").write_text("\n".join(f"{key}={value}" for key, value in labels.items()))
            source = temp / "WheelTest.java"
            source.write_text(r'''
import com.cubeon.client.emotes.*;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.Properties;
import javax.imageio.ImageIO;
public class WheelTest {
 static void check(boolean yes,String why){if(!yes)throw new AssertionError(why);}
 static class Canvas implements EmoteWheel.Canvas {
  final BufferedImage image; final Graphics2D graphics; final Properties labels; int calls;
  Canvas(int width,int height,Properties labels){
   this.labels=labels; image=new BufferedImage(width,height,BufferedImage.TYPE_INT_ARGB);
   graphics=image.createGraphics();graphics.setColor(new Color(0x0C131E));graphics.fillRect(0,0,width,height);
   graphics.setFont(new Font(Font.MONOSPACED,Font.PLAIN,9));
  }
  public String translate(String key){return labels.getProperty(key,key);}
  public void fill(int x0,int y0,int x1,int y1,int color){
   check(x0>=0&&y0>=0&&x1<=image.getWidth()&&y1<=image.getHeight(),"Wheel stays within window");
   graphics.setColor(new Color(color,true));graphics.fillRect(x0,y0,x1-x0,y1-y0);calls++;
  }
  public void text(String text,int centerX,int y,int color){
   graphics.setColor(new Color(color,true));
   graphics.drawString(text,centerX-graphics.getFontMetrics().stringWidth(text)/2,y+8);
  }
 }
 public static void main(String[] args)throws Exception{
  var labels=new Properties();try(var reader=new InputStreamReader(new FileInputStream(args[0]),StandardCharsets.UTF_8)){labels.load(reader);}
  for(int[] size:new int[][]{{320,240},{640,360},{960,540}}){
   int width=size[0],height=size[1],cx=width/2,cy=height/2-5;
   int radius=Math.min(116,Math.min((width-24)/2,(height-92)/2));
   var wheel=new EmoteWheel();wheel.layout(width,height);
   check(wheel.hit(cx,cy)==EmoteWheel.STOP,"Center stops; it never picks an emote");
   check(wheel.hit(0,0)==EmoteWheel.NONE,"Outside cannot accidentally start an emote");
   check(wheel.hit(cx+radius*.385,cy)==EmoteWheel.NONE,"Inner gutter is a dead zone");
   check(wheel.hit(cx,cy+radius+24)==EmoteWheel.TOGGLE,"Display toggle remains reachable");
   for(int i=0;i<6;i++){
    double angle=i*Math.PI/3-Math.PI/2;
    check(wheel.hit(cx+Math.cos(angle)*radius*.72,cy+Math.sin(angle)*radius*.72)==i,"All six wedge centers match labels");
   }
   Canvas canvas=new Canvas(width,height,labels);
   Thread.sleep(150);wheel.render(canvas,width,height,cx,cy-radius*3/4,true,true);
   wheel.focus(5);wheel.step(1);check(wheel.selection()==0,"Keyboard wraps clockwise");
   wheel.step(-1);check(wheel.selection()==5,"Keyboard wraps counterclockwise");
   wheel.render(canvas,width,height,cx,cy-radius*3/4,true,true);
   check(wheel.selection()==5,"Stationary mouse cannot undo keyboard selection");
   wheel.render(canvas,width,height,cx+1,cy-radius*3/4,true,true);
   check(wheel.selection()==0,"Moving mouse resumes pointer selection");
   Canvas preview=new Canvas(width,height,labels);Thread.sleep(100);
   wheel.render(preview,width,height,cx+1,cy-radius*3/4,true,true);
   check(preview.calls<2200,"Cached wheel rendering remains bounded");
   ImageIO.write(preview.image,"png",new File("/tmp/cubeon-emote-wheel-"+height+".png"));
   Canvas disabled=new Canvas(width,height,labels);wheel.render(disabled,width,height,cx,cy,false,false);
   wheel.layout(width+80,height);check(wheel.hit((width+80)/2,cy)==EmoteWheel.STOP,"Resize updates center even when radius is unchanged");
  }
  System.out.println("Six wedges, dead zones, stop/toggle, keyboard/mouse switching, resize, small windows and bounded drawing passed.");
 }
}
''')
            shared = ROOT / "mod/src/main/java/com/cubeon/client"
            paths = [source, shared / "Json.java", shared / "Bridge.java", *sorted((shared / "emotes").glob("*.java"))]
            result = subprocess.run(["javac", "--release", "17", "-d", str(temp), *map(str, paths)], capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run(["java", "-Djava.awt.headless=true", "-cp", str(temp), "WheelTest", str(temp / "labels.properties")], capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout.strip())


if __name__ == "__main__":
    unittest.main()
