"""Count loaded mod sources without inflating totals with bundled modules or built-ins."""
from pathlib import Path
import subprocess
import sys
import tempfile
from test_mod_bridge import find_jdk

ROOT = Path(__file__).resolve().parents[1]
JAVA = r'''
import com.cubeon.client.ModFileCount;
import java.nio.file.Path;
import java.util.*;
public class ModCountTest {
 static ModFileCount.Source source(String type,String kind,String... paths){
  return new ModFileCount.Source(type,kind,Arrays.stream(paths).map(Path::of).toList());
 }
 static void check(boolean v,String m){if(!v)throw new AssertionError(m);}
 public static void main(String[] args){
  var sources=new ArrayList<ModFileCount.Source>();
  for(int i=0;i<15;i++)sources.add(source("fabric","PATH","mods/mod-"+i+".jar"));
  for(int i=0;i<113;i++)sources.add(source("fabric","NESTED","mods/module-"+i+".jar"));
  sources.add(source("builtin","PATH","libraries/loader.jar"));
  sources.add(source("builtin","UNKNOWN"));
  check(ModFileCount.count(sources)==15,"15 files with 113 bundled components display as 15");
  sources.add(source("fabric","PATH","mods/nested/../mod-1.jar"));
  check(ModFileCount.count(sources)==15,"multiple entries in the same root jar counted once");
  sources.add(source("fabric","PATH","build/classes","build/resources"));
  sources.add(source("fabric","PATH","build/resources","build/classes"));
  check(ModFileCount.count(sources)==16,"development source groups count once regardless of order");
  sources.add(source("fabric","UNKNOWN","mods/unknown.jar"));
  sources.add(source("fabric","PATH"));
  check(ModFileCount.count(sources)==16,"unknown and empty sources do not invent installed files");
  check(ModFileCount.count(List.of())==0,"empty registry safe");
  System.out.println("Top-level mod count passed");
 }
}
'''
def main():
    javac, java = find_jdk()
    if not javac: print('SKIP: JDK required'); return 0
    with tempfile.TemporaryDirectory() as temp:
        path=Path(temp); (path/'ModCountTest.java').write_text(JAVA)
        subprocess.run([javac,'--release','17','-d',temp,str(ROOT/'mod/src/main/java/com/cubeon/client/ModFileCount.java'),str(path/'ModCountTest.java')],check=True)
        subprocess.run([java,'-cp',temp,'ModCountTest'],check=True)
    return 0
if __name__=='__main__':sys.exit(main())
