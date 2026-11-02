package com.cubeon.client.hud;

import net.minecraft.client.MinecraftClient;
import net.minecraft.client.texture.Sprite;
import net.minecraft.entity.effect.StatusEffect;
import net.minecraft.registry.entry.RegistryEntry;
import net.minecraft.text.Text;
import net.minecraft.world.LightType;
import java.util.ArrayList;
import java.util.Locale;
import java.lang.ref.WeakReference;

/** Client-tick reads only; disabled features do no world/terrain/system sampling. */
public final class HudReadings {
    private static boolean inWorld;
    private static WeakReference<Object> world = new WeakReference<>(null);
    private static int ticks;
    private HudReadings() { }
    public static boolean screenOpen() { return MinecraftClient.getInstance().currentScreen != null; }
    public static void tick() {
        var client = MinecraftClient.getInstance();
        if (world.get() != client.world || inWorld != (client.world != null)) {
            ExtraHud.reset(); world = new WeakReference<>(client.world); ticks = 0; inWorld = client.world != null;
        }
        var config = CubeonHudConfig.get();
        if (client.world == null || client.player == null || !config.extrasEnabled()) return;
        ticks++;
        var player = client.player; var level = client.world;
        ExtraHud.position(player.getX(), player.getY(), player.getZ(), player.getYaw());
        if (ticks % 5 == 1 && (config.extraEnabled("biome") || config.extraEnabled("daylight") || (config.extraEnabled("clock") && config.worldClock))) {
            var position = player.getBlockPos();
            String name = "";
            if (config.extraEnabled("biome")) name = level.getBiome(position).getKey().map(key -> {
                var id = key.getValue();
                String keyName = "biome." + id.getNamespace() + "." + id.getPath().replace('/', '.');
                String translated = Text.translatable(keyName).getString();
                return translated.equals(keyName) ? biomeName(id.getPath()) : translated;
            }).orElse("—");
            ExtraHud.environment(level.getTimeOfDay(), name,
                    config.extraEnabled("daylight") ? level.getLightLevel(LightType.BLOCK, position) : 0,
                    config.extraEnabled("daylight") ? level.getLightLevel(LightType.SKY, position) : 0);
        }
        if (config.extraEnabled("system") && ticks % 20 == 1) ExtraHud.system(client.getGpuUtilizationPercentage());
        if (config.extraEnabled("potions") && ticks % 5 == 1) {
            var effects = new ArrayList<ExtraHud.Effect>();
            for (var instance : player.getStatusEffects()) {
                if (!instance.shouldShowIcon()) continue;
                Object type = instance.getEffectType();
                StatusEffect effect = (StatusEffect)(type instanceof RegistryEntry<?> entry ? entry.value() : type);
                int seconds = instance.getDuration() / 20;
                String duration = instance.getDuration() < 0 ? "∞" : String.format(Locale.ROOT, "%d:%02d", seconds / 60, seconds % 60);
                effects.add(new ExtraHud.Effect(effect.getName().getString(), duration, effect.getColor(), instance.getAmplifier(), sprite(type)));
                if (effects.size() == 6) break;
            }
            ExtraHud.effects(effects);
        }
    }
    private static Sprite sprite(Object type) {
        StatusEffect effect = (StatusEffect)(type instanceof RegistryEntry<?> entry ? entry.value() : type);
        return com.cubeon.client.hud.screen.ClientUiDraw.effectIcon(net.minecraft.registry.Registries.STATUS_EFFECT.getId(effect));
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
