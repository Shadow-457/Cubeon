#version 330
#extension GL_ARB_separate_shader_objects : require
uniform sampler2D FarColor;
uniform sampler2D FarDepth;
uniform sampler2D NearDepth;
layout(std140) uniform LodFrame {
    mat4 FarViewProjection;
    mat4 InverseFarProjection;
    mat4 InverseNearProjection;
    ivec4 CameraBlock;
    vec4 CameraFraction;
    vec4 FogColorRange;
    vec4 Lighting;
};
layout(location=0) in vec2 texCoord;
layout(location=0) out vec4 fragColor;
float eyeDepth(mat4 inverseProjection, float depth) {
    float ndc = CameraBlock.w == 1 ? depth : depth * 2.0 - 1.0;
    vec4 p = inverseProjection * vec4(texCoord * 2.0 - 1.0, ndc, 1.0);
    return -p.z / p.w;
}
void main() {
    float farDepth = texture(FarDepth, texCoord).r;
    vec4 color = texture(FarColor, texCoord);
    if (farDepth <= 0.0 || color.a <= 0.0) discard;
    float nearDepth = texture(NearDepth, texCoord).r;
    if (nearDepth > 0.0 && eyeDepth(InverseNearProjection, nearDepth) <= eyeDepth(InverseFarProjection, farDepth) + 0.05) discard;
    // Far colour already contains premultiplied fluid blending.
    fragColor = color;
}
