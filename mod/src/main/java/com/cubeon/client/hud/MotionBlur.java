package com.cubeon.client.hud;

import net.fabricmc.loader.api.FabricLoader;

/**
 * Shared decisions for the 26.x motion blur (2026-10-24).
 *
 * <p>The effect itself is a Minecraft post effect shipped in the 26.x resources
 * ({@code assets/cubeon-client/post_effect/motion_blur_*.json}); the per-era
 * mixin only has to put its id on {@code GameRenderer}'s requested list. This
 * class holds the reasons that id should not be requested - and WHICH id to
 * request for the configured strength - so the three 26.x copies cannot
 * disagree about them.
 *
 * <p>Minecraft-free on purpose: it lives in {@code src/main/java}, which is the
 * part of the source tree shared by all 24 jars.
 */
public final class MotionBlur {
	/** Resource namespace of every {@code post_effect/motion_blur_*.json}. */
	public static final String NAMESPACE = "cubeon-client";

	/**
	 * Path of the post effect for one 1..3 strength level. Three separate JSON
	 * files (rather than a uniform poked at runtime) because a Minecraft post
	 * effect's uniforms are baked into the resource: swapping the id is the
	 * supported way to change BlurAmount, and it needs no accessor mixin into
	 * {@code PostChain}.
	 */
	private static final String[] PATHS = {
			"motion_blur_low",      // 1
			"motion_blur_medium",   // 2
			"motion_blur_high",     // 3
	};

	/**
	 * Iris replaces Minecraft's post-effect pipeline with its own shader-pack
	 * pipeline. Requesting a vanilla post effect under Iris is at best ignored
	 * and at worst fights the pack's own final pass, so Cubeon stays out of the
	 * way entirely when Iris is installed.
	 */
	private static Boolean irisLoaded;

	private MotionBlur() {
	}

	/** Whether the 26.x mixin should ask for the effect on this frame. */
	public static boolean active() {
		if (CubeonHudConfig.get().blurStrength() <= 0) {
			return false;
		}

		if (irisLoaded == null) {
			irisLoaded = FabricLoader.getInstance().isModLoaded("iris");
		}

		return !irisLoaded;
	}

	/** The {@code post_effect} path for the configured strength (1..3). */
	public static String effectId() {
		int strength = CubeonHudConfig.get().blurStrength();
		int index = Math.max(0, Math.min(PATHS.length - 1, strength - 1));
		return PATHS[index];
	}
}
