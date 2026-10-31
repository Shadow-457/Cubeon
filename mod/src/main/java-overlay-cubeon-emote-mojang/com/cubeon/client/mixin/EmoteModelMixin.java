package com.cubeon.client.mixin;
import com.cubeon.client.emotes.EmotePose;
import com.cubeon.client.emotes.EmoteState;
import com.cubeon.client.hud.CubeonHudConfig;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Unique;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
import net.minecraft.client.Minecraft;
import net.minecraft.client.model.geom.ModelPart;
import net.minecraft.client.model.HumanoidModel;
import net.minecraft.world.entity.player.Player;
import net.minecraft.client.renderer.entity.state.HumanoidRenderState;
import net.minecraft.client.renderer.entity.state.AvatarRenderState;
@Mixin(HumanoidModel.class)
public abstract class EmoteModelMixin {
    @Inject(method = "setupAnim(Lnet/minecraft/client/renderer/entity/state/HumanoidRenderState;)V", at = @At("TAIL"))
    private void cubeon$emote(HumanoidRenderState state, CallbackInfo ci) {

        if (!CubeonHudConfig.get().showEmotes || !EmoteState.active()) return;
        Minecraft client = Minecraft.getInstance();
        if (!(state instanceof AvatarRenderState avatarState) || client.level == null
                || !(client.level.getEntity(avatarState.id) instanceof Player player)) return;
        if (!player.isAlive() || player.isPassenger() || player.isFallFlying()
                || player.isSwimming() || player.isSleeping()) return;
        EmotePose pose = EmoteState.frame(player.getUUID(), player.getName().getString(), state.ageInTicks % 1);
        if (pose == null) return;
        HumanoidModel<?> model = (HumanoidModel<?>) (Object) this;
        pose.anchorBody(model.body.x, model.body.y, model.body.z,
                model.body.xRot, model.body.yRot, model.body.zRot);
        cubeon$pose(model.head, 0, pose); cubeon$pose(model.body, 1, pose);
        cubeon$pose(model.rightArm, 2, pose); cubeon$pose(model.leftArm, 3, pose);
        cubeon$pose(model.rightLeg, 4, pose); cubeon$pose(model.leftLeg, 5, pose);
        // The hat is a child of head, including injected 3D skin meshes.
        // Keep its local transform; head rotation is already inherited.
    }
    @Unique private static void cubeon$pose(ModelPart part, int index, EmotePose pose) {
        part.xRot = pose.blend(index, 0, part.xRot);
        part.yRot = pose.blend(index, 1, part.yRot);
        part.zRot = pose.blend(index, 2, part.zRot);
        pose.position(index, part.x, part.y, part.z);
        part.x += pose.offsets[index*3];
        part.y += pose.offsets[index*3+1];
        part.z += pose.offsets[index*3+2];
    }
}
