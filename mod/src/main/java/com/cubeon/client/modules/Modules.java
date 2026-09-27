package com.cubeon.client.modules;

import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

import net.minecraft.client.Minecraft;
import net.minecraft.client.Options;

/**
 * Every module the mod menu offers, and the tick that drives the ones that
 * need one.
 *
 * <p><b>Why these all work on one jar across both Minecraft eras.</b> Each
 * option module goes through {@link Options} accessors - {@code gamma()},
 * {@code fov()}, {@code bobView()} - and {@code OptionInstance.get/set}. Those
 * were checked with javap against the real 1.20.1 and 26.1.2 jars and are
 * identical, which is what lets one jar serve {@code >=1.20.1 <26} and
 * {@code >=26}. In 26.x the public <em>fields</em> became accessors, so this
 * calls the method form only - writing {@code options.gammaSetting} would
 * compile on one bracket and not the other.
 *
 * <p>Every option module remembers the player's own value and restores it on
 * disable. A module that only switched something off and never put it back
 * would be quiet vandalism of someone's video settings.
 *
 * <p>Nothing here is a cheat: each entry is a display or quality-of-life
 * option, and the PvP category is information the player could read off the
 * screen anyway (reach, cooldown, ping, armour) plus auto-sprint.
 */
public final class Modules {

    private static Modules instance;

    private final List<Module> all = new ArrayList<>();
    private final List<OptionModule> optionModules = new ArrayList<>();
    private final SessionClock clock = new SessionClock();
    private Path configFile;

    private Modules() {
        // ---- Render --------------------------------------------------------
        all.add(new OptionModule("fullbright", "Fullbright",
                "Removes darkness. Your own brightness comes back when you switch it off.",
                ModuleCategory.RENDER, "Brightness", GameOptions.GAMMA, 16, 16));
        all.add(new OptionModule("fov", "FOV Changer", "Field of view.",
                ModuleCategory.RENDER, "FOV", GameOptions.FOV, 90, 110));
        all.add(new OptionModule("nobob", "No View Bobbing",
                "Stops the camera dipping when you walk.",
                ModuleCategory.RENDER, "No bobbing", GameOptions.BOB_VIEW, 1, 1));
        all.add(new OptionModule("smoothcam", "Smooth Camera",
                "Smooths out camera movement.",
                ModuleCategory.RENDER, "Smooth", GameOptions.SMOOTH, 1, 1));

        // ---- PvP: information and quality of life, not automation ---------
        all.add(new AutoSprint());
        all.add(new Hud("reach", "Reach", "Blocks to whatever you are looking at.",
                ModuleCategory.PVP, view -> view.reach < 0 ? null
                        : String.format("Reach %.2f", view.reach)));
        all.add(new Hud("cooldown", "Attack Cooldown", "How ready your next hit is.",
                ModuleCategory.PVP, view -> view.cooldown < 0 ? null
                        : String.format("Cooldown %d%%", Math.round(view.cooldown * 100))));
        all.add(new Hud("ping", "Ping", "Your latency to the server.",
                ModuleCategory.PVP, view -> view.ping < 0 ? null
                        : view.ping + " ms"));
        all.add(new Hud("armor", "Armor", "Your armour points.",
                ModuleCategory.PVP, view -> "Armor " + view.armor));

        // ---- HUD -----------------------------------------------------------
        all.add(new Hud("fps", "FPS", "Frames per second.",
                ModuleCategory.HUD, view -> view.fps < 0 ? null : view.fps + " FPS"));
        all.add(new Hud("coords", "Coordinates", "Your block position.",
                ModuleCategory.HUD, view -> String.format("XYZ %.0f %.0f %.0f",
                        view.x, view.y, view.z)));
        all.add(new Hud("keys", "Keystrokes", "The keys you are holding.",
                ModuleCategory.HUD, view -> view.keys.isEmpty() ? null : view.keys));
        all.add(new Hud("session", "Session Time", "How long you have been connected.",
                ModuleCategory.UTILITY, view -> clock.line()));

        for (Module module : all) {
            if (module instanceof OptionModule option) {
                optionModules.add(option);
            }
        }
    }

    public static synchronized Modules get() {
        if (instance == null) {
            instance = new Modules();
        }
        return instance;
    }

    public List<Module> all() {
        return Collections.unmodifiableList(all);
    }

    /** Points the registry at its config file and applies what is in it. */
    public void loadFrom(Path file) {
        this.configFile = file;
        ModuleConfig.load(file).applyTo(all);
        // A load can turn modules on, and the game's own options have to agree
        // even if the player never opens the menu this session.
        for (OptionModule module : optionModules) {
            if (module.isEnabled()) {
                module.reapply();
            }
        }
        clock.markJoined();
    }

    public void save() {
        if (configFile != null) {
            ModuleConfig.save(configFile, all);
        }
    }

    public SessionClock clock() {
        return clock;
    }

    /**
     * Runs the modules that need a per-tick hook. Called from a mixin on the
     * local player's tick, so it only ever runs with a live player.
     */
    public void tick(Minecraft mc) {
        if (mc == null || mc.player == null) {
            return;
        }
        for (Module module : all) {
            if (module.isEnabled()) {
                try {
                    module.onTick();
                } catch (Throwable ignored) {
                    // One bad module must not stop the others, and must never
                    // propagate back into the player tick itself.
                }
            }
        }
    }
    /** How long the player has been connected, for the session-time module. */
    public static final class SessionClock {
        private long joinedAt = System.currentTimeMillis();

        private SessionClock() {
        }

        void markJoined() {
            joinedAt = System.currentTimeMillis();
        }

        /** mm:ss, or h:mm:ss past an hour. */
        public String line() {
            long seconds = Math.max(0, (System.currentTimeMillis() - joinedAt) / 1000L);
            long hours = seconds / 3600;
            long minutes = (seconds % 3600) / 60;
            if (hours > 0) {
                return String.format("Session %d:%02d:%02d", hours, minutes, seconds % 60);
            }
            return String.format("Session %d:%02d", minutes, seconds % 60);
        }
    }

    /**
     * A module that flips one of the game's own options, and puts back exactly
     * what was there before when switched off.
     *
     * <p>The capture happens on the first enable, not in the constructor, so a
     * module enabled by a config load still remembers the live value rather
     * than a hardcoded guess.
     */
    static final class OptionModule extends Module {

        private final String settingKey;
        private final OptionsAccessor accessor;
        private final int onValue;
        private final int max;
        private Object previous;

        OptionModule(String id, String name, String description,
                     ModuleCategory category, String settingKey,
                     OptionsAccessor accessor, int onValue, int max) {
            super(id, name, description, category);
            this.settingKey = settingKey;
            this.accessor = accessor;
            this.onValue = onValue;
            this.max = max;
            intSetting(settingKey, onValue, 0, max);
        }

        @Override
        protected void apply(boolean on) {
            Options options = Minecraft.getInstance().options;
            if (on) {
                if (previous == null) {
                    previous = accessor.read(options);
                }
                accessor.write(options, intValue(settingKey));
            } else if (previous != null) {
                accessor.write(options, previous);
                previous = null;
            }
        }

        /** Re-writes the option after a config load changed the setting. */
        void reapply() {
            if (isEnabled()) {
                try {
                    apply(true);
                } catch (Throwable ignored) {
                    // Same contract as setEnabled - never fatal.
                }
            }
        }
    }

    /**
     * Reads and writes one of the game's options across both eras. The 26.x
     * bracket turned these public fields into accessors, so every read and
     * write goes through the method form, which exists in 1.20.1 too.
     *
     * <p>Implemented in {@link GameOptions} so the casts to
     * {@code OptionInstance<Boolean/Double/Integer>} live in one place.
     */
    public interface OptionsAccessor {
        Object read(Options options);

        void write(Options options, int value);
    }

    /**
     * Auto-sprint: hold forward and you run. A quality-of-life toggle, and the
     * one PvP entry that changes input rather than reporting information.
     */
    static final class AutoSprint extends Module {

        AutoSprint() {
            super("autosprint", "Auto Sprint",
                    "Hold forward and you run without holding sprint.",
                    ModuleCategory.PVP);
        }

        @Override
        protected void apply(boolean on) {
            // Nothing to write; it is a per-tick behaviour.
        }

        @Override
        protected void onTick() {
            Minecraft mc = Minecraft.getInstance();
            if (mc.player == null) {
                return;
            }
            boolean forward = mc.options.keySprint.isDown()
                    || mc.player.input.forwardImpulse > 0.0F;
            if (forward && !mc.player.isSprinting()) {
                mc.player.setSprinting(true);
            }
        }
    }

    /** A module that only draws a line of text. */
    static final class Hud extends Module implements HudText.HudModule {

        private final HudText.HudModule body;

        Hud(String id, String name, String description, ModuleCategory category,
            HudText.HudModule body) {
            super(id, name, description, category);
            this.body = body;
        }

        @Override
        protected void apply(boolean on) {
            // Display only.
        }

        @Override
        public String line(HudText.View view) {
            return body.line(view);
        }
    }
}

}

        for (Module module : all) {
            if (module instanceof OptionModule option) {
                optionModules.add(option);
            }
        }
    }
