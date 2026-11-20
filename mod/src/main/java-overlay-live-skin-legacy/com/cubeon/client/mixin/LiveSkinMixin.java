package com.cubeon.client.mixin;
import com.cubeon.client.skins.LiveSkin;
import com.cubeon.client.skins.CosmeticSkinTexture;
import com.cubeon.client.cosmetics.CosmeticPlayers;
import net.minecraft.client.render.entity.PlayerModelPart;
import com.cubeon.client.skins.LiveCape;
import com.cubeon.client.skins.LiveCapeTexture;
import com.cubeon.client.skins.LiveSkinTexture;
import com.cubeon.client.skins.RemoteSkins;
import com.cubeon.client.skins.RemoteSkinTexture;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.network.AbstractClientPlayerEntity;
import net.minecraft.util.Identifier;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

/** Native Cubeon skin fallback for every player; confirmed cape choices remain local-only. */
@Mixin(value=AbstractClientPlayerEntity.class, priority=900)
public abstract class LiveSkinMixin {
    private boolean cubeon$local() { return (Object)this==MinecraftClient.getInstance().player; }
    private String cubeon$name() { return ((AbstractClientPlayerEntity)(Object)this).getName().getString(); }
    private RemoteSkins.Skin cubeon$remote() {
        var client=MinecraftClient.getInstance(); RemoteSkins.context(client.world);
        return RemoteSkins.get(cubeon$name());
    }
    @Inject(method="getSkinTexture",at=@At("RETURN"),cancellable=true,require=1)
    private void cubeon$skin(CallbackInfoReturnable<Identifier> callback) {
        var player=(AbstractClientPlayerEntity)(Object)this;
        var texture=cubeon$local()&&LiveSkin.get()!=null?LiveSkinTexture.texture():null;
        if(texture==null) texture=RemoteSkinTexture.texture(cubeon$name(),cubeon$remote());
        var source=texture==null?callback.getReturnValue():texture;
        var body=CosmeticSkinTexture.texture(source,this,CosmeticPlayers.selection(player),"slim".equals(player.getModel()));
        if(body!=null&&!body.equals(callback.getReturnValue())) callback.setReturnValue(body);
    }
    @Inject(method="getModel",at=@At("RETURN"),cancellable=true,require=1)
    private void cubeon$model(CallbackInfoReturnable<String> callback) {
        var skin=LiveSkin.get();
        if(cubeon$local()&&skin!=null&&LiveSkinTexture.texture()!=null) {
            callback.setReturnValue(skin.slim()?"slim":"default"); return;
        }
        var remote=cubeon$remote();
        if(RemoteSkinTexture.texture(cubeon$name(),remote)!=null)
            callback.setReturnValue(remote.slim()?"slim":"default");
    }
    @Inject(method="getElytraTexture",at=@At("RETURN"),cancellable=true,require=1)
    private void cubeon$elytra(CallbackInfoReturnable<Identifier> callback) {
        if(cubeon$local() && LiveCape.get()!=null) callback.setReturnValue(LiveCape.elytra(LiveCape.get(),
                callback.getReturnValue(),new Identifier("minecraft","textures/entity/elytra.png")));
    }
    @Inject(method="getCapeTexture",at=@At("RETURN"),cancellable=true,require=1)
    private void cubeon$cape(CallbackInfoReturnable<Identifier> callback) {
        var cape=LiveCape.get();
        if(!cubeon$local()) return;
        boolean visible=MinecraftClient.getInstance().options.isPlayerModelPartEnabled(PlayerModelPart.CAPE);
        if(!visible) { callback.setReturnValue(null); return; }
        if(cape==null) { LiveCapeTexture.texture(); return; }
        var texture=LiveCapeTexture.texture();
        if(cape.hidden()) { callback.setReturnValue(null); return; } if(texture!=null) callback.setReturnValue(texture);
    }
    @Inject(method="canRenderCapeTexture",at=@At("RETURN"),cancellable=true,require=1)
    private void cubeon$capeVisible(CallbackInfoReturnable<Boolean> callback) {
        var cape=LiveCape.get();
        if(!cubeon$local()) return;
        if(!MinecraftClient.getInstance().options.isPlayerModelPartEnabled(PlayerModelPart.CAPE)) { callback.setReturnValue(false); return; }
        if(cape==null) { LiveCapeTexture.texture(); return; }
        var texture=LiveCapeTexture.texture();
        if(cape.hidden()) callback.setReturnValue(false);
        else if(texture!=null) callback.setReturnValue(true);
    }
}
