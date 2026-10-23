package com.cubeon.client.hud.mixin;

import com.cubeon.client.hud.CrosshairScale;
import com.cubeon.client.hud.CubeonHudConfig;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.gui.DrawContext;
import net.minecraft.client.gui.hud.InGameHud;
import org.joml.Matrix3x2fStack;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/**
 * Scales the vanilla crosshair around the centre of the screen while it is over
 * an entity (2026-10-24).
 *
 * <p>1.21.6 replaced DrawContext's {@code MatrixStack} with JOML's
 * {@code Matrix3x2fStack}, so this is the same wrapper as the 1.20-era copy with
 * push/pop and 2D translate/scale instead of the 3D matrix calls. Everything
 * else - the HEAD/RETURN pair, the centre pivot, the reasoning for wrapping
 * vanilla instead of reimplementing it - is unchanged.
 */
@Mixin(InGameHud.class)
public class CrosshairMixin {
	/** Set at HEAD when this frame pushed a transform, cleared at RETURN. */
	private static Matrix3x2fStack cubeon$matrices;

	@Inject(method = "renderCrosshair", at = @At("HEAD"))
	private void cubeon$scaleCrosshair(DrawContext context, CallbackInfo ci) {
		if (!CubeonHudConfig.get().dynamicCrosshair) {
			CrosshairScale.reset();
			return;
		}

		float scale = CrosshairScale.update(MinecraftClient.getInstance().targetedEntity != null);

		if (scale <= CrosshairScale.IDLE) {
			return;
		}

		Matrix3x2fStack matrices = context.getMatrices();
		float centerX = context.getScaledWindowWidth() / 2.0F;
		float centerY = context.getScaledWindowHeight() / 2.0F;

		matrices.pushMatrix();
		matrices.translate(centerX, centerY);
		matrices.scale(scale, scale);
		matrices.translate(-centerX, -centerY);

		cubeon$matrices = matrices;
	}

	@Inject(method = "renderCrosshair", at = @At("RETURN"))
	private void cubeon$restoreCrosshair(CallbackInfo ci) {
		if (cubeon$matrices != null) {
			cubeon$matrices.popMatrix();
			cubeon$matrices = null;
		}
	}
}
