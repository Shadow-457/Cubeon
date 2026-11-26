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
import net.minecraft.client.Minecraft;
import net.minecraft.client.player.AbstractClientPlayer;
import net.minecraft.resources.Identifier;
import net.minecraft.world.entity.player.PlayerSkin;
import net.minecraft.core.ClientAsset;
import net.minecraft.world.entity.player.PlayerModelType;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

/** Native Cubeon skin fallback for every player; confirmed cape choices remain local-only. */
@Mixin(value=AbstractClientPlayer.class, priority=900)
public abstract class LiveSkinMixin {
    private static Identifier cubeon$vanillaElytra;
    private static Identifier cubeon$elytra() {
        if(cubeon$vanillaElytra==null) {
            cubeon$vanillaElytra=Identifier.parse("minecraft:textures/entity/equipment/wings/elytra.png");
        }
        return cubeon$vanillaElytra;
    }
    private boolean cubeon$local() { return (Object)this==Minecraft.getInstance().player; }
    private String cubeon$name() { return ((AbstractClientPlayer)(Object)this).getName().getString(); }
    private RemoteSkins.Skin cubeon$remote() {
        var client=Minecraft.getInstance(); RemoteSkins.context(client.level);
        return RemoteSkins.get(cubeon$name());
    }
    @Inject(method="getSkin",at=@At("RETURN"),cancellable=true,require=1)
    private void cubeon$skin(CallbackInfoReturnable<PlayerSkin> callback) {
        var original=callback.getReturnValue(); if(original==null) return;
        boolean local=cubeon$local();
        var skin=local?LiveSkin.get():null; var cape=local?LiveCape.get():null;
        // The local result belongs to the Wardrobe or CSL. Username
        // fallbacks apply to peers and cannot replace a local selection.
        var remote=local?null:cubeon$remote();
        var remoteTexture=RemoteSkinTexture.texture(cubeon$name(),remote);
        boolean visible=SkinNative.capeVisible();
        var texture=skin==null?remoteTexture:LiveSkinTexture.texture();
        boolean slim=texture==null?original.model()==PlayerModelType.SLIM:(skin!=null?skin.slim():remote.slim());
        var body=CosmeticSkinTexture.texture(texture==null?original.body().texturePath():texture, this,
                CosmeticPlayers.selection((AbstractClientPlayer)(Object)this), slim);
        var capeTexture=local?LiveCapeTexture.texture():null;
        var newCape=local?LiveCape.texture(cape,visible,original.cape(),capeTexture==null?null:new ClientAsset.ResourceTexture(capeTexture,capeTexture)):original.cape();
        callback.setReturnValue(new PlayerSkin(texture==null&&body.equals(original.body().texturePath())?original.body():new ClientAsset.ResourceTexture(body,body), newCape,
                local?LiveCape.elytra(cape,original.elytra(),cape!=null?new ClientAsset.ResourceTexture(cubeon$elytra(),cubeon$elytra()):null):original.elytra(), texture==null?original.model():(skin!=null?skin.slim():remote.slim())?PlayerModelType.SLIM:PlayerModelType.WIDE,
                texture==null?original.secure():false));
    }
}
