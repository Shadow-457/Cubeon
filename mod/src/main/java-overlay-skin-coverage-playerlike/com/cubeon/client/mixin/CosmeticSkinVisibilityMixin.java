package com.cubeon.client.mixin;

import com.cubeon.client.cosmetics.CosmeticPlayers;
import com.cubeon.client.cosmetics.CosmeticSkinCoverage;
import net.minecraft.entity.player.PlayerEntity;
import net.minecraft.entity.PlayerLikeEntity;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Coerce;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

@Mixin(PlayerLikeEntity.class)
public abstract class CosmeticSkinVisibilityMixin {
    @Inject(method = "isModelPartVisible", at = @At("RETURN"), cancellable = true)
    private void cubeon$coveredLayer(@Coerce Object part, CallbackInfoReturnable<Boolean> ci) {
        if (ci.getReturnValue() && (Object) this instanceof PlayerEntity player && part instanceof Enum<?> value
                && CosmeticSkinCoverage.hidden(CosmeticPlayers.selection(player), value.name()))
            ci.setReturnValue(false);
    }
}
