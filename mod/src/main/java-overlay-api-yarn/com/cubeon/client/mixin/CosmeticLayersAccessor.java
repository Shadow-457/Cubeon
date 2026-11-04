package com.cubeon.client.mixin;

import java.util.List;
import net.minecraft.client.render.entity.LivingEntityRenderer;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.gen.Accessor;

/** Layer ordering during renderer registration, never during a render iteration. */
@Mixin(LivingEntityRenderer.class)
public interface CosmeticLayersAccessor {
    @Accessor("features")
    List<?> cubeon$getCosmeticLayers();
}
