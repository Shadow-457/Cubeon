package com.cubeon.client.skins;

/** A confirmed cape selection. Null means keep the client's existing cape. */
public final class LiveCape {
    public record Applied(byte[] png, boolean hidden, long revision) { }
    private static volatile Applied applied;
    private static long revision;
    private LiveCape() { }
    public static Applied get() { return applied; }
    public static synchronized void apply(SkinLibrary.Skin cape) {
        applied = new Applied(cape.texturePng(), cape.hidden(), ++revision);
    }
}
