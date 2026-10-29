package com.cubeon.client.mixin;

import com.cubeon.client.hud.CubeonHudKeybinds;
import com.cubeon.client.hud.Zoom;
import net.minecraft.client.Mouse;
import net.minecraft.client.network.ClientPlayerEntity;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Unique;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Redirect;

/** Slow, lightly smoothed look while zooming; never rewrites vanilla options. */
@Mixin(Mouse.class)
public abstract class ZoomLookMixin {
    @Unique private final Zoom.LookSmoother cubeon$look = new Zoom.LookSmoother();

    @Redirect(method = "updateMouse", at = @At(value = "INVOKE",
            target = "Lnet/minecraft/client/network/ClientPlayerEntity;changeLookDirection(DD)V"))
    private void cubeon$zoomLook(ClientPlayerEntity player, double dx, double dy) {
        cubeon$look.apply(dx, dy, CubeonHudKeybinds.zoomActive());
        player.changeLookDirection(cubeon$look.x, cubeon$look.y);
    }
}
