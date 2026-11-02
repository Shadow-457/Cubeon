package com.cubeon.client.mixin;

import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Pseudo;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.ModifyArg;

/** Optional Sodium 0.8+ builder layout: the first two General ranges are distances. */
@Pseudo
@Mixin(targets = "net.caffeinemc.mods.sodium.client.gui.SodiumConfigBuilder", remap = false)
public abstract class SodiumDistanceMixin {
    @ModifyArg(method = "buildGeneralPage", index = 0, require = 0, remap = false,
            at = @At(value = "INVOKE", ordinal = 0,
                    target = "Lnet/caffeinemc/mods/sodium/api/config/structure/IntegerOptionBuilder;setRange(III)Lnet/caffeinemc/mods/sodium/api/config/structure/IntegerOptionBuilder;"))
    private int cubeon$renderMinimum(int original) { return 1; }

    @ModifyArg(method = "buildGeneralPage", index = 0, require = 0, remap = false,
            at = @At(value = "INVOKE", ordinal = 1,
                    target = "Lnet/caffeinemc/mods/sodium/api/config/structure/IntegerOptionBuilder;setRange(III)Lnet/caffeinemc/mods/sodium/api/config/structure/IntegerOptionBuilder;"))
    private int cubeon$simulationMinimum(int original) { return 1; }
}
