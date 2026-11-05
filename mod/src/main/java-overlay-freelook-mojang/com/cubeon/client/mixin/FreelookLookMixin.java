package com.cubeon.client.mixin;

import com.cubeon.client.hud.FreelookController;
import com.cubeon.client.hud.CubeonHudKeybinds;
import com.cubeon.client.hud.Zoom;
import net.minecraft.client.MouseHandler;
import net.minecraft.client.player.LocalPlayer;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Unique;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Redirect;

@Mixin(MouseHandler.class)
public abstract class FreelookLookMixin {
    @Unique private final Zoom.LookSmoother cubeon$look = new Zoom.LookSmoother();
    @Redirect(method = "turnPlayer", at = @At(value = "INVOKE",
            target = "Lnet/minecraft/client/player/LocalPlayer;turn(DD)V"))
    private void cubeon$freelookLook(LocalPlayer player, double dx, double dy) {
        if (FreelookController.look(dx, dy)) {
            cubeon$look.apply(0, 0, false);
            return;
        }
        // The 26.3 FOV/key adapter publishes held state. Earlier 26.x leaves it false.
        cubeon$look.apply(dx, dy, Zoom.isHeld() && CubeonHudKeybinds.freelookEligible());
        player.turn(cubeon$look.x, cubeon$look.y);
    }
}
