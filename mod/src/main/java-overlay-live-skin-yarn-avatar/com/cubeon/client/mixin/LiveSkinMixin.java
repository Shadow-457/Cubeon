package com.cubeon.client.mixin;
import com.cubeon.client.skins.LiveSkin;
import com.cubeon.client.hud.screen.SkinNative;
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
    private static Identifier cubeon$vanillaElytra;
    private static Identifier cubeon$elytra() {
        if(cubeon$vanillaElytra==null) {
            var old=Identifier.tryParse("minecraft:textures/entity/elytra.png");
            cubeon$vanillaElytra=MinecraftClient.getInstance().getResourceManager().getResource(old).isPresent()
                    ?old:Identifier.tryParse("minecraft:textures/entity/equipment/wings/elytra.png");
        }
        return cubeon$vanillaElytra;
    }
    private boolean cubeon$local() { return (Object)this==MinecraftClient.getInstance().player; }
    @Inject(method="getSkin",at=@At("RETURN"),cancellable=true,require=1)
    private void cubeon$skin(CallbackInfoReturnable<SkinTextures> callback) {
        if(!cubeon$local()) return;
        var skin=LiveSkin.get(); var cape=LiveCape.get();
        boolean visible=SkinNative.capeVisible();
        if(skin==null&&cape==null&&visible) { LiveCapeTexture.texture(); return; }
        var texture=skin==null?null:LiveSkinTexture.texture();
        var capeTexture=LiveCapeTexture.texture();
        var original=callback.getReturnValue(); if(original==null) return;
        var newCape=LiveCape.texture(cape,visible,original.cape(),capeTexture==null?null:new AssetInfo.TextureAssetInfo(capeTexture,capeTexture));
        callback.setReturnValue(new SkinTextures(texture==null?original.body():new AssetInfo.TextureAssetInfo(texture,texture), newCape,
                LiveCape.elytra(cape,original.elytra(),cape!=null?new AssetInfo.TextureAssetInfo(cubeon$elytra(),cubeon$elytra()):null), texture==null?original.model():skin.slim()?PlayerSkinType.SLIM:PlayerSkinType.WIDE,
                texture==null?original.secure():false));
    }
}
