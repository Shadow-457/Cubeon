package gg.cubeon.gate;

import net.kyori.adventure.text.Component;
import net.kyori.adventure.text.format.NamedTextColor;
import net.kyori.adventure.text.format.TextDecoration;
import org.bukkit.Bukkit;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.block.BlockBreakEvent;
import org.bukkit.event.block.BlockPlaceEvent;
import org.bukkit.event.inventory.InventoryClickEvent;
import org.bukkit.event.inventory.InventoryOpenEvent;
import org.bukkit.event.player.AsyncPlayerChatEvent;
import org.bukkit.event.player.AsyncPlayerPreLoginEvent;
import org.bukkit.event.player.PlayerCommandPreprocessEvent;
import org.bukkit.event.player.PlayerDropItemEvent;
import org.bukkit.event.player.PlayerInteractEvent;
import org.bukkit.event.player.PlayerJoinEvent;
import org.bukkit.event.player.PlayerMoveEvent;
import org.bukkit.event.player.PlayerPickupItemEvent;
import org.bukkit.event.player.PlayerQuitEvent;
import org.bukkit.event.player.PlayerTeleportEvent;
import org.bukkit.event.entity.EntityDamageByEntityEvent;
import org.bukkit.plugin.java.JavaPlugin;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.PBEKeySpec;

/**
 * CubeonGate - the Cubeon security check.
 *
 * One job: until a joining player's UUID has been verified against the
 * owner's server password, they get a password screen instead of the world -
 * before they spawn, move, run a command, chat, or touch anything.
 *
 * THE SCREEN (exact wording, shown as title + chat):
 *     "Cubeon security check: This password is required for your server
 *      to be safe and playable."
 *
 * HOW A PLAYER ANSWERS: they just type the password into chat. The chat
 * event is cancelled, so the attempt is never broadcast and never lands in
 * the server log - the password exists only in memory for the comparison.
 *
 * VERIFICATION PERSISTS: a correct answer stores the player's UUID in
 * state.json. Every later join by that UUID skips the screen entirely -
 * "so the prompt does not annoy the player again later".
 *
 * FAILURES ESCALATE, PERSISTENTLY:
 *     failures 1-2  -> warning, try again
 *     failure 3     -> locked out 10 minutes
 *     failure 4     -> locked out 20 minutes
 *     failure n>=4  -> 10 * 2^(n-3) minutes (40, 80, 160 ...)
 * Counters and lockouts live in state.json, so restarting the server (or
 * reconnecting) does not reset them.
 *
 * CREDENTIALS: plugins/CubeonGate/credentials.json holds ONLY a random salt
 * and a PBKDF2-HmacSHA256 hash - never the password. The hash is compared
 * with MessageDigest.isEqual (constant-time). When the owner sets a new
 * password, Cubeon (the launcher) deletes state.json's verified set, so a
 * changed password re-verifies everyone.
 */
public final class CubeonGate extends JavaPlugin implements Listener {

    private static final int PBKDF2_ITERATIONS = 60_000;
    private static final int PBKDF2_KEY_BITS = 256;
    private static final int BASE_LOCK_MINUTES = 10;
    private static final int FREE_FAILS = 2;      // fails 3+ lock the account
    private static final long MAX_LOCK_MINUTES = 7 * 24 * 60; // one week cap

    private static final String SCREEN_TITLE = "Cubeon security check";
    private static final String SCREEN_MESSAGE =
            "Cubeon security check: This password is required for your "
            + "server to be safe and playable.";
    // Short, box-friendly body text that also powers the kick message.
    private static final String FORM_BODY_1 =
            "This password is required for your server to be safe and playable.";

    /** Players currently in the password screen (this server session). */
    private final Set<UUID> pending = ConcurrentHashMap.newKeySet();

    private final SecureRandom random = new SecureRandom();

    private Path dataDir;
    private Path statePath;
    private Path credPath;

    // ---- persisted state (guarded by {@code stateLock} for writes) ----
    private final Map<UUID, String> verifiedNames = new ConcurrentHashMap<>();
    private final Map<UUID, int[]> failCounts = new ConcurrentHashMap<>(); // [count]
    private final Map<UUID, Long> lockedUntil = new ConcurrentHashMap<>();
    private String credentialsFingerprint = "";

    @Override
    public void onEnable() {
        dataDir = getDataFolder().toPath();
        statePath = dataDir.resolve("state.json");
        credPath = dataDir.resolve("credentials.json");
        loadState();
        getServer().getPluginManager().registerEvents(this, this);
        int verified = verifiedNames.size();
        boolean gateOn = readCredentials() != null;
        getLogger().info("CubeonGate active. Password gate: "
                + (gateOn ? "ON" : "OFF (owner hasn't set a password)")
                + ", verified UUIDs: " + verified);
    }

    @Override
    public void onDisable() {
        saveState();
    }

    // ------------------------------------------------------------------
    // Credentials - what the launcher writes, we only read.
    // ------------------------------------------------------------------

    private static final class Credentials {
        final String saltHex;
        final String hashHex;
        final int iterations;

        Credentials(String saltHex, String hashHex, int iterations) {
            this.saltHex = saltHex;
            this.hashHex = hashHex;
            this.iterations = iterations;
        }
    }

    /**
     * Re-read on every check, never cached across joins: the owner can set
     * a new password from the launcher at any time, and a stale in-memory
     * hash would keep authenticating against the OLD password - exactly the
     * bug a security gate must not have. The file is tiny; the cost is nil.
     */
    private Credentials readCredentials() {
        try {
            String json = new String(Files.readAllBytes(credPath),
                    StandardCharsets.UTF_8);
            String salt = extractString(json, "salt_hex");
            String hash = extractString(json, "hash_hex");
            int iters = extractInt(json, "iterations", PBKDF2_ITERATIONS);
            if (salt == null || hash == null || salt.isEmpty() || hash.isEmpty()) {
                return null;
            }
            Credentials c = new Credentials(salt, hash, iters);
            String fp = c.saltHex + ":" + c.hashHex;
            if (!fp.equals(credentialsFingerprint)) {
                // The password changed (or first read this session): a new
                // password invalidates every previously verified UUID.
                credentialsFingerprint = fp;
                if (!verifiedNames.isEmpty()) {
                    verifiedNames.clear();
                    saveState();
                    getLogger().info("Password changed - all verified UUIDs "
                            + "cleared, everyone re-verifies.");
                }
            }
            return c;
        } catch (IOException | RuntimeException ex) {
            return null; // no/unreadable credentials = gate off
        }
    }

    // ------------------------------------------------------------------
    // Gate entry point - fires BEFORE the player spawns into the world.
    // ------------------------------------------------------------------

    @EventHandler(priority = EventPriority.LOWEST)
    public void onPreLogin(AsyncPlayerPreLoginEvent event) {
        Credentials cred = readCredentials();
        if (cred == null) {
            return; // owner hasn't set a password - gate off
        }
        UUID uuid = event.getUniqueId();
        if (verifiedNames.containsKey(uuid)) {
            return; // already verified - no prompt, ever, until password changes
        }

        Long until = lockedUntil.get(uuid);
        long now = System.currentTimeMillis();
        if (until != null && until > now) {
            event.setLoginResult(AsyncPlayerPreLoginEvent.Result.KICK_OTHER);
            event.setKickMessage(SCREEN_MESSAGE + "\n"
                    + formatLockMessage(uuid, now));
            return;
        }
        if (until != null && until <= now) {
            lockedUntil.remove(uuid);
            saveState();
        }
        // Allowed in - they land directly on the password screen (join
        // handler below) and can do nothing until verified.
    }

    @EventHandler(priority = EventPriority.MONITOR)
    public void onJoin(PlayerJoinEvent event) {
        Player player = event.getPlayer();
        applyPlayerListBranding(player);
        if (readCredentials() == null) {
            return;
        }
        if (verifiedNames.containsKey(player.getUniqueId())) {
            return;
        }
        pending.add(player.getUniqueId());
        showScreen(player, null);
    }

    // ------------------------------------------------------------------
    // Tab-list branding. Pressing Tab shows "Cubeon" up top and the
    // server's public endpoint underneath - same slot Minekube's own
    // plugin uses, Cubeon branding instead.
    //
    // The address comes from address.txt, which the launcher's watcher
    // writes the moment the Connect plugin announces it (handles random
    // endpoints the config can't know). Falls back to the endpoint
    // configured in plugins/connect/config.yml, then to a plain tagline.
    // ------------------------------------------------------------------

    private void applyPlayerListBranding(Player player) {
        String address = readPublicAddress();
        player.sendPlayerListHeaderAndFooter(
                Component.text("Cubeon", NamedTextColor.GREEN, TextDecoration.BOLD),
                address != null
                        ? Component.text(address, NamedTextColor.GRAY)
                        : Component.text("Powered by Cubeon", NamedTextColor.DARK_GRAY));
    }

    private String readPublicAddress() {
        try {
            Path addrFile = dataDir.resolve("address.txt");
            if (Files.exists(addrFile)) {
                String address = new String(Files.readAllBytes(addrFile),
                        StandardCharsets.UTF_8).trim();
                if (!address.isEmpty()) {
                    return address;
                }
            }
        } catch (IOException ignored) {
            // fall through to the Connect config
        }
        try {
            Path connectCfg = dataDir.getParent().resolve("connect").resolve("config.yml");
            if (Files.exists(connectCfg)) {
                String yaml = new String(Files.readAllBytes(connectCfg),
                        StandardCharsets.UTF_8);
                java.util.regex.Matcher m = java.util.regex.Pattern
                        .compile("^endpoint\\s*:\\s*(.+)$", java.util.regex.Pattern.MULTILINE)
                        .matcher(yaml);
                if (m.find()) {
                    String endpoint = m.group(1).trim()
                            .replace("\"", "").replace("'", "");
                    if (!endpoint.isEmpty()) {
                        if (endpoint.contains(".")) {
                            return endpoint; // a full custom domain
                        }
                        return endpoint + ".play.minekube.net";
                    }
                }
            }
        } catch (IOException ignored) {
            // no Connect config - plain tagline it is
        }
        return null;
    }

    @EventHandler
    public void onQuit(PlayerQuitEvent event) {
        pending.remove(event.getPlayer().getUniqueId());
    }

    private void showScreen(Player player, String status, NamedTextColor statusColor) {
        player.sendTitle(SCREEN_TITLE, "Enter the server password to play", 10, 100, 10);
        openForm(player, status, statusColor);
    }

    private void showScreen(Player player, String status) {
        showScreen(player, status, NamedTextColor.GRAY);
    }

    /**
     * The gate's on-screen "form". Every line goes out as its own chat message
     * so the panel reads cleanly on any client with no resource pack. The three
     * labelled sections are the affordance the player needs to understand what
     * to do without being told twice:
     *   ▸ INPUT    - type the server password into chat
     *   ▸ SUBMIT   - press Enter to send it
     *   ▸ OUTPUT   - the live result of the last attempt (or a waiting state)
     */
    private void openForm(Player player, String status, NamedTextColor statusColor) {
        String bar = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━";
        player.sendMessage(Component.text("┏" + bar + "┓", NamedTextColor.DARK_GRAY));
        player.sendMessage(Component.text("  " + SCREEN_TITLE,
                NamedTextColor.GREEN, TextDecoration.BOLD));
        player.sendMessage(Component.text("  " + FORM_BODY_1, NamedTextColor.YELLOW));
        player.sendMessage(Component.text("┣" + bar + "┫", NamedTextColor.DARK_GRAY));
        player.sendMessage(Component.text("  ▸ INPUT    Type the server password into chat",
                NamedTextColor.GRAY));
        player.sendMessage(Component.text("  ▸ SUBMIT   Press Enter to submit  (never shown)",
                NamedTextColor.GRAY));
        player.sendMessage(Component.text("┣" + bar + "┫", NamedTextColor.DARK_GRAY));
        // OUTPUT area - the live status of the gate.
        player.sendMessage(Component.text("  ▸ OUTPUT   ", NamedTextColor.GRAY).append(
                Component.text(status == null ? "Waiting for your password…" : status,
                        status == null ? NamedTextColor.GRAY : statusColor)));
        player.sendMessage(Component.text("┗" + bar + "┛", NamedTextColor.DARK_GRAY));
    }

    private void sendVerifiedForm(Player player) {
        String bar = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━";
        player.sendMessage(Component.text("┏" + bar + "┓", NamedTextColor.DARK_GRAY));
        player.sendMessage(Component.text("  ✓ VERIFIED", NamedTextColor.GREEN, TextDecoration.BOLD));
        player.sendMessage(Component.text("  Welcome to the server.", NamedTextColor.GREEN));
        player.sendMessage(Component.text("  You won't be asked again unless the owner",
                NamedTextColor.GREEN));
        player.sendMessage(Component.text("  changes the password.", NamedTextColor.GREEN));
        player.sendMessage(Component.text("┗" + bar + "┛", NamedTextColor.DARK_GRAY));
    }

    // ------------------------------------------------------------------
    // The answer: chat input. Cancelled, so it never broadcasts or logs.
    //
    // LOWEST + ignoreCancelled=false is deliberate: AuthMe also cancels
    // chat (its own login flow) and if it cancelled first we would never
    // see the password. Running first means a gate-pending player's chat
    // is consumed HERE as a password attempt and AuthMe never sees it;
    // once verified, this handler passes everything through untouched and
    // AuthMe's own flow takes over normally.
    // ------------------------------------------------------------------

    @EventHandler(priority = EventPriority.LOWEST, ignoreCancelled = false)
    public void onChat(AsyncPlayerChatEvent event) {
        Player player = event.getPlayer();
        if (!pending.remove(player.getUniqueId())) {
            return; // not on the gate - AuthMe (or plain chat) proceeds
        }
        event.setCancelled(true);
        String attempt = event.getMessage() == null ? "" : event.getMessage().trim();
        // Hand off to the main thread: file IO and state mutation don't
        // belong on the async chat thread.
        Bukkit.getScheduler().runTask(this, () -> checkPassword(player, attempt));
    }

    private void checkPassword(Player player, String attempt) {
        Credentials cred = readCredentials();
        if (cred == null || !player.isOnline()) {
            return;
        }
        UUID uuid = player.getUniqueId();

        Long until = lockedUntil.get(uuid);
        long now = System.currentTimeMillis();
        if (until != null && until > now) {
            pending.add(uuid); // still not verified
            showScreen(player, formatLockMessage(uuid, now), NamedTextColor.RED);
            return;
        }

        if (hashMatches(attempt, cred)) {
            failCounts.remove(uuid);
            lockedUntil.remove(uuid);
            verifiedNames.put(uuid, player.getName());
            saveState();
            player.sendTitle("✓ Verified", "Welcome to the server!", 5, 40, 10);
            sendVerifiedForm(player);
            if (getServer().getPluginManager().getPlugin("AuthMe") != null) {
                player.sendMessage(Component.text(
                        "One more step: finish the server's account login "
                        + "(/register <password> or /login <password>).",
                        NamedTextColor.GRAY));
            }
            getLogger().info("UUID " + uuid + " passed the security check.");
            return;
        }

        int fails = bumpFails(uuid);
        if (fails >= FREE_FAILS + 1) {
            long minutes = lockMinutesFor(fails);
            long untilMs = now + minutes * 60_000L;
            lockedUntil.put(uuid, untilMs);
            saveState();
            player.kickPlayer(SCREEN_MESSAGE + "\n"
                    + "cToo many failed attempts. Locked for " + minutes
                    + " minute" + (minutes == 1 ? "" : "s") + ".");
            getLogger().warning("UUID " + uuid + " failed the security check "
                    + fails + " times - locked for " + minutes + " minutes.");
            return;
        }

        pending.add(uuid);
        showScreen(player, "Wrong password. Attempt " + fails + " of "
                + (FREE_FAILS + 1) + " before a "
                + BASE_LOCK_MINUTES + "-minute lockout.", NamedTextColor.RED);
    }

    /** 3rd fail -> 10 min, 4th -> 20, 5th -> 40 ... capped at one week. */
    private static long lockMinutesFor(int fails) {
        double minutes = BASE_LOCK_MINUTES * Math.pow(2, fails - (FREE_FAILS + 1));
        return Math.min((long) Math.ceil(minutes), MAX_LOCK_MINUTES);
    }

    private int bumpFails(UUID uuid) {
        int[] count = failCounts.computeIfAbsent(uuid, k -> new int[]{0});
        count[0] += 1;
        saveState();
        return count[0];
    }

    private String formatLockMessage(UUID uuid, long now) {
        Long until = lockedUntil.get(uuid);
        if (until == null) {
            return "cLocked. Try again later.";
        }
        long minutesLeft = (until - now + 59_999) / 60_000;
        return "cLocked after too many failed attempts. Try again in "
                + minutesLeft + " minute" + (minutesLeft == 1 ? "" : "s") + ".";
    }

    // ------------------------------------------------------------------
    // The wall: nothing happens until verified.
    // ------------------------------------------------------------------

    private boolean blocked(Player player) {
        return pending.contains(player.getUniqueId());
    }

    @EventHandler(priority = EventPriority.LOWEST, ignoreCancelled = true)
    public void onMove(PlayerMoveEvent event) {
        // Head rotation is allowed (looking around is harmless and less
        // disorienting); any actual position change is not.
        if (blocked(event.getPlayer())
                && (event.getFrom().getBlockX() != event.getTo().getBlockX()
                    || event.getFrom().getBlockY() != event.getTo().getBlockY()
                    || event.getFrom().getBlockZ() != event.getTo().getBlockZ())) {
            event.setTo(event.getFrom());
        }
    }

    @EventHandler(priority = EventPriority.LOWEST, ignoreCancelled = true)
    public void onTeleport(PlayerTeleportEvent event) {
        if (blocked(event.getPlayer())) {
            event.setCancelled(true);
        }
    }

    // AuthMe's own commands stay usable even while gate-pending. Without
    // this the two plugins deadlock: AuthMe demands "/register" before it
    // lets a player do anything, while the gate cancelled every command -
    // so neither plugin's screen could ever be satisfied. Either order
    // works now: the player can pass AuthMe first, the gate first, or
    // interleave; BOTH must pass before the world is interactive.
    private static final Set<String> AUTHME_COMMANDS = Set.of(
            "register", "reg", "login", "l", "log", "email", "captcha");

    @EventHandler(priority = EventPriority.LOWEST, ignoreCancelled = true)
    public void onCommand(PlayerCommandPreprocessEvent event) {
        if (!blocked(event.getPlayer())) {
            return;
        }
        String message = event.getMessage().toLowerCase();
        String root = message.startsWith("/") ? message.substring(1) : message;
        int space = root.indexOf(' ');
        if (space >= 0) {
            root = root.substring(0, space);
        }
        if (AUTHME_COMMANDS.contains(root)) {
            return; // account login/registration - AuthMe's business
        }
        event.setCancelled(true);
        event.getPlayer().sendMessage(Component.text(
                "[Cubeon] Verify your password first.", NamedTextColor.RED));
    }

    @EventHandler(priority = EventPriority.LOWEST, ignoreCancelled = true)
    public void onInteract(PlayerInteractEvent event) {
        if (blocked(event.getPlayer())) {
            event.setCancelled(true);
        }
    }

    @EventHandler(priority = EventPriority.LOWEST, ignoreCancelled = true)
    public void onBlockBreak(BlockBreakEvent event) {
        if (blocked(event.getPlayer())) {
            event.setCancelled(true);
        }
    }

    @EventHandler(priority = EventPriority.LOWEST, ignoreCancelled = true)
    public void onBlockPlace(BlockPlaceEvent event) {
        if (blocked(event.getPlayer())) {
            event.setCancelled(true);
        }
    }

    @EventHandler(priority = EventPriority.LOWEST, ignoreCancelled = true)
    public void onDrop(PlayerDropItemEvent event) {
        if (blocked(event.getPlayer())) {
            event.setCancelled(true);
        }
    }

    @EventHandler(priority = EventPriority.LOWEST, ignoreCancelled = true)
    public void onPickup(PlayerPickupItemEvent event) {
        if (blocked(event.getPlayer())) {
            event.setCancelled(true);
        }
    }

    @EventHandler(priority = EventPriority.LOWEST, ignoreCancelled = true)
    public void onInventoryClick(InventoryClickEvent event) {
        if (event.getWhoClicked() instanceof Player
                && blocked((Player) event.getWhoClicked())) {
            event.setCancelled(true);
        }
    }

    @EventHandler(priority = EventPriority.LOWEST, ignoreCancelled = true)
    public void onInventoryOpen(InventoryOpenEvent event) {
        if (event.getPlayer() instanceof Player
                && blocked((Player) event.getPlayer())) {
            event.setCancelled(true);
        }
    }

    @EventHandler(priority = EventPriority.LOWEST, ignoreCancelled = true)
    public void onDamage(EntityDamageByEntityEvent event) {
        if (event.getDamager() instanceof Player
                && blocked((Player) event.getDamager())) {
            event.setCancelled(true);
        }
    }

    // ------------------------------------------------------------------
    // Crypto + persistence.
    // ------------------------------------------------------------------

    private boolean hashMatches(String attempt, Credentials cred) {
        if (attempt.isEmpty()) {
            return false;
        }
        try {
            byte[] salt = hexToBytes(cred.saltHex);
            byte[] candidate = pbkdf2(attempt, salt, cred.iterations);
            byte[] expected = hexToBytes(cred.hashHex);
            return MessageDigest.isEqual(candidate, expected);
        } catch (RuntimeException ex) {
            return false;
        }
    }

    private byte[] pbkdf2(String password, byte[] salt, int iterations) {
        try {
            PBEKeySpec spec = new PBEKeySpec(password.toCharArray(), salt,
                    iterations, PBKDF2_KEY_BITS);
            SecretKeyFactory factory =
                    SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256");
            byte[] key = factory.generateSecret(spec).getEncoded();
            spec.clearPassword();
            return key;
        } catch (Exception ex) {
            throw new IllegalStateException("PBKDF2 unavailable", ex);
        }
    }

    private void loadState() {
        verifiedNames.clear();
        failCounts.clear();
        lockedUntil.clear();
        try {
            if (!Files.exists(statePath)) {
                return;
            }
            String json = new String(Files.readAllBytes(statePath),
                    StandardCharsets.UTF_8);
            // Minimal, dependency-free parsing of the exact shape we write:
            // {"verified":{"<uuid>":"<name>",...},
            //  "fails":{"<uuid>":n,...},
            //  "locked":{"<uuid>":epochMs,...}}
            parseSection(json, "verified", (uuid, name) -> verifiedNames.put(uuid, name));
            parseSection(json, "fails", (uuid, value) ->
                    failCounts.put(uuid, new int[]{Integer.parseInt(value.trim())}));
            parseSection(json, "locked", (uuid, value) ->
                    lockedUntil.put(uuid, Long.parseLong(value.trim())));
        } catch (IOException | RuntimeException ex) {
            getLogger().warning("Couldn't read state.json - starting with a "
                    + "clean slate (verified players will re-verify once).");
        }
    }

    private synchronized void saveState() {
        try {
            Files.createDirectories(dataDir);
            StringBuilder sb = new StringBuilder(64 + verifiedNames.size() * 80);
            sb.append('{');
            appendMap(sb, "verified", verifiedNames, true);
            sb.append(',');
            appendMap(sb, "fails", failCounts, false);
            sb.append(',');
            appendMap(sb, "locked", lockedUntil, false);
            sb.append('}');
            // Atomic replace: a crash mid-write can never leave a truncated
            // state file that would (worst case) forget a lockout.
            Path tmp = dataDir.resolve("state.json.tmp");
            Files.write(tmp, sb.toString().getBytes(StandardCharsets.UTF_8));
            Files.move(tmp, statePath, StandardCopyOption.REPLACE_EXISTING,
                    StandardCopyOption.ATOMIC_MOVE);
        } catch (IOException ex) {
            getLogger().warning("Couldn't persist CubeonGate state: "
                    + ex.getMessage());
        }
    }

    private interface EntrySink {
        void accept(UUID uuid, String value);
    }

    private static void parseSection(String json, String section, EntrySink sink) {
        int sec = json.indexOf('"' + section + '"');
        if (sec < 0) {
            return;
        }
        int objStart = json.indexOf('{', sec);
        int objEnd = json.indexOf('}', objStart);
        if (objStart < 0 || objEnd < 0) {
            return;
        }
        String body = json.substring(objStart + 1, objEnd);
        int i = 0;
        while (i < body.length()) {
            int keyStart = body.indexOf('"', i);
            if (keyStart < 0) {
                break;
            }
            int keyEnd = body.indexOf('"', keyStart + 1);
            int colon = body.indexOf(':', keyEnd);
            int comma = body.indexOf(',', colon);
            if (comma < 0) {
                comma = body.length();
            }
            String key = body.substring(keyStart + 1, keyEnd);
            String value = body.substring(colon + 1, comma).trim();
            value = value.startsWith("\"") ? value.substring(1, value.length() - 1) : value;
            try {
                sink.accept(UUID.fromString(key), value);
            } catch (RuntimeException ignored) {
                // malformed entry - skip, never crash the gate on bad state
            }
            i = comma + 1;
        }
    }

    @SuppressWarnings({"unchecked", "rawtypes"})
    private static void appendMap(StringBuilder sb, String section, Map map,
                           boolean quotedValues) {
        sb.append('"').append(section).append("\":{");
        boolean first = true;
        for (Object entryObj : map.entrySet()) {
            Map.Entry entry = (Map.Entry) entryObj;
            if (!first) {
                sb.append(',');
            }
            first = false;
            sb.append('"').append(entry.getKey()).append("\":");
            Object value = entry.getValue();
            if (quotedValues) {
                sb.append('"').append(value).append('"');
            } else {
                sb.append(value instanceof int[] ? ((int[]) value)[0] : value);
            }
        }
        sb.append('}');
    }

    private static String extractString(String json, String key) {
        int k = json.indexOf('"' + key + '"');
        if (k < 0) {
            return null;
        }
        int colon = json.indexOf(':', k);
        int quoteStart = json.indexOf('"', colon);
        int quoteEnd = json.indexOf('"', quoteStart + 1);
        if (quoteStart < 0 || quoteEnd < 0) {
            return null;
        }
        return json.substring(quoteStart + 1, quoteEnd);
    }

    private static int extractInt(String json, String key, int fallback) {
        int k = json.indexOf('"' + key + '"');
        if (k < 0) {
            return fallback;
        }
        int colon = json.indexOf(':', k);
        int comma = json.indexOf(',', colon);
        int end = comma < 0 ? json.indexOf('}', colon) : comma;
        try {
            return Integer.parseInt(json.substring(colon + 1, end).trim());
        } catch (RuntimeException ex) {
            return fallback;
        }
    }

    private static byte[] hexToBytes(String hex) {
        int len = hex.length();
        byte[] out = new byte[len / 2];
        for (int i = 0; i < out.length; i++) {
            out[i] = (byte) Integer.parseInt(hex.substring(i * 2, i * 2 + 2), 16);
        }
        return out;
    }
}
