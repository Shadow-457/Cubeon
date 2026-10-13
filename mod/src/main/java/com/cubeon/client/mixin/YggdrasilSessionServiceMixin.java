package com.cubeon.client.mixin;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

import java.util.UUID;

/**
 * Makes the client-side session check non-fatal so Cubeon (an offline/cracked
 * launcher) can join cracked-enabled servers that sit behind an online-mode
 * Velocity proxy.
 *
 * <p>Background: a cracked-enabled server network often runs a Velocity proxy
 * with {@code online-mode=true} plus a plugin that lets cracked players through
 * by treating a failed session verification as "this player is offline". The
 * proxy sends an {@code EncryptionRequest}; the vanilla client then calls
 * {@code MinecraftSessionService.joinServer} to register its session with
 * Mojang. With Cubeon's offline accessToken ("0") that call throws
 * {@code InvalidCredentialsException}, and the vanilla client disconnects with
 * "Invalid session" BEFORE it ever sends the encryption response — so the
 * proxy's cracked-fallback never gets a chance to run. Premium players (valid
 * session) and modified cracked clients (which send the response anyway) get
 * in; the vanilla cracked client does not. This is exactly the
 * {@code lemonmc.fun} case: a Velocity proxy (per mcsrvstat) that cracked
 * players join with other launchers but not with Cubeon's vanilla handshake.
 *
 * <p>This mixin cancels {@code joinServer} at HEAD, turning it into a no-op that
 * never contacts Mojang and never throws. The handshake then proceeds and the
 * encryption response is sent, so the proxy's cracked-fallback can do its job.
 * For offline-mode servers the method is never called at all (no
 * EncryptionRequest arrives), so this is a no-op there too. It only changes
 * behavior on servers that were already going to reject the offline token — for
 * a plain online-mode server with no fallback the player is still kicked, just
 * by the server's own check instead of the client giving up first.
 *
 * <p>{@code targets} is a STRING and {@code remap = false} on purpose: authlib is
 * a Mojang library with stable, unobfuscated names, so there is nothing to
 * remap, and resolving the target by name at RUNTIME (not compile time) is what
 * keeps this one shared source file safe across both build brackets. authlib
 * 10.x (Minecraft 26.x) restructured these classes away; on such versions the
 * target is simply not found and the mixin is skipped ({@code required: false}
 * in cubeon-client.mixins.json, {@code defaultRequire: 0} for injectors) rather
 * than failing the load.
 */
@Mixin(targets = "com.mojang.authlib.yggdrasil.YggdrasilMinecraftSessionService",
       remap = false)
public abstract class YggdrasilSessionServiceMixin {

    private static final Logger LOGGER = LoggerFactory.getLogger("cubeon-client");

    /**
     * One log line per session, not one per join attempt, so a reconnect loop
     * against a strict server does not spam the game log.
     */
    private static boolean cubeon$warned;

    @Inject(method = "joinServer", at = @At("HEAD"), cancellable = true,
            remap = false, require = 0)
    private void cubeon$skipSessionCheck(UUID profileId, String username,
                                         String serverId, CallbackInfo ci) {
        ci.cancel();
        if (!cubeon$warned) {
            cubeon$warned = true;
            LOGGER.info("Cubeon Client: skipped the online-mode session check "
                    + "(offline accessToken) so cracked-enabled proxies can "
                    + "let this player in.");
        }
    }
}
