package com.cubeon.client.emotes;

import com.cubeon.client.Bridge;
import com.cubeon.client.hud.CubeonHudConfig;
import net.minecraft.client.MinecraftClient;
import java.util.List;

public final class EmoteClient {
    private static Object world;
    private static String address = "";
    private static List<Bridge.EmoteEvent> previous = List.of();
    private EmoteClient() { }
    public static void tick() {
        MinecraftClient client = MinecraftClient.getInstance();
        if (client.player == null || client.world == null || !CubeonHudConfig.get().showEmotes) {
            if (world != null) { EmoteState.reset(); Bridge.get().setEmoteRoom(""); world = null; }
            return;
        }
        String current = client.getCurrentServerEntry() == null
                ? "single:" + client.player.getUuid() : client.getCurrentServerEntry().address;
        if (world != client.world || !address.equals(current)) {
            world = client.world; address = current; previous = List.of();
            EmoteState.reset(); Bridge.get().setEmoteRoom(EmoteRoom.hash(current));
        }
        if (client.isPaused()) return;
        EmoteState.tick();
        List<Bridge.EmoteEvent> fresh = Bridge.get().emotes();
        if (fresh != previous) { EmoteState.sync(fresh); previous = fresh; }
        if (EmoteState.playing(client.player.getUuid())
                && (client.player.getVelocity().horizontalLengthSquared() > .0004
                || client.options.jumpKey.isPressed() || client.options.attackKey.isPressed()
                || client.options.useKey.isPressed()
                || client.player.hasVehicle() || !client.player.isAlive())) play(-1);
    }
    public static void play(int emote) {
        if (emote >= EmoteState.NAMES.length) return;
        MinecraftClient client = MinecraftClient.getInstance();
        if (client.player == null || client.world == null || !CubeonHudConfig.get().showEmotes) return;
        int serial = EmoteState.play(client.player.getUuid(), client.player.getName().getString(), emote);
        Bridge.get().sendEmote(client.player.getUuid().toString(),
                emote < 0 ? "stop" : EmoteState.NAMES[emote], serial);
    }
}
