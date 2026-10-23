package com.cubeon.client.hud.mixin;

import com.cubeon.client.hud.MotionBlur;
import net.minecraft.client.Minecraft;
import net.minecraft.client.renderer.GameRenderer;
import net.minecraft.resources.Identifier;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Shadow;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/**
 * Asks for Cubeon's motion-blur post effect every frame (2026-10-24).
 *
 * <p>26.1/26.2 hold a single {@code postEffectId} and apply it after the world
 * is rendered but before the GUI, which is exactly the order a motion blur
 * wants: the world smears, the HUD stays sharp. Vanilla clears that id every
 * tick ({@code checkEntityPostEffect} calls {@code clearPostEffect} for anything
 * that is not a spectated creeper/spider/enderman), so it has to be re-armed at
 * the start of each render.
 *
 * <p>An id that is already set is left alone. That is what keeps the creeper,
 * spider and enderman spectator effects working: vanilla set those during the
 * tick, and motion blur only fills the empty slot.
 *
 * <p>{@code postEffectId}/{@code effectActive} are set directly instead of
 * calling the private {@code setPostEffect}, because that method is literally
 * "assign the id, set effectActive = true" and shadowing two fields needs no
 * accessor mixin (verified with javap on 26.1 and 26.2).
 */
@Mixin(GameRenderer.class)
public class MotionBlurMixin {
	@Shadow
	private Identifier postEffectId;

	@Shadow
	private boolean effectActive;

	@Inject(method = "render", at = @At("HEAD"))
	private void cubeon$applyMotionBlur(CallbackInfo ci) {
		if (!MotionBlur.active()) {
			return;
		}

		Minecraft minecraft = Minecraft.getInstance();

		// Title screen, loading screen, disconnected: there is no world frame to
		// smear, and the previous frame may be from a completely different place.
		if (minecraft.level == null || minecraft.player == null) {
			return;
		}

		if (this.postEffectId != null) {
			return;
		}

		this.postEffectId = Identifier.fromNamespaceAndPath(MotionBlur.NAMESPACE, MotionBlur.PATH);
		this.effectActive = true;
	}
}
