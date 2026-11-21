#version 330
#extension GL_ARB_separate_shader_objects : require
uniform sampler2D BlockAtlas;
layout(std140) uniform LodFrame {
    mat4 FarViewProjection;
    mat4 InverseFarProjection;
    mat4 InverseNearProjection;
    ivec4 CameraBlock;
    vec4 CameraFraction;
    vec4 FogColorRange;
    vec4 Lighting;
};
layout(location=0) in vec2 faceUv;
layout(location=1) flat in vec4 atlasRect;
layout(location=2) in vec4 faceColor;
layout(location=3) in float faceLight;
layout(location=4) flat in uint faceFlags;
layout(location=5) in vec3 relativePosition;
layout(location=0) out vec4 fragColor;
float linearFog(float distance, float start, float end) {
    if (distance <= start) return 0.0;
    if (distance >= end) return 1.0;
    return (distance - start) / (end - start);
}
void main() {
    float distance = length(relativePosition.xz);
    if (distance < CameraFraction.w || distance > FogColorRange.w) discard;
    // Clamp inside the sprite to prevent atlas neighbours bleeding into distant terrain.
    vec2 repeated = clamp(fract(faceUv), vec2(0.001), vec2(0.999));
    vec4 texel = textureGrad(BlockAtlas, atlasRect.xy + repeated * atlasRect.zw,
        dFdx(faceUv) * atlasRect.zw, dFdy(faceUv) * atlasRect.zw);
    if ((faceFlags & 2u) != 0u && texel.a < 0.3) discard;
    vec4 color = texel * faceColor;
    color.rgb *= faceLight;
    float fog = max(linearFog(length(relativePosition), Lighting.y, Lighting.z),
        linearFog(max(distance, abs(relativePosition.y)), Lighting.w, FogColorRange.w));
    color.rgb = mix(color.rgb, FogColorRange.rgb, fog);
    color.a = (faceFlags & 1u) != 0u ? faceColor.a : 1.0;
    fragColor = color;
}
