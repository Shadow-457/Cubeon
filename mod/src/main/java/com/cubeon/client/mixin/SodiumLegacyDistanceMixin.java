package com.cubeon.client.mixin;

import com.cubeon.client.ChunkDistanceOptions;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Pseudo;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Coerce;
import org.spongepowered.asm.mixin.injection.ModifyVariable;

/** Optional Sodium 0.4–0.7 layouts; identify distances by translation key. */
@Pseudo
@Mixin(targets = {"me.jellysquid.mods.sodium.client.gui.options.control.SliderControl",
        "net.caffeinemc.mods.sodium.client.gui.options.control.SliderControl"}, remap = false)
public abstract class SodiumLegacyDistanceMixin {
    @ModifyVariable(method = {
            "<init>(Lme/jellysquid/mods/sodium/client/gui/options/Option;IIILme/jellysquid/mods/sodium/client/gui/options/control/ControlValueFormatter;)V",
            "<init>(Lnet/caffeinemc/mods/sodium/client/gui/options/Option;IIILnet/caffeinemc/mods/sodium/client/gui/options/control/ControlValueFormatter;)V"
    }, at = @At("HEAD"), argsOnly = true, ordinal = 0, require = 0, remap = false)
    private static int cubeon$distanceMinimum(int original, @Coerce Object option,
                                       int min, int max, int step, @Coerce Object formatter) {
        return ChunkDistanceOptions.sodiumMinimum(option, original);
    }
}
