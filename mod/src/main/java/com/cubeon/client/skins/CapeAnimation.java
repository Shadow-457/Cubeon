package com.cubeon.client.skins;

import java.util.Arrays;
import java.util.Base64;
import java.util.Map;

/** One local cape selection, shared by the library and existing bridge poller. */
public final class CapeAnimation {
    public record Applied(byte[] png, boolean hidden, long revision, CapeFrames frames, long started, String id) {
        public int index(long now) { return frames==null?0:frames.index(now,started); }
        public byte[] frame(int index) { return frames==null?png:frames.png(index); }
    }
    private static volatile Applied applied;
    private static String polledRevision="";
    private static long revision;
    private CapeAnimation() { }
    public static Applied get() { return applied; }
    public static synchronized void apply(byte[] png, boolean hidden, CapeFrames frames, String id) {
        var old=applied;
        if(old!=null && old.hidden()==hidden && old.id().equals(id) && Arrays.equals(old.png(),png)
                && (old.frames()==null?frames==null:frames!=null && old.frames().key().equals(frames.key()))) return;
        applied=new Applied(png,hidden,++revision,frames,System.nanoTime(),id);
    }
    public static synchronized void accept(Map<String,Object> response) {
        if(!Boolean.TRUE.equals(response.get("ok"))) return;
        String stamp=String.valueOf(response.get("revision"));
        if(stamp.equals(polledRevision)) return;
        try {
            if(!Boolean.TRUE.equals(response.get("enabled"))) {
                applied=null; polledRevision=stamp; return;
            }
            if(!(response.get("applied") instanceof Map<?,?> skin)) return;
            byte[] png;
            if(skin.get("texture_path") instanceof String path) png=CapeFrames.localPng(path);
            else if(skin.get("png") instanceof String text && text.length()<=65536) {
                png=Base64.getDecoder().decode(text);
                CapeFrames.decodePng(png, false);
            }
            else return;
            CapeFrames frames=CapeFrames.read(skin.get("animation"));
            apply(png,Boolean.TRUE.equals(skin.get("hidden")),frames,String.valueOf(skin.get("id")));
            polledRevision=stamp;
        } catch(Exception invalid) {
            // Damaged/partially removed local files keep the last complete
            // texture. A future poll retries; the bridge itself stays healthy.
        }
    }
}
