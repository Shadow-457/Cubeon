package com.cubeon.client.cosmetics;

/** Selection and pose captured together for one player, before queued drawing. */
public record CosmeticView(CosmeticSelection.Items items, CosmeticAnimation.Frame animation) { }
