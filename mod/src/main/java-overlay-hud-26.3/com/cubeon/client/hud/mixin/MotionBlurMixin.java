package com.cubeon.client.hud.mixin;

import com.cubeon.client.hud.MotionBlur;
import net.minecraft.client.DeltaTracker;
import net.minecraft.client.Minecraft;
import net.minecraft.client.renderer.GameRenderer;
import net.minecraft.resources.Identifier;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

import java.util.List;

/**
 * Puts Cubeon's motion-blur post effect on the frame's requested list
 * (2026-10-24).
 *
 * <p>26.3 replaced the single {@code postEffectId} with a list that is rebuilt
 * every frame in {@code GameRenderer.update}: the update clears it, adds
 * vanilla's end-of-frame effect, the player's own effects and the spectated
 * entity's effect, and {@code extract} copies it into the render state that
 * {@code render} applies. Adding to the tail of that list is therefore both
 * safe (nothing else is lost) and correctly ordered (vanilla's effects run
 * first, motion blur composites their result).
 *
 * <p>The list is only copied when a player render state exists, so the title
 * screen and loading screens never get the effect even without the extra check
 * below; the check is kept because a level with no player is still a state the
 * effect must not remember.
 */
@Mixin(GameRenderer.class)
public class MotionBlurMixin {
	@Inject(method = "update(Lnet/minecraft/client/DeltaTracker;)V", at = @At("TAIL"))
	private void cubeon$requestMotionBlur(DeltaTracker delta, CallbackInfo ci) {
		if (!MotionBlur.active()) {
			return;
		}

		Minecraft minecraft = Minecraft.getInstance();

		if (minecraft.level == null || minecraft.player == null) {
			return;
		}

		GameRenderer renderer = (GameRenderer) (Object) this;
		Identifier id = Identifier.fromNamespaceAndPath(MotionBlur.NAMESPACE, MotionBlur.PATH);
		List<Identifier> requested = renderer.getRequestedPostEffects();

		if (!requested.contains(id)) {
			requested.add(id);
		}
	}
}
