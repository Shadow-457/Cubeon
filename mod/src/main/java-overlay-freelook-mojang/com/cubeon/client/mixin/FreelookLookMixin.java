package com.cubeon.client.mixin;

import com.cubeon.client.hud.FreelookController;
import net.minecraft.client.MouseHandler;
import net.minecraft.client.player.LocalPlayer;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Redirect;

@Mixin(MouseHandler.class)
public abstract class FreelookLookMixin {
    @Redirect(method = "turnPlayer", at = @At(value = "INVOKE",
            target = "Lnet/minecraft/client/player/LocalPlayer;turn(DD)V"))
    private void cubeon$freelookLook(LocalPlayer player, double dx, double dy) {
        if (!FreelookController.look(dx, dy)) player.turn(dx, dy);
    }
}
