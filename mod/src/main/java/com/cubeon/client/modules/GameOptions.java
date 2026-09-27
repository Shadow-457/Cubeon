package com.cubeon.client.modules;

import net.minecraft.client.Options;

/**
 * The handful of game options the Render modules drive, in one place.
 *
 * <p>All of them were checked with javap against the real 1.20.1 and 26.1.2
 * jars, and every accessor below exists with the same shape in both - which is
 * what keeps this inside the single-jar rule in mod/brackets.json.
 *
 * <p><b>The trap this file exists to avoid.</b> In 1.20.1 these options are
 * reachable as public <em>fields</em> ({@code options.gammaSetting}) as well as
 * accessors, and the field spelling is what most Fabric examples show. In 26.x
 * the fields are gone and only the accessor survives. Code written the
 * field-style compiles for the 1.20-1.21 bracket and fails the 26 build, so
 * only the accessor form is used anywhere in the mod.
 */
public final class GameOptions {

    private GameOptions() {
    }

    /** Brightness, the one Fullbright drives. 0-16 in game; 16 is full. */
    public static final OptionsAccessor GAMMA = new OptionsAccessor() {
        @Override
        public Object read(Options options) {
            return options.gamma().get();
        }

        @Override
        public void write(Options options, int value) {
            // Clamped to the game's own 0..16 range rather than the module's
            // slider range, so a hand-edited config cannot set a legal-looking
            // 999 that the options screen would then reject.
            options.gamma().set(Math.max(0.0, Math.min(16.0, value)));
        }
    };

    /** Field of view, in degrees. */
    public static final OptionsAccessor FOV = new OptionsAccessor() {
        @Override
        public Object read(Options options) {
            return options.fov().get();
        }

        @Override
        public void write(Options options, int value) {
            options.fov().set(Math.max(30, Math.min(170, value)));
        }
    };

    /** View bobbing - a boolean, carried through the int setting as 1/0. */
    public static final OptionsAccessor BOB_VIEW = new OptionsAccessor() {
        @Override
        public Object read(Options options) {
            return options.bobView().get();
        }

        @Override
        public void write(Options options, int value) {
            options.bobView().set(value != 0);
        }
    };

    /**
     * Smooth camera. This one is still a plain public field in both eras
     * (verified), not an {@code OptionInstance} - so it is written directly.
     */
    public static final OptionsAccessor SMOOTH = new OptionsAccessor() {
        @Override
        public Object read(Options options) {
            return options.smoothCamera;
        }

        @Override
        public void write(Options options, int value) {
            options.smoothCamera = value != 0;
        }
    };
}
