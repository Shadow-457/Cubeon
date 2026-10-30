package com.cubeon.client.mixin;
import com.cubeon.client.emotes.EmotePose;
import com.cubeon.client.emotes.EmoteState;
import com.cubeon.client.hud.CubeonHudConfig;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Unique;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.model.ModelPart;
import net.minecraft.client.render.entity.model.BipedEntityModel;
import net.minecraft.entity.player.PlayerEntity;
import net.minecraft.entity.LivingEntity;
@Mixin(BipedEntityModel.class)
public abstract class EmoteModelMixin {
    @Unique private boolean cubeon$posed;
    @Unique private float cubeon$drop;

    /** Older biped models leave head/body roll untouched between entities. */
    @Inject(method = "setAngles(Lnet/minecraft/entity/LivingEntity;FFFFF)V", at = @At("HEAD"))
    private void cubeon$reset(CallbackInfo ci) {
        if (cubeon$posed) {
            BipedEntityModel<?> model = (BipedEntityModel<?>) (Object) this;
            model.head.roll = 0; model.body.roll = 0;
            model.head.pivotY -= cubeon$drop; model.body.pivotY -= cubeon$drop;
            model.rightArm.pivotY -= cubeon$drop; model.leftArm.pivotY -= cubeon$drop;
            model.rightLeg.pivotY -= cubeon$drop; model.leftLeg.pivotY -= cubeon$drop;
            model.hat.pivotY -= cubeon$drop; cubeon$drop = 0;
            cubeon$posed = false;
        }
    }

    @Inject(method = "setAngles(Lnet/minecraft/entity/LivingEntity;FFFFF)V", at = @At("TAIL"))
    private void cubeon$emote(LivingEntity entity, float limbAngle, float limbDistance,
            float animationProgress, float headYaw, float headPitch, CallbackInfo ci) {

        if (!CubeonHudConfig.get().showEmotes || !EmoteState.active()) return;
        if (!(entity instanceof PlayerEntity player)) return;
        if (!player.isAlive() || player.hasVehicle() || player.isFallFlying()
                || player.isSwimming() || player.isSleeping()) return;
        EmotePose pose = EmoteState.frame(player.getUuid(), player.getName().getString(), animationProgress % 1);
        if (pose == null) return;
        BipedEntityModel<?> model = (BipedEntityModel<?>) (Object) this;
        cubeon$pose(model.head, 0, pose); cubeon$pose(model.body, 1, pose);
        cubeon$pose(model.rightArm, 2, pose); cubeon$pose(model.leftArm, 3, pose);
        cubeon$pose(model.rightLeg, 4, pose); cubeon$pose(model.leftLeg, 5, pose);
        cubeon$drop = pose.drop;
        model.hat.copyTransform(model.head);
        cubeon$posed = true;
    }
    @Unique private static void cubeon$pose(ModelPart part, int index, EmotePose pose) {
        part.pitch = pose.blend(index, 0, part.pitch);
        part.yaw = pose.blend(index, 1, part.yaw);
        part.roll = pose.blend(index, 2, part.roll);
        part.pivotY += pose.drop;
    }
}
