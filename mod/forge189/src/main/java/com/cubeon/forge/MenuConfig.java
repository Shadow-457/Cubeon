package com.cubeon.forge;

import com.cubeon.client.hud.CubeonHudConfig;
import com.cubeon.client.hud.HudFeatures;
import com.cubeon.client.ui.HudMenu;

/** Reads and writes the same CubeonHudConfig fields the 1.8.9 overlays already render. */
final class MenuConfig implements HudMenu.Settings {
    @Override public boolean visible(int overlay) { return Hud189.enabled(HudFeatures.ALL[overlay]); }
    @Override public float scale(int overlay) { return CubeonHudConfig.get().scaleFor(HudFeatures.ALL[overlay].slot); }
    @Override public void setScale(int overlay, float value) {
        CubeonHudConfig.get().setScaleFor(HudFeatures.ALL[overlay].slot, value);
    }
    @Override public boolean health() { return CubeonHudConfig.get().showEnemyHealth; }
    @Override public boolean animations() { return CubeonHudConfig.get().cosmeticAnimations; }
    @Override public boolean wingDepth() { return CubeonHudConfig.get().wingDepth; }
    @Override public boolean otherCosmetics() { return CubeonHudConfig.get().showOtherCosmetics; }
    @Override public boolean cameraBlur() { return CubeonHudConfig.get().cameraMotionBlur; }
    @Override public float blurIntensity() { return CubeonHudConfig.get().cameraBlurIntensity; }
    @Override public void setBlurIntensity(float value) { CubeonHudConfig.get().cameraBlurIntensity = value; }
    @Override public boolean sprint() { return CubeonHudConfig.get().autoSprint; }
    @Override public boolean fullBright() { return CubeonHudConfig.get().fullBright; }
    @Override public boolean worldClock() { return CubeonHudConfig.get().worldClock; }
    @Override public boolean ownNameTag() { return CubeonHudConfig.get().showOwnNameTag; }
    @Override public boolean menuAnimations() { return CubeonHudConfig.get().menuAnimations; }
    @Override public void save() { CubeonHudConfig.save(); }
}
