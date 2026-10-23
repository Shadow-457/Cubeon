package com.emotesmod.client;

import com.emotesmod.Emote;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.model.ModelPart;
import net.minecraft.client.render.entity.model.BipedEntityModel;
import net.minecraft.client.render.entity.state.BipedEntityRenderState;
import net.minecraft.client.render.entity.state.PlayerEntityRenderState;
import net.minecraft.entity.EntityPose;
import net.minecraft.util.math.MathHelper;

/**
 * Turns an {@link Emote} plus a point in time into concrete rotations for the biped model.
 *
 * <p>Model space conventions used throughout (verified against vanilla poses):
 * <ul>
 *   <li>{@code pitch} is negative to raise a limb; {@code -PI/2} points an arm forward and
 *       {@code -PI} points it straight up.</li>
 *   <li>{@code roll} is positive to swing a limb outwards for the right arm and outwards
 *       for the left arm when it is negative.</li>
 *   <li>Every limb starts from a clean default because {@code setAngles} calls
 *       {@code resetTransforms()} first, so absolute targets and additive offsets are both safe.</li>
 * </ul>
 */
public final class EmotePoses {
	private static final float HALF_PI = (float) (Math.PI / 2.0);

	private EmotePoses() {
	}

	/**
	 * Blends {@code model} towards the active emote of the entity that {@code state} belongs to.
	 * Does nothing when that entity is not emoting or when a vanilla pose would clash.
	 */
	public static void apply(BipedEntityModel<?> model, BipedEntityRenderState state) {
		// Only players carry an emote; every other biped has its own render state.
		if (!(state instanceof PlayerEntityRenderState playerState)) {
			return;
		}

		// Vanilla already owns these poses - fighting them would look broken.
		if (state.invisible || state.flipUpsideDown || state.deathTime > 0.0F
				|| state.hasVehicle || state.isGliding
				|| state.isInPose(EntityPose.SLEEPING) || playerState.spectator) {
			return;
		}

		ClientEmoteState.Active active = ClientEmoteState.get(playerState.id);

		if (active == null) {
			return;
		}

		Emote emote = active.emote();
		float age = ClientEmoteState.ageSeconds(active, tickProgress());
		float progress = age / emote.durationSeconds();

		// Already finished. The state sweeper removes these a tick later, this just avoids
		// rendering the final frame of a finished emote.
		if (!(progress < 1.0F)) {
			return;
		}

		switch (emote) {
			case WAVE -> wave(model, age, progress);
			case DANCE -> dance(model, age, progress);
			case BOW -> bow(model, age);
			case SALUTE -> salute(model, age, progress);
			case SHRUG -> shrug(model, age);
			case POINT -> point(model, age);
		}
	}

	private static float tickProgress() {
		return MinecraftClient.getInstance().getRenderTickCounter().getTickProgress(false);
	}

	// ---------------------------------------------------------------- emotes

	/** Right arm up and out, sweeping side to side. */
	private static void wave(BipedEntityModel<?> model, float t, float p) {
		float w = envelope(p);
		float sway = MathHelper.sin(t * 7.5F);

		set(model.rightArm, w, -2.45F + sway * 0.30F, -0.30F, 0.55F + sway * 0.45F);
		set(model.leftArm, w, 0.10F - sway * 0.10F, 0.0F, -0.10F);
		add(model.head, w, 0.0F, 0.0F, sway * 0.06F);
		add(model.body, w, 0.0F, MathHelper.sin(t * 3.75F) * 0.06F, 0.0F);
	}

	/** Energetic two-beat dance with a little hop. */
	private static void dance(BipedEntityModel<?> model, float t, float p) {
		float w = envelope(p);
		float beat = MathHelper.sin(t * 8.0F);
		float beatAlt = MathHelper.cos(t * 8.0F);
		float sway = MathHelper.sin(t * 4.0F);

		set(model.body, w, -0.10F + beat * 0.10F, sway * 0.28F, beatAlt * 0.06F);

		set(model.rightArm, w, -1.30F - beatAlt * 0.85F, 0.25F, 0.55F - beat * 0.35F);
		set(model.leftArm, w, -1.30F + beatAlt * 0.85F, -0.25F, -0.55F - beat * 0.35F);

		set(model.rightLeg, w, beat * 0.45F, 0.0F, 0.0F);
		set(model.leftLeg, w, -beat * 0.45F, 0.0F, 0.0F);

		add(model.head, w, -0.10F + beat * 0.12F, sway * 0.30F, 0.0F);

		float hop = Math.abs(beat) * 1.6F * w;
		model.body.originY += hop;
		model.head.originY += hop;
		model.rightArm.originY += hop;
		model.leftArm.originY += hop;
		model.rightLeg.originY += hop;
		model.leftLeg.originY += hop;
	}

	/** Formal bow: bend at the waist, hold, straighten up. */
	private static void bow(BipedEntityModel<?> model, float t) {
		float w = riseHoldFall(t, 0.9F, 2.0F, 3.0F);

		set(model.body, w, 0.55F, 0.0F, 0.0F);
		add(model.head, w, 0.42F, 0.0F, 0.0F);

		// Arm stretched out in front, the other drawn back across the chest.
		set(model.rightArm, w, -1.50F, -0.10F, 0.15F);
		set(model.leftArm, w, -2.05F, -0.35F, -0.45F);

		set(model.rightLeg, w, -0.18F, 0.0F, 0.0F);
		set(model.leftLeg, w, 0.12F, 0.0F, 0.0F);

		model.body.originY -= 1.5F * w;
		model.head.originY -= 1.5F * w;
	}

	/** Military salute. */
	private static void salute(BipedEntityModel<?> model, float t, float p) {
		float w = riseHoldFall(t, 0.5F, 2.0F, 3.0F);
		float tremble = MathHelper.sin(t * 5.0F);

		set(model.rightArm, w, -2.60F + tremble * 0.07F, -0.20F, 0.30F);
		set(model.leftArm, w, 0.12F, 0.0F, -0.06F);
		set(model.body, w, 0.06F, 0.0F, 0.0F);
		set(model.rightLeg, w, 0.05F, 0.0F, 0.0F);
		add(model.head, w, 0.10F + tremble * 0.05F, tremble * 0.04F, 0.0F);
	}

	/** Both palms up, shoulders shrugged. */
	private static void shrug(BipedEntityModel<?> model, float t) {
		float w = riseHoldFall(t, 0.4F, 1.6F, 2.5F);
		float tremble = MathHelper.sin(t * 6.0F);

		set(model.rightArm, w, 0.45F + tremble * 0.06F, -0.40F, 1.15F + tremble * 0.14F);
		set(model.leftArm, w, 0.45F - tremble * 0.06F, 0.40F, -1.15F - tremble * 0.14F);

		set(model.body, w, -0.05F, 0.0F, tremble * 0.04F);
		add(model.head, w, -0.20F, 0.0F, tremble * 0.05F);

		float raised = 2.0F * w;
		model.body.originY += raised;
		model.head.originY += raised;
		model.rightArm.originY += raised;
		model.leftArm.originY += raised;
	}

	/** Straight arm out in front, holding the point. */
	private static void point(BipedEntityModel<?> model, float t) {
		float w = riseHoldFall(t, 0.25F, 2.2F, 3.0F);
		float bob = MathHelper.sin(t * 5.0F);

		set(model.rightArm, w, -HALF_PI + bob * 0.10F, -0.05F, 0.12F);
		set(model.leftArm, w, 0.12F, 0.0F, -0.14F);
		add(model.head, w, -0.06F, 0.0F, 0.0F);
		add(model.body, w, 0.0F, bob * 0.07F, 0.0F);
	}

	// ---------------------------------------------------------------- helpers

	/** Blends the part towards an absolute pose. */
	private static void set(ModelPart part, float w, float pitch, float yaw, float roll) {
		part.pitch = MathHelper.lerp(w, part.pitch, pitch);
		part.yaw = MathHelper.lerp(w, part.yaw, yaw);
		part.roll = MathHelper.lerp(w, part.roll, roll);
	}

	/** Adds an offset to the part, preserving whatever vanilla already set. */
	private static void add(ModelPart part, float w, float pitch, float yaw, float roll) {
		part.pitch += pitch * w;
		part.yaw += yaw * w;
		part.roll += roll * w;
	}

	/** 0 at the very start, 1 through the middle, back to 0 at the very end. */
	private static float envelope(float p) {
		return smoothstep(0.0F, 0.12F, p) * (1.0F - smoothstep(0.85F, 1.0F, p));
	}

	/**
	 * Ramps 0 to 1 over {@code rise} seconds, stays at 1 until {@code hold} seconds, then ramps
	 * back to 0 by {@code end} seconds.
	 */
	private static float riseHoldFall(float t, float rise, float hold, float end) {
		if (t <= 0.0F) {
			return 0.0F;
		}

		if (t < rise) {
			return smoothstep(0.0F, rise, t);
		}

		if (t < hold) {
			return 1.0F;
		}

		return 1.0F - smoothstep(hold, end, t);
	}

	private static float smoothstep(float edge0, float edge1, float x) {
		float t = MathHelper.clamp((x - edge0) / (edge1 - edge0), 0.0F, 1.0F);
		return t * t * (3.0F - 2.0F * t);
	}
}
