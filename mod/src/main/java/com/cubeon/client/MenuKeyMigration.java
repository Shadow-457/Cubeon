package com.cubeon.client;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;

/** Move the former default K binding to Right Shift; keep other custom bindings. */
public final class MenuKeyMigration {
    private MenuKeyMigration() { }
    public static void migrate(File gameDirectory) {
        Path file = gameDirectory.toPath().resolve("options.txt"), temporary = null;
        try {
            String original = Files.readString(file, StandardCharsets.UTF_8);
            String updated = original.replaceAll(
                    "(?m)^key_cubeon-client\\.open_menu:key\\.keyboard\\.k(?=\\r?$)",
                    "key_cubeon-client.open_menu:key.keyboard.right.shift");
            if (updated.equals(original)) return;
            temporary = Files.createTempFile(file.getParent(), ".cubeon-menu-key-", ".tmp");
            Files.writeString(temporary, updated, StandardCharsets.UTF_8);
            Files.move(temporary, file, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
        } catch (IOException error) {
            // A read-only or missing file must never block game startup.
        } finally {
            if (temporary != null) try { Files.deleteIfExists(temporary); } catch (IOException ignored) { }
        }
    }
}
