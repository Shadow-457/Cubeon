package com.cubeon.client.hud;

import net.fabricmc.loader.api.FabricLoader;

/**
 * Shared decisions for the 26.x motion blur (2026-10-24).
 *
 * <p>The effect itself is a Minecraft post effect shipped in the 26.x resources
 * ({@code assets/cubeon-client/post_effect/motion_blur.json}); the per-era mixin
 * only has to put its id on {@code GameRenderer}'s requested list. This class
 * holds the two reasons that id should not be requested, so the three 26.x
 * copies cannot disagree about them.
 *
 * <p>Minecraft-free on purpose: it lives in {@code src/main/java}, which is the
 * part of the source tree shared by all 24 jars.
 */
public final class MotionBlur {
	/** Resource namespace and path of {@code post_effect/motion_blur.json}. */
	public static final String NAMESPACE = "cubeon-client";
	public static final String PATH = "motion_blur";

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
		if (!CubeonHudConfig.get().motionBlur) {
			return false;
		}

		if (irisLoaded == null) {
			irisLoaded = FabricLoader.getInstance().isModLoaded("iris");
		}

		return !irisLoaded;
	}
}
