package com.cubeon.forge;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.io.InputStreamReader;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;

/**
 * 1.8.9 only loads legacy .lang files, so the shared screen labels are read from the
 * same en_us.json the Fabric jars ship. Missing keys fall back to the key itself.
 */
final class Lang8 {
    private static Map<String, String> values;
    private Lang8() { }
    private static synchronized void load() {
        if (values != null) return;
        Map<String, String> loaded = new HashMap<String, String>();
        InputStream stream = Lang8.class.getResourceAsStream("/assets/cubeon-client/lang/en_us.json");
        if (stream != null) {
            try {
                JsonObject json = new JsonParser().parse(
                        new InputStreamReader(stream, StandardCharsets.UTF_8)).getAsJsonObject();
                for (Map.Entry<String, JsonElement> entry : json.entrySet())
                    if (entry.getValue().isJsonPrimitive()) loaded.put(entry.getKey(), entry.getValue().getAsString());
            } catch (RuntimeException ignored) {
                // A malformed lang file only costs labels, never a crash in a menu.
            } finally {
                try { stream.close(); } catch (java.io.IOException ignored) { }
            }
        }
        values = loaded;
    }
    static String translate(String key) {
        load();
        String value = values.get(key);
        return value == null ? key : value;
    }
}
