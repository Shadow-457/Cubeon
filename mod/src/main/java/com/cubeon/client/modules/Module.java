package com.cubeon.client.modules;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * One toggleable feature in the mod menu.
 *
 * <p>Intentionally Minecraft-free. Everything a module needs in order to be
 * <em>listed</em> - its name, blurb, category, on/off state and settings - lives
 * here with no Minecraft import, so the whole framework round-trips through
 * {@link ModuleConfig} and is unit-tested on a bare JDK (see
 * {@code mod/tools/SelfTest.java}). Only {@link #apply()} reaches for the game.
 *
 * <p><b>Settings.</b> A module declares a value with {@link #intSetting} or
 * {@link #boolSetting} in its constructor; the menu grows a control for each
 * one automatically, and {@link ModuleConfig} persists them. Values are clamped
 * on read, so a hand-edited or stale config file can never hand a module
 * something out of range.
 *
 * <p><b>Lifecycle.</b> {@link #setEnabled} re-applies immediately rather than
 * waiting for a tick, so toggling a Fullbright lights the world the same frame.
 * Modules that only need to do work continuously override {@link #onTick};
 * the registry calls it once per client tick, and only while a player exists.
 */
public abstract class Module {

    private final String id;
    private final String name;
    private final String description;
    private final ModuleCategory category;

    private boolean enabled;
    private final Map<String, Boolean> boolSettings = new LinkedHashMap<>();
    private final Map<String, Integer> intSettings = new LinkedHashMap<>();
    private final Map<String, Integer> intMin = new LinkedHashMap<>();
    private final Map<String, Integer> intMax = new LinkedHashMap<>();

    protected Module(String id, String name, String description,
                     ModuleCategory category) {
        this.id = id;
        this.name = name;
        this.description = description;
        this.category = category;
    }

    // ---- identity ---------------------------------------------------------

    /** Stable key used in the config file. Never shown, never localised. */
    public final String id() {
        return id;
    }

    public final String name() {
        return name;
    }

    public final String description() {
        return description;
    }

    public final ModuleCategory category() {
        return category;
    }

    // ---- on/off -----------------------------------------------------------

    public final boolean isEnabled() {
        return enabled;
    }

    /** Flips the module and re-applies it. Never throws - a broken module
     *  must not be able to take the menu down with it. */
    public final void setEnabled(boolean on) {
        if (this.enabled == on) {
            return;
        }
        this.enabled = on;
        try {
            apply(on);
        } catch (Throwable ignored) {
            // A module that cannot apply is one that cannot help; leaving the
            // toggle on would be a lie, so report it off.
            this.enabled = !on;
        }
    }

    /** Puts the game's own state in line with {@link #isEnabled}. */
    protected abstract void apply(boolean on);

    /** Called every client tick while enabled and a player exists. */
    protected void onTick() {
    }

    // ---- settings ---------------------------------------------------------

    protected final void boolSetting(String key, boolean initial) {
        boolSettings.put(key, initial);
    }

    protected final void intSetting(String key, int initial, int min, int max) {
        intSettings.put(key, initial);
        intMin.put(key, min);
        intMax.put(key, max);
    }

    public final boolean boolValue(String key) {
        return Boolean.TRUE.equals(boolSettings.get(key));
    }

    public final void setBoolValue(String key, boolean value) {
        boolSettings.put(key, value);
    }

    public final int intValue(String key) {
        return intSettings.getOrDefault(key, 0);
    }

    /** Sets an int setting, clamped to its declared range. */
    public final void setIntValue(String key, int value) {
        Integer lo = intMin.get(key);
        Integer hi = intMax.get(key);
        if (lo != null && value < lo) {
            value = lo;
        }
        if (hi != null && value > hi) {
            value = hi;
        }
        intSettings.put(key, value);
    }

    /** Setting keys in declaration order, booleans then ints. */
    public final java.util.List<String> settingKeys() {
        java.util.List<String> keys = new java.util.ArrayList<>(boolSettings.keySet());
        keys.addAll(intSettings.keySet());
        return keys;
    }

    public final boolean isBoolSetting(String key) {
        return boolSettings.containsKey(key);
    }

    /** Raw int, unclamped, for the config file. */
    public final int rawIntValue(String key) {
        return intSettings.getOrDefault(key, 0);
    }
}
