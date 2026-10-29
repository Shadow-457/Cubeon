package com.cubeon.client.emotes;

import com.cubeon.client.Bridge;
import com.cubeon.client.hud.CubeonHudConfig;
import net.minecraft.client.Minecraft;
import java.util.List;

public final class EmoteClient {
    private static Object world;
    private static String address = "";
    private static List<Bridge.EmoteEvent> previous = List.of();
    private EmoteClient() { }
    public static void tick() {
        Minecraft client = Minecraft.getInstance();
        if (client.player == null || client.level == null || !CubeonHudConfig.get().showEmotes) {
            if (world != null) { EmoteState.reset(); Bridge.get().setEmoteRoom(""); world = null; }
            return;
        }
        String current = client.getCurrentServer() == null
                ? "single:" + client.player.getUUID() : client.getCurrentServer().ip;
        if (world != client.level || !address.equals(current)) {
            world = client.level; address = current; previous = List.of();
            EmoteState.reset(); Bridge.get().setEmoteRoom(EmoteRoom.hash(current));
        }
        if (client.isPaused()) return;
        EmoteState.tick();
        List<Bridge.EmoteEvent> fresh = Bridge.get().emotes();
        if (fresh != previous) { EmoteState.sync(fresh); previous = fresh; }
        if (EmoteState.playing(client.player.getUUID())
                && (client.player.getDeltaMovement().horizontalDistanceSqr() > .0004
                || client.options.keyJump.isDown() || client.options.keyAttack.isDown()
                || client.options.keyUse.isDown() || client.player.isFallFlying()
                || client.player.isPassenger() || !client.player.isAlive())) play(-1);
    }
    public static void play(int emote) {
        if (emote >= EmoteState.NAMES.length) return;
        Minecraft client = Minecraft.getInstance();
        if (client.player == null || client.level == null || !CubeonHudConfig.get().showEmotes) return;
        int serial = EmoteState.play(client.player.getUUID(), client.player.getName().getString(), emote);
        Bridge.get().sendEmote(client.player.getUUID().toString(),
                emote < 0 ? "stop" : EmoteState.NAMES[emote], serial);
    }
}
