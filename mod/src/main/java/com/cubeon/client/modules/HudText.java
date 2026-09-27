package com.cubeon.client.modules;

import java.util.ArrayList;
import java.util.List;

/**
 * Turns the game's state into the lines the HUD shows.
 *
 * <p>Minecraft-free, and that is the whole point. Drawing an on-screen overlay
 * is the one part of this feature that Minecraft reshapes between versions
 * (1.20-1.21 renders the HUD through {@code Gui.render(GuiGraphics, float)},
 * 26.x through {@code Gui.extractRenderState(GuiGraphicsExtractor,
 * DeltaTracker)} - entirely different), so that half is per-bracket. But
 * <em>deciding what to write</em> did not move, so it lives here, once, and
 * each bracket only has to put strings on the screen.
 *
 * <p>Everything arrives as plain values, so this is testable without Minecraft.
 */
public final class HudText {

    private HudText() {
    }

    /**
     * Builds the HUD lines for the enabled modules, in a fixed order.
     *
     * @param fps        current framerate, or a negative number if unknown
     * @param x y z      the player's block position
     * @param pingMs     server latency, or a negative number if unknown
     * @param keys       the pressed-key row, already formatted by the caller
     *                   (it needs a keybinding lookup, which is game-side)
     * @param reach      distance to whatever the crosshair is on, or negative
     * @param cooldown   attack-cooldown strength 0..1, or negative
     * @param armor      the player's armour value
     */
    public static List<String> build(int fps, double x, double y, double z,
                                    int pingMs, String keys, double reach,
                                    double cooldown, int armor,
                                    List<Module> modules) {
        List<String> lines = new ArrayList<>();
        for (Module module : modules) {
            if (!module.isEnabled() || !(module instanceof HudModule hud)) {
                continue;
            }
            String line = hud.line(new View(fps, x, y, z, pingMs, keys, reach,
                                            cooldown, armor));
            if (line != null && !line.isEmpty()) {
                lines.add(line);
            }
        }
        return lines;
    }

    /** One frame's worth of game state, as plain values. */
    public static final class View {
        public final int fps;
        public final double x;
        public final double y;
        public final double z;
        public final int ping;
        public final String keys;
        public final double reach;
        public final double cooldown;
        public final int armor;

        public View(int fps, double x, double y, double z, int ping, String keys,
                    double reach, double cooldown, int armor) {
            this.fps = fps;
            this.x = x;
            this.y = y;
            this.z = z;
            this.ping = ping;
            this.keys = keys == null ? "" : keys;
            this.reach = reach;
            this.cooldown = cooldown;
            this.armor = armor;
        }
    }

    /** A module that draws one line of text. */
    public interface HudModule {
        /** The line to draw, or null/empty to draw nothing this frame. */
        String line(View view);
    }
}
