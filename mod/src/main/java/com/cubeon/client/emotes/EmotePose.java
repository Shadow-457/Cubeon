package com.cubeon.client.emotes;

/** Model transforms only: player physics, hitboxes and camera remain vanilla. */
public final class EmotePose {
    public final float[] angles = new float[18]; // head, body, right/left arm, right/left leg
    public final float[] offsets = new float[18];
    public final float weight;
    /** Model-space units downwards, shared by every body part for a grounded sit. */
    public float drop;
    public int mask;
    private boolean waistAnchored;
    private float hipX, hipY, hipZ, cy, sy, cr, sr, bendCos, bendSin;
    private EmotePose(float weight) { this.weight = weight; }
    public float blend(int part, int axis, float base) {
        if ((mask & (1 << part)) == 0) return base;
        float target = angles[part*3+axis];
        return part < 2 ? base + target * weight : base + (target-base)*weight;
    }
    private void set(int part, float x, float y, float z) {
        mask |= 1 << part;
        angles[part*3] = x; angles[part*3+1] = y; angles[part*3+2] = z;
    }
    /** ModelPart rotates Z/Y/X. Bow changes pitch only; preserve the vanilla
     * yaw/roll and rotate the upper body's origins about the torso's hip edge. */
    public void anchorBody(float x, float y, float z, float pitch, float yaw, float roll) {
        if (!waistAnchored) return;
        cy = (float)Math.cos(yaw); sy = (float)Math.sin(yaw);
        cr = (float)Math.cos(roll); sr = (float)Math.sin(roll);
        float dy = 12 * (float)Math.cos(pitch), dz = 12 * (float)Math.sin(pitch);
        hipX = x + cr * sy * dz - sr * dy;
        hipY = y + sr * sy * dz + cr * dy;
        hipZ = z + cy * dz;
        float bend = blend(1, 0, pitch) - pitch;
        bendCos = (float)Math.cos(bend); bendSin = (float)Math.sin(bend);
    }
    /** Record each additive origin offset so legacy reused models can undo it. */
    public void position(int part, float x, float y, float z) {
        int i = part * 3;
        offsets[i] = 0; offsets[i+1] = drop; offsets[i+2] = 0;
        if (!waistAnchored || part >= 4 || weight == 0) return;
        float dx = x - hipX, dy = y - hipY, dz = z - hipZ;
        // Into the torso's yaw/roll frame, pitch about the hips, then back.
        float rx = cr * dx + sr * dy, ry = -sr * dx + cr * dy;
        float lx = cy * rx - sy * dz, lz = sy * rx + cy * dz;
        float by = bendCos * ry - bendSin * lz;
        float bz = bendSin * ry + bendCos * lz;
        float bx = cy * lx + sy * bz, rz = -sy * lx + cy * bz;
        offsets[i] = hipX + cr * bx - sr * by - x;
        offsets[i+1] += hipY + sr * bx + cr * by - y;
        offsets[i+2] = hipZ + rz - z;
    }
    public static EmotePose sample(int emote, float age, float duration) {
        float weight = smooth(Math.min(age / .25f, (duration-age) / .35f));
        EmotePose pose = new EmotePose(weight);
        float beat = (float)Math.sin(age*8), sway = (float)Math.sin(age*4);
        switch (emote) {
            case 0 -> { // wave
                pose.set(2, -2.45f + beat*.22f, -.3f, .5f + beat*.35f);
                pose.set(3, .1f, 0, -.08f); pose.set(0, 0, 0, beat*.04f);
            }
            case 1 -> { // dance
                float other = (float)Math.cos(age*8);
                pose.set(1, -.06f + beat*.06f, sway*.2f, other*.04f);
                pose.set(2, -1.3f-other*.7f, .2f, .5f-beat*.25f);
                pose.set(3, -1.3f+other*.7f, -.2f, -.5f-beat*.25f);
                pose.set(4, beat*.4f, 0, 0); pose.set(5, -beat*.4f, 0, 0);
                pose.set(0, -.08f+beat*.08f, sway*.12f, 0);
            }
            case 2 -> { // bow
                pose.waistAnchored = true;
                pose.set(1, .5f, 0, 0); pose.set(0, .3f, 0, 0);
                pose.set(2, -1.5f, -.1f, .15f); pose.set(3, -2f, -.3f, -.4f);
            }
            case 3 -> { // salute
                pose.set(2, -2.6f, -.2f, .3f); pose.set(3, .12f, 0, -.06f);
                pose.set(0, .08f, 0, 0);
            }
            case 4 -> { // shrug
                pose.set(2, .4f, -.4f, 1.1f); pose.set(3, .4f, .4f, -1.1f);
                pose.set(0, -.18f, 0, sway*.03f);
            }
            case 5 -> { // point
                pose.set(2, -(float)Math.PI/2, -.05f, .12f);
                pose.set(3, .12f, 0, -.14f); pose.set(0, -.06f, 0, 0);
            }
            case 6 -> { // clap: hands meet in front, then open with a soft hold
                float close = .5f - .5f * (float)Math.cos(age * 9.5f);
                float hands = .12f + .34f * smooth(close);
                pose.set(2, -1.35f - close*.08f, -hands, -.04f);
                pose.set(3, -1.35f - close*.08f, hands, .04f);
                pose.set(0, .05f + close*.025f, 0, 0);
                pose.set(1, -.015f + close*.02f, 0, 0);
            }
            case 7 -> { // laugh: hand over mouth, little shoulder and head pulses
                float chuckle = (float)Math.sin(age*12);
                pose.set(2, -2.55f + chuckle*.035f, -.5f, -.14f);
                pose.set(3, -.65f, .55f, .18f);
                pose.set(0, -.16f + chuckle*.045f, -.04f, sway*.02f);
                pose.set(1, .075f + chuckle*.025f, 0, chuckle*.018f);
            }
            case 8 -> { // sit: legs forward, hands resting alongside the lap
                pose.drop = 10 * weight;
                pose.set(4, -(float)Math.PI/2, -.12f, .06f);
                pose.set(5, -(float)Math.PI/2, .12f, -.06f);
                pose.set(2, -.48f, -.08f, -.06f);
                pose.set(3, -.48f, .08f, .06f);
                pose.set(1, .04f, 0, 0); pose.set(0, .06f + sway*.012f, 0, 0);
            }
            case 9 -> { // celebrate: arms up, small alternating fist pumps
                float pump = (float)Math.sin(age*7);
                pose.set(2, -2.8f + pump*.15f, -.12f, .3f);
                pose.set(3, -2.8f - pump*.15f, .12f, -.3f);
                pose.set(0, -.13f + pump*.02f, sway*.04f, 0);
                pose.set(1, -.04f, sway*.05f, pump*.025f);
                pose.set(4, pump*.06f, 0, 0); pose.set(5, -pump*.06f, 0, 0);
            }
            default -> { }
        }
        return pose;
    }
    private static float smooth(float t) { t=Math.max(0,Math.min(1,t)); return t*t*(3-2*t); }
}
