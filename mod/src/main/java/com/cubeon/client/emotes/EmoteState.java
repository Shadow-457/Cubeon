package com.cubeon.client.emotes;

import com.cubeon.client.Bridge;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

/** Client-thread-only, bounded active poses. No timers or rendering-thread I/O. */
public final class EmoteState {
    public static final String[] NAMES = {"wave", "dance", "bow", "salute", "shrug", "point"};
    private static final float[] DURATIONS = {3, 6, 3, 3, 2.5f, 3};
    private record Active(String username, int emote, int serial, float start, boolean local) { }
    private static final Map<String, Active> ACTIVE = new HashMap<>();
    private static final Map<String, Integer> LOCAL_SERIAL = new HashMap<>();
    private static float ticks;
    private static int serial;
    private EmoteState() { }

    public static int id(String name) {
        for (int i=0; i<NAMES.length; i++) if (NAMES[i].equals(name)) return i;
        return -1;
    }
    public static void reset() { ACTIVE.clear(); LOCAL_SERIAL.clear(); ticks = 0; }
    public static void tick() {
        ticks++;
        ACTIVE.entrySet().removeIf(e -> (ticks - e.getValue().start()) / 20 >= DURATIONS[e.getValue().emote()]);
    }
    public static boolean active() { return !ACTIVE.isEmpty(); }
    public static boolean playing(UUID uuid) { return ACTIVE.containsKey(uuid.toString()); }
    public static int play(UUID uuid, String name, int emote) {
        serial = serial == Integer.MAX_VALUE ? 1 : serial + 1;
        LOCAL_SERIAL.put(uuid.toString(), serial);
        if (emote < 0) ACTIVE.remove(uuid.toString());
        else if (emote < NAMES.length) ACTIVE.put(uuid.toString(), new Active(name, emote, serial, ticks, true));
        return serial;
    }
    public static void sync(List<Bridge.EmoteEvent> events) {
        Set<String> live = new HashSet<>();
        for (Bridge.EmoteEvent event : events) {
            int emote = id(event.emote());
            if (event.serial() < LOCAL_SERIAL.getOrDefault(event.uuid(), -1)) continue;
            if (emote < 0 || !Float.isFinite(event.age()) || event.age() < 0
                    || event.age() >= DURATIONS[emote] || !event.username().matches("[A-Za-z0-9_]{3,16}")) continue;
            try { UUID.fromString(event.uuid()); } catch (IllegalArgumentException invalid) { continue; }
            live.add(event.uuid());
            Active previous = ACTIVE.get(event.uuid());
            if (previous != null && previous.serial() == event.serial() && previous.emote() == emote) {
                if (previous.local()) ACTIVE.put(event.uuid(), new Active(previous.username(), emote,
                        previous.serial(), previous.start(), false));
                continue;
            }
            if (ACTIVE.size() < 128 || previous != null) ACTIVE.put(event.uuid(),
                    new Active(event.username(), emote, event.serial(), ticks - event.age() * 20, false));
        }
        ACTIVE.entrySet().removeIf(e -> !e.getValue().local() && !live.contains(e.getKey()));
    }
    public static EmotePose frame(UUID uuid, String name, float partialTick) {
        if (ACTIVE.isEmpty()) return null;
        Active active = ACTIVE.get(uuid.toString());
        if (active == null || !active.username().equalsIgnoreCase(name)) return null;
        float age = (ticks + Math.max(0, Math.min(1, partialTick)) - active.start()) / 20;
        return age >= DURATIONS[active.emote()] ? null : EmotePose.sample(active.emote(), age, DURATIONS[active.emote()]);
    }
}
