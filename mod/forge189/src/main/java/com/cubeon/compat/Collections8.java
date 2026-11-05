package com.cubeon.compat;

import java.util.*;

/** Java 8 equivalents for the small modern collection API used by shared code. */
public final class Collections8 {
    public static String encode(String value) {
        try { return java.net.URLEncoder.encode(value, "UTF-8"); }
        catch (java.io.UnsupportedEncodingException impossible) { throw new AssertionError(impossible); }
    }
    public static byte[] read(java.io.InputStream in, int limit) throws java.io.IOException {
        java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream();
        byte[] block = new byte[Math.min(8192, limit)];
        while (out.size() < limit) {
            int count = in.read(block, 0, Math.min(block.length, limit - out.size()));
            if (count < 0) break;
            out.write(block, 0, count);
        }
        return out.toByteArray();
    }
    public static byte[] read(java.nio.file.Path file, int limit) throws java.io.IOException {
        try (java.io.InputStream in = java.nio.file.Files.newInputStream(file)) {
            byte[] bytes = read(in, limit + 1);
            if (bytes.length > limit) throw new java.io.IOException("Cubeon settings too large");
            return bytes;
        }
    }
    public static void writeAtomic(java.nio.file.Path file, byte[] bytes) throws java.io.IOException {
        java.nio.file.Files.createDirectories(file.getParent());
        java.nio.file.Path temp = java.nio.file.Files.createTempFile(file.getParent(), ".cubeon-hud-", ".tmp");
        try {
            java.nio.file.Files.write(temp, bytes);
            try { java.nio.file.Files.move(temp, file, java.nio.file.StandardCopyOption.ATOMIC_MOVE, java.nio.file.StandardCopyOption.REPLACE_EXISTING); }
            catch (java.nio.file.AtomicMoveNotSupportedException e) {
                java.nio.file.Files.move(temp, file, java.nio.file.StandardCopyOption.REPLACE_EXISTING);
            }
        } finally { java.nio.file.Files.deleteIfExists(temp); }
    }
    public static String hex(byte[] bytes) {
        StringBuilder text = new StringBuilder(bytes.length * 2);
        for (byte value : bytes) text.append(Character.forDigit((value >> 4) & 15, 16)).append(Character.forDigit(value & 15, 16));
        return text.toString();
    }
    private Collections8() { }
    @SafeVarargs public static <T> List<T> list(T... values) {
        for (T value : values) Objects.requireNonNull(value);
        return Collections.unmodifiableList(new ArrayList<T>(Arrays.asList(values)));
    }
    public static <T> List<T> copy(Collection<? extends T> values) {
        List<T> result = new ArrayList<T>(values);
        for (T value : result) Objects.requireNonNull(value);
        return Collections.unmodifiableList(result);
    }
    public static boolean blank(String value) {
        for (int i = 0; i < value.length();) {
            int cp = value.codePointAt(i);
            if (!Character.isWhitespace(cp)) return false;
            i += Character.charCount(cp);
        }
        return true;
    }
}
