package com.cubeon.client.cosmetics;

/** Tick-based cosmetic poses shared by all Minecraft render APIs.
 * Cached rest geometry and UVs are never changed. One scratch quad per draw
 * avoids allocating thousands of vertices or rebuilding feather meshes each frame.
 */
public final class CosmeticAnimation {
    private static final float TAU = (float) (Math.PI * 2);
    private CosmeticAnimation() { }

    /** Seconds come from interpolated entity age, so pause freezes animation. */
    public static Frame sample(float seconds, float movement, boolean gliding) {
        float t = Float.isFinite(seconds) ? seconds : 0;
        float move = Float.isFinite(movement) ? Math.max(0, Math.min(1, movement)) : 0;
        return new Frame(t, move, gliding ? 1 : 0, 0, t * 2.6f % TAU, -1);
    }

    /** Render-local response smoothing; no timer, global map or background work. */
    public static final class Tracker {
        private float previous = Float.NaN, movement, flight, sprint, phase;

        public Frame sample(float seconds, float targetMovement, boolean gliding) {
            return sample(seconds, targetMovement, gliding, false);
        }

        /** Frequency follows sprinting without ever multiplying age by a changing speed. */
        public Frame sample(float seconds, float targetMovement, boolean gliding, boolean sprinting) {
            return sample(seconds, targetMovement, gliding, sprinting, -1);
        }

        public Frame sample(float seconds, float targetMovement, boolean gliding,
                            boolean sprinting, float dragonElapsed) {
            float t = Float.isFinite(seconds) ? seconds : 0;
            float target = Float.isFinite(targetMovement)
                    ? Math.max(0, Math.min(1, targetMovement)) : 0;
            if (!Float.isFinite(previous) || t < previous || t - previous > 1) {
                movement = target;
                flight = gliding ? 1 : 0;
                sprint = sprinting ? 1 : 0;
                phase = t * 2.6f % TAU;
            } else {
                float elapsed = t - previous;
                float blend = 1 - (float) Math.exp(-elapsed * 8);
                movement += (target - movement) * blend;
                flight += ((gliding ? 1 : 0) - flight) * blend;
                float goal = sprinting ? 1 : 0;
                float response = 1 - (float) Math.exp(-elapsed * 4);
                // Exact integral of the easing curve: consistent at every frame rate.
                phase += 2.6f * elapsed + 4.4f * (goal * elapsed
                        + (sprint - goal) * response / 4);
                phase %= TAU;
                sprint += (goal - sprint) * response;
            }
            previous = t;
            return new Frame(t, movement, flight, sprint, phase, dragonElapsed);
        }

        /** Null denotes the cached rest pose; no Frame or transforms are allocated. */
        public Frame disabled() {
            previous = Float.NaN;
            return null;
        }
    }

    public static final class Frame {
        private final Transform body, head, leftWing, rightWing, pack;
        private final float time, movement, flight, sprinting, wingPhase, dragon;
        private final float[] feathers;
        private final CosmeticCatalog.Item featherItem;

        private Frame(float t, float move, float gliding, float sprint, float phase, float dragonElapsed) {
            time = t; movement = move; flight = gliding; sprinting = sprint;
            wingPhase = phase; dragon = dragonElapsed; feathers = null; featherItem = null;
            float breath = 0.018f * sin(t * 2.2f);
            body = new Transform(0, 0, 0.012f * sin(t * 1.1f)
                    + move * 0.025f * sin(t * 9), 1 + breath);
            // A slow glance, a smaller secondary nod and a quiet head tilt.
            head = new Transform(0.09f * sin(t * 1.7f),
                    0.23f * sin(t * 0.8f) + 0.06f * sin(t * 2.1f),
                    0.06f * sin(t * 1.3f), 1);
            // The shoulder stroke is the parent of independently bending feathers.
            // Quiet, slightly asymmetric down/up strokes with a delayed tip lift.
            // Idle ~0.4 beats/sec, sprint ~1.1; gliding settles into a spread pose.
            float stroke = sin(phase) + 0.12f * sin(phase * 2);
            float beat = stroke * (0.07f + sprint * 0.045f);
            float sweep = (0.36f + beat) * (1 - gliding)
                    + (0.12f + 0.018f * sin(t * 2.6f)) * gliding;
            float lift = (-0.05f + (0.028f + sprint * 0.012f)
                    * sin(phase - 0.45f)) * (1 - gliding) - 0.10f * gliding;
            float pitch = 0;
            if (Float.isFinite(dragonElapsed) && dragonElapsed >= 0 && dragonElapsed < WingAction.DURATION) {
                // Spread and lift first, then three sweeping dragon-like beats.
                // Smooth entry/exit blends back into the uninterrupted idle phase.
                float weight = smooth(dragonElapsed / 0.35f)
                        * smooth((WingAction.DURATION - dragonElapsed) / 0.65f);
                float beatPhase = Math.max(0, dragonElapsed - 0.35f) * 7.1f;
                float dragonSweep = 0.10f + 0.09f * sin(beatPhase - 0.4f);
                float dragonLift = -0.12f - 0.43f * (float) Math.cos(beatPhase)
                        - 0.08f * sin(beatPhase * 2);
                sweep += (dragonSweep - sweep) * weight;
                lift += (dragonLift - lift) * weight;
                pitch = (0.10f + 0.13f * sin(beatPhase - 0.5f)) * weight;
            }
            leftWing = new Transform(pitch, -sweep, lift, 1);
            rightWing = new Transform(pitch, sweep, -lift, 1);
            // A backpack follows the wearer, rather than breathing like a pet.
            pack = new Transform(move * 0.025f * sin(t * 9),
                    move * 0.035f * sin(t * 8), 0, 1);
        }

        private Frame(Frame source, CosmeticCatalog.Item item) {
            body = source.body; head = source.head; leftWing = source.leftWing;
            rightWing = source.rightWing; pack = source.pack;
            time = source.time; movement = source.movement; flight = source.flight;
            sprinting = source.sprinting; wingPhase = source.wingPhase; dragon = source.dragon;
            featherItem = item;
            feathers = new float[item.feathers.size() * 3];
            float action = item.wingFlare && Float.isFinite(dragon) && dragon >= 0 && dragon < WingAction.DURATION
                    ? smooth(dragon / .35f) * smooth((WingAction.DURATION - dragon) / .65f) : 0;
            float beat = Math.max(0, dragon - .35f) * 7.1f;
            for (int j = 0; j < item.feathers.size(); j++) {
                // Delayed recoil, a smaller vane twist and a gentle fan opening.
                // Root weights vanish; distal weights grow quadratically along each feather.
                float lag = .18f + j * .19f;
                float phase = wingPhase - lag;
                float bend = (.025f + sprinting * .02f) * sin(phase)
                        + .007f * sin(phase * 2 - .6f);
                bend = bend * (1 - flight) + .009f * sin(time * 2.6f - lag) * flight;
                float fan = (.007f + sprinting * .004f) * sin(phase - .8f);
                float twist = (.045f + sprinting * .025f) * sin(phase - .4f);
                bend += (.16f * sin(beat - lag) + .025f * sin(beat * 2 - lag) - bend) * action;
                fan += (.034f * sin(beat - lag - .8f) - fan) * action;
                twist += (.20f * sin(beat - lag - .4f) - twist) * action;
                feathers[j*3] = bend; feathers[j*3+1] = fan; feathers[j*3+2] = twist;
            }
        }

        /** Prepare once per selected item, before submission. Snapshots stay immutable. */
        public Frame forItem(CosmeticCatalog.Item item) {
            // A just-swapped Small selection must ignore an already-captured Giant flare,
            // even before the next input tick cancels it.
            if (!item.wingFlare && Float.isFinite(dragon) && dragon >= 0 && dragon < WingAction.DURATION)
                return new Frame(time, movement, flight, sprinting, wingPhase, -1).forItem(item);
            return item.feathers.isEmpty() || item == featherItem ? this : new Frame(this, item);
        }
    }

    private static float sin(float value) { return (float) Math.sin(value); }

    private static float smooth(float value) {
        float t = Math.max(0, Math.min(1, value));
        return t * t * (3 - 2 * t);
    }

    /** Rotation R_y R_x R_z, followed by a local Y scale. */
    private static final class Transform {
        final float a, b, c, d, e, f, g, h, i, scale;

        Transform(float pitch, float yaw, float roll, float scale) {
            float sx = sin(pitch), cx = (float) Math.cos(pitch);
            float sy = sin(yaw), cy = (float) Math.cos(yaw);
            float sz = sin(roll), cz = (float) Math.cos(roll);
            a = cy * cz + sy * sx * sz; b = -cy * sz + sy * sx * cz; c = sy * cx;
            d = cx * sz; e = cx * cz; f = -sx;
            g = -sy * cz + cy * sx * sz; h = sy * sz + cy * sx * cz; i = cy * cx;
            this.scale = scale;
        }
    }

    /** Reusable posed coordinates in model units; source UVs remain on Quad. */
    public static final class PosedQuad {
        public final float[] x = new float[4], y = new float[4], z = new float[4];
        public float normalX, normalY, normalZ;
        private float px, py, pz;
        private Frame offsetsFrame;
        private float[] offsets = new float[0];
        private int[] stamps = new int[0];
        private int stamp;

        public void set(CosmeticGeometry.Quad quad, Frame frame) {
            if (frame == null) {
                System.arraycopy(quad.x, 0, x, 0, 4);
                System.arraycopy(quad.y, 0, y, 0, 4);
                System.arraycopy(quad.z, 0, z, 0, 4);
                normalX = quad.normalX; normalY = quad.normalY; normalZ = quad.normalZ;
                return;
            }
            Transform inner = switch (quad.motion) {
                case "head" -> frame.head;
                case "wing" -> quad.mirrored ? frame.rightWing : frame.leftWing;
                case "pack" -> frame.pack;
                default -> null;
            };
            boolean pet = "head".equals(quad.motion) || "body".equals(quad.motion);
            boolean feather = quad.feathers != null && frame.feathers != null;
            if (feather && offsetsFrame != frame) {
                offsetsFrame = frame;
                if (stamps.length < quad.featherVertexCount) {
                    stamps = new int[quad.featherVertexCount];
                    offsets = new float[quad.featherVertexCount * 3];
                }
                if (++stamp == 0) { java.util.Arrays.fill(stamps, 0); stamp = 1; }
            }
            for (int vertex = 0; vertex < 4; vertex++) {
                px = quad.x[vertex]; py = quad.y[vertex]; pz = quad.z[vertex];
                if (feather) {
                    var weight = quad.feathers[vertex];
                    float side = quad.mirrored ? -1 : 1;
                    int index = weight.index * 3;
                    if (stamps[weight.index] != stamp) {
                        float dx = 0, dy = 0, dz = 0;
                        for (int j = 0; j < weight.bones.length; j++) {
                            int b = weight.bones[j] * 3, c = j * 4;
                            dz += weight.coefficients[c] * frame.feathers[b]
                                    + weight.coefficients[c+3] * frame.feathers[b+2];
                            dx += weight.coefficients[c+1] * frame.feathers[b+1];
                            dy += weight.coefficients[c+2] * frame.feathers[b+1];
                        }
                        offsets[index] = dx; offsets[index+1] = dy; offsets[index+2] = dz;
                        stamps[weight.index] = stamp;
                    }
                    px += side * offsets[index]; py += offsets[index+1]; pz += offsets[index+2];
                }
                if (inner != null) point(inner, quad.pivotX, quad.pivotY, quad.pivotZ);
                // The head is a child of the breathing body, keeping the neck attached.
                if (pet) point(frame.body,
                        "body".equals(quad.motion) ? quad.pivotX : quad.parentPivotX,
                        "body".equals(quad.motion) ? quad.pivotY : quad.parentPivotY,
                        "body".equals(quad.motion) ? quad.pivotZ : quad.parentPivotZ);
                x[vertex] = px; y[vertex] = py; z[vertex] = pz;
            }
            if (feather) {
                // Lighting follows the flexed surface. The catalogue's outward winding
                // is opposite the TL->TR cross TL->BL convention used here.
                float ax = x[1]-x[0], ay = y[1]-y[0], az = z[1]-z[0];
                float bx = x[3]-x[0], by = y[3]-y[0], bz = z[3]-z[0];
                px = bz*ay - by*az; py = bx*az - bz*ax; pz = by*ax - bx*ay;
                float length = (float) Math.sqrt(px*px + py*py + pz*pz);
                if (length > .000001f) {
                    normalX = px / length; normalY = py / length; normalZ = pz / length;
                    return;
                }
            }
            px = quad.normalX; py = quad.normalY; pz = quad.normalZ;
            if (inner != null) normal(inner);
            if (pet) normal(frame.body);
            float length = (float) Math.sqrt(px * px + py * py + pz * pz);
            normalX = px / length; normalY = py / length; normalZ = pz / length;
        }

        private void point(Transform m, float pivotX, float pivotY, float pivotZ) {
            float vx = px - pivotX, vy = (py - pivotY) * m.scale, vz = pz - pivotZ;
            px = pivotX + m.a * vx + m.b * vy + m.c * vz;
            py = pivotY + m.d * vx + m.e * vy + m.f * vz;
            pz = pivotZ + m.g * vx + m.h * vy + m.i * vz;
        }

        private void normal(Transform m) {
            float vx = px, vy = py / m.scale, vz = pz;
            px = m.a * vx + m.b * vy + m.c * vz;
            py = m.d * vx + m.e * vy + m.f * vz;
            pz = m.g * vx + m.h * vy + m.i * vz;
        }
    }
}
