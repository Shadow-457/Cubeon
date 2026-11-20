package com.cubeon.client.mixin;

import com.cubeon.client.hud.FullBright;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.option.SimpleOption;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

/** Overrides lighting options only during lightmap work; saved settings stay intact. */
@Mixin(SimpleOption.class)
public abstract class FullBrightOptionMixin<T> {
    @SuppressWarnings("unchecked")
    @Inject(method = "getValue()Ljava/lang/Object;", at = @At("RETURN"), cancellable = true, require = 1)
    private void cubeon$gamma(CallbackInfoReturnable<T> ci) {
        if (!FullBright.isActive() || !(ci.getReturnValue() instanceof Double value)) return;
        var client = MinecraftClient.getInstance();
        if (client == null || client.options == null) return;
        if ((Object)this == client.options.getGamma())
            ci.setReturnValue((T)Double.valueOf(FullBright.gamma(value)));
        else if ((Object)this == client.options.getDarknessEffectScale())
            ci.setReturnValue((T)Double.valueOf(FullBright.darkness(value)));
    }
}
