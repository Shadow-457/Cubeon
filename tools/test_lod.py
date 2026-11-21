"""Run the production Minecraft-free LOD algorithms and atomic option storage."""
from pathlib import Path
import os
import subprocess
import shutil
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'mod/src/main/java-overlay-lod-26.3/com/cubeon/client/lod'
HARNESS = r'''
import com.cubeon.client.lod.*;
import com.cubeon.client.lod.core.*;
import java.nio.*;
import java.nio.file.*;
import java.util.*;
public class LodTest {
 static int checks;
 static void check(boolean ok, String why) { checks++; if (!ok) throw new AssertionError(why); }
 static Terrain.Material stone = new Terrain.Material(1, 0xffabcdef, 0xf0, 0);
 static Terrain.Chunk chunk(int x, int z, int height) {
  Terrain.Column[] columns = new Terrain.Column[256];
  Arrays.fill(columns, new Terrain.Column(List.of(new Terrain.Span(-64,height,stone))));
  return new Terrain.Chunk(x,z,1,columns);
 }
 public static void main(String[] args) throws Exception {
  Path folder = Path.of(args[0]);
  LodOptions options = new LodOptions(folder.resolve("options.json"));
  check(!options.active().enabled() && options.active().distance()==128,"Safe defaults");
  Files.writeString(folder.resolve("options.json"),"{\"enabled\":true,\"distance\":9000}"); options.load();
  check(options.active().distance()==4096 && options.active().backgroundUpdates(),"Limit plus partial-file defaults");
  var old = options.active();
  Files.delete(folder.resolve("options.json")); Files.createDirectory(folder.resolve("options.json"));
  try { options.commit(LodOptions.DEFAULT); throw new AssertionError("Save must fail"); }
  catch (java.io.IOException expected) { check(options.active().equals(old),"Failed save keeps active settings"); }
  Files.delete(folder.resolve("options.json")); options.commit(LodOptions.DEFAULT); options.load();
  check(options.active().equals(LodOptions.DEFAULT),"Atomic persisted round trip");
  check(Files.list(folder).noneMatch(p->p.getFileName().toString().endsWith(".tmp")),"No stale save temporary files");
  for (int x : new int[]{-30000000,-17,-1,0,1,30000000})
   check(Terrain.x(Terrain.key(x,-x))==x && Terrain.z(Terrain.key(x,-x))==-x,"Signed coordinates round trip");
  var key = new TilePlan.Key(-1,-1,0);
  check(key.parent().x()==-1 && key.blockX()==-16,"Negative quadtree alignment");
  var sparse = List.of(chunk(500,500,70),chunk(501,500,71));
  var selected = TilePlan.select(sparse,0,0,4,4096,LodOptions.Detail.MAXIMUM_FPS);
  check(selected.size()==2 && selected.stream().allMatch(k->k.level()==0),"Sparse trail never fills unknown footprint");
  check(TilePlan.select(sparse,0,0,4,100000,LodOptions.Detail.MEDIUM).equals(
   TilePlan.select(sparse,0,0,4,4096,LodOptions.Detail.MEDIUM)),"Planning clamps range");
  var full = new ArrayList<Terrain.Chunk>();
  for(int z=0;z<16;z++)for(int x=0;x<16;x++)full.add(chunk(512+x,512+z,80));
  var finest=TilePlan.select(full,0,0,4,4096,LodOptions.Detail.FULL);
  var medium=TilePlan.select(full,0,0,4,4096,LodOptions.Detail.MEDIUM);
  var fast=TilePlan.select(full,0,0,4,4096,LodOptions.Detail.MAXIMUM_FPS);
  check(finest.size()>=medium.size() && medium.size()>=fast.size(),"Coarser distant detail reduces tiles");
  var seam = TilePlan.select(List.of(chunk(5,0,64)),8,8,4,128,LodOptions.Detail.MAXIMUM_FPS);
  check(seam.get(0).level()==0,"Finest transition cells");
  var terrain=chunk(0,0,10); var mesh=TileMesh.build(new TilePlan.Key(0,0,0),TilePlan.grid(new TilePlan.Key(0,0,0),List.of(terrain)));
  double area=0;
  for(var f:mesh.faces()) area+=f.width()*f.height();
  check(area==2*256+4*16*74,"Merged mesh has exact exposed solid surface area");
  try { TileMesh.build(mesh.key(),TilePlan.grid(mesh.key(),List.of(terrain)),1);throw new AssertionError("Face budget"); }
  catch(TileMesh.BudgetExceeded expected){check(true,"Face construction is bounded");}
  var a=PackedMesh.pack(mesh,false,new TextureCatalog(),1,128L<<20);
  var b=PackedMesh.pack(mesh,true,new TextureCatalog(),1,128L<<20);
  check(a.solidCount()==b.solidCount()*6 && a.solid().length==b.solid().length*6,"CPU/GPU shared face records");
  ByteBuffer cpu=ByteBuffer.wrap(a.solid()).order(ByteOrder.nativeOrder());
  ByteBuffer gpu=ByteBuffer.wrap(b.solid()).order(ByteOrder.nativeOrder());
  int[] corners={0,1,2,0,2,3};
  for(int f=0;f<mesh.faces().size();f++)for(int v=0;v<6;v++) {
   float[] p=TileMesh.corner(mesh.faces().get(f),corners[v]);
   int at=(f*6+v)*PackedMesh.STRIDE;
   check(cpu.getFloat(at+8)==p[0] && cpu.getFloat(at+12)==p[1] && cpu.getFloat(at+16)==p[2],"CPU vertex position parity");
  }
  var fluid=new Terrain.Material(2,0xafffffff,0xf0,Terrain.FLUID);
  Terrain.Column[] water=new Terrain.Column[256]; Arrays.fill(water,new Terrain.Column(List.of(new Terrain.Span(0,2,fluid))));
  var waterMesh=TileMesh.build(mesh.key(),water);
  check(waterMesh.faces().stream().allMatch(f->(f.material().flags()&Terrain.FLUID)!=0),"Fluids retain separate pass material");
  var leaves=new Terrain.Material(3,0xff00ff00,0xf0,Terrain.CUTOUT);
  Terrain.Column[] planted=new Terrain.Column[256];
  Arrays.fill(planted,new Terrain.Column(List.of(new Terrain.Span(0,1,stone),new Terrain.Span(1,2,leaves))));
  var plantedMesh=TileMesh.build(mesh.key(),planted);
  check(plantedMesh.faces().stream().filter(f->f.direction()==3 && f.y()==1 && f.material().equals(stone))
    .mapToDouble(f->f.width()*f.height()).sum()==256,"Ground beneath transparent plants remains covered");
  Arrays.fill(planted,new Terrain.Column(List.of(new Terrain.Span(0,1,stone),new Terrain.Span(1,2,fluid))));
  check(TileMesh.build(mesh.key(),planted).faces().stream().filter(f->f.direction()==3 && f.y()==1 && f.material().equals(stone))
    .mapToDouble(f->f.width()*f.height()).sum()==256,"Ground remains visible through water");
  Arrays.fill(planted,new Terrain.Column(List.of(new Terrain.Span(0,1,stone),new Terrain.Span(1,2,stone))));
  check(TileMesh.build(mesh.key(),planted).faces().stream().noneMatch(f->f.y()==1 && (f.direction()==2 || f.direction()==3)),
    "Opaque vertical boundaries stay hidden");
  var cache=new DiskCache(folder.resolve("cache"),"world/dimension/material");
  cache.write(chunk(-5,9,84)); var restored=cache.read(Terrain.key(-5,9));
  check(restored.x==-5 && restored.z==9 && restored.at(0,0).spans().get(0).max()==84,"Compressed cache round trip");
  var other=new DiskCache(folder.resolve("cache"),"other/dimension/material"); other.write(chunk(2,2,7));
  cache.clear();check(other.read(Terrain.key(2,2))!=null,"Clear cache preserves other worlds");
  cache.write(chunk(-5,9,84));
  Files.write(folder.resolve("cache/world/dimension/material/-5_9.clod"),new byte[]{1,2,3});
  try {cache.read(Terrain.key(-5,9));throw new AssertionError("Corruption must fail");}
  catch(java.io.IOException expected){check(!cache.keys().contains(Terrain.key(-5,9)),"Damaged cache is evicted");}
  check(cache.bytes()<=LodOptions.DISK_LIMIT,"Disk quota maintained");

  // Fill the bounded owner with farther summaries: it must keep nearby coverage.
  var worker=new TerrainWorker(1,folder.resolve("worker-cache"),new CacheIdentity(),new TextureCatalog(),false);
  worker.request(new TerrainWorker.Request(8,8,2,LodOptions.DEFAULT,true,0));
  var done=new java.util.concurrent.CompletableFuture<Void>();
  worker.submit(()->{
   try {
    var layers=new ArrayList<Terrain.Span>();for(int i=0;i<512;i++)layers.add(new Terrain.Span(i,i+1,stone));
    var columns=new Terrain.Column[256];Arrays.fill(columns,new Terrain.Column(layers));
    for(int x:new int[]{0,1,2,100,101,102,103})worker.accept(new Terrain.Chunk(x,0,1,columns));
    var field=TerrainWorker.class.getDeclaredField("chunks");field.setAccessible(true);
    var retained=(Map<?,?>)field.get(worker);
    check(retained.containsKey(Terrain.key(0,0)) && retained.containsKey(Terrain.key(1,0)),"Far cache loading cannot evict nearest terrain");
    var bytes=TerrainWorker.class.getDeclaredField("chunkBytes");bytes.setAccessible(true);
    check(bytes.getLong(worker)<=LodOptions.CPU_LIMIT/4,"Nearest-first eviction retains the summary budget");
    done.complete(null);
   }catch(Throwable ex){done.completeExceptionally(ex);}
  });
  try {
   done.get(10,java.util.concurrent.TimeUnit.SECONDS);
   worker.request(new TerrainWorker.Request(8,8,2,LodOptions.DEFAULT,true,0));
   var stable=new java.util.concurrent.CompletableFuture<Void>();
   worker.submit(()->{
    try {
     var revision=TerrainWorker.class.getDeclaredField("revision");revision.setAccessible(true);
     check(revision.getLong(worker)==7,"Stationary cache loading does not reload evicted farther chunks");
     stable.complete(null);
    }catch(Throwable ex){stable.completeExceptionally(ex);}
   });
   stable.get(10,java.util.concurrent.TimeUnit.SECONDS);
   worker.request(new TerrainWorker.Request(1608,8,2,LodOptions.DEFAULT,true,0));
   var moved=new java.util.concurrent.CompletableFuture<Void>();
   worker.submit(()->{
    try {
     var field=TerrainWorker.class.getDeclaredField("chunks");field.setAccessible(true);
     check(((Map<?,?>)field.get(worker)).containsKey(Terrain.key(100,0)),"Moving the camera resumes loading deferred terrain");
     moved.complete(null);
    }catch(Throwable ex){moved.completeExceptionally(ex);}
   });
   moved.get(10,java.util.concurrent.TimeUnit.SECONDS);
  }finally{worker.close();}
  System.out.println("PASS "+checks+" LOD assertions");
 }
}
'''


def main():
    gson = max((p for p in (Path.home()/'.gradle/caches/modules-2/files-2.1/com.google.code.gson/gson').glob('**/gson-*.jar') if p.stem.split('-')[-1][0].isdigit()), key=lambda p: tuple(int(n) for n in p.stem.split('-')[-1].split('.')))
    with tempfile.TemporaryDirectory(prefix='cubeon-lod-test-') as name:
        root = Path(name)
        stub = root/'com/cubeon/client/lod/TextureCatalog.java'
        stub.parent.mkdir(parents=True)
        stub.write_text('package com.cubeon.client.lod; public class TextureCatalog { public record Uv(float u,float v,float width,float height) {} public Uv get(int s,int f){return new Uv(0,0,1,1);} }')
        stub.with_name('CacheIdentity.java').write_text('package com.cubeon.client.lod; public class CacheIdentity { public String fingerprint() throws java.io.IOException { return "fixture"; } }')
        stub.with_name('LodClient.java').write_text('package com.cubeon.client.lod; public class LodClient { public static final Log LOG=new Log(); public static class Log { public void warn(String message,Throwable error) {} } }')
        (root/'LodTest.java').write_text(HARNESS)
        sources = list((SOURCE/'core').glob('*.java')) + [SOURCE/'LodOptions.java', SOURCE/'PackedMesh.java',SOURCE/'TerrainWorker.java',stub,stub.with_name('CacheIdentity.java'),stub.with_name('LodClient.java'),root/'LodTest.java']
        java = Path(shutil.which('javac')).resolve().parent
        subprocess.run([str(java/'javac'),'-cp',str(gson),'-d',str(root),*map(str,sources)],check=True)
        subprocess.run([str(java/'java'),'-cp',f'{root}:{gson}','LodTest',str(root)],check=True)


if __name__ == '__main__':
    main()
