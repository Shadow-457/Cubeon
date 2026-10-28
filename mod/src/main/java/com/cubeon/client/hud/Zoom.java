package com.cubeon.client.hud;

/**
 * Hold-to-zoom state, shared by the version-specific field-of-view and mouse
 * scroll hooks (2026-10-28).
 *
 * <p>Easing is driven by wall-clock time, not by ticks or frames, so the same
 * fade feels identical at 30, 60 or 240 fps: every call moves the current zoom
 * a fixed fraction of the distance to the target, where the fraction comes from
 * how long the previous frame took.
 *
 * <p>Minecraft-free on purpose: the mixin that can see the keybinding passes
 * "held" in and this class only does the maths, which is also what lets
 * {@code tools/test_mod_compile.py} compile the shared tree on a plain JDK.
 */
public final class Zoom {
	/** Zoom factor that means "the normal view". */
	public static final float MIN = 1.0F;
	/** Strongest zoom a config may ask for, matching CubeonHudConfig's clamp. */
	public static final float MAX = 8.0F;
	/**
	 * Time constant of the ease. 75 ms is quick enough to feel instant on the
	 * press and slow enough that the change is visible instead of a snap.
	 */
	private static final float EASE_SECONDS = 0.075F;
	/** How much one scroll notch multiplies the zoom. */
	private static final double SCROLL_STEP = 1.2;

	/** The factor the player scrolled to; survives releasing the key. */
	private static float target = MIN;
	/** Where the view is right now; eased toward {@link #target}. */
	private static float current = MIN;
	private static long lastNanos;
	private static boolean held;

	private Zoom() {
	}

	/** Whether the hold key is down this frame. */
	public static void setHeld(boolean value) {
		held = value;
	}

	public static boolean isHeld() {
		return held;
	}

	/** One scroll notch (or a fraction, for smooth-scrolling mice). */
	public static void onScroll(double notches) {
		if (notches == 0.0D) {
			return;
		}

		double next = target * Math.pow(SCROLL_STEP, notches);
		target = (float) Math.max(MIN, Math.min(maxZoom(), next));
	}

	/** The configured ceiling, clamped so a hand-edited file cannot break the view. */
	private static float maxZoom() {
		float configured = CubeonHudConfig.get().zoomFactor;
		return Math.max(MIN + 0.25F, Math.min(MAX, configured));
	}

	/**
	 * The multiplier to apply to the field of view: 1 while not zooming, and
	 * 1/zoom while the key is held. Called once per frame by the FOV hook.
	 */
	public static float fovFactor(boolean isHeld) {
		setHeld(isHeld);

		long now = System.nanoTime();
		float elapsed = lastNanos == 0L ? 0.016F
				: Math.min(0.1F, (now - lastNanos) / 1_000_000_000.0F);
		lastNanos = now;

		float goal = held ? target : MIN;
		float step = 1.0F - (float) Math.exp(-elapsed / EASE_SECONDS);
		current += (goal - current) * step;

		// Stop chasing an invisible difference, so a released zoom really is 1.0.
		if (Math.abs(goal - current) < 0.002F) {
			current = goal;
		}

		if (current <= MIN + 0.001F) {
			current = MIN;
			return 1.0F;
		}

		return 1.0F / current;
	}

	/** True while the view is zoomed or on its way back, for the HUD to read. */
	public static boolean isActive() {
		return current > MIN + 0.001F;
	}
}
