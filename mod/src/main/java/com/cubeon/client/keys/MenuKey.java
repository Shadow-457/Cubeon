package com.cubeon.client.keys;

import org.lwjgl.glfw.GLFW;

/**
 * Opens the mod menu from a key press.
 *
 * <p><b>Why raw GLFW rather than a vanilla {@code KeyMapping}.</b> The obvious
 * route is a keybind, but that is exactly the API this mod cannot use once:
 * {@code KeyMapping}'s category is a plain {@code String} in 1.20-1.21 and a
 * {@code KeyMapping.Category} record in 26.x, and the registration call that
 * makes a mapping actually RECEIVE input is not on {@code Options} in either
 * version (checked with javap in both real jars). Every step of that route is
 * per-bracket archaeology for a feature that is one boolean.
 *
 * <p>GLFW is a native library, so its API is identical on every Minecraft
 * version: {@code glfwGetCurrentContext()} gives the window the client is
 * running on, {@code glfwGetKey} its key state. No Minecraft type is touched,
 * so this file is shared and there is nothing to remap.
 *
 * <p><b>Trade-off, stated plainly:</b> the key is not listed under
 * Options -> Controls, because registering it there is the version-specific
 * part. It is a fixed key (K, unbound in vanilla) stored in the module
 * config, so it can be changed in that file even though it cannot be
 * rebound in-game yet.
 *
 * <p>Two details that stop it misfiring: it only fires on a fresh PRESS, so
 * holding the key down does not reopen the menu every tick; and it only
 * fires with no screen open, so typing K into chat or a text field is never
 * intercepted.
 */
public final class MenuKey {

    /** K - unbound in vanilla, and unused by the rest of this mod. */
    public static final int DEFAULT_KEY = GLFW.GLFW_KEY_K;

    private static int key = DEFAULT_KEY;
    private static boolean wasDown;

    private MenuKey() {
    }

    /** The configured key code. */
    public static int key() {
        return key;
    }

    /** Changes the key, clearing the press state so it cannot fire on switch. */
    public static void setKey(int newKey) {
        key = newKey;
        wasDown = false;
    }

    /** True exactly once per physical press of the key. */
    public static boolean justPressed() {
        long window;
        try {
            window = GLFW.glfwGetCurrentContext();
        } catch (Throwable ignored) {
            return false;   // GLFW not initialised; no keybinds this tick
        }
        if (window == 0) {
            return false;
        }
        boolean down;
        try {
            down = GLFW.glfwGetKey(window, key) == GLFW.GLFW_PRESS;
        } catch (Throwable ignored) {
            return false;
        }
        boolean pressed = down && !wasDown;
        wasDown = down;
        return pressed;
    }

    /** Drops any held state, so opening a screen cannot leave a stale press. */
    public static void forget() {
        wasDown = false;
    }
}
