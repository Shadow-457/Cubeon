package com.cubeon.client.mixin;

import com.cubeon.client.chat.ChatStack;
import net.minecraft.ChatFormatting;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.components.ChatComponent;
import net.minecraft.client.multiplayer.chat.GuiMessage;
import net.minecraft.network.chat.Component;
import org.spongepowered.asm.mixin.Final;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Shadow;
import org.spongepowered.asm.mixin.Unique;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.ModifyVariable;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

import java.util.List;

@Mixin(ChatComponent.class)
public abstract class ChatStackMixin {
    @Shadow @Final private Minecraft minecraft;
    @Shadow @Final private List<GuiMessage.Line> trimmedMessages;
    @Shadow private int chatScrollbarPos;
    @Unique private final ChatStack cubeon$stack = new ChatStack();

    @ModifyVariable(method = "addMessageToDisplayQueue", at = @At("HEAD"), argsOnly = true)
    private GuiMessage cubeon$stackLine(GuiMessage message) {
        Object head = trimmedMessages.isEmpty() ? null : trimmedMessages.get(0);
        int count = cubeon$stack.accept(message.content(), message.source(), message.tag(),
                message.addedTime(), minecraft.getConnection(), head);
        if (count == 1) return message;
        int removed = ChatStack.removeLatest(trimmedMessages, GuiMessage.Line::endOfEntry);
        chatScrollbarPos = Math.max(0, chatScrollbarPos - removed);
        Component display = Component.empty().append(message.content().copy())
                .append(Component.literal(" ×" + count).withStyle(ChatFormatting.GRAY));
        return new GuiMessage(message.addedTime(), display, message.signature(), message.source(), message.tag());
    }

    @Inject(method = "addMessageToDisplayQueue", at = @At("TAIL"))
    private void cubeon$rememberHead(CallbackInfo ci) {
        cubeon$stack.rememberHead(trimmedMessages.isEmpty() ? null : trimmedMessages.get(0));
    }

    @Inject(method = {"clearMessages", "refreshTrimmedMessages"}, at = @At("HEAD"))
    private void cubeon$reset(CallbackInfo ci) {
        cubeon$stack.reset();
    }
}
