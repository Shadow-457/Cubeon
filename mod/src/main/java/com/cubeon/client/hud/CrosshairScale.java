package com.cubeon.client.hud;

/**
 * The animated size of the vanilla crosshair (2026-10-24).
 *
 * <p>The crosshair is drawn by Minecraft itself, so the per-era mixins
 * ({@code CrosshairMixin}) only wrap that call in a scale transform. This class
 * owns the number they scale by, and it is deliberately Minecraft-free so all
 * eight HUD eras can share one implementation instead of eight copies that
 * would drift apart.
 *
 * <p>The growth is smoothed with an exponential approach rather than snapping
 * between two sizes: a crosshair that instantly doubles the frame a mob walks
 * under it reads as a glitch, and at 260 fps an instant change is invisible for
 * a single frame anyway. {@code TAU} is the time constant - after it elapses,
 * about 63% of the gap to the target has been covered - so the change takes
 * roughly 100 ms to be clearly visible, fast enough to still feel responsive
 * when flicking onto a target.
 */
public final class CrosshairScale {
	/** Normal size: exactly what vanilla draws. */
	public static final float IDLE = 1.0F;
	/** On-target size. "A bit big", not a HUD-sized box. */
	public static final float ON_TARGET = 1.3F;

	private static final double TAU_SECONDS = 0.045D;
	/**
	 * A stalled or minimised window can produce a huge frame delta. Clamping it
	 * keeps the first frame after a hitch from jumping the whole way to the
	 * target, which would defeat the smoothing this class exists for.
	 */
	private static final double MAX_STEP_SECONDS = 0.1D;

	private static float scale = IDLE;
	private static long lastNanos;

	private CrosshairScale() {
	}

	/**
	 * Advances the animation one frame and returns the scale to draw with.
	 *
	 * @param onTarget whether {@code MinecraftClient.targetedEntity} (or its
	 *                 26.x equivalent) is non-null this frame
	 */
	public static float update(boolean onTarget) {
		long now = System.nanoTime();
		double elapsed = lastNanos == 0L ? 1.0D / 120.0D : (now - lastNanos) / 1.0E9D;
		lastNanos = now;
		elapsed = Math.max(0.0D, Math.min(MAX_STEP_SECONDS, elapsed));

		float target = onTarget ? ON_TARGET : IDLE;
		float blend = (float) (1.0D - Math.exp(-elapsed / TAU_SECONDS));
		scale += (target - scale) * blend;

		// Stop chasing a fraction of a pixel: without this the crosshair keeps
		// re-scaling forever and the matrix push below never becomes a no-op.
		if (Math.abs(target - scale) < 0.001F) {
			scale = target;
		}

		return scale;
	}

	/** Puts the crosshair back to its normal size, e.g. when the toggle is off. */
	public static void reset() {
		scale = IDLE;
		lastNanos = 0L;
	}
}
