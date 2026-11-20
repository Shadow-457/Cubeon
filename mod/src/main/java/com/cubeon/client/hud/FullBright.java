package com.cubeon.client.hud;

/** Scopes the full-bright gamma override to Minecraft's lightmap calculation. */
public final class FullBright {
    public static final double GAMMA = 16.0D;
    private static final ThreadLocal<Integer> LIGHTMAP_DEPTH = new ThreadLocal<>();

    private FullBright() { }

    public static void beginLightmap() {
        Integer depth = LIGHTMAP_DEPTH.get();
        LIGHTMAP_DEPTH.set(depth == null ? 1 : depth + 1);
    }

    public static void endLightmap() {
        Integer depth = LIGHTMAP_DEPTH.get();
        if (depth == null || depth <= 1) LIGHTMAP_DEPTH.remove();
        else LIGHTMAP_DEPTH.set(depth - 1);
    }

    public static double gamma(double vanilla) {
        return isActive() ? GAMMA : vanilla;
    }

    public static boolean isActive() {
        return LIGHTMAP_DEPTH.get() != null && CubeonHudConfig.get().fullBright;
    }

    public static double darkness(double vanilla) {
        return isActive() ? 0.0D : vanilla;
    }
}
