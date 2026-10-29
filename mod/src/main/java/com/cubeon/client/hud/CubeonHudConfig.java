package com.cubeon.client.hud;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import net.fabricmc.loader.api.FabricLoader;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

/**
 * Persisted toggles and overlay positions, stored as cubeon-client-hud.json in the config folder.
 *
 * <p>Positions are kept as fractions of the free space that is left after the overlay's
 * own size is subtracted from the screen, so a saved spot stays at the same relative
 * place at any window size, resolution or aspect ratio.
 */
public final class CubeonHudConfig {
	private static final Gson GSON = new GsonBuilder().setPrettyPrinting().create();
	private static final Path FILE = FabricLoader.getInstance().getConfigDir().resolve("cubeon-client-hud.json");
	/**
	 * The HUD's file name before it was renamed (this mod absorbed that mod, and the
	 * old name describes it), read ONCE as a migration so an upgrading player keeps
	 * their overlay positions and toggles instead of silently getting the defaults
	 * back. Never written: the first save lands in {@link #FILE}, after which this
	 * one is dead weight and the player can delete it.
	 */
	private static final Path LEGACY_FILE = FabricLoader.getInstance().getConfigDir().resolve("keyhud.json");

	public boolean showFps = false;
	public boolean showKeys = false;
	public boolean showArmor = false;
	public boolean showPing = false;
	public boolean showCps = false;
	/** Compact bars anchored beneath nearby enemy names, opt-in. */
	public boolean showEnemyHealth = false;

	/**
	 * 26.x only: blends the previous world frame into the current one, so fast
	 * camera movement leaves a short trail. The effect is a Minecraft post
	 * effect (post_effect/motion_blur_*.json) driven by {@link MotionBlur}; on
	 * the 1.20-1.21 jars there is no row for it and the flag does nothing.
	 *
	 * <p>Kept as the pre-strength on/off switch so an existing config that had
	 * it OFF stays off after the upgrade (see {@link #blurStrength()}).
	 */
	public boolean motionBlur = true;

	/**
	 * 0 = off, 1 = low, 2 = medium, 3 = high (2026-10-24). {@code null} means
	 * "written by a version that only had the boolean", which is how an old
	 * config is migrated without silently turning blur back on for someone who
	 * had disabled it.
	 */
	public Integer motionBlurStrength = null;

	public boolean showArmorHelmet = true;
	public boolean showArmorChest = true;
	public boolean showArmorLegs = true;
	public boolean showArmorFeet = true;

	/**
	 * Size of each overlay, independent of the others (2026-10-28). A single
	 * global scale made the keystrokes widget and the FPS counter share one
	 * size, so making one readable made the other huge.
	 *
	 * <p>Null means "not set by this version" - {@link #scaleFor(String)} then
	 * falls back to {@link #scale}, which is what an upgraded config's shared
	 * size becomes. The fields stay null in a config saved without ever
	 * touching that overlay, so the old global value keeps working.
	 */
	public Float fpsScale = null;
	public Float keysScale = null;
	public Float armorScale = null;
	public Float pingScale = null;
	public Float cpsScale = null;

	/**
	 * The legacy single size, kept so a config written by an older jar (and an
	 * older jar reading a newer config) still means what it meant. New code
	 * reads per-overlay sizes through {@link #scaleFor(String)}.
	 */
	public float scale = 1.0F;

	/** How far the hold-to-zoom key magnifies: 1 = off, 8 = strongest. */
	public float zoomFactor = 4.0F;

	/** 0 = flush left, 1 = flush right. */
	public float fpsX = 0.0F;
	/** 0 = top, 1 = bottom. */
	public float fpsY = 0.0F;
	/** 0 = flush left, 1 = flush right. */
	public float keysX = 0.0F;
	/** 0 = top, 1 = bottom. */
	public float keysY = 0.55F;
	/** 0 = flush left, 1 = flush right. */
	public float armorX = 1.0F;
	/** 0 = top, 1 = bottom. */
	public float armorY = 0.35F;
	/** 0 = flush left, 1 = flush right. */
	public float pingX = 1.0F;
	/** 0 = top, 1 = bottom. */
	public float pingY = 0.0F;
	/** 0 = flush left, 1 = flush right. */
	public float cpsX = 0.0F;
	/** 0 = top, 1 = bottom. */
	public float cpsY = 0.10F;

	private static CubeonHudConfig instance = new CubeonHudConfig();

	private CubeonHudConfig() {
	}

	public static CubeonHudConfig get() {
		return instance;
	}

	public static void load() {
		try {
			// New name first, then the pre-rename file (see LEGACY_FILE).
			Path source = Files.exists(FILE) ? FILE : (Files.exists(LEGACY_FILE) ? LEGACY_FILE : null);

			if (source != null) {
				CubeonHudConfig loaded = GSON.fromJson(Files.readString(source, StandardCharsets.UTF_8), CubeonHudConfig.class);

				if (loaded != null) {
					instance = loaded;
				}
			}
		} catch (Exception e) {
			CubeonHudClient.LOGGER.warn("Could not read cubeon-client-hud.json, using defaults.", e);
		}

		instance.clampAll();
	}

	public static void save() {
		try {
			instance.clampAll();
			Files.writeString(FILE, GSON.toJson(instance) + System.lineSeparator(), StandardCharsets.UTF_8);
		} catch (Exception e) {
			CubeonHudClient.LOGGER.warn("Could not write cubeon-client-hud.json.", e);
		}
	}

	/** Puts every overlay back to its factory position and size. */
	public static void resetPositions() {
		CubeonHudConfig defaults = new CubeonHudConfig();
		instance.fpsX = defaults.fpsX;
		instance.fpsY = defaults.fpsY;
		instance.keysX = defaults.keysX;
		instance.keysY = defaults.keysY;
		instance.armorX = defaults.armorX;
		instance.armorY = defaults.armorY;
		instance.pingX = defaults.pingX;
		instance.pingY = defaults.pingY;
		instance.cpsX = defaults.cpsX;
		instance.cpsY = defaults.cpsY;
		instance.resetScales();
	}

	public static final float MIN_SCALE = 0.5F;
	public static final float MAX_SCALE = 2.0F;

	/** The size of one overlay ("fps", "keys", "armor", "ping", "cps"). */
	public float scaleFor(String slot) {
		Float value = switch (slot) {
			case "fps" -> fpsScale;
			case "keys" -> keysScale;
			case "armor" -> armorScale;
			case "ping" -> pingScale;
			case "cps" -> cpsScale;
			default -> null;
		};
		return value == null ? clampScale(scale) : clampScale(value);
	}

	/** Sets one overlay's size and saves. Unknown slots are ignored. */
	public void setScaleFor(String slot, float value) {
		float clamped = clampScale(value);
		switch (slot) {
			case "fps" -> fpsScale = clamped;
			case "keys" -> keysScale = clamped;
			case "armor" -> armorScale = clamped;
			case "ping" -> pingScale = clamped;
			case "cps" -> cpsScale = clamped;
			default -> {
				return;
			}
		}
		save();
	}

	/** Clears the per-overlay sizes, so every overlay uses {@link #scale} again. */
	public void resetScales() {
		fpsScale = null;
		keysScale = null;
		armorScale = null;
		pingScale = null;
		cpsScale = null;
		// The reset button means "back to how a fresh install looks", so the
		// legacy shared value goes back to 1.0 too - leaving it at an old
		// global size would make every overlay still oversized after a reset
		// that visibly did nothing.
		scale = 1.0F;
	}

	private static float clampScale(float value) {
		if (Float.isNaN(value)) {
			return 1.0F;
		}
		return Math.max(MIN_SCALE, Math.min(MAX_SCALE, value));
	}

	/**
	 * The motion-blur strength as a 0..3 level. A config from before the
	 * strength setting existed has a null field, so it falls back to the old
	 * boolean: OFF stays OFF, ON becomes Medium (the old single effect's feel).
	 */
	public int blurStrength() {
		if (motionBlurStrength == null) {
			return motionBlur ? 2 : 0;
		}

		return Math.max(0, Math.min(3, motionBlurStrength));
	}

	/** Sets the strength and keeps the legacy boolean in step with it. */
	public void setBlurStrength(int value) {
		motionBlurStrength = Math.max(0, Math.min(3, value));
		motionBlur = motionBlurStrength > 0;
	}

	public static float clamp01(float value) {
		if (Float.isNaN(value)) {
			return 0.0F;
		}

		return Math.max(0.0F, Math.min(1.0F, value));
	}

	private void clampAll() {
		fpsX = clamp01(fpsX);
		fpsY = clamp01(fpsY);
		keysX = clamp01(keysX);
		keysY = clamp01(keysY);
		armorX = clamp01(armorX);
		armorY = clamp01(armorY);
		pingX = clamp01(pingX);
		pingY = clamp01(pingY);
		cpsX = clamp01(cpsX);
		cpsY = clamp01(cpsY);

		scale = clampScale(scale);

		if (fpsScale != null) fpsScale = clampScale(fpsScale);
		if (keysScale != null) keysScale = clampScale(keysScale);
		if (armorScale != null) armorScale = clampScale(armorScale);
		if (pingScale != null) pingScale = clampScale(pingScale);
		if (cpsScale != null) cpsScale = clampScale(cpsScale);

		// 1 is "no zoom" and would make the hold key look broken, so the
		// useful range starts a little in.
		if (Float.isNaN(zoomFactor)) zoomFactor = 4.0F;
		if (zoomFactor < 1.25F) zoomFactor = 1.25F;
		if (zoomFactor > 8.0F) zoomFactor = 8.0F;
	}
}
