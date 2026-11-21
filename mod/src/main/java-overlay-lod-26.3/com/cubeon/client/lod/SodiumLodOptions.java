package com.cubeon.client.lod;

import java.io.IOException;
import java.util.function.*;
import net.caffeinemc.mods.sodium.api.config.*;
import net.caffeinemc.mods.sodium.api.config.structure.*;
import net.minecraft.network.chat.Component;
import net.minecraft.resources.Identifier;

/** Public Sodium config extension: its controls own pending values and Apply/Cancel. */
public final class SodiumLodOptions implements ConfigEntryPoint {
    /** Replace the backing component so Minecraft's visual-order cache cannot retain old text. */
    private static final class StatusText implements Component {
        private Component value = Component.literal("LOD is off");
        public net.minecraft.network.chat.ComponentContents getContents() { return value.getContents(); }
        public net.minecraft.network.chat.Style getStyle() { return value.getStyle(); }
        public java.util.List<Component> getSiblings() { return value.getSiblings(); }
        public net.minecraft.util.FormattedCharSequence getVisualOrderText() { return value.getVisualOrderText(); }
    }
    private static final StatusText STATUS = new StatusText();
    private static String shown = "";
    public static void refreshStatus() {
        String value = LodClient.status();
        if (!value.equals(shown)) { shown = value; STATUS.value = Component.literal(value); }
    }
    private LodOptions.Value pending;
    private StorageEventHandler storage;
    public void registerConfigEarly(ConfigBuilder builder) { }
    public void registerConfigLate(ConfigBuilder builder) {
        var config = LodClient.options(); pending = config.active(); refreshStatus();
        storage = new StorageEventHandler() {
            public void afterSave() {
                try { config.commit(pending); LodClient.applied(); }
                catch (IOException error) { LodClient.LOG.warn("LOD options were not applied", error); }
                refreshStatus();
            }
        };
        var page = builder.createOptionPage().setName(label("page"));
        var general = builder.createOptionGroup().setName(label("terrain"));
        general.addOption(bool(builder, "enabled", v -> v.enabled(), n -> pending = new LodOptions.Value(n, pending.distance(), pending.detail(), pending.processing(), pending.backgroundUpdates(), pending.terrainCache(), pending.shaderIntegration(), pending.shadows()), false));
        general.addOption(builder.createIntegerOption(id("distance")).setName(label("distance"))
                .setRange(0, 7, 1).setDefaultValue(2).setStorageHandler(storage)
                .setValueFormatter(n -> Component.literal(LodOptions.DISTANCES[n] + " chunks"))
                .setTooltip(label("distance.tooltip")).setBinding(n -> pending = new LodOptions.Value(pending.enabled(), LodOptions.DISTANCES[n], pending.detail(), pending.processing(), pending.backgroundUpdates(), pending.terrainCache(), pending.shaderIntegration(), pending.shadows()), () -> {
                    int d = config.active().distance(); for (int i = 0; i < 8; i++) if (LodOptions.DISTANCES[i] == d) return i; return 2;
                }));
        general.addOption(builder.createEnumOption(id("detail"), LodOptions.Detail.class).setName(label("detail"))
                .setDefaultValue(LodOptions.Detail.MEDIUM).setStorageHandler(storage).setTooltip(label("detail.tooltip"))
                .setElementNameProvider(n -> label("detail." + n.name().toLowerCase(java.util.Locale.ROOT)))
                .setBinding(n -> pending = new LodOptions.Value(pending.enabled(), pending.distance(), n, pending.processing(), pending.backgroundUpdates(), pending.terrainCache(), pending.shaderIntegration(), pending.shadows()), () -> config.active().detail()));
        general.addOption(builder.createEnumOption(id("processing"), LodOptions.Processing.class).setName(label("processing"))
                .setDefaultValue(LodOptions.Processing.AUTO).setStorageHandler(storage).setTooltip(label("processing.tooltip"))
                .setElementNameProvider(n -> Component.literal(n == LodOptions.Processing.AUTO ? "Auto" : n.name()))
                .setBinding(n -> pending = new LodOptions.Value(pending.enabled(), pending.distance(), pending.detail(), n, pending.backgroundUpdates(), pending.terrainCache(), pending.shaderIntegration(), pending.shadows()), () -> config.active().processing()));
        page.addOptionGroup(general);
        var advanced = builder.createOptionGroup().setName(label("advanced"));
        advanced.addOption(bool(builder, "background", v -> v.backgroundUpdates(), n -> pending = new LodOptions.Value(pending.enabled(), pending.distance(), pending.detail(), pending.processing(), n, pending.terrainCache(), pending.shaderIntegration(), pending.shadows()), true));
        advanced.addOption(bool(builder, "cache", v -> v.terrainCache(), n -> pending = new LodOptions.Value(pending.enabled(), pending.distance(), pending.detail(), pending.processing(), pending.backgroundUpdates(), n, pending.shaderIntegration(), pending.shadows()), true));
        advanced.addOption(bool(builder, "shaders", v -> v.shaderIntegration(), n -> pending = new LodOptions.Value(pending.enabled(), pending.distance(), pending.detail(), pending.processing(), pending.backgroundUpdates(), pending.terrainCache(), n, pending.shadows()), true));
        advanced.addOption(bool(builder, "shadows", v -> v.shadows(), n -> pending = new LodOptions.Value(pending.enabled(), pending.distance(), pending.detail(), pending.processing(), pending.backgroundUpdates(), pending.terrainCache(), pending.shaderIntegration(), n), false));
        advanced.addOption(builder.createExternalButtonOption(id("clear")).setName(label("clear"))
                .setTooltip(label("clear.tooltip")).setScreenConsumer(parent -> LodClient.clearCache()));
        advanced.addOption(builder.createExternalButtonOption(id("status")).setName(STATUS)
                .setTooltip(label("status.tooltip")).setScreenConsumer(parent -> { if (!config.error().isEmpty()) storage.afterSave(); }));
        page.addOptionGroup(advanced);
        builder.registerOwnModOptions().addPage(page);
    }
    private BooleanOptionBuilder bool(ConfigBuilder builder, String name, Function<LodOptions.Value, Boolean> get,
                                      Consumer<Boolean> set, boolean initial) {
        return builder.createBooleanOption(id(name)).setName(label(name)).setTooltip(label(name + ".tooltip"))
                .setDefaultValue(initial).setStorageHandler(storage).setBinding(set, () -> get.apply(LodClient.options().active()));
    }
    private static Identifier id(String name) { return Identifier.parse("cubeon-client:lod/" + name); }
    private static Component label(String name) { return Component.translatable("cubeonclient.lod." + name); }
}
