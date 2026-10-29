package com.cubeon.client.cosmetics;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.WeakHashMap;

/**
 * Turns catalogue boxes into the exact quads the launcher preview draws.
 *
 * <p>The preview ({@code cubeon.cosmetics.preview_faces}) and this class are two
 * implementations of one contract. They must agree pixel for pixel, or a wing
 * that looks right in the Skin tab hangs the wrong way in game - which is
 * exactly the bug this class exists to prevent. {@code tools/test_cosmetics.py}
 * compiles this file and compares every quad against the Python implementation.
 *
 * <p>Minecraft-free: coordinates stay in model space (+x left, +y down, -z
 * front) as plain floats. The per-era renderer divides by 16 and applies the
 * body pose; nothing here knows what a {@code MatrixStack} is.
 */
public final class CosmeticGeometry {

    /** One textured quad. Vertices are wound top-left, top-right, bottom-right,
     *  bottom-left, matching the preview's tile mapping. */
    public static final class Quad {
        public final float[] x = new float[4];
        public final float[] y = new float[4];
        public final float[] z = new float[4];
        public final float[] u = new float[4];
        public final float[] v = new float[4];
        public float normalX;
        public float normalY;
        public float normalZ;
        public String motion;
        public boolean mirrored;
        public float pivotX, pivotY, pivotZ;
        public float parentPivotX, parentPivotY, parentPivotZ;
    }

    private static final Map<CosmeticCatalog.Item, List<Quad>> CACHE =
            Collections.synchronizedMap(new WeakHashMap<>());

    private CosmeticGeometry() {
    }

    /** Cached quads for one item. The catalogue never changes at runtime. */
    public static List<Quad> quads(CosmeticCatalog.Item item, float anchorX) {
        List<Quad> cached = CACHE.get(item);
        if (cached == null) {
            cached = build(item, anchorX);
            CACHE.put(item, cached);
        }
        return cached;
    }

    /** Builds quads without touching the cache. Public for the cross-check test. */
    public static List<Quad> build(CosmeticCatalog.Item item, float anchorX) {
        List<Quad> out = new ArrayList<>();
        CosmeticCatalog.Box parent = null;
        for (CosmeticCatalog.Box box : item.boxes) {
            if ("body".equals(box.motion)) {
                parent = box;
                break;
            }
        }
        for (CosmeticCatalog.Box box : item.boxes) {
            int first = out.size();
            float x0 = box.x;
            float y0 = box.y;
            float z0 = box.z;
            float x1 = x0 + box.width;
            float y1 = y0 + box.height;
            float z1 = z0 + box.depth;

            float u = box.uvX;
            float v = box.uvY;
            float px = box.px;
            Rect front = new Rect(u + box.depth * px, v + box.depth * px,
                    box.width * px, box.height * px);
            Rect back = new Rect(u + (2 * box.depth + box.width) * px,
                    v + box.depth * px, box.width * px, box.height * px);
            Rect left = new Rect(u, v + box.depth * px, box.depth * px,
                    box.height * px);
            Rect right = new Rect(u + (box.depth + box.width) * px,
                    v + box.depth * px, box.depth * px, box.height * px);
            Rect top = new Rect(u + box.depth * px, v, box.width * px,
                    box.depth * px);
            Rect bottom = new Rect(u + (box.depth + box.width) * px, v,
                    box.width * px, box.depth * px);

            addBox(out, x0, y0, z0, x1, y1, z1,
                    front, back, left, right, top, bottom,
                    item.texWidth, item.texHeight, false);

            if (box.mirror) {
                // Mirror about the slot's anchor, swap the side tiles and flip
                // every tile horizontally - the same three things the preview
                // does. Skipping the tile swap puts a left-hand edge on the
                // right-hand wing.
                float mirroredX0 = 2 * anchorX - x1;
                float mirroredX1 = 2 * anchorX - x0;
                addBox(out, mirroredX0, y0, z0, mirroredX1, y1, z1,
                        front, back, right, left, top, bottom,
                        item.texWidth, item.texHeight, true);
            }
            for (int i = first; i < out.size(); i++) {
                Quad quad = out.get(i);
                quad.motion = box.motion;
                quad.mirrored = i - first >= 6;
                quad.pivotX = quad.mirrored ? 2 * anchorX - box.pivotX : box.pivotX;
                quad.pivotY = box.pivotY;
                quad.pivotZ = box.pivotZ;
                if (parent != null) {
                    quad.parentPivotX = parent.pivotX;
                    quad.parentPivotY = parent.pivotY;
                    quad.parentPivotZ = parent.pivotZ;
                }
            }
        }
        return out;
    }

    private static void addBox(List<Quad> out, float x0, float y0, float z0,
                               float x1, float y1, float z1,
                               Rect front, Rect back, Rect left, Rect right,
                               Rect top, Rect bottom,
                               int texWidth, int texHeight, boolean flipU) {
        // Front is -z (the player's face side); the back face is +z.
        addQuad(out, front, flipU, texWidth, texHeight,
                x0, y0, z0, x1, y0, z0, x0, y1, z0, 0, 0, -1);
        addQuad(out, back, flipU, texWidth, texHeight,
                x1, y0, z1, x0, y0, z1, x1, y1, z1, 0, 0, 1);
        addQuad(out, left, flipU, texWidth, texHeight,
                x1, y0, z0, x1, y0, z1, x1, y1, z0, 1, 0, 0);
        addQuad(out, right, flipU, texWidth, texHeight,
                x0, y0, z1, x0, y0, z0, x0, y1, z1, -1, 0, 0);
        addQuad(out, top, flipU, texWidth, texHeight,
                x0, y0, z1, x1, y0, z1, x0, y0, z0, 0, -1, 0);
        addQuad(out, bottom, flipU, texWidth, texHeight,
                x0, y1, z0, x1, y1, z0, x0, y1, z1, 0, 1, 0);
    }

    private static void addQuad(List<Quad> out, Rect rect, boolean flipU,
                                int texWidth, int texHeight,
                                float ax, float ay, float az,
                                float bx, float by, float bz,
                                float cx, float cy, float cz,
                                float nx, float ny, float nz) {
        // Sample the edge texel centers, never the transparent atlas gutter or
        // the neighboring face. This also works for a one-texel feather edge.
        float u0 = (rect.x + 0.5f) / texWidth;
        float u1 = (rect.x + rect.width - 0.5f) / texWidth;
        float v0 = (rect.y + 0.5f) / texHeight;
        float v1 = (rect.y + rect.height - 0.5f) / texHeight;
        if (flipU) {
            float swap = u0;
            u0 = u1;
            u1 = swap;
        }
        Quad quad = new Quad();
        // TL, TR, BL from the catalogue contract; the fourth corner is implied.
        // Emit TL, TR, BR, BL so the four vertices form a valid quad cycle.
        quad.x[0] = ax;
        quad.y[0] = ay;
        quad.z[0] = az;
        quad.x[1] = bx;
        quad.y[1] = by;
        quad.z[1] = bz;
        quad.x[2] = bx + cx - ax;
        quad.y[2] = by + cy - ay;
        quad.z[2] = bz + cz - az;
        quad.x[3] = cx;
        quad.y[3] = cy;
        quad.z[3] = cz;
        quad.u[0] = u0;
        quad.v[0] = v0;
        quad.u[1] = u1;
        quad.v[1] = v0;
        quad.u[2] = u1;
        quad.v[2] = v1;
        quad.u[3] = u0;
        quad.v[3] = v1;
        quad.normalX = nx;
        quad.normalY = ny;
        quad.normalZ = nz;
        out.add(quad);
    }

    private static final class Rect {
        final float x;
        final float y;
        final float width;
        final float height;

        Rect(float x, float y, float width, float height) {
            this.x = x;
            this.y = y;
            this.width = width;
            this.height = height;
        }
    }
}
