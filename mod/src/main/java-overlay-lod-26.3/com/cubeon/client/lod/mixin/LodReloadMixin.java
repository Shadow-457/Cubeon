package com.cubeon.client.lod.mixin;
import com.cubeon.client.lod.LodClient;
import com.cubeon.client.lod.LodRenderer;
import net.minecraft.client.renderer.GameRenderer;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.*;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(GameRenderer.class)
public abstract class LodReloadMixin {
    @Inject(method = "render", at = @At("HEAD"))
    private void cubeon$lodFrame(CallbackInfo ci) { LodRenderer.beginFrame(); }
    @Inject(method = "close", at = @At("HEAD"))
    private void cubeon$lodClose(CallbackInfo ci) { LodRenderer.shutdown(); }
    @Inject(method = "onResourceManagerReload", at = @At("HEAD"))
    private void cubeon$lodReload(CallbackInfo ci) { LodClient.reload(); }
}
