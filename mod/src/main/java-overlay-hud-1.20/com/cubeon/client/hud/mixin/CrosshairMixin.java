package com.cubeon.client.hud.mixin;

import com.cubeon.client.hud.CrosshairScale;
import com.cubeon.client.hud.CubeonHudConfig;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.gui.DrawContext;
import net.minecraft.client.gui.hud.InGameHud;
import net.minecraft.client.util.math.MatrixStack;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/**
 * Scales the vanilla crosshair around the centre of the screen while it is over
 * an entity (2026-10-24).
 *
 * <p>Minecraft's own {@code renderCrosshair} is wrapped instead of reimplemented.
 * That method has changed its parameters and internals several times across
 * 1.20-1.21, but the crosshair is always drawn at the centre of the GUI through
 * the DrawContext's matrix stack, so one push at HEAD and one pop at RETURN
 * survives every one of those changes - and vanilla's attack indicator,
 * spectator handling and HUD hiding stay exactly as they were.
 *
 * <p>The injection names the method without a descriptor on purpose: 1.20.2-1.20.6
 * take only the DrawContext while 1.21-1.21.5 also take a RenderTickCounter, and
 * a name-only target resolves against whichever one the running jar has.
 */
@Mixin(InGameHud.class)
public class CrosshairMixin {
	/** Set at HEAD when this frame pushed a transform, cleared at RETURN. */
	private static MatrixStack cubeon$matrices;

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

		MatrixStack matrices = context.getMatrices();
		float centerX = context.getScaledWindowWidth() / 2.0F;
		float centerY = context.getScaledWindowHeight() / 2.0F;

		matrices.push();
		matrices.translate(centerX, centerY, 0.0F);
		matrices.scale(scale, scale, 1.0F);
		matrices.translate(-centerX, -centerY, 0.0F);

		cubeon$matrices = matrices;
	}

	@Inject(method = "renderCrosshair", at = @At("RETURN"))
	private void cubeon$restoreCrosshair(CallbackInfo ci) {
		if (cubeon$matrices != null) {
			cubeon$matrices.pop();
			cubeon$matrices = null;
		}
	}
}
