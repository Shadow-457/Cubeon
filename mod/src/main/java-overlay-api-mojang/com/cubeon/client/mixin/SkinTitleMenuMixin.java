package com.cubeon.client.mixin;

import com.cubeon.client.hud.screen.SkinLibraryScreen;
import com.cubeon.client.hud.screen.FriendsChatScreen;
import net.minecraft.client.gui.screens.Screen;
import net.minecraft.client.gui.screens.TitleScreen;
import net.minecraft.client.gui.components.Button;
import net.minecraft.network.chat.Component;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/** Minecraft's title menu entry point, outside the vanilla play/options rows. */
@Mixin(TitleScreen.class)
public abstract class SkinTitleMenuMixin extends Screen {
    protected SkinTitleMenuMixin() { super(Component.empty()); }
    @Inject(method="init",at=@At("TAIL"),require=1)
    private void cubeon$skinsButton(CallbackInfo ci) {
        addRenderableWidget(Button.builder(Component.translatable("cubeonclient.cosmetics.title"),
                button->SkinLibraryScreen.open((Screen)(Object)this))
                .bounds(this.width-98,8,90,20).build());
        addRenderableWidget(Button.builder(Component.translatable("cubeonclient.friends.chat_title"),
                button->FriendsChatScreen.open((Screen)(Object)this))
                .bounds(this.width-98,32,90,20).build());
    }
}
