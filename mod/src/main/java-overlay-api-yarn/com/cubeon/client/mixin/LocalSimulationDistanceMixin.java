package com.cubeon.client.mixin;

import net.minecraft.server.integrated.IntegratedServer;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.ModifyArg;
import org.spongepowered.asm.mixin.injection.Slice;

/** Apply the chosen simulation distance only to this client's local server. */
@Mixin(IntegratedServer.class)
public abstract class LocalSimulationDistanceMixin {
    @ModifyArg(method = "tick", index = 0, require = 0,
            at = @At(value = "INVOKE", target = "Ljava/lang/Math;max(II)I"),
            slice = @Slice(from = @At(value = "INVOKE", target = "Lnet/minecraft/client/option/GameOptions;getSimulationDistance()Lnet/minecraft/client/option/SimpleOption;"),
                    to = @At(value = "INVOKE", target = "Lnet/minecraft/server/PlayerManager;setSimulationDistance(I)V")))
    private int cubeon$localSimulationMinimum(int original) { return 1; }
}
