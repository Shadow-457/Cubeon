package dev.keyhud.client;

import net.minecraft.client.Minecraft;
import net.minecraft.network.protocol.ping.ServerboundPingRequestPacket;

/**
 * Measures the connection round-trip time the same way vanilla's own ping debug
 * monitor does: about once a second a ping request carrying the current time is sent
 * and every pong echoes that time back, so the latency is simply now minus the echoed
 * time. Unlike the latency reported through the tab list this is measured by the
 * client itself, updates every second and behaves the same on every server.
 *
 * <p>Only the 26.3 build uses this - 1.21.11 has no client initiated ping packet, so
 * that version falls back to the tab-list latency, which is server measured and the
 * only value available to it.
 */
public final class PingProbe {
	private static final long INTERVAL_MS = 1000L;

	private static long lastRequestMs;
	private static int lastPing = -1;

	private PingProbe() {
	}

	/** Called once per client tick; sends a fresh ping request about once a second. */
	public static void tick() {
		var connection = Minecraft.getInstance().getConnection();

		if (connection == null) {
			lastPing = -1;
			return;
		}

		long now = System.currentTimeMillis();

		if (now - lastRequestMs < INTERVAL_MS) {
			return;
		}

		lastRequestMs = now;
		connection.send(new ServerboundPingRequestPacket(now));
	}

	/** Called from the pong packet handler with the send time the server echoed back. */
	public static void onPong(long sentAtMillis) {
		lastPing = (int) Math.max(0, System.currentTimeMillis() - sentAtMillis);
	}

	/** Latest measured latency in ms, or -1 when nothing has been measured yet. */
	public static int current() {
		return lastPing;
	}
}
