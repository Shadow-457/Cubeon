package com.cubeon.client.lod.mixin;
import com.cubeon.client.lod.LodClient;
import net.minecraft.client.Minecraft;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.*;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(Minecraft.class)
public abstract class LodLifecycleMixin {
    @Inject(method = "tick", at = @At("TAIL"))
    private void cubeon$lodTick(CallbackInfo ci) { LodClient.tick(); if (net.fabricmc.loader.api.FabricLoader.getInstance().isModLoaded("sodium")) com.cubeon.client.lod.SodiumLodOptions.refreshStatus(); }
    @Inject(method = "close", at = @At("HEAD"))
    private void cubeon$lodClose(CallbackInfo ci) { LodClient.stop(); }
}
