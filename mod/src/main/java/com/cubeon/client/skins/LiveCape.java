package com.cubeon.client.skins;

/** A confirmed cape selection. Null means keep the client's existing cape. */
public final class LiveCape {
    private LiveCape() { }
    public static CapeAnimation.Applied get() { return CapeAnimation.get(); }
    public static synchronized void apply(SkinLibrary.Skin cape) {
        CapeAnimation.apply(cape.texturePng(), cape.hidden(), cape.animation(), cape.id());
    }
}
