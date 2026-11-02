package com.cubeon.client.hud;

import net.minecraft.client.Minecraft;
import net.minecraft.world.level.LightLayer;
import net.minecraft.network.chat.Component;
import java.util.ArrayList;
import java.util.Locale;
import java.lang.ref.WeakReference;

/** Client-tick reads only; disabled features do no world/terrain/system sampling. */
public final class HudReadings {
    private static boolean inWorld;
    private static WeakReference<Object> world = new WeakReference<>(null);
    private static int ticks;
    private HudReadings() { }
    public static boolean screenOpen() { return CubeonHud.screenOpen(); }
    public static void tick() {
        var client = Minecraft.getInstance();
        if (world.get() != client.level || inWorld != (client.level != null)) {
            ExtraHud.reset(); world = new WeakReference<>(client.level); ticks = 0; inWorld = client.level != null;
        }
        var config = CubeonHudConfig.get();
        if (client.level == null || client.player == null || !config.extrasEnabled()) return;
        ticks++;
        var player = client.player; var level = client.level;
        ExtraHud.position(player.getX(), player.getY(), player.getZ(), player.getYRot());
        if (ticks % 5 == 1 && (config.extraEnabled("biome") || config.extraEnabled("daylight") || (config.extraEnabled("clock") && config.worldClock))) {
            var position = player.blockPosition();
            String name = "";
            if (config.extraEnabled("biome")) name = level.getBiome(position).unwrapKey().map(key -> {
                var id = key.identifier();
                String keyName = "biome." + id.getNamespace() + "." + id.getPath().replace('/', '.');
                String translated = Component.translatable(keyName).getString();
                return translated.equals(keyName) ? biomeName(id.getPath()) : translated;
            }).orElse("—");
            ExtraHud.environment(level.getDefaultClockTime(), name,
                    config.extraEnabled("daylight") ? level.getBrightness(LightLayer.BLOCK, position) : 0,
                    config.extraEnabled("daylight") ? level.getBrightness(LightLayer.SKY, position) : 0);
        }
        if (config.extraEnabled("system") && ticks % 20 == 1) ExtraHud.system(client.getGpuUtilization());
        if (config.extraEnabled("potions") && ticks % 5 == 1) {
            var effects = new ArrayList<ExtraHud.Effect>();
            for (var instance : player.getActiveEffects()) {
                if (!instance.showIcon()) continue;
                var effect = instance.getEffect().value();
                int seconds = instance.getDuration() / 20;
                String duration = instance.getDuration() < 0 ? "∞" : String.format(Locale.ROOT, "%d:%02d", seconds / 60, seconds % 60);
                var icon = instance.getEffect().unwrapKey().map(key -> key.identifier().withPrefix("mob_effect/")).orElse(null);
                effects.add(new ExtraHud.Effect(effect.getDisplayName().getString(), duration, effect.getColor(), instance.getAmplifier(), icon));
                if (effects.size() == 6) break;
            }
            ExtraHud.effects(effects);
        }
    }
    private static String biomeName(String path) {
        StringBuilder label = new StringBuilder();
        for (String word : path.replace('/', '_').split("_")) {
            if (word.isEmpty()) continue;
            if (label.length() > 0) label.append(' ');
            label.append(Character.toUpperCase(word.charAt(0))).append(word.substring(1));
        }
        return label.toString();
    }
}
