package com.cubeon.client.skins;

/** A confirmed launcher Apply, consumed by the native skin adapter on the game thread. */
public final class LiveSkin {
    public record Applied(byte[] png, boolean slim, long revision) { }
    private static volatile Applied applied;
    private static long revision;
    private LiveSkin() { }
    public static Applied get() { return applied; }
    public static synchronized void apply(SkinLibrary.Skin skin) {
        applied = new Applied(skin.png(), skin.slim(), ++revision);
    }
}
