"""Production Java wing poses rasterized as actual textured triangles, all four corners."""
from pathlib import Path
import math, struct, subprocess, tempfile, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from cubeon import cosmetics, skins
from cubeon.appearance import CharacterModel
OUT=ROOT/'archive/ui-captures/layered-wings'
COUNT=24
HARNESS=r'''
import com.cubeon.client.cosmetics.*;
import java.nio.file.*;import java.io.*;
public class FeatherCapture {
 public static void main(String[] args) throws Exception {
  var catalog=CosmeticCatalog.Catalog.parse(Files.readString(Path.of(args[0])));
  var item=catalog.get(args[2]);
  if(args.length>3) item=(CosmeticCatalog.Item)item.getClass().getMethod("forWingDepth",boolean.class).invoke(item,false);
  var quads=CosmeticGeometry.quads(item,0);
  var tracker=new CosmeticAnimation.Tracker();var posed=new CosmeticAnimation.PosedQuad();
  try(var out=new DataOutputStream(new BufferedOutputStream(Files.newOutputStream(Path.of(args[1]))))){
   out.writeInt(quads.size());
   for(var q:quads)for(int v=0;v<4;v++){out.writeFloat(q.u[v]);out.writeFloat(q.v[v]);}
   for(int n=-1;n<24;n++){
    float elapsed=n/7f;
    var frame=n<0?null:tracker.sample(100+elapsed,0,false,false,elapsed<WingAction.DURATION?elapsed:-1).forItem(item);
    for(var q:quads){posed.set(q,frame);
     for(int v=0;v<4;v++){out.writeFloat(posed.x[v]);out.writeFloat(posed.y[v]);out.writeFloat(posed.z[v]);}
     out.writeFloat(posed.normalX);out.writeFloat(posed.normalY);out.writeFloat(posed.normalZ);
    }
   }
  }
 }
}
'''
def font(size):return ImageFont.truetype(str(ROOT/'web/assets/fonts/Inter.ttf'),size)
def transform(points,yaw=155,pitch=6,normal=False):
 p=points.copy();p[...,1]=(-p[...,1] if normal else 8-p[...,1]);p[...,2]=-p[...,2]
 y,x=math.radians(yaw),math.radians(pitch)
 a=p[...,0]*math.cos(y)+p[...,2]*math.sin(y);z=-p[...,0]*math.sin(y)+p[...,2]*math.cos(y)
 return np.stack((a,p[...,1]*math.cos(x)-z*math.sin(x),p[...,1]*math.sin(x)+z*math.cos(x)),axis=-1)
def render(rows,uv,texture,body,scale,yaw=155,pitch=6):
 width,height=460,400;canvas=np.zeros((height,width,4),dtype=np.uint8);depth=np.full((height,width),-1e6,dtype=np.float32)
 for vertices,normals,tiles,coords in ((rows[:,:12].reshape(-1,4,3),rows[:,12:],texture,uv),body):
  v=transform(vertices,yaw=yaw,pitch=pitch);norm=transform(normals,yaw=yaw,pitch=pitch,normal=True)
  for i in range(len(v)):
   if norm[i,2]<=.001:continue
   tex=tiles[i] if isinstance(tiles,list) else tiles
   points=np.stack((width/2+v[i,:,0]*scale,height/2-v[i,:,1]*scale),axis=-1)
   lighting=.72+.28*max(0,norm[i,1]*.5+norm[i,2]*.8)
   for indices in ((0,1,2),(0,2,3)):
    ids=list(indices);tri=points[ids];z=v[i,ids,2];texcoords=coords[i,ids]
    left=max(0,math.floor(tri[:,0].min()));right=min(width,math.ceil(tri[:,0].max()))
    top=max(0,math.floor(tri[:,1].min()));bottom=min(height,math.ceil(tri[:,1].max()))
    if left>=right or top>=bottom:continue
    a,b,c=tri;det=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
    if abs(det)<1e-6:continue
    xx,yy=np.meshgrid(np.arange(left,right)+.5,np.arange(top,bottom)+.5)
    wa=((b[1]-c[1])*(xx-c[0])+(c[0]-b[0])*(yy-c[1]))/det
    wb=((c[1]-a[1])*(xx-c[0])+(a[0]-c[0])*(yy-c[1]))/det;wc=1-wa-wb
    inside=(wa>=-1e-5)&(wb>=-1e-5)&(wc>=-1e-5)
    zz=wa*z[0]+wb*z[1]+wc*z[2];inside&=zz>depth[top:bottom,left:right]
    tx=np.clip((wa*texcoords[0,0]+wb*texcoords[1,0]+wc*texcoords[2,0]).astype(int),0,tex.shape[1]-1)
    ty=np.clip((wa*texcoords[0,1]+wb*texcoords[1,1]+wc*texcoords[2,1]).astype(int),0,tex.shape[0]-1)
    colours=tex[ty,tx].copy();inside&=colours[:,:,3]>0
    colours[:,:,:3]=(colours[:,:,:3]*lighting).astype(np.uint8)
    canvas[top:bottom,left:right][inside]=colours[inside];depth[top:bottom,left:right][inside]=zz[inside]
 return Image.fromarray(canvas)
def main():
 OUT.mkdir(parents=True,exist_ok=True)
 base=CharacterModel(skins.default_base_skin());points=[];normals=[];tiles=[];uvs=[]
 for face in base.faces:
  a,b,c=face.vertices;p=np.array((a,b,tuple(b[j]+c[j]-a[j] for j in range(3)),c),dtype=np.float32)
  p[:,1]=24-p[:,1];p[:,2]=-p[:,2];points.append(p);normals.append((face.normal[0],-face.normal[1],-face.normal[2]))
  tile=np.array(face.texture);tiles.append(tile);h,w=tile.shape[:2];uvs.append(((.5,.5),(w-.5,.5),(w-.5,h-.5),(.5,h-.5)))
 body=(np.array(points),np.array(normals,dtype=np.float32),tiles,np.array(uvs))
 board=Image.new('RGB',(1700,1000),'#111117');d=ImageDraw.Draw(board);d.text((24,20),'UNCHANGED SMALL + LAYERED GIANT WINGS',font=font(30),fill='#faf1de')
 for row,size in enumerate(('_small','')):
  for col,theme in enumerate(('ember','frost','leaf','void','aurora')):
   item=cosmetics.get('back_'+theme+'_wings'+size);model=CharacterModel(skins.default_base_skin(),cosmetics_faces=cosmetics.preview_faces(item))
   pic=model.render(155,6,size=(340,400));board.paste(pic,(col*340,70+row*460),pic)
   d.text((col*340+20,450+row*460),item['name'],font=font(17),fill='#e5d5bd')
 board.save(OUT/'small-and-giant.png')
 source=ROOT/'mod/src/main/java/com/cubeon/client'
 with tempfile.TemporaryDirectory(dir=OUT) as temp:
  folder=Path(temp);harness=folder/'FeatherCapture.java';harness.write_text(HARNESS)
  files=[source/'Json.java']+[source/'cosmetics'/(n+'.java') for n in ('CosmeticCatalog','CosmeticGeometry','CosmeticAnimation','WingAction')]
  subprocess.run(['javac','--release','17','-d',str(folder),*map(str,files),str(harness)],check=True)
  for size,scale in (('',4.7),('_small',9)):
   item=cosmetics.get('back_ember_wings'+size);binary=folder/'poses.bin'
   subprocess.run(['java','-cp',str(folder),'FeatherCapture',str(ROOT/'assets/cosmetics/catalog.json'),str(binary),item['id']],check=True)
   data=binary.read_bytes();count=struct.unpack_from('>I',data)[0]
   uv=np.frombuffer(data,dtype='>f4',count=count*8,offset=4).reshape(count,4,2).astype(np.float32)
   texture=np.array(cosmetics.texture(item));uv[:,:,0]*=texture.shape[1];uv[:,:,1]*=texture.shape[0]
   poses=np.frombuffer(data,dtype='>f4',offset=4+count*32).reshape(COUNT+1,count,15).astype(np.float32)
   if not size:
    flat_binary=folder/'flat.bin'
    subprocess.run(['java','-cp',str(folder),'FeatherCapture',str(ROOT/'assets/cosmetics/catalog.json'),str(flat_binary),item['id'],'flat'],check=True)
    flat_data=flat_binary.read_bytes();flat_count=struct.unpack_from('>I',flat_data)[0]
    flat_uv=np.frombuffer(flat_data,dtype='>f4',count=flat_count*8,offset=4).reshape(flat_count,4,2).astype(np.float32)
    flat_texture=np.array(cosmetics.texture(item['flat']));flat_uv[:,:,0]*=flat_texture.shape[1];flat_uv[:,:,1]*=flat_texture.shape[0]
    flat_pose=np.frombuffer(flat_data,dtype='>f4',offset=4+flat_count*32).reshape(COUNT+1,flat_count,15).astype(np.float32)[0]
    settings_compare=Image.new('RGB',(1380,900),'#111117');draw=ImageDraw.Draw(settings_compare)
    for col,yaw in enumerate((180,135,90)):
     for row,(pose,coords,tex,label) in enumerate(((poses[0],uv,texture,'3D WINGS ON / CURVED FEATHERS'),(flat_pose,flat_uv,flat_texture,'3D WINGS OFF / LIGHTWEIGHT FLAT MESH'))):
      pic=render(pose,coords,tex,body,scale,yaw=yaw);settings_compare.paste(pic,(col*460,row*450+35),pic)
      draw.text((col*460+16,row*450+10),label,font=font(16),fill='#faf1de')
    settings_compare.save(OUT/'3d-setting.png')
    # Compare against the actual committed renderer/catalog, not a drawn mockup.
    baseline=folder/'previous';baseline.mkdir()
    baseline_sources=[]
    for relative in ['Json.java']+['cosmetics/'+n+'.java' for n in ('CosmeticCatalog','CosmeticGeometry','CosmeticAnimation','WingAction')]:
     target=baseline/Path(relative).name
     target.write_bytes(subprocess.check_output(['git','show','HEAD:mod/src/main/java/com/cubeon/client/'+relative],cwd=ROOT))
     baseline_sources.append(str(target))
    old_catalog=baseline/'catalog.json';old_catalog.write_bytes(subprocess.check_output(['git','show','HEAD:assets/cosmetics/catalog.json'],cwd=ROOT))
    old_texture=baseline/'wing.png';old_texture.write_bytes(subprocess.check_output(['git','show','HEAD:assets/cosmetics/back_ember_wings.png'],cwd=ROOT))
    subprocess.run(['javac','--release','17','-d',str(baseline),*baseline_sources,str(harness)],check=True)
    old_binary=baseline/'poses.bin'
    subprocess.run(['java','-cp',str(baseline),'FeatherCapture',str(old_catalog),str(old_binary),item['id']],check=True)
    old_data=old_binary.read_bytes();old_count=struct.unpack_from('>I',old_data)[0]
    old_uv=np.frombuffer(old_data,dtype='>f4',count=old_count*8,offset=4).reshape(old_count,4,2).astype(np.float32)
    old_tex=np.array(Image.open(old_texture));old_uv[:,:,0]*=old_tex.shape[1];old_uv[:,:,1]*=old_tex.shape[0]
    old_pose=np.frombuffer(old_data,dtype='>f4',offset=4+old_count*32).reshape(COUNT+1,old_count,15).astype(np.float32)[0]
    compare=Image.new('RGB',(1380,900),'#111117');draw=ImageDraw.Draw(compare)
    for col,yaw in enumerate((180,135,90)):
     for row,(pose,coords,tex,label) in enumerate(((old_pose,old_uv,old_tex,'BEFORE / JOINED SHEET'),(poses[0],uv,texture,'AFTER / SEPARATE CURVED FEATHERS'))):
      pic=render(pose,coords,tex,body,scale,yaw=yaw);compare.paste(pic,(col*460,row*450+35),pic)
      draw.text((col*460+16,row*450+10),label,font=font(17),fill='#faf1de')
    compare.save(OUT/'before-after.png')
   rest=render(poses[0],uv,texture,body,scale);images=[]
   for n in range(COUNT):
    pic=render(poses[n+1],uv,texture,body,scale);canvas=Image.new('RGB',(920,450),'#111117')
    canvas.paste(rest,(0,35),rest);canvas.paste(pic,(460,35),pic);d=ImageDraw.Draw(canvas)
    d.text((20,12),'MOTION OFF',font=font(20),fill='#a496a3');d.text((480,12),'SMALL / GENTLE MOTION' if size else 'N / SEPARATE FEATHER MOTION',font=font(20),fill='#f4d2a3')
    d.text((480,420),f'{n/7:.2f}s',font=font(17),fill='#a496a3');images.append(canvas)
   name='small' if size else 'giant';durations=[143]*COUNT;durations[0]=300;durations[-1]=1000
   images[0].save(OUT/(name+'-feathers.gif'),save_all=True,append_images=images[1:],duration=durations,loop=0,disposal=2,optimize=False)
   strip=Image.new('RGB',(1840,900),'#111117')
   for slot,n in enumerate((0,5,10,20)):strip.paste(images[n],((slot%2)*920,(slot//2)*450))
   strip.save(OUT/(name+'-feather-frames.png'));print(name,'production triangles captured',flush=True)
if __name__=='__main__':main()
