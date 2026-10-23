#version 330
#extension GL_ARB_separate_shader_objects : require

// Cubeon Client's motion blur (2026-10-24).
//
// The post effect in post_effect/motion_blur.json renders the current world
// frame and the previous frame into the same screen-sized target, then copies
// the result back to main and into the persistent "prev" target for the next
// frame. That makes this a frame-accumulation blur: a stationary scene blends
// two identical frames and looks unchanged, while a moving camera leaves a
// short trail that fades geometrically because "prev" is already blurred.
//
// The alpha channel is used as a validity mask rather than as colour. A fresh
// persistent target is cleared to transparent black, so prev.a is 0 until the
// blit pass has written a real frame into it; without this check the first
// frame after a world load or a window resize would mix 65% black into the
// image for one frame.

uniform sampler2D InSampler;
uniform sampler2D PrevSampler;

layout(location = 0) in vec2 texCoord;

layout(std140) uniform MotionBlurConfig {
    float BlurAmount;
};

layout(location = 0) out vec4 fragColor;

void main() {
    vec4 current = texture(InSampler, texCoord);
    vec4 previous = texture(PrevSampler, texCoord);

    float valid = step(0.5, previous.a);
    vec3 blended = mix(current.rgb, previous.rgb, BlurAmount * valid);

    fragColor = vec4(blended, 1.0);
}
