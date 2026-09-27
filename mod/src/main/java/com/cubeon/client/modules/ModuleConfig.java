package com.cubeon.client.modules;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Loads and saves which modules are on, and their settings.
 *
 * <p>Minecraft-free on purpose, so the format can be round-tripped on a bare
 * JDK. The parser is the mod's own {@link com.cubeon.client.Json} rather than
 * the Gson Minecraft happens to ship - see that class for why.
 *
 * <p>Format, one object per module id:
 * <pre>
 * {"fullbright": {"on": true}, "fov": {"on": true, "value": 90}}
 * </pre>
 *
 * <p><b>Never throws.</b> A missing, unreadable, truncated or hand-mangled
 * file degrades to "defaults", because losing a preference is annoying and
 * refusing to start the game over it would be absurd. Writes go to a temp file
 * and are moved into place, so a crash mid-save cannot leave a half-written
 * file that reads as "everything off".
 */
public final class ModuleConfig {

    public static final String FILE_NAME = "cubeon-modules.json";

    private final Map<String, Map<String, Object>> data = new LinkedHashMap<>();

    /** Builds the config object from a raw parsed map. */
    public static ModuleConfig fromMap(Map<String, Object> raw) {
        ModuleConfig config = new ModuleConfig();
        if (raw == null) {
            return config;
        }
        for (Map.Entry<String, Object> entry : raw.entrySet()) {
            if (entry.getKey() == null || !(entry.getValue() instanceof Map<?, ?> m)) {
                continue;   // not a module block - ignore rather than guess
            }
            Map<String, Object> copy = new LinkedHashMap<>();
            for (Map.Entry<?, ?> field : m.entrySet()) {
                if (field.getKey() != null) {
                    copy.put(String.valueOf(field.getKey()), field.getValue());
                }
            }
            config.data.put(entry.getKey(), copy);
        }
        return config;
    }

    /** Parses JSON text, returning an empty config on anything malformed. */
    public static ModuleConfig parse(String text) {
        try {
            return fromMap(com.cubeon.client.Json.parseObject(text));
        } catch (Throwable ignored) {
            return new ModuleConfig();
        }
    }

    /** Applies this config onto a set of modules. Unknown ids are ignored. */
    public void applyTo(List<Module> modules) {
        for (Module module : modules) {
            Map<String, Object> stored = data.get(module.id());
            if (stored == null) {
                continue;
            }
            Object on = stored.get("on");
            if (on instanceof Boolean flag) {
                // setEnabled re-applies, so a module that is already on is left
                // alone rather than needlessly rewriting the game's options.
                if (flag != module.isEnabled()) {
                    module.setEnabled(flag);
                }
            }
            for (String key : module.settingKeys()) {
                Object value = stored.get(key);
                if (value instanceof Boolean flag) {
                    module.setBoolValue(key, flag);
                } else if (value instanceof Number number) {
                    // setIntValue clamps, so a hand-edited 9999 cannot stick.
                    module.setIntValue(key, number.intValue());
                }
            }
        }
    }

    /** The JSON text for a set of modules. */
    public static String toJson(List<Module> modules) {
        StringBuilder out = new StringBuilder("{\n");
        for (int i = 0; i < modules.size(); i++) {
            Module module = modules.get(i);
            out.append("  \"").append(module.id()).append("\": {\"on\": ")
               .append(module.isEnabled());
            for (String key : module.settingKeys()) {
                out.append(", \"").append(key).append("\": ");
                if (module.isBoolSetting(key)) {
                    out.append(module.boolValue(key));
                } else {
                    out.append(module.rawIntValue(key));
                }
            }
            out.append("}");
            if (i < modules.size() - 1) {
                out.append(',');
            }
            out.append('\n');
        }
        return out.append("}\n").toString();
    }

    /** Reads the config, or returns an empty one. Never throws. */
    public static ModuleConfig load(Path file) {
        try {
            if (!Files.isRegularFile(file)) {
                return new ModuleConfig();
            }
            return parse(Files.readString(file, StandardCharsets.UTF_8));
        } catch (Throwable ignored) {
            return new ModuleConfig();
        }
    }

    /** Writes the config atomically. Returns false if it could not be saved. */
    public static boolean save(Path file, List<Module> modules) {
        try {
            Path parent = file.getParent();
            if (parent != null) {
                Files.createDirectories(parent);
            }
            Path tmp = file.resolveSibling(FILE_NAME + ".tmp");
            Files.writeString(tmp, toJson(modules), StandardCharsets.UTF_8);
            Files.move(tmp, file, java.nio.file.StandardCopyOption.REPLACE_EXISTING);
            return true;
        } catch (IOException | RuntimeException ignored) {
            return false;
        }
    }
}
