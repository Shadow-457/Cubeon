package com.cubeon.client.skins;

import java.awt.image.BufferedImage;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import javax.imageio.ImageIO;

/** Bounded, fully decoded animation. Loading belongs to a worker, never a game callback. */
public final class CapeFrames {
    private final byte[][] frames;
    private final int[][] previews;
    private final long[] ends;
    private final long loops;
    private final String key;
    private final long started = System.nanoTime();
    private CapeFrames(byte[][] frames, int[][] previews, long[] ends, long loops, String key) {
        this.frames=frames; this.previews=previews; this.ends=ends; this.loops=loops; this.key=key;
    }
    public String key() { return key; }
    public int count() { return frames.length; }
    public byte[] png(int index) { return frames[index]; }
    public int[] preview(int index) { return previews[index]; }
    public int previewIndex() { return index(System.nanoTime(), started); }
    public int index(long now, long start) {
        long elapsed=Math.max(0,(now-start)/1_000_000L), total=ends[ends.length-1];
        if(loops>0 && elapsed/total>=loops) return frames.length-1;
        long position=elapsed%total;
        for(int i=0;i<ends.length;i++) if(position<ends[i]) return i;
        return frames.length-1;
    }
    public static byte[] localPng(String path) throws Exception {
        byte[] data=localBytes(path);
        decodePng(data, false);
        return data;
    }
    public static BufferedImage decodePng(byte[] data, boolean preview) throws Exception {
        var reader=ImageIO.getImageReadersByFormatName("png").next();
        try(var stream=ImageIO.createImageInputStream(new ByteArrayInputStream(data))) {
            reader.setInput(stream);
            int width=reader.getWidth(0), height=reader.getHeight(0);
            if(preview ? width!=64 || (height!=32 && height!=64)
                    : width<64 || width>1024 || Integer.bitCount(width)!=1 || width!=height*2)
                throw new IllegalArgumentException("Invalid cape or skin source dimensions.");
            return reader.read(0);
        } finally { reader.dispose(); }
    }
    private static byte[] localBytes(String path) throws Exception {
        Path file=Path.of(path);
        if(!file.isAbsolute() || Files.isSymbolicLink(file) || Files.size(file)>8*1024*1024)
            throw new IllegalArgumentException("Invalid cape source.");
        byte[] bytes=Files.readAllBytes(file);
        if(bytes.length>8*1024*1024) throw new IllegalArgumentException("Cape source is too large.");
        return bytes;
    }
    public static byte[] localGif(String path) throws Exception {
        byte[] data=localBytes(path);
        if(data.length<6 || data[0]!='G' || data[1]!='I' || data[2]!='F')
            throw new IllegalArgumentException("Invalid GIF cape export.");
        return data;
    }
    public static CapeFrames read(Object value) throws Exception {
        if(value==null) return null;
        if(!(value instanceof Map<?,?> raw) || !(raw.get("path") instanceof String path)
                || !(raw.get("key") instanceof String key) || !(raw.get("durations") instanceof List<?> durations))
            throw new IllegalArgumentException("Invalid cape animation.");
        int count=integer(raw.get("count")), width=integer(raw.get("width")), height=integer(raw.get("height"));
        if(count<2 || count>500 || (width!=64 && width!=128) || height!=width/2 || durations.size()!=count)
            throw new IllegalArgumentException("Invalid cape animation dimensions.");
        long loops=raw.get("loop")==null?1:integer(raw.get("loop"));
        if(loops<0 || loops>65535) throw new IllegalArgumentException("Invalid cape animation loop.");
        if(loops!=0 && raw.get("loop")!=null) loops++;
        long[] ends=new long[count]; long total=0;
        for(int i=0;i<count;i++) {
            int duration=integer(durations.get(i));
            if(duration<10 || duration>655350) throw new IllegalArgumentException("Invalid cape frame timing.");
            ends[i]=total+=duration;
        }
        byte[] data=localBytes(path);
        var reader=ImageIO.getImageReadersByFormatName("png").next();
        BufferedImage atlas;
        try(var stream=ImageIO.createImageInputStream(new ByteArrayInputStream(data))) {
            reader.setInput(stream);
            if(reader.getWidth(0)!=width || reader.getHeight(0)!=height*count)
                throw new IllegalArgumentException("Invalid cape animation atlas.");
            atlas=reader.read(0);
        } finally { reader.dispose(); }
        byte[][] frames=new byte[count][]; int[][] previews=new int[count][];
        for(int i=0;i<count;i++) {
            var frame=atlas.getSubimage(0,i*height,width,height);
            var buffer=new ByteArrayOutputStream(); ImageIO.write(frame,"PNG",buffer); frames[i]=buffer.toByteArray();
            int[] pixels=new int[64*32]; int scale=width/64;
            for(int y=0;y<32;y++) for(int x=0;x<64;x++) pixels[y*64+x]=frame.getRGB(x*scale,y*scale);
            previews[i]=pixels;
        }
        return new CapeFrames(frames,previews,ends,loops,key);
    }
    private static int integer(Object value) {
        if(!(value instanceof Number n) || n.doubleValue()!=n.intValue())
            throw new IllegalArgumentException("Invalid cape animation number.");
        return n.intValue();
    }
}
