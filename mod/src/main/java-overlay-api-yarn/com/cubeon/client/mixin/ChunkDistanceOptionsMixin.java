package com.cubeon.client.mixin;

import net.minecraft.client.option.GameOptions;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Constant;
import org.spongepowered.asm.mixin.injection.ModifyConstant;
import org.spongepowered.asm.mixin.injection.Slice;

/** Lower only these two ranges; their codec, maximum and defaults stay native. */
@Mixin(GameOptions.class)
public abstract class ChunkDistanceOptionsMixin {
    @ModifyConstant(method = "<init>", constant = @Constant(intValue = 2), require = 0,
            slice = @Slice(from = @At(value = "CONSTANT", args = "stringValue=options.renderDistance"),
                    to = @At(value = "FIELD", target = "Lnet/minecraft/client/option/GameOptions;viewDistance:Lnet/minecraft/client/option/SimpleOption;")))
    private int cubeon$renderMinimum(int original) { return 1; }

    @ModifyConstant(method = "<init>", constant = {@Constant(intValue = 5), @Constant(intValue = 2)}, require = 0,
            slice = @Slice(from = @At(value = "CONSTANT", args = "stringValue=options.simulationDistance"),
                    to = @At(value = "FIELD", target = "Lnet/minecraft/client/option/GameOptions;simulationDistance:Lnet/minecraft/client/option/SimpleOption;")))
    private int cubeon$simulationMinimum(int original) { return 1; }
}
