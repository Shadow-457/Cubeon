package com.cubeon.client.lod;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.security.*;
import java.util.*;
import net.minecraft.client.Minecraft;
import net.minecraft.server.packs.*;
import net.minecraft.server.packs.repository.Pack;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.storage.LevelResource;

/** Capture identities on the client; hash owned pack streams only on a background worker. */
public record CacheIdentity(String worldDimension, List<Pack> packs) {
    public CacheIdentity { packs = List.copyOf(packs); }
    public static CacheIdentity capture(Minecraft mc) {
        String world = mc.getSingleplayerServer() != null
                ? "local:" + mc.getSingleplayerServer().getWorldPath(LevelResource.ROOT).toAbsolutePath().normalize()
                : mc.getCurrentServer() != null ? "server:" + mc.getCurrentServer().ip.toLowerCase(Locale.ROOT) : "session:" + mc.level;
        return new CacheIdentity(hash(world) + "/" + hash(mc.level.dimension().identifier().toString()),
                List.copyOf(mc.getResourcePackRepository().getSelectedPacks()));
    }
    public String fingerprint() throws IOException {
        MessageDigest digest = digest();
        update(digest, "26.3:clod1:faces2");
        for (var state : Block.BLOCK_STATE_REGISTRY) update(digest, Block.getId(state) + ":" + state);
        byte[] buffer = new byte[8192];
        for (Pack pack : packs) {
            update(digest, pack.getId());
            try (var opened = pack.open()) {
                for (PackResources resources : opened.toList()) try (resources) {
                    var contents = new TreeMap<String, net.minecraft.server.packs.resources.IoSupplier<InputStream>>();
                    for (String namespace : new TreeSet<>(resources.getNamespaces(PackType.CLIENT_RESOURCES))) {
                        for (String folder : List.of("textures", "models", "blockstates", "atlases"))
                            resources.listResources(PackType.CLIENT_RESOURCES, namespace, folder,
                                    (id, stream) -> contents.put(id.toString(), stream));
                    }
                    for (var entry : contents.entrySet()) {
                        if (Thread.currentThread().isInterrupted()) throw new IOException("Cache fingerprint cancelled");
                        update(digest, entry.getKey());
                        try (InputStream input = entry.getValue().get()) {
                            int count; while ((count = input.read(buffer)) != -1) digest.update(buffer, 0, count);
                        }
                    }
                }
            }
        }
        return worldDimension + "/" + HexFormat.of().formatHex(digest.digest());
    }
    private static void update(MessageDigest digest, String value) { digest.update(value.getBytes(StandardCharsets.UTF_8)); digest.update((byte)0); }
    private static MessageDigest digest() {
        try { return MessageDigest.getInstance("SHA-256"); }
        catch (NoSuchAlgorithmException ex) { throw new AssertionError(ex); }
    }
    private static String hash(String value) { return HexFormat.of().formatHex(digest().digest(value.getBytes(StandardCharsets.UTF_8))).substring(0, 24); }
}
