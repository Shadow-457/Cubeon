package com.emotesmod.mixin.client;

import com.emotesmod.client.EmotePoses;
import net.minecraft.client.render.entity.model.BipedEntityModel;
import net.minecraft.client.render.entity.state.BipedEntityRenderState;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/**
 * Applies the active emote after vanilla has finished posing the model.
 *
 * <p>Hooking {@link BipedEntityModel} rather than {@code PlayerEntityModel} means armour,
 * and any other biped equipment model, follows the emote as well: they all receive the very
 * same {@link BipedEntityRenderState} instance, so the entity id needed to look up the
 * emote is available for every one of them.
 *
 * <p>{@code setAngles} calls {@code resetTransforms()} first, so this runs on a clean pose
 * every time and is safe even though the renderer may call it more than once per frame.
 */
@Mixin(BipedEntityModel.class)
public abstract class ModelMixin {
	@Inject(
			method = "setAngles(Lnet/minecraft/client/render/entity/state/BipedEntityRenderState;)V",
			at = @At("TAIL")
	)
	private void emotes$applyEmote(BipedEntityRenderState state, CallbackInfo ci) {
		EmotePoses.apply((BipedEntityModel<?>) (Object) this, state);
	}
}
