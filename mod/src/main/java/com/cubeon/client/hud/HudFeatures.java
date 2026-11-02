package com.cubeon.client.hud;

/** Stable ordering shared by native overlay adapters and the settings catalogue. */
public enum HudFeatures {
    FPS("fps", "HUD", 64, 12), KEYS("keys", "HUD", 66, 76), ARMOR("armor", "Player", 96, 28),
    PING("ping", "HUD", 64, 12), CPS("cps", "HUD", 64, 12),
    CLOCK("clock", "HUD", 84, 12), SYSTEM("system", "HUD", 146, 24),
    POTIONS("potions", "Player", 150, 74), COORDINATES("coordinates", "HUD", 146, 24),
    DIRECTION("direction", "HUD", 112, 12),
    BIOME("biome", "HUD", 132, 12), DAYLIGHT("daylight", "HUD", 146, 24),
    COMBO("combo", "Player", 72, 12);

    public static final HudFeatures[] ALL = values();
    public final String slot, category;
    public final int width, height;
    HudFeatures(String slot, String category, int width, int height) {
        this.slot = slot; this.category = category; this.width = width; this.height = height;
    }
    public String label() { return "cubeonclient.hud." + slot; }
    public boolean extra() { return ordinal() >= 5; }
    public static HudFeatures at(int index) { return ALL[index]; }
    public static HudFeatures slot(String value) {
        for (HudFeatures feature : ALL) if (feature.slot.equals(value)) return feature;
        return null;
    }
    public float defaultX() {
        return switch (this) {
            case CLOCK, DIRECTION, COMBO -> .5f;
            case SYSTEM, POTIONS -> 1f;
            default -> 0f;
        };
    }
    public float defaultY() {
        return switch (this) {
            case CLOCK -> 0f;
            case DIRECTION -> .08f;
            case COORDINATES -> .20f;
            case BIOME -> .32f;
            case DAYLIGHT, SYSTEM -> .42f;
            case COMBO -> .72f;
            case POTIONS -> .62f;
            default -> 0f;
        };
    }
}
