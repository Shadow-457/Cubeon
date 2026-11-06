package com.cubeon.client.mixin;

import com.cubeon.client.hud.screen.SkinLibraryScreen;
import com.cubeon.client.hud.screen.FriendsChatScreen;
import net.minecraft.client.gui.screen.Screen;
import net.minecraft.client.gui.screen.TitleScreen;
import net.minecraft.client.gui.widget.ButtonWidget;
import net.minecraft.text.Text;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/** Minecraft's title menu entry point, outside the vanilla play/options rows. */
@Mixin(TitleScreen.class)
public abstract class SkinTitleMenuMixin extends Screen {
    protected SkinTitleMenuMixin() { super(Text.empty()); }
    @Inject(method="init",at=@At("TAIL"),require=1)
    private void cubeon$skinsButton(CallbackInfo ci) {
        addDrawableChild(ButtonWidget.builder(Text.translatable("cubeonclient.cosmetics.title"),
                button->SkinLibraryScreen.open((Screen)(Object)this))
                .dimensions(this.width-98,8,90,20).build());
        addDrawableChild(ButtonWidget.builder(Text.translatable("cubeonclient.friends.chat_title"),
                button->FriendsChatScreen.open((Screen)(Object)this))
                .dimensions(this.width-98,32,90,20).build());
    }
}
