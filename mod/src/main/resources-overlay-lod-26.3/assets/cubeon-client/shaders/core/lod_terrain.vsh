#version 330
#extension GL_ARB_separate_shader_objects : require
layout(location=0) in ivec2 TileOrigin;
layout(location=1) in vec3 FacePosition;
layout(location=2) in vec2 FaceUv;
layout(location=3) in uint FaceDirection;
layout(location=4) in vec4 FaceColor;
layout(location=5) in vec4 AtlasRect;
layout(location=6) in uint FaceLight;
layout(location=7) in uint FaceFlags;
layout(std140) uniform LodFrame {
    mat4 FarViewProjection;
    mat4 InverseFarProjection;
    mat4 InverseNearProjection;
    ivec4 CameraBlock;
    vec4 CameraFraction;
    vec4 FogColorRange;
    vec4 Lighting;
};
layout(location=0) out vec2 faceUv;
layout(location=1) flat out vec4 atlasRect;
layout(location=2) out vec4 faceColor;
layout(location=3) out float faceLight;
layout(location=4) flat out uint faceFlags;
layout(location=5) out vec3 relativePosition;
void main() {
    vec3 position = FacePosition;
    vec2 uv = FaceUv;
#ifdef LOD_GPU
    const int corners[6] = int[6](0, 1, 2, 0, 2, 3);
    int corner = corners[gl_VertexIndex % 6];
    uv = vec2(corner == 1 || corner == 2 ? FaceUv.x : 0.0, corner >= 2 ? FaceUv.y : 0.0);
    if (FaceDirection == 0u) position += vec3(0, uv.y, uv.x);
    else if (FaceDirection == 1u) position += vec3(0, uv.y, -uv.x);
    else if (FaceDirection == 2u) position += vec3(uv.x, 0, uv.y);
    else if (FaceDirection == 3u) position += vec3(uv.x, 0, -uv.y);
    else if (FaceDirection == 4u) position += vec3(-uv.x, uv.y, 0);
    else position += vec3(uv.x, uv.y, 0);
#endif
    // Integer subtraction precedes float conversion, preserving blocks at world-border coordinates.
    relativePosition = vec3(TileOrigin.x - CameraBlock.x, -CameraBlock.y, TileOrigin.y - CameraBlock.z)
        + position - CameraFraction.xyz;
    gl_Position = FarViewProjection * vec4(relativePosition, 1.0);
    faceUv = uv;
    atlasRect = AtlasRect;
    faceColor = FaceColor;
    faceFlags = FaceFlags;
    float sky = float((FaceLight >> 4u) & 15u) / 15.0 * Lighting.x;
    float block = float(FaceLight & 15u) / 15.0;
    float directional = FaceDirection == 3u ? 1.0 : FaceDirection == 2u ? 0.5 : FaceDirection < 2u ? 0.65 : 0.8;
    faceLight = (0.2 + 0.8 * max(sky, block)) * directional;
}
