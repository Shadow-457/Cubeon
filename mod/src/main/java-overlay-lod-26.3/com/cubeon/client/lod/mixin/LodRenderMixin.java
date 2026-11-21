package com.cubeon.client.lod.mixin;
import com.cubeon.client.lod.LodClient;
import com.cubeon.client.lod.LodRenderer;
import net.minecraft.client.renderer.LevelRenderer;
import net.minecraft.client.Minecraft;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.*;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/** Before hands and post effects. Higher priority also runs before Iris's final composite. */
@Mixin(value = LevelRenderer.class, priority = 1100)
public abstract class LodRenderMixin {
    @Inject(method = "render", at = @At("TAIL"))
    private void cubeon$lodRender(CallbackInfo ci) {
        if (LodClient.enabled()) LodRenderer.render(Minecraft.getInstance().gameRenderer);
    }
}
