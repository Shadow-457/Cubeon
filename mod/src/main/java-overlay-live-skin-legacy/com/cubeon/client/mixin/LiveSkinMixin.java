package com.cubeon.client.mixin;
import com.cubeon.client.skins.LiveSkin;
import com.cubeon.client.skins.LiveCape;
import com.cubeon.client.skins.LiveCapeTexture;
import com.cubeon.client.skins.LiveSkinTexture;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.network.AbstractClientPlayerEntity;
import net.minecraft.util.Identifier;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

/** Local-player-only skin override; confirmed cape choices are local-only; elytra and other players are preserved. */
@Mixin(value=AbstractClientPlayerEntity.class, priority=900)
public abstract class LiveSkinMixin {
    private boolean cubeon$local() { return (Object)this==MinecraftClient.getInstance().player; }
    @Inject(method="getSkinTexture",at=@At("RETURN"),cancellable=true,require=1)
    private void cubeon$skin(CallbackInfoReturnable<Identifier> callback) {
        if(!cubeon$local()||LiveSkin.get()==null) return;
        var texture=LiveSkinTexture.texture(); if(texture!=null) callback.setReturnValue(texture);
    }
    @Inject(method="getModel",at=@At("RETURN"),cancellable=true,require=1)
    private void cubeon$model(CallbackInfoReturnable<String> callback) {
        var skin=LiveSkin.get();
        if(cubeon$local()&&skin!=null&&LiveSkinTexture.texture()!=null) callback.setReturnValue(skin.slim()?"slim":"default");
    }
    @Inject(method="getCapeTexture",at=@At("RETURN"),cancellable=true,require=1)
    private void cubeon$cape(CallbackInfoReturnable<Identifier> callback) {
        var cape=LiveCape.get();
        if(!cubeon$local()) return;
        if(cape==null) { LiveCapeTexture.texture(); return; }
        var texture=LiveCapeTexture.texture();
        if(cape.hidden()) { callback.setReturnValue(null); return; } if(texture!=null) callback.setReturnValue(texture);
    }
    @Inject(method="canRenderCapeTexture",at=@At("RETURN"),cancellable=true,require=1)
    private void cubeon$capeVisible(CallbackInfoReturnable<Boolean> callback) {
        var cape=LiveCape.get();
        if(!cubeon$local()) return;
        if(cape==null) { LiveCapeTexture.texture(); return; }
        var texture=LiveCapeTexture.texture();
        if(cape.hidden()) callback.setReturnValue(false);
        else if(texture!=null) callback.setReturnValue(true);
    }
}
