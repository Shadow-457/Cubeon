package com.cubeon.client.lod;

import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.client.renderer.GameRenderer;
import java.util.List;

/** Optional Iris boundary; ordinary clients never resolve Iris classes. */
public final class IrisAdapter {
    private static final boolean PRESENT = FabricLoader.getInstance().isModLoaded("iris");
    private static String reason = "";
    public static boolean active() {
        return PRESENT && net.irisshaders.iris.api.v0.IrisApi.getInstance().isShaderPackInUse();
    }
    public static boolean allowed(LodOptions.Value options) {
        if (!active()) return true;
        if (!options.shaderIntegration()) { reason = "Paused: shader integration is off while an Iris pack is active"; return false; }
        reason = "Paused: Iris LOD stages are not available";
        return false;
    }
    public static String reason() { return reason; }
    public static void render(GameRenderer renderer, List<PackedMesh> meshes) { }
}
