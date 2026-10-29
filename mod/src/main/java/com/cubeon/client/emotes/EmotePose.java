package com.cubeon.client.emotes;

/** Rotations only: player physics, hitboxes and camera remain vanilla. */
public final class EmotePose {
    public final float[] angles = new float[18]; // head, body, right/left arm, right/left leg
    public final float weight;
    public int mask;
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
            default -> { }
        }
        return pose;
    }
    private static float smooth(float t) { t=Math.max(0,Math.min(1,t)); return t*t*(3-2*t); }
}
