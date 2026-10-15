package dev.keyhud.client;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import net.fabricmc.loader.api.FabricLoader;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

/**
 * Persisted toggles and overlay positions, stored as keyhud.json in the config folder.
 *
 * <p>Positions are kept as fractions of the free space that is left after the overlay's
 * own size is subtracted from the screen, so a saved spot stays at the same relative
 * place at any window size, resolution or aspect ratio.
 */
public final class KeyHudConfig {
	private static final Gson GSON = new GsonBuilder().setPrettyPrinting().create();
	private static final Path FILE = FabricLoader.getInstance().getConfigDir().resolve("keyhud.json");

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

	private static KeyHudConfig instance = new KeyHudConfig();

	private KeyHudConfig() {
	}

	public static KeyHudConfig get() {
		return instance;
	}

	public static void load() {
		try {
			if (Files.exists(FILE)) {
				KeyHudConfig loaded = GSON.fromJson(Files.readString(FILE, StandardCharsets.UTF_8), KeyHudConfig.class);

				if (loaded != null) {
					instance = loaded;
				}
			}
		} catch (Exception e) {
			KeyHudClient.LOGGER.warn("Could not read keyhud.json, using defaults.", e);
		}

		instance.clampAll();
	}

	public static void save() {
		try {
			instance.clampAll();
			Files.writeString(FILE, GSON.toJson(instance) + System.lineSeparator(), StandardCharsets.UTF_8);
		} catch (Exception e) {
			KeyHudClient.LOGGER.warn("Could not write keyhud.json.", e);
		}
	}

	/** Puts both overlays back to their factory positions. */
	public static void resetPositions() {
		KeyHudConfig defaults = new KeyHudConfig();
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
