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

	/** Puts both overlays back to their factory positions. */
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
	}
}
