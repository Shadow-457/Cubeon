package com.cubeon.client.mixin;
import com.cubeon.client.skins.LiveSkin;
import com.cubeon.client.skins.CosmeticSkinTexture;
import com.cubeon.client.cosmetics.CosmeticPlayers;
import com.cubeon.client.hud.screen.SkinNative;
import com.cubeon.client.skins.LiveCape;
import com.cubeon.client.skins.LiveCapeTexture;
import com.cubeon.client.skins.LiveSkinTexture;
import com.cubeon.client.skins.RemoteSkins;
import com.cubeon.client.skins.RemoteSkinTexture;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.network.AbstractClientPlayerEntity;
import net.minecraft.util.Identifier;
import net.minecraft.client.util.SkinTextures;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

/** Native Cubeon skin fallback for every player; confirmed cape choices remain local-only. */
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
    private String cubeon$name() { return ((AbstractClientPlayerEntity)(Object)this).getName().getString(); }
    private RemoteSkins.Skin cubeon$remote() {
        var client=MinecraftClient.getInstance(); RemoteSkins.context(client.world);
        return RemoteSkins.get(cubeon$name());
    }
    @Inject(method="getSkinTextures",at=@At("RETURN"),cancellable=true,require=1)
    private void cubeon$skin(CallbackInfoReturnable<SkinTextures> callback) {
        var original=callback.getReturnValue(); if(original==null) return;
        boolean local=cubeon$local();
        var skin=local?LiveSkin.get():null; var cape=local?LiveCape.get():null;
        var remote=skin==null?cubeon$remote():null;
        var remoteTexture=RemoteSkinTexture.texture(cubeon$name(),remote);
        boolean visible=SkinNative.capeVisible();
        var texture=skin==null?remoteTexture:LiveSkinTexture.texture();
        boolean slim=texture==null?original.model()==SkinTextures.Model.SLIM:(skin!=null?skin.slim():remote.slim());
        var body=CosmeticSkinTexture.texture(texture==null?original.texture():texture, this,
                CosmeticPlayers.selection((AbstractClientPlayerEntity)(Object)this), slim);
        var capeTexture=local?LiveCapeTexture.texture():null;
        var newCape=local?LiveCape.texture(cape,visible,original.capeTexture(),capeTexture):original.capeTexture();
        callback.setReturnValue(new SkinTextures(body, original.textureUrl(), newCape,
                local?LiveCape.elytra(cape,original.elytraTexture(),cape!=null?cubeon$elytra():null):original.elytraTexture(), texture==null?original.model():(skin!=null?skin.slim():remote.slim())?SkinTextures.Model.SLIM:SkinTextures.Model.WIDE,
                texture==null?original.secure():false));
    }
}
