package com.cubeon.client.emotes;

import java.util.ArrayList;
import java.util.List;

/** Stable names in config; neither catalog additions nor reordering changes favorites. */
public final class EmoteFavorites {
    public static final int MAX = 8;
    private EmoteFavorites() { }
    public static String[] defaults() {
        return new String[]{"wave", "dance", "bow", "salute", "shrug", "point", "clap", "celebrate"};
    }
    public static String[] normalize(String[] names) {
        List<String> valid = new ArrayList<>();
        if (names != null) for (String name : names) {
            if (EmoteState.id(name) >= 0 && !valid.contains(name)) valid.add(name);
            if (valid.size() == MAX) break;
        }
        return valid.isEmpty() ? defaults() : valid.toArray(String[]::new);
    }
}
