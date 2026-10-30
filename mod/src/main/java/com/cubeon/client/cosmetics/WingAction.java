package com.cubeon.client.cosmetics;

import java.lang.ref.WeakReference;

/** A local, one-shot wing flourish driven by entity age and normal client input. */
public final class WingAction {
    public static final WingAction INSTANCE = new WingAction();
    public static final float DURATION = 3.25f;

    private WeakReference<Object> player = new WeakReference<>(null);
    private WeakReference<Object> world = new WeakReference<>(null);
    private String wing;
    private boolean down;
    private float started = Float.NaN, previous = Float.NaN;

    /** Queued taps are consumed by the adapter even when input is ineligible. */
    public void tick(boolean held, boolean pressed, boolean eligible, Object owner,
                     Object level, String selectedWing, float seconds) {
        boolean trigger = pressed && !down;
        down = held;
        if (!eligible || owner == null || level == null || selectedWing == null
                || !Float.isFinite(seconds)) {
            reset();
            return;
        }
        if (player.get() != owner || world.get() != level || !selectedWing.equals(wing)) {
            reset();
            player = new WeakReference<>(owner);
            world = new WeakReference<>(level);
            wing = selectedWing;
        }
        if (Float.isFinite(previous) && (seconds < previous || seconds - previous > 1)) {
            started = Float.NaN;
        }
        previous = seconds;
        // Further presses and keyboard repeats cannot restart an active stroke.
        if (trigger && elapsed(owner, level, seconds) < 0) started = seconds;
    }

    /** An inactive action is -1. Render interpolation can precede a tick by 50 ms. */
    public float elapsed(Object owner, Object level, float seconds) {
        if (owner == null || level == null || player.get() != owner || world.get() != level
                || !Float.isFinite(started) || !Float.isFinite(seconds)
                || seconds < started - 0.05f || seconds >= started + DURATION) return -1;
        return Math.max(0, seconds - started);
    }

    private void reset() {
        player.clear();
        world.clear();
        wing = null;
        previous = started = Float.NaN;
    }
}
