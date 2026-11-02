package com.cubeon.client.mixin;

import com.cubeon.client.chat.ChatStack;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.gui.hud.ChatHud;
import net.minecraft.client.gui.hud.ChatHudLine;
import net.minecraft.text.Text;
import net.minecraft.util.Formatting;
import org.spongepowered.asm.mixin.Final;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Shadow;
import org.spongepowered.asm.mixin.Unique;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.ModifyVariable;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

import java.util.List;

/** Collapse only rendered lines, preserving raw history, signatures and logging. */
@Mixin(ChatHud.class)
public abstract class ChatStackMixin {
    @Shadow @Final private MinecraftClient client;
    @Shadow @Final private List<ChatHudLine.Visible> visibleMessages;
    @Shadow private int scrolledLines;
    @Unique private final ChatStack cubeon$stack = new ChatStack();

    @ModifyVariable(method = "addVisibleMessage", at = @At("HEAD"), argsOnly = true)
    private ChatHudLine cubeon$stackLine(ChatHudLine message) {
        Object head = visibleMessages.isEmpty() ? null : visibleMessages.get(0);
        int count = cubeon$stack.accept(message.content(), message.signature() != null,
                message.indicator(), message.creationTick(), client.getNetworkHandler(), head);
        if (count == 1) return message;
        int removed = ChatStack.removeLatest(visibleMessages, ChatHudLine.Visible::endOfEntry);
        scrolledLines = Math.max(0, scrolledLines - removed);
        Text display = Text.empty().append(message.content().copy())
                .append(Text.literal(" ×" + count).formatted(Formatting.GRAY));
        return new ChatHudLine(message.creationTick(), display, message.signature(), message.indicator());
    }

    @Inject(method = "addVisibleMessage", at = @At("TAIL"))
    private void cubeon$rememberHead(CallbackInfo ci) {
        cubeon$stack.rememberHead(visibleMessages.isEmpty() ? null : visibleMessages.get(0));
    }

    @Inject(method = {"clear", "refresh"}, at = @At("HEAD"))
    private void cubeon$reset(CallbackInfo ci) {
        cubeon$stack.reset();
    }
}
