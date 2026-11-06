package com.cubeon.client.mixin;
import com.cubeon.client.skins.LiveSkin;
import com.cubeon.client.skins.LiveCape;
import com.cubeon.client.skins.LiveCapeTexture;
import com.cubeon.client.skins.LiveSkinTexture;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.network.AbstractClientPlayerEntity;
import net.minecraft.util.Identifier;
import net.minecraft.client.util.SkinTextures;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

/** Local-player-only skin override; confirmed cape choices are local-only; elytra and other players are preserved. */
@Mixin(value=AbstractClientPlayerEntity.class, priority=900)
public abstract class LiveSkinMixin {
    private boolean cubeon$local() { return (Object)this==MinecraftClient.getInstance().player; }
    @Inject(method="getSkinTextures",at=@At("RETURN"),cancellable=true,require=1)
    private void cubeon$skin(CallbackInfoReturnable<SkinTextures> callback) {
        if(!cubeon$local()) return;
        var skin=LiveSkin.get(); var cape=LiveCape.get();
        if(skin==null&&cape==null) return;
        var texture=skin==null?null:LiveSkinTexture.texture();
        var capeTexture=cape==null||cape.hidden()?null:LiveCapeTexture.texture();
        var original=callback.getReturnValue(); if(original==null) return;
        var newCape=cape==null?original.capeTexture():cape.hidden()?null:capeTexture==null?original.capeTexture():capeTexture;
        callback.setReturnValue(new SkinTextures(texture==null?original.texture():texture, original.textureUrl(), newCape,
                original.elytraTexture(), texture==null?original.model():skin.slim()?SkinTextures.Model.SLIM:SkinTextures.Model.WIDE,
                texture==null?original.secure():false));
    }
}
