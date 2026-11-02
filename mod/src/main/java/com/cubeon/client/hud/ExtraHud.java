package com.cubeon.client.hud;

import com.cubeon.client.ui.ClientUi;
import java.time.LocalTime;
import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.Locale;

/** Bounded shared display state. Native adapters supply readings on the client thread. */
public final class ExtraHud {
    public record Effect(String name, String duration, int color, int amplifier, Object icon) { }
    private static final DateTimeFormatter CLOCK = DateTimeFormatter.ofPattern("HH:mm:ss");
    private static int combo, target = -1;
    private static long lastHit, clockSecond = -1;
    private static String clock = "--:--:--", biome = "", worldTime = "06:00";
    private static long day, ramUsed, ramMax;
    private static double gpu = Double.NaN, px, py, pz;
    private static final String[] DIRECTIONS = {"S", "SW", "W", "NW", "N", "NE", "E", "SE"};
    private static float yaw;
    private static int blockLight, skyLight;
    private static List<Effect> effects = List.of();
    private static List<String> effectLabels = List.of();
    private static String coordinatesXY = "X 0.0   Y 0.0", coordinatesZ = "Z 0.0", compass = "S  180°",
            ramText = "RAM —", gpuText = "GPU frame: —", dayText = "Day 0   06:00", lightText = "Block 0   Sky 0";
    private ExtraHud() { }

    public static void reset() {
        combo = 0; target = -1; lastHit = 0;
        effects = List.of(); effectLabels = List.of();
    }
    public static void position(double x, double y, double z, float rotation) {
        px = x; py = y; pz = z; yaw = rotation;
        if (CubeonHudConfig.get().extraEnabled("coordinates")) {
            coordinatesXY = String.format(Locale.ROOT, "X %.1f   Y %.1f", px, py);
            coordinatesZ = String.format(Locale.ROOT, "Z %.1f", pz);
        }
        if (CubeonHudConfig.get().extraEnabled("direction"))
            compass = DIRECTIONS[Math.floorMod(Math.round(yaw / 45), 8)] + "  " + Math.floorMod(Math.round(yaw + 180), 360) + "°";
    }
    public static void environment(long time, String name, int block, int sky) {
        day = Math.floorDiv(time, 24000);
        int minutes = Math.floorMod(time + 6000, 24000) * 60 / 1000;
        worldTime = String.format(Locale.ROOT, "%02d:%02d", minutes / 60, minutes % 60);
        biome = name; blockLight = block; skyLight = sky;
        dayText = "Day " + day + "   " + worldTime;
        lightText = "Block " + blockLight + "   Sky " + skyLight;
    }
    public static void system(double utilization) {
        Runtime runtime = Runtime.getRuntime();
        ramUsed = (runtime.totalMemory() - runtime.freeMemory()) / 1048576;
        ramMax = runtime.maxMemory() / 1048576;
        gpu = Double.isFinite(utilization) && utilization > 0 ? Math.min(100, utilization) : Double.NaN;
        ramText = "RAM " + ramUsed + " / " + ramMax + " MiB";
        gpuText = Double.isNaN(gpu) ? "GPU frame: —" : "GPU frame: " + Math.round(gpu) + "%";
    }
    public static void effects(List<Effect> values) {
        effects = List.copyOf(values.subList(0, Math.min(6, values.size())));
        effectLabels = effects.stream().map(effect -> effect.name + (effect.amplifier > 0 ? " " + (effect.amplifier + 1) : "")).toList();
    }
    public static List<Effect> effects() { return effects; }
    public static void damage(int damaged, int cause, int direct, int local, long now) {
        if (!CubeonHudConfig.get().extraEnabled("combo")) { combo = 0; target = -1; return; }
        if (damaged == local) { combo = 0; target = -1; return; }
        if (cause != local || direct != local || damaged == local) return;
        combo = target == damaged && now - lastHit >= 0 && now - lastHit <= 3000 ? Math.min(999, combo + 1) : 1;
        target = damaged; lastHit = now;
    }
    public static int combo(long now) { return now - lastHit <= 3000 && now >= lastHit ? combo : 0; }
    public static int height(HudFeatures feature) {
        return feature == HudFeatures.POTIONS ? Math.max(12, 2 + effects.size() * 12) : feature.height;
    }
    /** Match the original HUD: bounds follow text, with just two pixels of padding. */
    public static int width(HudFeatures feature, java.util.function.ToIntFunction<String> measure) {
        int textWidth = switch (feature) {
            case CLOCK -> measure.applyAsInt(CubeonHudConfig.get().worldClock ? worldTime : "00:00:00");
            case SYSTEM -> Math.max(measure.applyAsInt(ramText), measure.applyAsInt(gpuText));
            case COORDINATES -> Math.max(measure.applyAsInt(coordinatesXY), measure.applyAsInt(coordinatesZ));
            case DIRECTION -> measure.applyAsInt(compass);
            case BIOME -> measure.applyAsInt(biome.isBlank() ? "—" : biome);
            case DAYLIGHT -> Math.max(measure.applyAsInt(dayText), measure.applyAsInt(lightText));
            case COMBO -> measure.applyAsInt("Combo " + combo(System.currentTimeMillis()));
            case POTIONS -> {
                int longest = measure.applyAsInt("No active effects");
                for (int i = 0; i < effects.size(); i++) longest = Math.max(longest,
                        14 + measure.applyAsInt(effectLabels.get(i)) + 6 + measure.applyAsInt(effects.get(i).duration));
                yield longest;
            }
            default -> feature.width - 4;
        };
        return Math.max(8, Math.min(feature.width, textWidth + 4));
    }
    public static void render(ClientUi.Canvas canvas, HudFeatures feature, int x, int y, boolean preview) {
        long now = System.currentTimeMillis();
        if (!preview && (feature == HudFeatures.POTIONS && effects.isEmpty()
                || feature == HudFeatures.COMBO && combo(now) == 0)) return;
        int width = width(feature, canvas::width);
        // Same light black backing and white shadowed text as FPS/CPS; no green rim/card.
        canvas.fill(x, y, x + width, y + height(feature), 0x88000000);
        switch (feature) {
            case CLOCK -> {
                if (now / 1000 != clockSecond) { clockSecond = now / 1000; clock = LocalTime.now().format(CLOCK); }
                line(canvas, CubeonHudConfig.get().worldClock ? worldTime : clock, x, y, width, 1);
            }
            case SYSTEM -> {
                line(canvas, ramText, x, y, width, 1);
                line(canvas, gpuText, x, y, width, 12);
            }
            case COORDINATES -> {
                line(canvas, coordinatesXY, x, y, width, 1);
                line(canvas, coordinatesZ, x, y, width, 12);
            }
            case DIRECTION -> {
                line(canvas, compass, x, y, width, 1);
            }
            case BIOME -> line(canvas, biome.isBlank() ? "—" : biome, x, y, width, 1);
            case DAYLIGHT -> {
                line(canvas, dayText, x, y, width, 1);
                line(canvas, lightText, x, y, width, 12);
            }
            case COMBO -> line(canvas, "Combo " + (preview ? 3 : combo(now)), x, y, width, 1);
            case POTIONS -> {
                if (effects.isEmpty()) line(canvas, canvas.translate("cubeonclient.hud.no_effects"), x, y, width, 1);
                for (int i = 0; i < effects.size(); i++) {
                    Effect effect = effects.get(i); int row = y + 1 + i * 12;
                    // Native adapters paint the actual status-effect sprite in this reserved cell.
                    canvas.fill(x + 4, row + 2, x + 10, row + 8, 0xFF000000 | effect.color);
                    String label = effectLabels.get(i);
                    int timerWidth = canvas.width(effect.duration);
                    ClientUi.left(canvas, ClientUi.fit(canvas, label, width - 24 - timerWidth), x + 14, row, 0xFFFFFFFF);
                    ClientUi.left(canvas, effect.duration, x + width - 2 - timerWidth, row, 0xFFFFFFFF);
                }
            }
            default -> { }
        }
    }
    private static void line(ClientUi.Canvas canvas, String value, int x, int y, int width, int offset) {
        ClientUi.left(canvas, ClientUi.fit(canvas, value, width - 4), x + 2, y + offset, 0xFFFFFFFF);
    }
}
