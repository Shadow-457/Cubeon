package com.cubeon.client.mixin;
import com.cubeon.client.skins.LiveSkin;
import com.cubeon.client.skins.LiveCape;
import com.cubeon.client.skins.LiveCapeTexture;
import com.cubeon.client.skins.LiveSkinTexture;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.network.AbstractClientPlayerEntity;
import net.minecraft.util.Identifier;
import net.minecraft.entity.player.SkinTextures;
import net.minecraft.util.AssetInfo;
import net.minecraft.entity.player.PlayerSkinType;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

/** Local-player-only skin override; confirmed cape choices are local-only; elytra and other players are preserved. */
@Mixin(value=AbstractClientPlayerEntity.class, priority=900)
public abstract class LiveSkinMixin {
    private boolean cubeon$local() { return (Object)this==MinecraftClient.getInstance().player; }
    @Inject(method="getSkin",at=@At("RETURN"),cancellable=true,require=1)
    private void cubeon$skin(CallbackInfoReturnable<SkinTextures> callback) {
        if(!cubeon$local()) return;
        var skin=LiveSkin.get(); var cape=LiveCape.get();
        if(skin==null&&cape==null) return;
        var texture=skin==null?null:LiveSkinTexture.texture();
        var capeTexture=cape==null||cape.hidden()?null:LiveCapeTexture.texture();
        var original=callback.getReturnValue(); if(original==null) return;
        var newCape=cape==null?original.cape():cape.hidden()?null:capeTexture==null?original.cape():new AssetInfo.TextureAssetInfo(capeTexture,capeTexture);
        callback.setReturnValue(new SkinTextures(texture==null?original.body():new AssetInfo.TextureAssetInfo(texture,texture), newCape,
                original.elytra(), texture==null?original.model():skin.slim()?PlayerSkinType.SLIM:PlayerSkinType.WIDE,
                texture==null?original.secure():false));
    }
}
