package com.cubeon.client.modules;

/**
 * The tab a module sits under in the menu.
 *
 * <p>Deliberately Minecraft-free (no imports beyond java.lang) so the whole
 * module framework can be unit-tested on a bare JDK, like
 * {@link com.cubeon.client.Json} and {@link com.cubeon.client.BadgeNames}.
 * That is only possible if none of the machinery below drags in a class that
 * only exists inside a Minecraft jar.
 *
 * <p>{@link #ALL} is not a real category - it is the "show everything" tab, and
 * {@link #matches} treats it as a wildcard.
 */
public enum ModuleCategory {
    ALL("All"),
    HUD("HUD"),
    PVP("PvP"),
    RENDER("Render"),
    UTILITY("Utility");

    private final String label;

    ModuleCategory(String label) {
        this.label = label;
    }

    /** The tab's own name, as shown on the button. */
    public String label() {
        return label;
    }

    /** True when this category should show a module in the given category. */
    public boolean matches(ModuleCategory other) {
        return this == ALL || this == other;
    }
}
