package com.cubeon.client.skins;

/** A confirmed cape selection. Null means keep the client's existing cape. */
public final class LiveCape {
    private LiveCape() { }
    public static CapeAnimation.Applied get() { return CapeAnimation.get(); }
    /** Local options take precedence over a server's model-part flags. */
    public static <T> T texture(CapeAnimation.Applied cape, boolean visible, T original, T replacement) {
        if (!visible || cape != null && cape.hidden()) return null;
        return cape == null || replacement == null ? original : replacement;
    }
    /** Raw cape sheets have no wing artwork; keep elytra independent of the live cape. */
    public static <T> T elytra(CapeAnimation.Applied cape, T original, T vanilla) {
        return cape != null && original == null ? vanilla : original;
    }
    public static synchronized void apply(SkinLibrary.Skin cape) {
        CapeAnimation.apply(cape.texturePng(), cape.hidden(), cape.animation(), cape.id());
    }
}
