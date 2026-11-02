package com.cubeon.client.mixin;

import com.cubeon.client.chat.ChatStack;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.gui.hud.ChatHud;
import net.minecraft.client.gui.hud.ChatHudLine;
import net.minecraft.client.gui.hud.MessageIndicator;
import net.minecraft.network.message.MessageSignatureData;
import net.minecraft.text.StringVisitable;
import net.minecraft.text.Text;
import net.minecraft.util.Formatting;
import org.spongepowered.asm.mixin.Final;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Shadow;
import org.spongepowered.asm.mixin.Unique;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.ModifyArg;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

import java.util.List;

/** 1.20–1.20.4: only the line-wrapper argument changes, never stored message text. */
@Mixin(ChatHud.class)
public abstract class ChatStackMixin {
    @Shadow @Final private MinecraftClient client;
    @Shadow @Final private List<ChatHudLine.Visible> visibleMessages;
    @Shadow private int scrolledLines;
    @Unique private final ChatStack cubeon$stack = new ChatStack();
    @Unique private Text cubeon$display;

    @Inject(method = "addMessage(Lnet/minecraft/text/Text;Lnet/minecraft/network/message/MessageSignatureData;ILnet/minecraft/client/gui/hud/MessageIndicator;Z)V",
            at = @At("HEAD"))
    private void cubeon$prepare(Text message, MessageSignatureData signature, int tick,
                                MessageIndicator indicator, boolean refresh, CallbackInfo ci) {
        Object head = visibleMessages.isEmpty() ? null : visibleMessages.get(0);
        int count = cubeon$stack.accept(message, signature != null, indicator, tick,
                client.getNetworkHandler(), head);
        cubeon$display = message;
        if (count == 1) return;
        int removed = ChatStack.removeLatest(visibleMessages, ChatHudLine.Visible::endOfEntry);
        scrolledLines = Math.max(0, scrolledLines - removed);
        cubeon$display = Text.empty().append(message.copy())
                .append(Text.literal(" ×" + count).formatted(Formatting.GRAY));
    }

    @ModifyArg(method = "addMessage(Lnet/minecraft/text/Text;Lnet/minecraft/network/message/MessageSignatureData;ILnet/minecraft/client/gui/hud/MessageIndicator;Z)V",
            at = @At(value = "INVOKE", target = "Lnet/minecraft/client/util/ChatMessages;breakRenderedChatMessageLines(Lnet/minecraft/text/StringVisitable;ILnet/minecraft/client/font/TextRenderer;)Ljava/util/List;"), index = 0)
    private StringVisitable cubeon$renderText(StringVisitable original) {
        return cubeon$display == null ? original : cubeon$display;
    }

    @Inject(method = "addMessage(Lnet/minecraft/text/Text;Lnet/minecraft/network/message/MessageSignatureData;ILnet/minecraft/client/gui/hud/MessageIndicator;Z)V",
            at = @At("TAIL"))
    private void cubeon$rememberHead(CallbackInfo ci) {
        cubeon$stack.rememberHead(visibleMessages.isEmpty() ? null : visibleMessages.get(0));
        cubeon$display = null;
    }

    @Inject(method = {"clear", "refresh"}, at = @At("HEAD"))
    private void cubeon$reset(CallbackInfo ci) {
        cubeon$stack.reset();
        cubeon$display = null;
    }
}
