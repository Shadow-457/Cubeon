package com.cubeon.client.skins;

import com.cubeon.client.ui.ClientUi;
import java.util.Arrays;

/** Small cached textured 3D model, independent of Minecraft's GUI/rendering eras. */
public final class SkinPreview {
    private int width, height, angle, layers;
    private SkinLibrary.Skin skin;
    private SkinLibrary.Skin cape;
    private int[] raster;
    private double[] depth;
    private double sin, cos, scale;
    public void render(ClientUi.Canvas canvas, SkinLibrary.Skin value, int x, int y, int w, int h, int yaw) {
        render(canvas, value, x, y, w, h, yaw, 63);
    }
    public void render(ClientUi.Canvas canvas, SkinLibrary.Skin value, int x, int y, int w, int h, int yaw, int mask) {
        render(canvas, value, null, x, y, w, h, yaw, mask);
    }
    public void render(ClientUi.Canvas canvas, SkinLibrary.Skin value, SkinLibrary.Skin selectedCape,
                       int x, int y, int w, int h, int yaw, int mask) {
        if (value == null || w < 1 || h < 1) return;
        // Only re-rasterize when skin, model, rotation or viewport actually changes.
        if (value != skin || selectedCape != cape || w != width || h != height || yaw != angle || mask != layers) {
            skin = value; cape = selectedCape; width = w; height = h; angle = yaw; layers = mask;
            raster = new int[w * h]; depth = new double[w * h]; Arrays.fill(depth, -Double.MAX_VALUE);
            sin = Math.sin(Math.toRadians(yaw)); cos = Math.cos(Math.toRadians(yaw));
            scale = Math.min(w / 23.0, h / 37.0);
            parts(false); parts(true);
            if(cape != null && !cape.hidden() && (layers & 64) != 0)
                box(-5,8,-3.5,10,16,1,0,0,0,cape);
        }
        for (int row = 0; row < height; row++) {
            int from = 0;
            while (from < width) {
                int color = raster[row * width + from], end = from + 1;
                while (end < width && raster[row * width + end] == color) end++;
                if ((color >>> 24) != 0) canvas.fill(x + from, y + row, x + end, y + row + 1, color);
                from = end;
            }
        }
    }
    public int[] pixels() { return raster == null ? new int[0] : raster.clone(); }
    private void parts(boolean outer) {
        double pad = outer ? .22 : 0;
        int arm = skin.slim() ? 3 : 4;
        if (!outer || (layers & 1) != 0) box(-4,24,-4,8,8,8,outer?32:0,0,outer?.45:0);
        if (!outer || (layers & 2) != 0) box(-4,12,-2,8,12,4,16,outer?32:16,pad);
        if (!outer || (layers & 4) != 0) box(-4-arm,12,-2,arm,12,4,40,outer?32:16,pad);
        if (!outer || (layers & 8) != 0) box(4,12,-2,arm,12,4,outer?48:32,48,pad);
        if (!outer || (layers & 16) != 0) box(-4,0,-2,4,12,4,0,outer?32:16,pad);
        if (!outer || (layers & 32) != 0) box(0,0,-2,4,12,4,outer?0:16,48,pad);
    }
    private void box(double x,double y,double z,int w,int h,int d,int u,int v,double pad) {
        box(x,y,z,w,h,d,u,v,pad,skin);
    }
    private void box(double x,double y,double z,int w,int h,int d,int u,int v,double pad,SkinLibrary.Skin texture) {
        double x0=x-pad,x1=x+w+pad,y0=y-pad,y1=y+h+pad,z0=z-pad,z1=z+d+pad;
        boolean capeSheet=texture.height()==32;
        face(new double[][]{{x0,y1,z1},{x1,y1,z1},{x1,y0,z1},{x0,y0,z1}},u+d+(capeSheet?w+d:0),v+d,w,h,1,texture);
        face(new double[][]{{x1,y1,z0},{x0,y1,z0},{x0,y0,z0},{x1,y0,z0}},u+d+(capeSheet?0:w+d),v+d,w,h,.78,texture);
        face(new double[][]{{x0,y1,z0},{x0,y1,z1},{x0,y0,z1},{x0,y0,z0}},u,v+d,d,h,.72,texture);
        face(new double[][]{{x1,y1,z1},{x1,y1,z0},{x1,y0,z0},{x1,y0,z1}},u+d+w,v+d,d,h,.85,texture);
        face(new double[][]{{x0,y1,z0},{x1,y1,z0},{x1,y1,z1},{x0,y1,z1}},u+d,v,w,d,1.08,texture);
        face(new double[][]{{x0,y0,z1},{x1,y0,z1},{x1,y0,z0},{x0,y0,z0}},u+d+w,v,w,d,.65,texture);
    }
    private void face(double[][] points,int u,int v,int tw,int th,double shade,SkinLibrary.Skin texture) {
        double[][] projected = new double[4][5];
        for(int i=0;i<4;i++) {
            double px=points[i][0]*cos-points[i][2]*sin;
            double pz=points[i][0]*sin+points[i][2]*cos, py=points[i][1]-16;
            projected[i]=new double[]{width/2.0+px*scale,height/2.0-(py*.978-pz*.208)*scale,
                    pz*.978+py*.208,u+(i==1||i==2?tw:0),v+(i>=2?th:0)};
        }
        triangle(projected[0],projected[1],projected[2],shade,texture);
        triangle(projected[0],projected[2],projected[3],shade,texture);
    }
    private void triangle(double[] a,double[] b,double[] c,double shade,SkinLibrary.Skin texture) {
        double area=edge(a,b,c[0],c[1]); if(Math.abs(area)<.00001) return;
        int x0=Math.max(0,(int)Math.floor(Math.min(a[0],Math.min(b[0],c[0]))));
        int x1=Math.min(width-1,(int)Math.ceil(Math.max(a[0],Math.max(b[0],c[0]))));
        int y0=Math.max(0,(int)Math.floor(Math.min(a[1],Math.min(b[1],c[1]))));
        int y1=Math.min(height-1,(int)Math.ceil(Math.max(a[1],Math.max(b[1],c[1]))));
        for(int y=y0;y<=y1;y++) for(int x=x0;x<=x1;x++) {
            double wa=edge(b,c,x+.5,y+.5)/area,wb=edge(c,a,x+.5,y+.5)/area,wc=1-wa-wb;
            if(wa<0||wb<0||wc<0) continue;
            double z=wa*a[2]+wb*b[2]+wc*c[2]; int index=y*width+x;
            if(z<depth[index]) continue;
            int tx=Math.max(0,Math.min(texture.width()-1,(int)(wa*a[3]+wb*b[3]+wc*c[3])));
            int ty=Math.max(0,Math.min(texture.height()-1,(int)(wa*a[4]+wb*b[4]+wc*c[4])));
            int color=texture.pixels()[ty*texture.width()+tx]; if((color>>>24)<128) continue;
            int r=Math.min(255,(int)(((color>>16)&255)*shade));
            int g=Math.min(255,(int)(((color>>8)&255)*shade));
            int bl=Math.min(255,(int)((color&255)*shade));
            raster[index]=0xFF000000|(r<<16)|(g<<8)|bl; depth[index]=z;
        }
    }
    private static double edge(double[] a,double[] b,double x,double y) {
        return (x-a[0])*(b[1]-a[1])-(y-a[1])*(b[0]-a[0]);
    }
    public static void face(ClientUi.Canvas canvas,SkinLibrary.Skin skin,int x,int y,int size) {
        if(skin.height()==32) {
            if(skin.hidden()) {
                canvas.text("-",x+size/2,y+size/2-4,0xFFAAAAAA); return;
            }
            int panelW=Math.max(1,size*10/16),offset=(size-panelW)/2;
            for(int row=0;row<16;row++) for(int col=0;col<10;col++) {
                int color=skin.pixels()[(row+1)*64+col+1];
                if((color>>>24)!=0) canvas.fill(x+offset+col*panelW/10,y+row*size/16,
                        x+offset+(col+1)*panelW/10,y+(row+1)*size/16,color);
            }
            return;
        }
        for(int row=0;row<8;row++) for(int col=0;col<8;col++) {
            int base=skin.pixels()[(row+8)*64+col+8], hat=skin.pixels()[(row+8)*64+col+40];
            int color=(hat>>>24)>=128?hat:base;
            canvas.fill(x+col*size/8,y+row*size/8,x+(col+1)*size/8,y+(row+1)*size/8,color|0xFF000000);
        }
    }
}
