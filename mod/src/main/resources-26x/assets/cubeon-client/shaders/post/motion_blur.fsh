#version 330
#extension GL_ARB_separate_shader_objects : require

// Cubeon Client's motion blur (2026-10-24).
//
// The post effect in post_effect/motion_blur_{low,medium,high}.json renders the
// current world frame and the previous frame into the same screen-sized target,
// then copies the result back to main and into the persistent "prev" target for
// the next frame. The three files differ only in BlurAmount, which is how the
// menu's Off/Low/Medium/High setting is implemented.
//
// Two details keep this smooth instead of chunky:
//
//   1. The previous frame is read with a 5-tap cross, not one bilinear tap. A
//      single tap leaves a hard ghost edge on fast pans; the small average
//      turns that edge into a smear for four extra taps of a resident texture.
//   2. The blend is masked by how much the CURRENT frame differs from the
//      previous one (measured against the unblurred centre tap, not the
//      average, or the spatial blur would look like motion). A stationary
//      scene then blends nothing and stays sharp, while a moving camera gets
//      the full configured amount - which is what stops the old effect from
//      slowly softening and then staying soft.
//
// The alpha channel is used as a validity mask rather than as colour. A fresh
// persistent target is cleared to transparent black, so prev.a is 0 until the
// blit pass has written a real frame into it; without this check the first
// frame after a world load or a window resize would mix black into the image
// for one frame.

uniform sampler2D InSampler;
uniform sampler2D PrevSampler;

layout(location = 0) in vec2 texCoord;

layout(std140) uniform MotionBlurConfig {
    float BlurAmount;
};

layout(location = 0) out vec4 fragColor;

void main() {
    vec4 current = texture(InSampler, texCoord);
    vec4 prevCentre = texture(PrevSampler, texCoord);

    vec2 texel = 1.0 / vec2(textureSize(InSampler, 0));
    vec2 stepX = vec2(texel.x * 1.5, 0.0);
    vec2 stepY = vec2(0.0, texel.y * 1.5);

    vec4 previous = prevCentre * 2.0;
    previous += texture(PrevSampler, texCoord + stepX);
    previous += texture(PrevSampler, texCoord - stepX);
    previous += texture(PrevSampler, texCoord + stepY);
    previous += texture(PrevSampler, texCoord - stepY);
    previous /= 6.0;

    float valid = step(0.5, prevCentre.a);
    float motion = clamp(length(current.rgb - prevCentre.rgb) * 6.0, 0.0, 1.0);
    float weight = BlurAmount * valid * motion;

    fragColor = vec4(mix(current.rgb, previous.rgb, weight), 1.0);
}
