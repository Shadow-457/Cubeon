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
import net.minecraft.client.render.entity.state.BipedEntityRenderState;
import net.minecraft.client.render.entity.state.PlayerEntityRenderState;
@Mixin(BipedEntityModel.class)
public abstract class EmoteModelMixin {
    @Inject(method = "setAngles(Lnet/minecraft/client/render/entity/state/BipedEntityRenderState;)V", at = @At("TAIL"))
    private void cubeon$emote(BipedEntityRenderState state, CallbackInfo ci) {

        if (!CubeonHudConfig.get().showEmotes || !EmoteState.active()) return;
        MinecraftClient client = MinecraftClient.getInstance();
        if (!(state instanceof PlayerEntityRenderState playerState) || client.world == null
                || !(client.world.getEntityById(playerState.id) instanceof PlayerEntity player)) return;
        if (!player.isAlive() || player.hasVehicle() || state.isGliding
                || player.isSwimming() || player.isSleeping()) return;
        EmotePose pose = EmoteState.frame(player.getUuid(), player.getName().getString(), state.age % 1);
        if (pose == null) return;
        BipedEntityModel<?> model = (BipedEntityModel<?>) (Object) this;
        cubeon$pose(model.head, 0, pose); cubeon$pose(model.body, 1, pose);
        cubeon$pose(model.rightArm, 2, pose); cubeon$pose(model.leftArm, 3, pose);
        cubeon$pose(model.rightLeg, 4, pose); cubeon$pose(model.leftLeg, 5, pose);
        // Since 1.21.2 the hat is a child of head. Its local transform must
        // remain vanilla: copying head rotations here applies them twice,
        // including to the mesh injected by 3D Skin Layers.
    }
    @Unique private static void cubeon$pose(ModelPart part, int index, EmotePose pose) {
        part.pitch = pose.blend(index, 0, part.pitch);
        part.yaw = pose.blend(index, 1, part.yaw);
        part.roll = pose.blend(index, 2, part.roll);
        part.originY += pose.drop;
    }
}
