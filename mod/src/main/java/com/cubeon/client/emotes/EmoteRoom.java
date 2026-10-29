package com.cubeon.client.emotes;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.Locale;

public final class EmoteRoom {
    private EmoteRoom() { }
    public static String hash(String address) {
        String canonical = address.trim().toLowerCase(Locale.ROOT);
        if (canonical.endsWith(":25565")) canonical = canonical.substring(0, canonical.length()-6);
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(("cubeon-emotes-v1:"+canonical).getBytes(StandardCharsets.UTF_8)));
        } catch (java.security.NoSuchAlgorithmException impossible) {
            throw new IllegalStateException(impossible);
        }
    }
}
