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
        public FeatherWeight[] feathers;
        public int featherVertexCount;
        public int feather = -1;
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
                    item.texWidth, item.texHeight, false, box.faces);

            int mirrorStart = out.size();

            if (box.mirror) {
                // Mirror about the slot's anchor, swap the side tiles and flip
                // every tile horizontally - the same three things the preview
                // does. Skipping the tile swap puts a left-hand edge on the
                // right-hand wing.
                float mirroredX0 = 2 * anchorX - x1;
                float mirroredX1 = 2 * anchorX - x0;
                addBox(out, mirroredX0, y0, z0, mirroredX1, y1, z1,
                        front, back, right, left, top, bottom,
                        item.texWidth, item.texHeight, true,
                        (box.faces & ~12) | ((box.faces & 4) << 1) | ((box.faces & 8) >> 1));
            }
            for (int i = first; i < out.size(); i++) {
                Quad quad = out.get(i);
                quad.motion = box.motion;
                quad.feather = box.feather;
                quad.mirrored = i >= mirrorStart;
                quad.pivotX = quad.mirrored ? 2 * anchorX - box.pivotX : box.pivotX;
                quad.pivotY = box.pivotY;
                quad.pivotZ = box.pivotZ;
                if (item.separateFeathers && box.feather >= 0 && box.feather < item.feathers.size())
                    curveRest(quad, item.feathers.get(box.feather), anchorX);
                if (parent != null) {
                    quad.parentPivotX = parent.pivotX;
                    quad.parentPivotY = parent.pivotY;
                    quad.parentPivotZ = parent.pivotZ;
                }
            }
        }
        if (!item.feathers.isEmpty()) bindFeathers(item, out, anchorX);
        return out;
    }

    private static double depthAt(CosmeticCatalog.Feather f, double x) {
        // The root stays flat through the next shared strip boundary. Starting
        // the curve mid-strip lifts short covert roots away from their attachment.
        double root = 1 + Math.ceil((f.x - 1) / 4) * 4;
        double extent = f.endX - root;
        double t = Math.abs(extent) < .1 ? 0 : Math.max(0, Math.min(1, (x - root) / extent));
        // Binary-grid endpoints make Java/Python rest meshes identical, including seams.
        return Math.floor((f.curl * t * t + f.tilt * (f.endX - f.x) * t) * 4096 + .5) / 4096;
    }

    /** Four-model-unit strips make a curved feather from joined planar caps. */
    private static void curveRest(Quad quad, CosmeticCatalog.Feather f, float anchorX) {
        double minX = Double.POSITIVE_INFINITY;
        for (float x : quad.x) minX = Math.min(minX, quad.mirrored ? 2 * anchorX - x : x);
        double left = 1 + Math.floor((minX - 1) / 4) * 4;
        double first = depthAt(f, left), slope = (depthAt(f, left + 4) - first) / 4;
        for (int v = 0; v < 4; v++) {
            double x = quad.mirrored ? 2 * anchorX - quad.x[v] : quad.x[v];
            quad.z[v] += (float) (first + (x - left) * slope);
        }
        float sign = quad.mirrored ? -1 : 1;
        quad.normalX -= sign * (float) slope * quad.normalZ;
        float length = (float) Math.sqrt(quad.normalX * quad.normalX
                + quad.normalY * quad.normalY + quad.normalZ * quad.normalZ);
        quad.normalX /= length; quad.normalY /= length; quad.normalZ /= length;
    }

    private static void addBox(List<Quad> out, float x0, float y0, float z0,
                               float x1, float y1, float z1,
                               Rect front, Rect back, Rect left, Rect right,
                               Rect top, Rect bottom,
                               int texWidth, int texHeight, boolean flipU, int faces) {
        // Front is -z (the player's face side); the back face is +z.
        if ((faces & 1) != 0) addQuad(out, front, flipU, texWidth, texHeight,
                x0, y0, z0, x1, y0, z0, x0, y1, z0, 0, 0, -1);
        if ((faces & 2) != 0) addQuad(out, back, flipU, texWidth, texHeight,
                x1, y0, z1, x0, y0, z1, x1, y1, z1, 0, 0, 1);
        if ((faces & 4) != 0) addQuad(out, left, flipU, texWidth, texHeight,
                x1, y0, z0, x1, y0, z1, x1, y1, z0, 1, 0, 0);
        if ((faces & 8) != 0) addQuad(out, right, flipU, texWidth, texHeight,
                x0, y0, z1, x0, y0, z0, x0, y1, z1, -1, 0, 0);
        if ((faces & 16) != 0) addQuad(out, top, flipU, texWidth, texHeight,
                x0, y0, z1, x1, y0, z1, x0, y0, z0, 0, -1, 0);
        if ((faces & 32) != 0) addQuad(out, bottom, flipU, texWidth, texHeight,
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

    /** Cached sparse deformation coefficients. No guide searches in the draw loop. */
    public static final class FeatherWeight {
        public final int index;
        public final int[] bones;
        // bend-Z, fan-X, fan-Y, twist-Z, for each nonzero bone.
        public final float[] coefficients;
        FeatherWeight(int index, float[] dense) {
            this.index = index;
            int count = 0;
            for (int j = 0; j < dense.length; j += 4)
                if (Math.abs(dense[j]) + Math.abs(dense[j+1]) + Math.abs(dense[j+2])
                        + Math.abs(dense[j+3]) > 0.000001f) count++;
            bones = new int[count]; coefficients = new float[count * 4];
            int n = 0;
            for (int j = 0; j < dense.length; j += 4) {
                if (Math.abs(dense[j]) + Math.abs(dense[j+1]) + Math.abs(dense[j+2])
                        + Math.abs(dense[j+3]) <= 0.000001f) continue;
                bones[n] = j / 4;
                System.arraycopy(dense, j, coefficients, n++ * 4, 4);
            }
        }
    }

    private static final class Node {
        final float x, y;
        final float[] weights;
        Node a, b;
        float blend, span;
        FeatherWeight frozen;
        Node(float x, float y, float[] weights) { this.x = x; this.y = y; this.weights = weights; }
    }
    private record Edge(boolean horizontal, float line, float start, float end) { }
    private static long key(float x, float y) {
        return ((long) Math.round(x * 4096) << 32) | (Math.round(y * 4096) & 0xffffffffL);
    }

    private static float smooth(float value) {
        float t = Math.max(0, Math.min(1, value));
        return t * t * (3 - 2 * t);
    }

    private static float[] weights(CosmeticCatalog.Item item, float x, float y, int bone) {
        int count = item.feathers.size();
        float[] result = new float[count * 4];
        if (bone >= 0) {
            var f = item.feathers.get(bone);
            float dx = f.endX - f.x, dy = f.endY - f.y;
            float length = (float) Math.hypot(dx, dy);
            float t = Math.max(0, Math.min(1, ((x - f.x) * dx + (y - f.y) * dy) / (length * length)));
            float root = smooth(((float) Math.hypot(x - item.boxes.get(0).pivotX,
                    y - item.boxes.get(0).pivotY) - 1.25f) / 3);
            float side = ((x - f.x) * -dy + (y - f.y) * dx) / length
                    - f.curve * (float) Math.sin(Math.PI * t);
            float tip = t * t * root;
            result[bone*4] = length * tip;
            result[bone*4+1] = -dy * tip;
            result[bone*4+2] = dx * tip;
            result[bone*4+3] = side * t * root;
            return result;
        }
        float[] ts = new float[count], sides = new float[count], lengths = new float[count];
        float[] scores = new float[count];
        int first = 0, second = -1;
        for (int j = 0; j < count; j++) {
            var f = item.feathers.get(j);
            float dx = f.endX - f.x, dy = f.endY - f.y;
            float length = (float) Math.hypot(dx, dy);
            float t = ((x - f.x) * dx + (y - f.y) * dy) / (length * length);
            ts[j] = Math.max(0, Math.min(1, t)); lengths[j] = length;
            float side = ((x - f.x) * -dy + (y - f.y) * dx) / length
                    - f.curve * (float) Math.sin(Math.PI * ts[j]);
            sides[j] = side;
            float beyond = (t - ts[j]) * length;
            scores[j] = side * side / (f.width * f.width) + beyond * beyond + 0.01f;
            if (scores[j] < scores[first]) { second = first; first = j; }
            else if (j != first && (second < 0 || scores[j] < scores[second])) second = j;
        }
        float rootX = item.boxes.get(0).pivotX, rootY = item.boxes.get(0).pivotY;
        float root = smooth(((float) Math.hypot(x - rootX, y - rootY) - 1.25f) / 3);
        for (int j : new int[]{first, second}) {
            if (j < 0) continue;
            float influence = second < 0 ? 1 : (j == first ? scores[second] : scores[first])
                    / (scores[first] + scores[second]);
            var f = item.feathers.get(j);
            float tip = ts[j] * ts[j] * root * influence;
            result[j*4] = lengths[j] * tip;
            result[j*4+1] = -(f.endY - f.y) * tip;
            result[j*4+2] = (f.endX - f.x) * tip;
            result[j*4+3] = sides[j] * ts[j] * root * influence;
        }
        return result;
    }

    private static void bindFeathers(CosmeticCatalog.Item item, List<Quad> quads, float anchorX) {
        if (!item.separateFeathers) {
            bindGroup(item, quads, anchorX, -1, 0);
            return;
        }
        int next = 0;
        for (int bone = 0; bone < item.feathers.size(); bone++) {
            List<Quad> group = new ArrayList<>();
            for (Quad quad : quads) if (quad.feather == bone) group.add(quad);
            next = bindGroup(item, group, anchorX, bone, next);
        }
        for (Quad quad : quads) if (quad.feathers != null) quad.featherVertexCount = next;
    }

    private static int bindGroup(CosmeticCatalog.Item item, List<Quad> quads, float anchorX,
                                 int bone, int firstIndex) {
        Map<Long, Node> nodes = new java.util.LinkedHashMap<>();
        for (Quad q : quads) {
            if (!"wing".equals(q.motion)) continue;
            for (int v = 0; v < 4; v++) {
                float x = q.mirrored ? 2 * anchorX - q.x[v] : q.x[v], y = q.y[v];
                nodes.computeIfAbsent(key(x, y), unused -> new Node(x, y, weights(item, x, y, bone)));
            }
        }
        // Weld T junctions: caps of different sizes must agree along shared edges.
        // Overlapping collinear edges share their outer endpoints as one straight span.
        List<Edge> edges = new ArrayList<>();
        for (var box : item.boxes) if ((box.faces & 3) != 0 && (bone < 0 || box.feather == bone)) {
            edges.add(new Edge(true, box.y, box.x, box.x + box.width));
            edges.add(new Edge(true, box.y + box.height, box.x, box.x + box.width));
            edges.add(new Edge(false, box.x, box.y, box.y + box.height));
            edges.add(new Edge(false, box.x + box.width, box.y, box.y + box.height));
        }
        edges.sort(java.util.Comparator.comparing(Edge::horizontal)
                .thenComparingDouble(Edge::line).thenComparingDouble(Edge::start));
        List<Edge> merged = new ArrayList<>();
        for (Edge edge : edges) {
            if (!merged.isEmpty()) {
                Edge previous = merged.get(merged.size() - 1);
                if (previous.horizontal == edge.horizontal && previous.line == edge.line
                        && edge.start < previous.end) {
                    merged.set(merged.size() - 1, new Edge(edge.horizontal, edge.line,
                            previous.start, Math.max(previous.end, edge.end)));
                    continue;
                }
            }
            merged.add(edge);
        }
        for (Edge edge : merged) {
            Node a = nodes.get(key(edge.horizontal ? edge.start : edge.line,
                    edge.horizontal ? edge.line : edge.start));
            Node b = nodes.get(key(edge.horizontal ? edge.end : edge.line,
                    edge.horizontal ? edge.line : edge.end));
            if (a == null || b == null) continue;
            for (Node node : nodes.values()) {
                float line = edge.horizontal ? node.y : node.x;
                float value = edge.horizontal ? node.x : node.y;
                if (line == edge.line && value > edge.start && value < edge.end
                        && edge.end - edge.start > node.span) {
                    node.a = a; node.b = b;
                    node.blend = (value - edge.start) / (edge.end - edge.start);
                    node.span = edge.end - edge.start;
                }
            }
        }
        // Resolve coefficient dependencies once during mesh construction, never per frame.
        for (int pass = 0; pass < 2048; pass++) {
            float difference = 0;
            for (Node node : nodes.values()) if (node.a != null) {
                for (int j = 0; j < node.weights.length; j++) {
                    float next = node.a.weights[j] * (1 - node.blend) + node.b.weights[j] * node.blend;
                    difference = Math.max(difference, Math.abs(node.weights[j] - next));
                    node.weights[j] = next;
                }
            }
            if (difference < 0.0000005f) break;
        }
        int index = firstIndex;
        for (Node node : nodes.values()) node.frozen = new FeatherWeight(index++, node.weights);
        for (Quad q : quads) if ("wing".equals(q.motion)) {
            q.feathers = new FeatherWeight[4];
            q.featherVertexCount = nodes.size();
            for (int v = 0; v < 4; v++)
                q.feathers[v] = nodes.get(key(q.mirrored ? 2 * anchorX - q.x[v] : q.x[v], q.y[v])).frozen;
        }
        return index;
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
