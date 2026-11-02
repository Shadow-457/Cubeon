package com.cubeon.client.mixin;

import net.minecraft.client.server.IntegratedServer;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.ModifyArg;
import org.spongepowered.asm.mixin.injection.Slice;

/** Apply the chosen simulation distance only to this client's local server. */
@Mixin(IntegratedServer.class)
public abstract class LocalSimulationDistanceMixin {
    @ModifyArg(method = "tickServer", index = 0, require = 0,
            at = @At(value = "INVOKE", target = "Ljava/lang/Math;max(II)I"),
            slice = @Slice(from = @At(value = "INVOKE", target = "Lnet/minecraft/client/Options;simulationDistance()Lnet/minecraft/client/OptionInstance;"),
                    to = @At(value = "INVOKE", target = "Lnet/minecraft/server/players/PlayerList;setSimulationDistance(I)V")))
    private int cubeon$localSimulationMinimum(int original) { return 1; }
}
