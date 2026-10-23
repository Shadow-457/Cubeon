package com.emotesmod.mixin.client;

import com.emotesmod.client.EmotePoses;
import net.minecraft.client.model.HumanoidModel;
import net.minecraft.client.renderer.entity.state.HumanoidRenderState;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/**
 * Applies the active emote after vanilla has finished posing the model.
 *
 * <p>Hooking {@link HumanoidModel} rather than the player model means armour and other
 * humanoid equipment follows the emote as well, since they are all handed the same render
 * state. The mixin only acts on {@code AvatarRenderState}, so zombies, villagers and the
 * rest are untouched.
 *
 * <p>{@code setupAnim} calls {@code resetPose()} first, so this runs on a clean pose every
 * time and is safe even though the renderer may call it more than once per frame.
 */
@Mixin(HumanoidModel.class)
public abstract class ModelMixin {
	@Inject(
			method = "setupAnim(Lnet/minecraft/client/renderer/entity/state/HumanoidRenderState;)V",
			at = @At("TAIL")
	)
	private void emotes$applyEmote(HumanoidRenderState state, CallbackInfo ci) {
		EmotePoses.apply((HumanoidModel<?>) (Object) this, state);
	}
}
