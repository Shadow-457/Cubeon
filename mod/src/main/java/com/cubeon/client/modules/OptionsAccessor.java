package com.cubeon.client.modules;

import net.minecraft.client.Options;

/**
 * Reads and writes one of the game's own options, in a way that survives both
 * Minecraft eras.
 *
 * <p>26.x turned the public {@code Options} <em>fields</em> into accessor
 * methods, while 1.20.1 has both. Every read and write in the mod therefore
 * goes through the accessor form - the one spelling that exists in both - and
 * an option is wrapped in an implementation of this rather than being touched
 * directly, so the unchecked cast to {@code OptionInstance<T>} lives in exactly
 * one place per option.
 */
public interface OptionsAccessor {

    /** The option's current value, boxed, for restoring later. */
    Object read(Options options);

    /** Sets the option. The implementation clamps to the game's own range. */
    void write(Options options, int value);

    /**
     * Puts back a value captured by {@link #read}.
     *
     * <p>Separate from {@code write} because the captured value is the option's
     * own boxed type - a {@code Double} for gamma, an {@code Integer} for FOV -
     * while {@code write} takes the module's int setting. Routing a restore
     * through {@code write} would either lose the type or re-clamp a value the
     * player actually chose.
     */
    void writeRaw(Options options, Object value);
}
